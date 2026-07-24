"""The DS / DR / DRS expansion engine — the heart of BG3 damage calc.

Verified mechanics (bg3.wiki Damage_mechanics):
- A Damage Source (DS) is an attack/effect that directly deals damage. One weapon
  attack = 1 DS = (weapon die + enchantment + ability mod) of a damage type.
- A Damage Rider (DR) adds bonus damage that "rides" a DS; it triggers ONCE per DS.
- A Damage Rider treated as Source (DRS) is itself a new DS — it triggers another
  round of all DRs. Depth is capped at 2 (BG3 has no DRS-that-spawns-DRS chain).

Algorithm:
  sources = [base DS] + [each DRS as a new DS]
  total_pool = sum over sources of (source + apply_all_DRs(source))

Crit is applied at EV time via with_doubled_dice(): dice components double, flat
components (enchantment, ability mod, flat riders like Caustic Band +2) do NOT.

Resistance is applied per-type at the very end by DamagePool.apply_resistances().
"""
from .damage import DamageComponent, DamagePool
from . import dice as dice_mod
import re


def _resolve_flat(val, resolver):
    """val is int or symbolic string like 'str_mod'. resolver maps symbols->int."""
    if val is None:
        return 0
    if isinstance(val, str):
        return int(resolver(val))
    return int(val)


def build_base_ds(weapon, attack_kind, resolver, flat_bonus=0, savage=False,
                  savage_attacks=False) -> DamagePool:
    """The weapon's own DS: die + enchantment(flat) + ability mod(flat) + flat_bonus.

    flat_bonus: extra flat damage of the weapon's type (e.g. GWM/Sharpshooter +10).
    savage: if True, apply Savage Attacker (reroll weapon dice, keep higher) as a
            flat bonus of the weapon's type. (Crit-doubling of the savage bonus is
            approximated away in v1 — the non-crit majority is exact.)
    savage_attacks: if True, mark the base weapon-die component so a crit adds ONE
            extra die (Half-Orc racial). Only melee weapon attacks (caller filters).
    """
    pool = DamagePool()
    wtype = weapon.get('damage_type') or 'Slashing'
    # Resolve die expression: weapons may use 'die' ("1d8") or 'damage' ("1d8 Slashing"/"1d8 + 1")
    die = weapon.get('die')
    extra_flat = 0
    if not die and weapon.get('damage'):
        dmg = str(weapon['damage'])
        m = re.match(r'\s*(\d+d\d+)(?:\s*\+\s*(\d+))?', dmg)
        if m:
            die = m.group(1)
            extra_flat = int(m.group(2)) if m.group(2) else 0
    if die:
        pool.add(DamageComponent(type=wtype, dice=die, savage_attacks=savage_attacks))
        if savage:
            # Savage Attacker: extra EV from reroll-keep-higher on the weapon dice
            extra = dice_mod.upgrade_savage(die)
            if extra > 0:
                pool.add(DamageComponent(type=wtype, flat=extra))
    else:
        # no die (e.g. non-monk unarmed base 1)
        bf = weapon.get('base_flat', 0)
        if bf:
            pool.add(DamageComponent(type=wtype, flat=bf))
    try:
        ench = int(weapon.get('enchantment') or 0)
    except (ValueError, TypeError):
        ench = 0
    if ench or extra_flat:
        pool.add(DamageComponent(type=wtype, flat=ench + extra_flat))
    # flat damage bonus from attack modifiers (GWM/Sharpshooter +10) — weapon type
    if flat_bonus:
        pool.add(DamageComponent(type=wtype, flat=int(flat_bonus)))
    # ability modifier for the attack
    amod = resolver('ability_mod')
    if amod:
        pool.add(DamageComponent(type=wtype, flat=amod))
    return pool


def applicable_riders(riders, attack_kind, target, resolver):
    """Filter a list of rider dicts to those that fire for this attack.

    Each rider: {trigger, kind, damage:{dice,flat,type,flat_sym}, condition, ...}
    trigger taxonomy: weapon_attack_hit, melee_weapon_attack_hit,
        ranged_weapon_attack_hit, thrown_attack_hit, unarmed_attack_hit,
        spell_attack_hit, spell_damage_dealt.
    attack_kind maps: melee->weapon_attack_hit+melee_weapon_attack_hit,
        ranged->weapon_attack_hit+ranged_weapon_attack_hit,
        thrown->thrown_attack_hit, unarmed->unarmed_attack_hit, spell->spell_attack_hit.
    """
    kind_map = {
        'melee': {'weapon_attack_hit', 'melee_weapon_attack_hit'},
        'ranged': {'weapon_attack_hit', 'ranged_weapon_attack_hit'},
        'thrown': {'thrown_attack_hit', 'weapon_attack_hit'},
        'unarmed': {'unarmed_attack_hit'},
        'spell': {'spell_attack_hit', 'spell_damage_dealt'},
    }
    active_triggers = kind_map.get(attack_kind, set())
    out = []
    for r in riders:
        # trigger may be a single value or pipe-separated
        triggers = r.get('trigger', '').split('|')
        if not any(t in active_triggers for t in triggers):
            continue
        # condition check (simple: target_has:X etc. — handled by caller setting flags)
        if not _condition_met(r.get('condition'), target):
            continue
        out.append(r)
    return out


def _condition_met(cond, target):
    """Evaluate a condition expression against target. None = always met.

    Supported: target_has:ConditionName (target.conditions list),
               any named flag in target.flags (e.g. sneak_attack_eligible,
               target_le_half_hp, target_illuminated, target_obscured,
               attacker_has_advantage, self_healed_recently).
    Unset flags -> condition not met (rider skipped).
    """
    if not cond:
        return True
    conds = set(getattr(target, 'conditions', []) or [])
    flags = set(getattr(target, 'flags', []) or [])
    if cond.startswith('target_has:'):
        return cond.split(':', 1)[1] in conds
    # any other condition string is treated as a flag the build must set
    return cond in flags


def _trigger_matches(trigger_str, attack_kind):
    """True if any of a rider's pipe-separated triggers is active for attack_kind."""
    kind_map = {
        'melee': {'weapon_attack_hit', 'melee_weapon_attack_hit'},
        'ranged': {'weapon_attack_hit', 'ranged_weapon_attack_hit'},
        'thrown': {'thrown_attack_hit', 'weapon_attack_hit'},
        'unarmed': {'unarmed_attack_hit'},
        'spell': {'spell_attack_hit', 'spell_damage_dealt'},
    }
    active_triggers = kind_map.get(attack_kind, set())
    return any(t in active_triggers for t in trigger_str.split('|'))


def _rider_type(dmg, wtype):
    """Resolve a rider's damage type; 'SameAsWeapon'/'SameAsSpell' -> the triggering
    source's type (wtype is the weapon or spell-source damage type)."""
    t = dmg.get('type', 'Force')
    return wtype if t in ('SameAsWeapon', 'SameAsSpell') else t


def expand_attack(weapon, attack_kind, riders, target, resolver, flat_bonus=0, savage=False,
                  honour_mode=False, savage_attacks=False, bypass_types=None) -> DamagePool:
    """One attack -> DamagePool (pre-resistance, dice at 1x; crit applied later).

    riders: list of ALL active riders (equipment + buffs + feats), pre-filtered here.
    resolver: callable(str)->int mapping 'ability_mod','str_mod','prof','dex_mod' etc.
    flat_bonus: flat weapon-type damage from GWM/Sharpshooter (not doubled on crit).
    savage: apply Savage Attacker to the weapon dice (reroll keep higher).
    honour_mode: if True, DRS riders are downgraded to plain DR (bg3.wiki Honour Mode
        exception) — they no longer act as new damage sources and do not re-trigger DRs.
    """
    base_ds = build_base_ds(weapon, attack_kind, resolver, flat_bonus=flat_bonus,
                            savage=savage, savage_attacks=savage_attacks)
    wtype = weapon.get('damage_type') or 'Slashing'
    active = applicable_riders(riders, attack_kind, target, resolver)

    if honour_mode:
        # Honour mode: every DRS becomes a plain DR (no new source, no re-trigger).
        # DS_added is a legacy alias for DRS (an added damage source); treat alike.
        drs_list = []
        dr_list = [r for r in active if r.get('kind') in ('DR', 'DRS', 'DS_added')]
    else:
        drs_list = [r for r in active if r.get('kind') in ('DRS', 'DS_added')]
        dr_list = [r for r in active if r.get('kind') == 'DR']

    # Each DRS becomes a new DS (its own DamagePool of one component).
    drs_sources = []
    for drs in drs_list:
        dmg = drs.get('damage', {})
        drs_sources.append(DamagePool([_comp_from_rider(dmg, wtype, resolver)]))

    return expand_sources([base_ds] + drs_sources, dr_list, wtype, resolver, bypass_types)


def _comp_from_rider(dmg, wtype, resolver, bypass_types=None):
    """Build a DamageComponent from a rider's damage dict."""
    rtype = _rider_type(dmg, wtype)
    return DamageComponent(
        type=rtype,
        dice=dmg.get('dice'),
        flat=_resolve_flat(dmg.get('flat'), resolver),
        flat_sym=dmg.get('flat_sym'),
        bypass_resistance=bool(dmg.get('bypass_resistance', False)) or
        (rtype in (bypass_types or set())))


def expand_sources(sources, dr_list, wtype, resolver, bypass_types=None):
    """Apply all DRs to each source. Shared core of attack and spell expansion.

    sources: list of DamagePool (each is one DS — base DS and each DRS for attacks,
        or each projectile/segment for multi-source spells).
    dr_list: DR riders to apply once per source.
    wtype: weapon/triggering damage type, for resolving 'SameAsWeapon' rider types.
    bypass_types: damage types that bypass resistance/immunity (Elemental Adept).
    Returns a single combined DamagePool.
    """
    total = DamagePool()
    for src in sources:
        # also flag source components matching bypass_types
        for c in src.components:
            if c.type in (bypass_types or set()) and not c.bypass_resistance:
                c.bypass_resistance = True
        total = total + src
        for dr in dr_list:
            dmg = dr.get('damage', {})
            total.add(_comp_from_rider(dmg, wtype, resolver, bypass_types))
    return total


def attack_ev(weapon, attack_kind, riders, target, resolver,
              attack_bonus, ac, crit_threshold_val=20, advantage=False, disadvantage=False,
              flat_bonus=0, savage=False, honour_mode=False, savage_attacks=False,
              halfling_luck=False, bypass_types=None):
    """Full per-attack expected damage vs AC.

    Returns dict: {per_type_ev (pre-resist), per_type_ev_post_resist, total_ev}.

    Target crit state (target.crit_immune / target.auto_crit) is read here and
    passed to p_hit. on_crit riders (Sword of Life Stealing, Craterflesh Gloves)
    fire only on a crit; their dice are doubled by the crit (Craterflesh +1d6 -> 2d6)
    while their flat values are not (Life Stealing +10 stays). They contribute only
    to the crit branch (weighted by p_crit).
    """
    from .attack import p_hit
    crit_immune = bool(getattr(target, 'crit_immune', False))
    # auto_crit (Paralysed/Sleeping) applies to melee-range attacks only (bg3.wiki).
    auto_crit = bool(getattr(target, 'auto_crit', False)) and attack_kind in ('melee', 'thrown', 'unarmed')
    pn, pc, pm = p_hit(attack_bonus, ac, crit_threshold_val, advantage, disadvantage,
                       crit_immune=crit_immune, auto_crit=auto_crit,
                       halfling_luck=halfling_luck)
    base_pool = expand_attack(weapon, attack_kind, riders, target, resolver,
                              flat_bonus=flat_bonus, savage=savage, honour_mode=honour_mode,
                              savage_attacks=savage_attacks, bypass_types=bypass_types)
    crit_pool = base_pool.with_doubled_dice()

    # on_crit riders: fire only on a critical hit. They are NOT subject to the normal
    # condition filter (their 'condition' is the literal 'on_crit' marker), so we pull
    # them straight from the raw rider list. Dice double with the crit; flat does not.
    on_crit_riders = [r for r in riders
                      if r.get('condition') == 'on_crit' and r.get('kind') in ('DR', 'DRS')
                      and _trigger_matches(r.get('trigger', ''), attack_kind)]
    on_crit_dice_pool = DamagePool()
    on_crit_flat_by_type = {}
    wtype = weapon.get('damage_type') or 'Slashing'
    for r in on_crit_riders:
        dmg = r.get('damage', {})
        rt = _rider_type(dmg, wtype)
        if dmg.get('dice'):
            on_crit_dice_pool.add(DamageComponent(type=rt, dice=dmg['dice']))
        if dmg.get('flat') or dmg.get('flat_sym'):
            on_crit_flat_by_type[rt] = on_crit_flat_by_type.get(rt, 0.0) + _resolve_flat(dmg.get('flat'), resolver)
    # crit-doubled dice EV for the on_crit dice
    on_crit_dice_ev = on_crit_dice_pool.with_doubled_dice().ev_by_type(crit=False, resolver=resolver)

    per_type = {}
    bt = base_pool.ev_by_type(crit=False, resolver=resolver)
    # crit_pool already has dice physically doubled via with_doubled_dice(),
    # so evaluate it at crit=False (don't double again).
    ct = crit_pool.ev_by_type(crit=False, resolver=resolver)
    for dtype in set(bt) | set(ct) | set(on_crit_dice_ev) | set(on_crit_flat_by_type):
        crit_val = ct.get(dtype, 0.0) + on_crit_dice_ev.get(dtype, 0.0) + on_crit_flat_by_type.get(dtype, 0.0)
        per_type[dtype] = pn * bt.get(dtype, 0.0) + pc * crit_val

    # Elemental Adept: damage dice of the chosen type cannot roll a 1 (treated as 2).
    # Add the extra EV per die term of matching type, weighted by hit/crit (crit pool
    # has doubled dice, so its min2 bonus is also doubled).
    if bypass_types:
        from . import dice as _dice
        for dtype in bypass_types:
            for c in base_pool.components:
                if c.type == dtype and c.dice:
                    per_type[dtype] = per_type.get(dtype, 0.0) + pn * _dice.upgrade_min2(c.dice)
            for c in crit_pool.components:
                if c.type == dtype and c.dice:
                    per_type[dtype] = per_type.get(dtype, 0.0) + pc * _dice.upgrade_min2(c.dice)

    post = base_pool.apply_resistances(per_type, target)
    total = sum(post.values())
    return {
        'p_normal': pn, 'p_crit': pc, 'p_miss': pm,
        'per_type_ev': per_type,
        'per_type_ev_post_resist': post,
        'total_ev': total,
    }
