"""Round orchestrator: iterate a build's round_actions, dispatch to attack/save
modules, sum expected damage per type, apply resistances once at the end.

Action types in round_actions:
  {"type":"attack","weapon":"main_hand","attack_kind":"melee","count":3,
   "advantage":false,"smites":[{"slot_level":2}]}
  {"type":"spell","ref":"Fireball","upcast_level":3,"n_targets":1}
  {"type":"smite","slot_level":2,"weapon":"main_hand"}  # adds DS to next attack (simplified)
"""
import json
from .character import Character, Target
from . import rider_engine
from . import save as save_mod
from . import dice as dice_mod
from .attack import p_hit
from .damage import DamageComponent, DamagePool


def expected_round_damage(build_or_path, verbose=False):
    """Compute expected damage for one round. Returns dict with per-action + total."""
    if isinstance(build_or_path, str):
        build = json.load(open(build_or_path, encoding='utf-8'))
    else:
        build = build_or_path
    char = Character(build)
    target = Target(build.get('target', {}))
    # Apply attacker-side target_vulnerability riders (e.g. Bhaalist Armour:
    # enemies within 3m become Vulnerable to Piercing). These add to the target's
    # vulnerability set for damage calculation.
    for vuln_type in char.target_vulnerabilities():
        if vuln_type not in target.vulnerabilities:
            target.vulnerabilities.append(vuln_type)
    # Derive crit_immune / auto_crit from target conditions (bg3.wiki Critical_hit):
    # Paralysed/Sleeping/Unconscious => melee attacks auto-crit; Adamantine-style
    # crit immunity is set explicitly via the target dict's crit_immune flag.
    _apply_target_condition_effects(char, target)
    # If the target represents a player character, apply its species resistances
    # (e.g. a Tiefling target takes half Fire). bg3.wiki raw_races/.
    if getattr(target, 'species', ''):
        from .catalog import SPECIES_RESISTANCES, SPECIES_SAVE_ADVANTAGE
        for r in SPECIES_RESISTANCES.get(target.species, []):
            if r not in target.resistances:
                target.resistances.append(r)
        # Gnome Cunning: Advantage on INT/WIS/CHA saves (attribute-level). Other
        # species advantages are effect-category-based (Charmed/Poisoned) and need
        # spell tagging; attribute-level ones are applied here.
        for cat in SPECIES_SAVE_ADVANTAGE.get(target.species, []):
            if cat in ('INT', 'WIS', 'CHA'):
                target.save_bonus.setdefault(cat + '_adv', True)
    # Defensive gear worn by a PC target (Adamantine crit immunity, Superior
    # Padding/Magical Plate flat reduction). bg3.wiki equipment.json.
    for slot, name in (getattr(target, 'equipped', {}) or {}).items():
        if not name:
            continue
        ddef = char.catalog.defense_for(name)
        if not ddef:
            continue
        if ddef.get('crit_immune'):
            target.crit_immune = True
        for t, v in (ddef.get('flat_reduction') or {}).items():
            target.flat_reduction[t] = max(target.flat_reduction.get(t, 0), v)
    actions = build.get('round_actions', [])

    results = []
    total_per_type = {}
    for i, action in enumerate(actions):
        atype = action.get('type')
        if atype == 'attack':
            r = _attack_action(char, target, action)
        elif atype == 'spell':
            r = _spell_action(char, target, action)
        elif atype == 'racial_breath':
            r = _racial_breath_action(char, target, action)
        elif atype == 'bonus_attack':
            r = _bonus_attack_action(char, target, action)
        elif atype == 'wild_shape':
            r = _wild_shape_action(char, target, action)
        elif atype == 'summon':
            r = _summon_action(char, target, action)
        elif atype == 'ki_spell':
            r = _ki_spell_action(char, target, action)
        else:
            r = {'total_ev': 0.0, 'per_type_ev': {}, 'note': f'unknown action {atype}'}
        results.append(r)
        for dt, v in r.get('per_type_ev_post_resist', r.get('per_type_ev', {})).items():
            total_per_type[dt] = total_per_type.get(dt, 0.0) + v

    # Apply conditions inflicted by the character's hits this round (bg3.wiki: e.g.
    # Spineshudder Amulet inflicts Reverberation on ranged spell hit, Winter's Clutches
    # inflicts Encrusted with Frost on cold hit). These riders (kind=inflicts_condition)
    # stack onto the target so end_of_turn can settle Reverberation 5-stack / Encrusted
    # 7-stack triggers. Assumes hits land (offense-side EV).
    _apply_inflicted_conditions(char, target, results)

    # End-of-turn damage from target conditions (bg3.wiki raw_conditions/): Burning
    # (1d4 Fire/turn), Brittle (2d6 Cold/turn), Electrocuted (1d4 Lightning/turn),
    # and Reverberation 5-stack trigger (1d4 Thunder DRS + Prone save). BURNING
    # stack-id conditions are mutually exclusive — take the strongest.
    eot = _end_of_turn_damage(char, target)
    if eot.get('per_type_ev'):
        results.append(eot)
        for dt, v in eot['per_type_ev'].items():
            total_per_type[dt] = total_per_type.get(dt, 0.0) + v

    return {
        'build': build.get('name', ''),
        'per_action': results,
        'total_per_type': total_per_type,
        'total_ev': sum(total_per_type.values()),
    }


# BURNING stack-id family: only the strongest applies per turn (bg3.wiki Burning).
_BURNING_FAMILY = {
    'Burning': ('1d4', 'Fire'), 'Burning Fiercely': ('1d10', 'Fire'),
    'Holy Fire': ('1d4', 'Radiant'), 'Melting': ('10d6', 'Fire'),
    'Roiling Hellfire': ('6d6', 'Fire'),
}


def _apply_inflicted_conditions(char, target, action_results):
    """Stack conditions inflicted by the character's hit-type riders this round
    (kind=inflicts_condition, e.g. Spineshudder->Reverberation, Winter's Clutches->
    Encrusted with Frost). Stacks accumulate on the target so _end_of_turn_damage can
    settle Reverberation 5-stack (1d4 Thunder DRS) / Encrusted 7-stack (Frozen+1d4 Cold).
    Assumes hits land (offense-side EV); count attacks that dealt damage this round.
    """
    cat = char.catalog
    # expected hits this round, per attack kind. Attack actions report p_normal/p_crit
    # and count; spell actions report n_hits (sources * hit prob).
    n_weapon_hits = 0.0
    n_spell_hits = 0.0
    for r in action_results:
        if r.get('type') == 'attack':
            ph = r.get('p_normal', 0) + r.get('p_crit', 0)
            n_weapon_hits += ph * r.get('count', 1)
        elif r.get('type') == 'spell':
            n_spell_hits += float(r.get('n_hits', 0) or 0)
    if not n_weapon_hits and not n_spell_hits:
        return
    inflicted = {}  # condition_name -> total stacks (expected)
    for attack_kind, n in (('melee', n_weapon_hits), ('ranged', n_weapon_hits),
                           ('thrown', n_weapon_hits), ('unarmed', n_weapon_hits),
                           ('spell', n_spell_hits)):
        if not n:
            continue
        for r in char.active_riders(attack_kind):
            if r.get('kind') != 'inflicts_condition':
                continue
            cname = r.get('condition_inflicted')
            if not cname:
                continue
            inflicted[cname] = inflicted.get(cname, 0.0) + int(r.get('stacks', 1)) * n
    for cname, stacks in inflicted.items():
        if cname == 'Reverberation':
            target.reverberation_stacks = getattr(target, 'reverberation_stacks', 0) + stacks
            if 'Reverberation' not in (target.conditions or []):
                target.conditions = (target.conditions or []) + ['Reverberation']
        elif cname == 'Encrusted with Frost':
            target.encrusted_stacks = getattr(target, 'encrusted_stacks', 0) + stacks
            if 'Encrusted with Frost' not in (target.conditions or []):
                target.conditions = (target.conditions or []) + ['Encrusted with Frost']
        elif cname == 'Prone':
            if 'Prone' not in (target.conditions or []):
                target.conditions = (target.conditions or []) + ['Prone']
        # Radiating Orb / Noxious Fumes / Mental Fatigue: debuffs, no end_of_turn damage


def _end_of_turn_damage(char, target):
    """Damage the target takes at the start/end of its turn from lingering conditions.

    Consumes conditions.json `damage_per_turn` for Burning/Brittle/Electrocuted, with
    BURNING-family mutual exclusion (strongest wins). Reverberation at 5+ stacks
    triggers 1d4 Thunder DRS + a DC 10 CON save (effective ~15) vs Prone.
    """
    cat = char.catalog
    conds = set(getattr(target, 'conditions', []) or [])
    per_type = {}

    # BURNING family: pick the strongest member present.
    burning_present = [c for c in _BURNING_FAMILY if c in conds]
    if burning_present:
        # strongest by expected dice value
        best = max(burning_present, key=lambda c: dice_mod.ev(_BURNING_FAMILY[c][0]))
        dice_expr, dtype = _BURNING_FAMILY[best]
        per_type[dtype] = per_type.get(dtype, 0.0) + dice_mod.ev(dice_expr)
    elif 'Burning' in cat.conditions:
        # generic Burning if no family member explicitly listed
        pass

    # Other per-turn conditions (Brittle 2d6 Cold, Electrocuted 1d4 Lightning).
    for cname in conds:
        cdef = cat.conditions.get(cname) if hasattr(cat, 'conditions') else None
        if not cdef:
            continue
        dpt = cdef.get('damage_per_turn')
        if dpt and cname not in _BURNING_FAMILY:
            per_type[dpt.get('type', 'Fire')] = per_type.get(dpt.get('type', 'Fire'), 0.0) + \
                dice_mod.ev(dpt.get('dice', '0'))

    # Reverberation 5+ stacks: 1d4 Thunder DRS (+ Prone save, not modelled as damage).
    if 'Reverberation' in conds:
        rdef = cat.conditions.get('Reverberation') or {}
        stacks = getattr(target, 'reverberation_stacks', 5)
        if stacks >= rdef.get('stack_threshold', 5):
            per_type['Thunder'] = per_type.get('Thunder', 0.0) + dice_mod.ev('1d4')

    # Encrusted with Frost 7+ stacks: 1d4 Cold DRS + Frozen (2 turns). The 1d4 Cold
    # is NOT halved on a successful save (bg3.wiki bug). Frozen adds Bludgeoning/Thunder/
    # Force vulnerability (already applied via _apply_target_condition_effects if Frozen
    # is in conditions). Here we add the 1d4 Cold and the Frozen condition's per-turn
    # none (Frozen has no per-turn damage, only vulnerability/shatter).
    if 'Encrusted with Frost' in conds:
        edef = cat.conditions.get('Encrusted with Frost') or {}
        estacks = getattr(target, 'encrusted_stacks', 0)
        if estacks >= edef.get('stack_threshold', 7):
            per_type['Cold'] = per_type.get('Cold', 0.0) + dice_mod.ev('1d4')
            # Frozen grants Bludgeoning/Thunder/Force vulnerability — apply for the
            # rest of this end_of_turn by adding to target.vulnerabilities (best-effort).
            for v in ('Bludgeoning', 'Thunder', 'Force'):
                if v not in (target.vulnerabilities or []):
                    target.vulnerabilities = (target.vulnerabilities or []) + [v]

    post = DamagePool().apply_resistances(per_type, target)
    return {'type': 'end_of_turn', 'note': 'condition damage',
            'per_type_ev': post, 'per_type_ev_post_resist': post,
            'total_ev': sum(post.values())}


# Conditions that force every melee hit to crit (bg3.wiki Critical_hit: melee-range
# attacks vs Paralysed/Sleeping/Unconscious targets are guaranteed critical hits).
AUTO_CRIT_CONDITIONS = {'Paralysed', 'Sleeping', 'Unconscious'}


# Summon stat blocks (bg3.wiki, verified): per-round attack EV. {summon: {dice, type, flat, attack_bonus, extra?}}.
SUMMON_ATTACKS = {
    "Skeleton": {"dice": "1d6", "type": "Piercing", "flat": 3, "attack_bonus": 5,
                 "extra": {"dice": "1d10", "type": "Necrotic"},
                 "source": "https://bg3.wiki/wiki/Animate_Dead"},
    "Zombie": {"dice": "2d6", "type": "Bludgeoning", "flat": 3, "attack_bonus": 5,
               "source": "https://bg3.wiki/wiki/Animate_Dead"},
    "Ghoul": {"dice": "3d6", "type": "Slashing", "flat": 3, "attack_bonus": 6,
              "source": "https://bg3.wiki/wiki/Animate_Dead"},
    "Mummy": {"dice": "4d6", "type": "Bludgeoning", "flat": 6, "attack_bonus": 7,
              "extra": {"dice": "6d6", "type": "Necrotic"},
              "source": "https://bg3.wiki/wiki/Create_Undead"},
    "Fire Elemental": {"dice": "2d6", "type": "Fire", "flat": 0, "attack_bonus": 5,
                       "source": "https://bg3.wiki/wiki/Conjure_Elemental"},
    "Water Elemental": {"dice": "2d6", "type": "Cold", "flat": 0, "attack_bonus": 7,
                        "source": "https://bg3.wiki/wiki/Conjure_Elemental"},
    "Air Elemental": {"dice": "2d6", "type": "Thunder", "flat": 1, "attack_bonus": 4,
                      "source": "https://bg3.wiki/wiki/Conjure_Elemental"},
    "Earth Elemental": {"dice": "2d6", "type": "Bludgeoning", "flat": 6, "attack_bonus": 8,
                        "source": "https://bg3.wiki/wiki/Conjure_Elemental"},
    "Minor Elemental (Mud Mephit)": {"dice": "3d6", "type": "Bludgeoning", "flat": 1, "attack_bonus": 3,
                        "source": "https://bg3.wiki/wiki/Conjure_Minor_Elemental"},
    "Dryad": {"dice": "4d8", "type": "Bludgeoning", "flat": 0, "attack_bonus": 5,
              "source": "https://bg3.wiki/wiki/Conjure_Woodland_Being"},
    "Danse Macabre Ghoul": {"dice": "2d6", "type": "Slashing", "flat": 3, "attack_bonus": 6,
                            "source": "https://bg3.wiki/wiki/Danse_Macabre"},
    "Cambion (Planar Ally)": {"dice": "1d10", "type": "Slashing", "flat": 4, "attack_bonus": 8,
                              "source": "https://bg3.wiki/wiki/Planar_Ally"},
    "Deva (Planar Ally)": {"dice": "1d6", "type": "Bludgeoning", "flat": 4, "attack_bonus": 8,
                           "extra": {"dice": "4d8", "type": "Radiant"},
                           "source": "https://bg3.wiki/wiki/Planar_Ally"},
}

# Way of the Four Elements ki spells (bg3.wiki, verified). {name: {dice, type, save, save_effect, ki}}.
# Ki save DC = 8 + prof + WIS (Water Whip uses weapon-action DC; simplified to spell DC).
KI_SPELLS = {
    "Fist of Unbroken Air": {"dice": "3d10", "type": "Bludgeoning", "save": "STR",
                             "save_effect": "half", "ki": 2,
                             "source": "https://bg3.wiki/wiki/Way_of_the_Four_Elements"},
    "Fist of Four Thunders": {"dice": "2d8", "type": "Thunder", "save": "CON",
                              "save_effect": "half", "ki": 2,
                              "source": "https://bg3.wiki/wiki/Way_of_the_Four_Elements"},
    "Water Whip": {"dice": "3d10", "type": "Bludgeoning", "save": "DEX",
                   "save_effect": "half", "ki": 2,
                   "source": "https://bg3.wiki/wiki/Way_of_the_Four_Elements"},
    "Sweeping Cinder Strike": {"dice": "3d6", "type": "Fire", "save": "DEX",
                               "save_effect": "half", "ki": 2,
                               "source": "https://bg3.wiki/wiki/Way_of_the_Four_Elements"},
    "Gong of the Summit": {"dice": "3d8", "type": "Thunder", "save": "CON",
                           "save_effect": "half", "ki": 3,
                           "source": "https://bg3.wiki/wiki/Way_of_the_Four_Elements"},
    "Embrace of the Inferno": {"dice": "6d6", "type": "Fire", "save": None,
                               "save_effect": None, "ki": 3, "attack": True,
                               "source": "https://bg3.wiki/wiki/Way_of_the_Four_Elements"},
    "Flames of the Phoenix": {"dice": "8d6", "type": "Fire", "save": "DEX",
                              "save_effect": "half", "ki": 4,
                              "source": "https://bg3.wiki/wiki/Way_of_the_Four_Elements"},
}


def _apply_target_condition_effects(char, target):
    """Derive engine-relevant target state from its conditions, consulting
    data/conditions.json.

    Effects consumed:
      - resistances (Petrified resists all; Blade Ward resists B/P/S) -> appended to
        target.resistances.
      - auto_crit_vs_melee (Paralysed/Sleeping/Unconscious/Frozen) -> target.auto_crit
        (used for melee/thrown/unarmed attacks). Suppressed if target is crit_immune.
      - advantage_vs / disadvantage_self -> stored on target for the attack layer to
        flip advantage/disadvantage (applied in _attack_action).
    """
    conds = {c for c in (getattr(target, 'conditions', []) or [])}
    cat = char.catalog
    for cname in conds:
        cdef = cat.conditions.get(cname) if hasattr(cat, 'conditions') else None
        if not cdef:
            continue
        for r in cdef.get('resistances', []) or []:
            if r not in target.resistances:
                target.resistances.append(r)
        # vulnerabilities (Wet -> Cold/Lightning; Frozen -> Bludgeoning/Thunder/Force;
        # Chilled -> Cold; Brittle -> Bludgeoning/Thunder). bg3.wiki elemental reactions.
        for v in cdef.get('vulnerabilities', []) or []:
            if v not in target.vulnerabilities:
                target.vulnerabilities.append(v)
        for im in cdef.get('immunities', []) or []:
            if im not in target.immunities:
                target.immunities.append(im)
        if cdef.get('auto_crit_vs_melee') and not target.crit_immune:
            target.auto_crit = True
    # legacy: also honour the bare condition-name set
    cond_norm = {c.lower().capitalize() for c in conds}
    if (cond_norm & AUTO_CRIT_CONDITIONS) and not target.crit_immune:
        target.auto_crit = True


def _apply_target_crit_state(target):
    """Deprecated shim — logic moved into _apply_target_condition_effects."""
    pass


def _target_grants_advantage(char, target, attack_kind):
    """True if a target condition grants advantage on this attack (bg3.wiki Conditions):
    Blinded/Restrained/Stunned/Unconscious -> advantage vs (all kinds);
    Prone -> advantage vs melee, disadvantage vs ranged."""
    conds = getattr(target, 'conditions', []) or []
    cat = char.catalog
    adv = False
    dis = False
    for cname in conds:
        cdef = cat.conditions.get(cname) if hasattr(cat, 'conditions') else None
        if not cdef:
            continue
        if cdef.get('advantage_vs'):
            adv = True
        if cdef.get('advantage_vs_melee') and attack_kind == 'melee':
            adv = True
        if cdef.get('disadvantage_vs_ranged') and attack_kind == 'ranged':
            dis = True
    if dis and not adv:
        return False  # caller handles disadvantage via action flag; here only report adv
    return adv


def _build_smite_drs(slot_level, target, char):
    """Build a Divine Smite rider (DRS per bg3.wiki) for the given spell-slot level.

    Base 2d8 Radiant at slot 1; +1d8 per slot above 1; total capped at 5d8.
    +1d8 vs Fiends/Undead (paladin-side mechanic, not target vulnerability).
    Smite is itself a DRS (new damage source) per the wiki. The base rider definition
    is read from data/riders.json ('Divine Smite') so the data stays the source of
    truth; only the slot-scaled dice count is overridden here.
    """
    base = dict(char.catalog.rider_by_key('Divine Smite') or {
        'trigger': 'melee_weapon_attack_hit', 'kind': 'DRS',
        'damage': {'dice': '2d8', 'flat': 0, 'type': 'Radiant'},
        'source': 'https://bg3.wiki/wiki/Divine_Smite'})
    base['kind'] = 'DRS'  # normalize legacy 'DS_added' to DRS
    dice = 2 + max(0, slot_level - 1)  # slot1=2d8, slot2=3d8, ...
    dice = min(dice, 5)  # cap 5d8
    ctype = (getattr(target, 'creature_type', '') or '').lower()
    if ctype in ('undead', 'fiend'):
        dice += 1
    base['damage'] = dict(base.get('damage', {}))
    base['damage']['dice'] = f'{dice}d8'
    base['_smite'] = True
    return base


def _set_auto_flag(target, flag, value):
    """Set/unset one auto-inferred condition flag on the target for one attack.
    Auto flags are tracked in target._auto_flags and removed before the next attack
    (see _clear_auto_flags); manual flags from the build are preserved."""
    if not hasattr(target, '_auto_flags'):
        target._auto_flags = set()
    if value:
        target._auto_flags.add(flag)
        if hasattr(target, 'flags') and flag not in target.flags:
            target.flags.append(flag)
    else:
        target._auto_flags.discard(flag)
        if hasattr(target, 'flags') and flag in target.flags:
            target.flags.remove(flag)


def _clear_auto_flags(target):
    """Remove all auto-inferred flags set during the previous attack."""
    for f in getattr(target, '_auto_flags', set()):
        if hasattr(target, 'flags') and f in target.flags:
            target.flags.remove(f)
    target._auto_flags = set()


def _attack_bypass_types(char, attack_kind):
    """Damage types whose resistance this attack ignores: Elemental Adept, dr_bypass
    items (Bonespike), and Monk Ki-Empowered Strikes (L6 unarmed counts as magical,
    bypassing non-magical physical resistance — simplified to bypass Bludgeoning)."""
    bt = set(char.elemental_adept_types()) | set(char.bypass_resistance_types())
    if attack_kind == 'unarmed' and char.class_level('Monk') >= 6:
        bt.add('Bludgeoning')
    return bt


def _attack_action(char, target, action):
    weapon_slot = action.get('weapon', 'main_hand')
    attack_kind = action.get('attack_kind', 'melee')
    equipped_name = char.equipped.get(weapon_slot)
    weapon = char.weapon_for(weapon_slot, attack_kind)
    if weapon is None:
        raise ValueError(
            f"weapon '{weapon_slot}' (name={equipped_name!r}) not found in catalog; "
            f"add it to weapons_named.json / legendary_effects.json or fix the build")
    count = action.get('count', 1)
    # Extra Attack (bg3.wiki class progression): if the action declares "extra_attack":
    # true, add the character's Extra Attack count on top of the base count. This lets
    # builds express "I take the Attack action" without hardcoding the per-class count.
    if action.get('extra_attack'):
        count = count + char.extra_attacks()
    advantage = action.get('advantage', False)
    disadvantage = action.get('disadvantage', False)
    # Reckless Attack (Barbarian 2): toggle on a melee attack grants Advantage (bg3.wiki:
    # enemies also gain Advantage against you — offense-side only here).
    if action.get('reckless') and attack_kind == 'melee' and char.class_level('Barbarian') >= 2:
        advantage = True
    # Assassin subclass (Rogue 3): Assassinate — vs a Surprised target, Advantage + auto-crit.
    assassin_surprise = False
    if char.has_subclass('Rogue', 'Assassin') and 'surprised' in (target.flags or []):
        advantage = True
        assassin_surprise = True
    # Target conditions granting attack advantage (Blinded/Restrained/Stunned/Prone-melee).
    advantage = advantage or _target_grants_advantage(char, target, attack_kind)
    # Auto-inferred condition flags for this attack (bg3.wiki rider conditions that
    # follow from the action declaration, so builds don't have to set them manually):
    #  - attacker_has_advantage: Crimson Mischief Redvein Savagery needs Advantage.
    #  - off_hand_attack: Gloves of the Balanced Hands (off-hand ability mod to damage).
    _clear_auto_flags(target)
    _set_auto_flag(target, 'attacker_has_advantage', advantage and not disadvantage)
    _set_auto_flag(target, 'off_hand_attack', weapon_slot == 'off_hand')

    resolver = char.resolver(attack_kind, weapon)
    atk_bonus = char.attack_bonus(weapon, attack_kind)
    crit_thresh = char.crit_threshold()
    riders = list(char.active_riders(attack_kind))
    flat_bonus = char.damage_bonus(attack_kind)
    savage = char.has_savage_attacker() and attack_kind == 'melee'
    # Half-Orc Savage Attacks: +1 weapon die on melee weapon crit (not thrown/unarmed).
    # Half-Orc Savage Attacks OR Barbarian 9 Brutal Critical: +1 weapon die on melee
    # crit. (Both add one die each; v1 models a single +1 die — stacking is a known
    # simplification, noted in CLAUDE.md.)
    savage_attacks = (char.has_savage_attacks() or char.class_level('Barbarian') >= 9) \
        and attack_kind == 'melee'

    # Smite declaration: applies to a specific attack in the count.
    # action['smite'] = {"slot_level": 2, "attack_index": 0}  (default index 0)
    smite = action.get('smite')
    smite_idx = None
    smite_drs = None
    if smite:
        slot = int(smite.get('slot_level', 1))
        smite_idx = int(smite.get('attack_index', 0))
        smite_drs = _build_smite_drs(slot, target, char)

    per_type = {}
    pinfo = None
    sneak_used = False
    for i in range(count):
        # Sneak Attack is once per turn: include it only on the first eligible attack
        atk_riders = riders
        if sneak_used:
            atk_riders = [r for r in atk_riders if not r.get('once_per_turn')]
        # Smite applies only to the declared attack
        if smite_drs is not None and i == smite_idx:
            atk_riders = atk_riders + [smite_drs]
        # Assassin Assassinate: auto-crit vs Surprised (temporary flag for this attack only).
        _saved_auto_crit = target.auto_crit
        if assassin_surprise:
            target.auto_crit = True
        r = rider_engine.attack_ev(
            weapon, attack_kind, atk_riders, target, resolver,
            atk_bonus, target.ac, crit_threshold_val=crit_thresh,
            advantage=advantage, disadvantage=disadvantage, flat_bonus=flat_bonus,
            savage=savage, honour_mode=char.honour_mode, savage_attacks=savage_attacks,
            halfling_luck=char.has_halfling_luck(),
            bypass_types=_attack_bypass_types(char, attack_kind))
        target.auto_crit = _saved_auto_crit
        # if Sneak Attack fired this attack (eligible + present), mark used
        if not sneak_used and any(r2.get('once_per_turn') for r2 in atk_riders):
            # verify the SA rider's condition was met (it only fires if eligible)
            sa = next((r2 for r2 in atk_riders if r2.get('once_per_turn')), None)
            if sa and rider_engine._condition_met(sa.get('condition'), target):
                sneak_used = True
        pinfo = r
        for dt, v in r['per_type_ev'].items():
            per_type[dt] = per_type.get(dt, 0.0) + v

    post = DamagePool().apply_resistances(
        per_type, target, bypass_types=_attack_bypass_types(char, attack_kind))
    # Portent (Divination Wizard 2): force one attack to hit using a pre-rolled high die.
    # Adds the missed-probability share of one attack's non-crit damage as a guaranteed hit.
    # Declared via active_buff 'Portent' (requires Divination subclass).
    if (char._has_active_buff('Portent') and char.has_subclass('Wizard', 'Divination')
            and char.class_level('Wizard') >= 2 and pinfo):
        p_miss = pinfo.get('p_miss', 0)
        if p_miss > 0 and count > 0:
            # one attack's non-crit EV ~ per_type / count (approx); add the missed share
            single = {dt: v / count for dt, v in per_type.items()}
            for dt, v in single.items():
                post[dt] = post.get(dt, 0.0) + p_miss * v
    # Uncanny Dodge (Rogue 5): reaction to halve one hit's damage. Approximated as
    # halving the whole attack action's EV (one reaction per round). bg3.wiki.
    if getattr(target, 'uncanny_dodge', False):
        post = {dt: v * 0.5 for dt, v in post.items()}
    return {
        'type': 'attack', 'weapon': weapon.get('name', weapon_slot),
        'attack_kind': attack_kind, 'count': count,
        'attack_bonus': atk_bonus, 'crit_threshold': crit_thresh,
        'p_normal': pinfo['p_normal'] if pinfo else 0, 'p_crit': pinfo['p_crit'] if pinfo else 0,
        'per_type_ev': per_type,
        'per_type_ev_post_resist': post,
        'total_ev': sum(post.values()),
    }


def _spell_action(char, target, action):
    spell_name = action.get('ref')
    spell = char.catalog.spell(spell_name)
    if not spell:
        return {'total_ev': 0.0, 'per_type_ev': {}, 'note': f'spell {spell_name} not in catalog'}
    n_targets = action.get('n_targets', 1)
    upcast = action.get('upcast_level', spell.get('level', 1))
    base_level = spell.get('level', 0)
    notes = []
    # Class eligibility check (bg3.wiki spell_classes): warn if the build's classes
    # cannot learn this spell. Doesn't zero the result (racial/item casting still works),
    # but surfaces the mismatch.
    if not char.can_cast(spell_name):
        notes.append(f'class mismatch: {spell_name} not learnable by {char.classes}')
    # Spell-slot cap (bg3.wiki): upcast level cannot exceed the caster's max slot.
    max_slot = char.max_spell_slot()
    if max_slot and upcast > max_slot:
        notes.append(f'upcast {upcast} > max slot {max_slot}; clamped')
        upcast = max_slot
    # Metamagic (bg3.wiki Sorcerer): declared as active_buffs.
    metamagic = {b.get('ref') for b in char.active_buffs if b.get('ref', '').startswith('Metamagic')}
    has_empowered = 'Metamagic: Empowered' in metamagic and char.class_level('Sorcerer') >= 3
    has_heightened = 'Metamagic: Heightened' in metamagic and char.class_level('Sorcerer') >= 3
    # Twinned Spell: single-target spells hit an additional target (n_targets x2).
    if 'Metamagic: Twinned' in metamagic and char.class_level('Sorcerer') >= 3 and n_targets == 1:
        n_targets = 2
    # Destructive Wrath (Cleric Tempest Domain Channel Divinity, L2): deal MAXIMUM
    # Lightning/Thunder damage on a spell. Declared as active_buff; one use per short rest.
    has_destructive_wrath = (char._has_active_buff('Destructive Wrath')
                             and char.has_subclass('Cleric', 'Tempest Domain')
                             and char.class_level('Cleric') >= 2)
    # Wild Magic Surge (Sorcerer Wild Magic subclass): 5% chance per spell of a random
    # surge; a few surges deal damage (self-Fireball ~28, lightning, etc.). Average
    # damage contribution ~1.4 EV/spell (5% * ~28 avg of the damaging surges * ~1 share).
    # Declared via active_buff 'Wild Magic Surge' (requires Wild Magic subclass).
    wild_surge = (char._has_active_buff('Wild Magic Surge')
                  and char.class_level('Sorcerer') >= 1
                  and ('Wild Magic' in str(char.classes)))
    WILD_SURGE_EV = 1.4

    # Resolve the spell's damage sources. A single spell may split into SEVERAL
    # independent damage sources (bg3.wiki Damage_mechanics): each projectile of
    # Magic Missile/Scorching Ray/Eldritch Blast, and each damage[] entry of
    # multi-segment spells (Ice Knife piercing+cold, Hail of Thorns hit+explosion).
    # Each source re-triggers applicable spell riders (DR/DRS).
    sources = _spell_sources(spell, action, char, upcast, base_level)
    if not sources:
        return {'total_ev': 0.0, 'per_type_ev': {}, 'note': 'spell deals no damage'}

    save = spell.get('save')
    is_attack = spell.get('attack_type') == 'spell_attack'

    # Spell-side riders that fire on spell damage (Callous Glow Ring, Necklace of
    # Elemental Augmentation, etc.). Filter by trigger AND condition (rider_engine
    # would normally do this, but spell sources are built here, so apply the same
    # condition check to avoid firing riders whose condition isn't met).
    spell_riders = [r for r in char.active_riders('spell')
                    if r.get('kind') in ('DR', 'DRS')
                    and rider_engine._condition_met(r.get('condition'), target)]
    resolver = char.resolver('spell')

    per_type = {}
    ea_types = set(char.elemental_adept_types())
    _spell_pn = 0.0
    _spell_pc = 0.0
    for src in sources:
        dice_expr, dtype = src['dice'], src['type']
        # Build this source's pool, then layer spell riders (each source is a DS;
        # DRs apply once per source, DRSs add new sources — honour_mode downgrades).
        src_pool = DamagePool([DamageComponent(type=dtype, dice=dice_expr)])
        # Shadow Blade: a spell-weapon that adds STR or DEX modifier to damage (bg3.wiki).
        if spell.get('name') == 'Shadow Blade':
            src_pool.add(DamageComponent(
                type='Psychic',
                flat=max(char.ability_modifier('STR'), char.ability_modifier('DEX'))))
        dr_list = [r for r in spell_riders if r.get('kind') == 'DR']
        drs_list = [r for r in spell_riders if r.get('kind') == 'DRS']
        if char.honour_mode:
            dr_list = dr_list + drs_list
            drs_list = []
        drs_sources = []
        for drs in drs_list:
            d = drs.get('damage', {})
            drs_sources.append(DamagePool([rider_engine._comp_from_rider(
                {'type': d.get('type', dtype), 'dice': d.get('dice'),
                 'flat': d.get('flat'), 'flat_sym': d.get('flat_sym'),
                 'bypass_resistance': d.get('bypass_resistance', False)},
                dtype, resolver)]))
        pool = rider_engine.expand_sources([src_pool] + drs_sources, dr_list, dtype, resolver)

        # Destructive Wrath (Tempest Channel Divinity): Lightning/Thunder dice deal
        # MAXIMUM damage. Convert those components' dice to a flat = max_roll.
        if has_destructive_wrath and dtype in ('Lightning', 'Thunder'):
            from . import dice as _dice
            for c in pool.components:
                if c.type in ('Lightning', 'Thunder') and c.dice:
                    mx = _dice.max_roll(c.dice)
                    c.flat = (c.flat or 0) + mx   # dice EV (cur) is replaced by max
                    c.dice = None

        if save:
            dc = char.spell_save_dc(_spellcasting_ability(char, spell))
            ability = save.get('ability', 'DEX')
            sb = target.save_for(ability)
            save_effect = save.get('save_effect', 'half')
            full = pool.ev(crit=False, resolver=resolver)
            # Heightened Spell (Metamagic): target has Disadvantage on its save -> higher fail rate.
            save_dis = has_heightened or target.save_bonus.get(ability + '_dis', False)
            pf = save_mod.p_fail(dc, sb,
                                 advantage=target.save_bonus.get(ability + '_adv', False),
                                 disadvantage=save_dis)
            ps = 1 - pf
            # Evasion (Rogue 7 / Monk 7): on a DEX save, half-damage spells deal NO damage
            # on a successful save (bg3.wiki). Target flag evasion=True.
            if save_effect == 'half' and ability == 'DEX' and getattr(target, 'evasion', False):
                save_effect = 'none'
            if save_effect in ('none', 'no_damage_on_save'):
                src_ev = pf * full
            elif save_effect == 'full':
                src_ev = full
            else:  # half
                src_ev = pf * full + ps * full / 2.0
        elif is_attack:
            cast_ab = _spellcasting_ability(char, spell)
            atk_bonus = char.spell_attack_bonus(cast_ab)
            crit_thresh = char.crit_threshold(attack_kind='spell')
            pn, pc, pm = p_hit(atk_bonus, target.ac, crit_thresh)
            _spell_pn, _spell_pc = pn, pc  # expose for inflicts_condition hit counting
            bt = pool.ev_by_type(crit=False, resolver=resolver)
            ct = pool.with_doubled_dice().ev_by_type(crit=False, resolver=resolver)
            src_ev_by = {t: pn * bt.get(t, 0) + pc * ct.get(t, 0) for t in set(bt) | set(ct)}
            # Elemental Adept min2 bonus on spell-attack dice (crit pool has doubled dice).
            if ea_types:
                from . import dice as _dice
                for c in pool.components:
                    if c.type in ea_types and c.dice:
                        src_ev_by[c.type] = src_ev_by.get(c.type, 0.0) + pn * _dice.upgrade_min2(c.dice)
                ctp = pool.with_doubled_dice()
                for c in ctp.components:
                    if c.type in ea_types and c.dice:
                        src_ev_by[c.type] = src_ev_by.get(c.type, 0.0) + pc * _dice.upgrade_min2(c.dice)
            # Hat of the Sharp Caster: reroll spell-attack damage dice of 1 or 2, keep
            # higher. Adds upgrade_reroll_low2 to each die term (crit pool doubled too).
            if any(v == 'Hat of the Sharp Caster' for v in char.equipped.values()):
                from . import dice as _dice
                for c in pool.components:
                    if c.dice:
                        src_ev_by[c.type] = src_ev_by.get(c.type, 0.0) + pn * _dice.upgrade_reroll_low2(c.dice)
                ctp = pool.with_doubled_dice()
                for c in ctp.components:
                    if c.dice:
                        src_ev_by[c.type] = src_ev_by.get(c.type, 0.0) + pc * _dice.upgrade_reroll_low2(c.dice)
            # Empowered Spell (Metamagic): reroll damage dice, keep higher (all dice terms).
            if has_empowered:
                from . import dice as _dice
                for c in pool.components:
                    if c.dice:
                        src_ev_by[c.type] = src_ev_by.get(c.type, 0.0) + pn * _dice.upgrade_savage(c.dice)
                ctp = pool.with_doubled_dice()
                for c in ctp.components:
                    if c.dice:
                        src_ev_by[c.type] = src_ev_by.get(c.type, 0.0) + pc * _dice.upgrade_savage(c.dice)
            for t, v in src_ev_by.items():
                per_type[t] = per_type.get(t, 0.0) + v
            continue
        else:
            # auto-hit spell (Magic Missile etc.): no attack roll, no crit
            src_ev = pool.ev(crit=False, resolver=resolver)
        # fold the source pool's per-type EV into a single type bucket for save/auto
        # (pool may have multiple types from riders; expand per type)
        by_t = pool.ev_by_type(crit=False, resolver=resolver)
        # Elemental Adept min2 bonus: dice of ea types cannot roll 1 (treated as 2).
        ea_bonus = {}
        if ea_types:
            for c in pool.components:
                if c.type in ea_types and c.dice:
                    ea_bonus[c.type] = ea_bonus.get(c.type, 0.0) + dice_mod.upgrade_min2(c.dice)
        # Empowered Spell (Metamagic): reroll damage dice keep higher (all dice).
        emp_bonus = {}
        if has_empowered:
            for c in pool.components:
                if c.dice:
                    emp_bonus[c.type] = emp_bonus.get(c.type, 0.0) + dice_mod.upgrade_savage(c.dice)
        if save or not is_attack:
            for t, v in by_t.items():
                # scale by save outcome ratio (same ratio across types for this source)
                ratio = src_ev / sum(by_t.values()) if sum(by_t.values()) else 0
                per_type[t] = per_type.get(t, 0.0) + v * ratio
                if t in ea_bonus:
                    per_type[t] += ea_bonus[t] * ratio
                if t in emp_bonus:
                    per_type[t] += emp_bonus[t] * ratio
    # multiply by number of targets
    per_type = {t: v * n_targets for t, v in per_type.items()}
    # Wild Magic Surge: small random damage contribution per spell cast.
    if wild_surge:
        per_type['Force'] = per_type.get('Force', 0.0) + WILD_SURGE_EV
    post = DamagePool().apply_resistances(per_type, target, bypass_types=ea_types)
    # expected number of hits for inflicts_condition stacking: each source is a hit
    # opportunity; attack-roll spells weight by hit probability, save/auto assume affect.
    if is_attack:
        n_hits = len(sources) * (_spell_pn + _spell_pc)
    elif save:
        n_hits = len(sources)  # save spells still "affect" the target for condition infliction
    else:
        n_hits = len(sources)
    return {
        'type': 'spell', 'spell': spell_name, 'upcast': upcast, 'n_targets': n_targets,
        'per_type_ev': per_type, 'per_type_ev_post_resist': post,
        'total_ev': sum(post.values()),
        'p_normal': _spell_pn, 'p_crit': _spell_pc,
        'n_hits': n_hits,
        'notes': notes,
    }


def _spell_sources(spell, action, char, upcast, base_level):
    """Return list of {dice, type} damage sources for one cast.

    Multi-source spells (Magic Missile, Scorching Ray, Eldritch Blast) expand to one
    source per projectile; multi-segment spells (Ice Knife, Hail of Thorns) expand to
    one source per damage[] entry. Upcast adds projectiles or extra dice.
    """
    ms = char.catalog.multisource_spell(spell.get('name', ''))
    dmg = spell.get('damage', [])
    if not dmg:
        return []
    # Shadow Blade: a spell-weapon. Dice scale 2d8@2nd, +1d8 per 2 slot levels above 2nd
    # (3rd-4th=3d8, 5th-6th=4d8, 7th+=5d8). bg3.wiki Shadow_Blade. Handled here so the
    # spell action deals the right dice; the STR/DEX mod is added in _spell_action.
    if spell.get('name') == 'Shadow Blade':
        ndice = 2 + max(0, (upcast - 1)) // 2  # 2->2, 3->3, 5->4, 7->5
        return [{'dice': f'{ndice}d8', 'type': 'Psychic'}]
    # upcast extra dice for leveled single-source spells (e.g. Fireball +1d6/level)
    upcast_per = spell.get('upcast_per_level', 0) or 0
    extra_dice = upcast_per * max(0, upcast - base_level) if (upcast_per and base_level > 0) else 0

    if ms:
        # projectile-based multi-source spell
        per_proj = ms['per_projectile']
        count = ms.get('projectiles_at_base', 1)
        if 'extra_at_levels' in ms:
            # Eldritch Blast: beam count by caster level (sum of class levels)
            caster_lvl = sum(c['level'] for c in char.classes)
            count = 1
            for lvl, n in sorted(ms['extra_at_levels'].items()):
                if caster_lvl >= lvl:
                    count = n
        else:
            count += ms.get('projectiles_per_upcast', 0) * max(0, upcast - base_level)
        # action['count'] overrides (explicit projectile count from build)
        count = int(action.get('count', count))
        sources = []
        for _ in range(count):
            for seg in per_proj:
                sources.append({'dice': seg['dice'], 'type': seg.get('type', 'Force')})
        return sources

    # default: one source per damage[] entry (handles Ice Knife piercing+cold, etc.)
    sources = []
    for comp in dmg:
        dice_expr = comp.get('dice', '0')
        if extra_dice:
            p = dice_mod.parse(dice_expr)
            if p.dice:
                sides = p.dice[0].sides
                dice_expr = f"{dice_expr} + {extra_dice}d{sides}"
        sources.append({'dice': dice_expr, 'type': comp.get('type', 'Force')})
    return sources


def _wild_shape_action(char, target, action):
    """Druid Wild Shape (bg3.wiki Wild_Shape). The druid attacks in beast form using
    the beast's attack profile (dice + beast STR mod), with Multiattack. Declared as
    {"type":"wild_shape","form":"Owlbear"} — form must be in catalog.BEAST_FORMS."""
    form_name = action.get('form', '')
    form = char.catalog.beast_form(form_name)
    if not form:
        return {'total_ev': 0.0, 'per_type_ev': {}, 'note': f'beast form {form_name!r} not found'}
    if form.get('moon_only') and not char.has_subclass('Druid', 'Circle of the Moon'):
        return {'total_ev': 0.0, 'per_type_ev': {}, 'note': f'{form_name} requires Circle of the Moon'}
    # beast attacks use the beast's STR mod (not the druid's); prof from druid total level.
    prof = char.prof
    atk_bonus = prof + form['attacks'][0]['str_mod']  # approx, beast STR mod
    n_attacks = action.get('count', form.get('multiattack', 1))
    pn, pc, pm = p_hit(atk_bonus, target.ac, char.crit_threshold(),
                       advantage=action.get('advantage', False))
    per_type = {}
    for _ in range(n_attacks):
        for atk in form['attacks']:
            from . import dice as _dice
            base_dmg = _dice.ev(atk['dice']) + atk['str_mod']
            crit_dmg = _dice.ev(atk['dice'], crit=True) + atk['str_mod']
            ev = pn * base_dmg + pc * crit_dmg
            per_type[atk['type']] = per_type.get(atk['type'], 0.0) + ev
    post = DamagePool().apply_resistances(per_type, target)
    return {'type': 'wild_shape', 'form': form_name, 'count': n_attacks,
            'attack_bonus': atk_bonus, 'p_normal': pn, 'p_crit': pc,
            'per_type_ev': per_type, 'per_type_ev_post_resist': post,
            'total_ev': sum(post.values())}


def _summon_action(char, target, action):
    """Summon spells (Animate Dead / Conjure Elemental / etc.): the summon makes one
    attack per round. Declared as {"type":"summon","summon":"Skeleton","attack_bonus":N}.
    The summon's per-round attack EV is added (bg3.wiki summon stat blocks)."""
    summon = action.get('summon', '')
    atk = SUMMON_ATTACKS.get(summon)
    if not atk:
        return {'total_ev': 0.0, 'per_type_ev': {}, 'note': f'summon {summon!r} not in SUMMON_ATTACKS'}
    ab = action.get('attack_bonus', atk.get('attack_bonus', 4))
    pn, pc, pm = p_hit(ab, target.ac, 20)
    from . import dice as _dice
    base = _dice.ev(atk['dice']) + atk.get('flat', 0)
    crit = _dice.ev(atk['dice'], crit=True) + atk.get('flat', 0)
    per_type = {atk['type']: pn * base + pc * crit}
    # extra damage (e.g. Skeleton +1d10 Necrotic, Mummy +6d6 Necrotic)
    ex = atk.get('extra')
    if ex:
        ex_base = _dice.ev(ex['dice'])
        ex_crit = _dice.ev(ex['dice'], crit=True)
        per_type[ex['type']] = per_type.get(ex['type'], 0.0) + pn * ex_base + pc * ex_crit
    post = DamagePool().apply_resistances(per_type, target)
    return {'type': 'summon', 'summon': summon, 'per_type_ev': per_type,
            'per_type_ev_post_resist': post, 'total_ev': sum(post.values())}


def _ki_spell_action(char, target, action):
    """Way of the Four Elements ki spells (bg3.wiki). Declared as
    {"type":"ki_spell","ref":"<name>"} — looks up KI_SPELLS for dice/save/type."""
    name = action.get('ref', '')
    ki = KI_SPELLS.get(name)
    if not ki:
        return {'total_ev': 0.0, 'per_type_ev': {}, 'note': f'ki spell {name!r} not in KI_SPELLS'}
    if char.class_level('Monk') < 3 or 'Way of the Four Elements' not in str(char.classes):
        return {'total_ev': 0.0, 'per_type_ev': {}, 'note': f'{name} requires Way of the Four Elements'}
    dc = 8 + char.prof + char.ability_modifier('WIS')  # monk ki save DC = WIS
    n_targets = action.get('n_targets', 1)
    if ki.get('attack'):
        # spell-attack ki (e.g. Embrace of the Inferno): roll vs AC
        atk_bonus = char.prof + char.ability_modifier('WIS')
        pn, pc, pm = p_hit(atk_bonus, target.ac, 20)
        full = dice_mod.ev(ki['dice'])
        crit = dice_mod.ev(ki['dice'], crit=True)
        per_target = pn * full + pc * crit
    elif ki.get('save'):
        ability = ki['save']
        sb = target.save_for(ability)
        pf = save_mod.p_fail(dc, sb)
        full = dice_mod.ev(ki['dice'])
        per_target = pf * full + (1 - pf) * full / 2.0 if ki.get('save_effect') == 'half' else pf * full
    else:
        per_target = dice_mod.ev(ki['dice'])
    per_type = {ki['type']: per_target * n_targets}
    post = DamagePool().apply_resistances(per_type, target)
    return {'type': 'ki_spell', 'spell': name, 'per_type_ev': per_type,
            'per_type_ev_post_resist': post, 'total_ev': sum(post.values())}


def _spellcasting_ability(char, spell):
    """Infer spellcasting ability from build classes. Default CHA."""
    classes = {c['cls'].lower() for c in char.classes}
    if 'wizard' in classes or 'fighter' in classes and 'eldritch' in str(char.feats).lower():
        return 'INT'
    if 'cleric' in classes or 'druid' in classes or 'ranger' in classes:
        return 'WIS'
    return 'CHA'


def _racial_breath_action(char, target, action):
    """Dragonborn breath weapon (bg3.wiki raw_races/*_Breath.html).

    2d6 -> 3d6 @ char level 6 -> 4d6 @ char level 11. Save DC = 8 + CON mod +
    proficiency. Half damage on save. Damage type / save ability / shape by subrace
    (catalog.DRAGONBORN_BREATH). n_targets applies the AoE target count.
    """
    from .catalog import DRAGONBORN_BREATH
    species = char.species or ''
    subrace = species.split(':', 1)[1] if ':' in species else ''
    breath = DRAGONBORN_BREATH.get(subrace)
    if not breath:
        return {'total_ev': 0.0, 'per_type_ev': {},
                'note': f'no breath weapon for species {species!r}'}
    dmg_type, save_ability, _shape = breath
    n_targets = action.get('n_targets', 1)
    char_lvl = sum(c['level'] for c in char.classes)
    dice = 2 if char_lvl < 6 else (3 if char_lvl < 11 else 4)
    dice_expr = f'{dice}d6'
    dc = 8 + char.ability_modifier('CON') + char.prof
    sb = target.save_for(save_ability)
    per_target = save_mod.save_spell_ev(
        dice_expr, dc, sb, save_effect='half',
        advantage=target.save_bonus.get(save_ability + '_adv', False))
    per_type = {dmg_type: per_target * n_targets}
    post = DamagePool().apply_resistances(per_type, target)
    return {'type': 'racial_breath', 'spell': f'{subrace} Breath', 'upcast': char_lvl,
            'n_targets': n_targets, 'per_type_ev': per_type,
            'per_type_ev_post_resist': post, 'total_ev': sum(post.values())}


def _bonus_attack_action(char, target, action):
    """Bonus-action extra attack from feats (bg3.wiki Feats).

    Polearm Master: when wielding a polearm (Glaive/Halberd/Pike/Quarterstaff/Spear),
    a bonus action attacks with the butt for 1d4 + max(STR,DEX) of the weapon's type.
    GWM Bonus Attack: on crit/kill, another melee weapon attack (full weapon).
    Declared in round_actions as {"type":"bonus_attack","feat":"Polearm Master",...}
    or {"type":"bonus_attack","feat":"Great Weapon Master","trigger_on_crit":true}.
    """
    feat = action.get('feat', '')
    weapon_slot = action.get('weapon', 'main_hand')
    attack_kind = action.get('attack_kind', 'melee')
    weapon = char.weapon_for(weapon_slot, attack_kind)
    if weapon is None:
        return {'total_ev': 0.0, 'per_type_ev': {}, 'note': 'bonus_attack weapon missing'}

    if feat == 'Polearm Master':
        # butt end: 1d4 + max(STR,DEX), weapon's damage type
        wtype = weapon.get('damage_type') or 'Bludgeoning'
        amod = max(char.ability_modifier('STR'), char.ability_modifier('DEX'))
        butt_weapon = {'name': 'Polearm Butt', 'die': '1d4', 'enchantment': 0,
                       'damage_type': wtype, 'properties': ''}
        # synthesize an attack action and reuse _attack_action logic via a temp weapon
        synth_action = dict(action)
        synth_action.pop('feat', None)
        synth_action['type'] = 'attack'
        # temporarily swap the slot's weapon to the butt weapon
        orig = char.equipped.get(weapon_slot)
        char.equipped[weapon_slot] = '__polearm_butt__'
        # inject butt weapon into catalog patch? simpler: monkeypatch weapon_for
        _orig_weapon_for = char.weapon_for
        char.weapon_for = lambda slot='main_hand', kind='melee': butt_weapon if slot == weapon_slot else _orig_weapon_for(slot, kind)
        r = _attack_action(char, target, synth_action)
        char.weapon_for = _orig_weapon_for
        char.equipped[weapon_slot] = orig
        # butt attack uses max(STR,DEX) not the build's attack_ability — approximate
        # by overriding attack_bonus already applied via attack_ability_mod; the butt
        # weapon has no enchantment so only prof + ability. Re-add the STR/DEX delta.
        r['note'] = 'Polearm Master butt (1d4 + max(STR,DEX))'
        return r
    elif feat == 'Great Weapon Master':
        # GWM Bonus Attack: another full melee weapon attack, triggered on crit/kill.
        # Weight by p_crit (kill approximated as p_crit for EV purposes).
        synth_action = dict(action)
        synth_action.pop('feat', None)
        synth_action.pop('trigger_on_crit', None)
        synth_action['type'] = 'attack'
        r = _attack_action(char, target, synth_action)
        pcrit = r.get('p_crit', 0.0)
        # scale this bonus attack's EV by crit probability (trigger chance)
        scaled_post = {t: v * pcrit for t, v in r.get('per_type_ev_post_resist', {}).items()}
        scaled_pre = {t: v * pcrit for t, v in r.get('per_type_ev', {}).items()}
        return {'type': 'bonus_attack', 'note': f'GWM bonus attack (x p_crit={pcrit:.2f})',
                'per_type_ev': scaled_pre, 'per_type_ev_post_resist': scaled_post,
                'total_ev': sum(scaled_post.values())}
    return {'total_ev': 0.0, 'per_type_ev': {}, 'note': f'unknown bonus_attack feat {feat}'}
