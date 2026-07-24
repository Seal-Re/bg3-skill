"""Character: load a build definition + target, compute derived stats, and
provide a resolver() for symbolic flats (str_mod, ability_mod, prof, etc.).

Build JSON schema (data/builds/<name>.json):
  classes: [{cls, level}], abilities: {STR,DEX,...}, proficiency_bonus: int,
  feats: [name], equipped: {main_hand, off_hand, armor, ring1, ring2, gloves, ...},
  active_buffs: [{ref, ...}], target: {ac, save_bonus, resistances, ...},
  round_actions: [{type, ...}]
"""
import json, os
from .catalog import Catalog

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')


def ability_mod(score):
    return (score - 10) // 2


class Target:
    def __init__(self, d):
        self.ac = d.get('ac', 15)
        self.save_bonus = d.get('save_bonus', {})  # {DEX: 5, ...}
        self.resistances = d.get('resistances', [])
        self.immunities = d.get('immunities', [])
        self.vulnerabilities = d.get('vulnerabilities', [])
        self.conditions = d.get('conditions', [])
        self.flags = d.get('flags', [])  # target_illuminated, target_le_half_hp, ...
        self.creature_type = d.get('creature_type', '')  # 'undead','fiend','humanoid',...
        # crit_immune: Adamantine etc. — nat20 is a plain hit (no crit).
        # auto_crit: Paralysed/Sleeping target — every hit crits (bg3.wiki Critical_hit).
        # These may be set directly on the target dict or derived from conditions
        # (see Character.apply_target_condition_effects) at round setup.
        self.crit_immune = bool(d.get('crit_immune', False))
        self.auto_crit = bool(d.get('auto_crit', False))
        # species: when the target represents a player character (e.g. computing
        # damage a PC receives), its species drives racial resistances / save advantage.
        self.species = d.get('species', '')
        # equipped: defensive gear worn by a PC target (Adamantine crit immunity,
        # Superior Padding/Magical Plate flat reduction). Applied at round setup.
        self.equipped = d.get('equipped', {}) or {}
        self.flat_reduction = {}  # {type: flat} or {'all': flat}, filled by round setup
        # Defensive class features (承受侧, bg3.wiki): Evasion (Rogue7/Monk7) halves DEX-save
        # spell dmg to 0 on success; Uncanny Dodge (Rogue5) reaction-halves one hit.
        self.evasion = bool(d.get('evasion', False))
        self.uncanny_dodge = bool(d.get('uncanny_dodge', False))

    def save_for(self, ability):
        return self.save_bonus.get(ability, 0)


class Character:
    def __init__(self, build):
        self.build = build
        self.abilities = build.get('abilities', {})
        self.classes = build.get('classes', [])
        # proficiency bonus: bg3.wiki (total_level-1)//4 + 2, capped at 6.
        # 1-4=2, 5-8=3, 9-12=4, 13-16=5, 17-20=6. Auto-derived if the build omits it;
        # an explicit proficiency_bonus in the build is respected (back-compat).
        if 'proficiency_bonus' in build:
            self.prof = build['proficiency_bonus']
        else:
            total_lvl = sum(c.get('level', 0) for c in self.classes)
            self.prof = min(6, (max(0, total_lvl - 1)) // 4 + 2)
        self.feats = build.get('feats', [])
        self.equipped = build.get('equipped', {})
        self.active_buffs = build.get('active_buffs', [])
        # Fighting Style (Fighter/Paladin/Ranger L1): 'Archery'/'Dueling'/
        # 'Two-Weapon Fighting'/'Great Weapon Fighting'. bg3.wiki class feature.
        self.fighting_style = build.get('fighting_style', '')
        self.catalog = Catalog.get()
        # primary attack ability: STR for melee/thrown, DEX for ranged/finesse
        self.attack_ability = build.get('attack_ability', 'STR')
        # Honour mode: nearly all DRS effects are treated as plain DR (bg3.wiki
        # Damage_mechanics Honour Mode exception). When True, rider_engine downgrades
        # DRS -> DR so they no longer act as new damage sources.
        self.honour_mode = bool(build.get('honour_mode', False))
        # Species (race). Encoded as "Race" or "Race:Subrace" (e.g. "Dragonborn:Black",
        # "Halfling:Strongheart"). Drives racial resistances, Savage Attacks, Halfling
        # Luck, breath weapon, and save advantages (bg3.wiki raw_races/).
        self.species = build.get('species', '')

    @classmethod
    def from_file(cls, path):
        return cls(json.load(open(path, encoding='utf-8')))

    # ---- derived stats ----
    def ability_modifier(self, ability):
        return ability_mod(self.abilities.get(ability, 10))

    def attack_ability_mod(self, attack_kind='melee', weapon=None):
        """Ability mod for the attack. Finesse/ranged -> DEX if higher; else attack_ability."""
        if attack_kind in ('ranged',):
            return self.ability_modifier('DEX')
        if weapon and 'Finesse' in (weapon.get('properties', '') if isinstance(weapon.get('properties'), str) else ''):
            return max(self.ability_modifier('STR'), self.ability_modifier('DEX'))
        if attack_kind == 'unarmed':
            # monk: DEX or STR (Dextrous Attacks); else STR
            return self.ability_modifier(self.attack_ability) if self.attack_ability in ('DEX','STR') else max(self.ability_modifier('STR'), self.ability_modifier('DEX'))
        return self.ability_modifier(self.attack_ability)

    def attack_bonus(self, weapon, attack_kind):
        """Total attack roll bonus: prof + ability mod + weapon enchantment + item bonuses.

        INTENTIONALLY NOT MODELLED (bg3.wiki Attack_roll): Bless (+1d4), high-ground
        (+/-2), coatings, and other misc attack-roll sources.
        """
        bonus = self.prof + self.attack_ability_mod(attack_kind, weapon)
        bonus += int(weapon.get('enchantment', 0) or 0)
        # attack_modifier riders (GWM/Sharpshooter toggle, Legacy of the Masters +2,
        # Circlet of Hunting +1d4 approximated as +2.5, Marksmanship Hat +1, etc.)
        from . import dice as _dice
        for mod in self._attack_modifiers():
            bonus += mod.get('attack_bonus', 0)
            if mod.get('attack_bonus_dice'):
                # approximate a bonus die as its EV (e.g. 1d4 -> +2.5) on the attack roll
                bonus += _dice.ev(mod['attack_bonus_dice'])
        # Fighting Style: Archery (+2 to ranged attack rolls).
        if self.fighting_style == 'Archery' and attack_kind == 'ranged':
            bonus += 2
        # Tavern Brawler: STR mod added twice to the Attack Roll (and damage) on
        # unarmed / improvised / thrown attacks (bg3.wiki Feats).
        if 'Tavern Brawler' in self.feats and attack_kind in ('unarmed', 'thrown'):
            bonus += self.ability_modifier('STR')
        return bonus

    def _attack_modifiers(self):
        out = []
        seen = set()  # dedupe by source (a feat and its active_buff ref can both resolve
                      # to the same rider, e.g. GWM feat + 'Great Weapon Master (active)' buff)
        cat = self.catalog
        # equipped items with attack_modifier riders (e.g. Legacy of the Masters +2/+2,
        # Circlet of Hunting +1d4, Marksmanship Hat +1)
        for slot, name in self.equipped.items():
            if not name:
                continue
            for r in cat.riders_for_item(name):
                if r.get('kind') == 'attack_modifier':
                    key = r.get('source', '') + str(r.get('attack_bonus')) + str(r.get('damage_bonus'))
                    if key not in seen:
                        seen.add(key); out.append(r)
        # check feats (e.g. "Great Weapon Master") and active buffs
        sources = list(self.feats) + [b.get('ref') for b in self.active_buffs if b.get('ref')]
        for f in sources:
            if not f:
                continue
            # try exact key, then "(active)" suffix (GWM/Sharpshooter toggle)
            for key in (f, f + ' (active)'):
                r = cat.rider_by_key(key)
                if r:
                    if isinstance(r, list):
                        for rr in r:
                            if rr.get('kind') == 'attack_modifier':
                                k = rr.get('source', '') + str(rr.get('attack_bonus')) + str(rr.get('damage_bonus'))
                                if k not in seen:
                                    seen.add(k); out.append(rr)
                    elif r.get('kind') == 'attack_modifier':
                        k = r.get('source', '') + str(r.get('attack_bonus')) + str(r.get('damage_bonus'))
                        if k not in seen:
                            seen.add(k); out.append(r)
                    break
        return out

    def damage_bonus(self, attack_kind='melee'):
        """Flat damage bonus from active attack modifiers (e.g. GWM/Sharpshooter +10)
        + Dueling fighting style (+2 melee, one-handed). Applied to the weapon's DS."""
        bonus = sum(int(m.get('damage_bonus', 0) or 0) for m in self._attack_modifiers())
        # Fighting Style: Dueling (+2 damage with a one-handed melee weapon, no off-hand).
        if self.fighting_style == 'Dueling' and attack_kind == 'melee' and not self.equipped.get('off_hand'):
            bonus += 2
        return bonus

    def target_vulnerabilities(self):
        """Damage types the attacker forces the target to be vulnerable to
        (e.g. Bhaalist Armour -> Piercing). Drawn from equipped items' riders
        of kind 'target_vulnerability'."""
        out = []
        cat = self.catalog
        for slot, name in self.equipped.items():
            if not name:
                continue
            for r in cat.riders_for_item(name):
                if r.get('kind') == 'target_vulnerability' and r.get('vulnerability'):
                    out.append(r['vulnerability'])
        return out

    def bypass_resistance_types(self):
        """Damage types whose resistance/immunity the attacker ignores, from equipped
        items of kind 'dr_bypass' (e.g. Bonespike Gloves ignore S/P/B resistance)."""
        out = []
        cat = self.catalog
        for slot, name in self.equipped.items():
            if not name:
                continue
            for r in cat.riders_for_item(name):
                if r.get('kind') == 'dr_bypass':
                    out.extend(r.get('bypass_types', []) or [])
        return out

    def has_savage_attacker(self):
        """True if the Savage Attacker feat is present (reroll melee weapon dice)."""
        feats = {f.lower() for f in self.feats}
        return 'savage attacker' in feats

    # ---- species (race) derived traits (bg3.wiki raw_races/) ----
    def self_resistances(self):
        """Damage types this character resists (when computing damage the character
        RECEIVES). Sources: species (Tiefling Fire, Dwarf/Duergar/Strongheart-Halfling
        Poison, Dragonborn by ancestry) + active Rage (Barbarian: physical B/P/S)."""
        from .catalog import SPECIES_RESISTANCES
        out = list(SPECIES_RESISTANCES.get(self.species, []))
        # Rage (Barbarian): resistance to bludgeoning/piercing/slashing while raging.
        if self._has_active_buff('Rage (Barbarian)') and self.class_level('Barbarian') >= 1:
            for t in ('Bludgeoning', 'Piercing', 'Slashing'):
                if t not in out:
                    out.append(t)
        return out

    def _has_active_buff(self, ref):
        return any(b.get('ref') == ref for b in self.active_buffs)

    def has_savage_attacks(self):
        """Half-Orc racial: +1 weapon die on melee weapon crit (not the whole group)."""
        return self.species == 'Half-Orc'

    def has_halfling_luck(self):
        """Halfling racial: reroll a natural 1 on attack rolls/saves, keep new roll."""
        return self.species.startswith('Halfling')

    def save_advantage_categories(self):
        """Set of save categories this species has Advantage on (Gnome Cunning,
        Fey Ancestry, Dwarven/Duergar/Strongheart Resilience, Halfling Brave)."""
        from .catalog import SPECIES_SAVE_ADVANTAGE
        cats = set(SPECIES_SAVE_ADVANTAGE.get(self.species, []))
        # base Halfling Brave applies to all halfling subraces
        if self.species.startswith('Halfling'):
            cats.add('Frightened')
        return cats

    def elemental_adept_types(self):
        """Damage types chosen for Elemental Adept (feat 'Elemental Adept: <type>').
        bg3.wiki: spells/attacks ignore resistance to that type, and damage dice of
        that type cannot roll a 1 (treated as 2)."""
        types = []
        for f in self.feats:
            if f.startswith('Elemental Adept'):
                t = f.split(':', 1)[1].strip() if ':' in f else ''
                if t:
                    types.append(t)
        return types

    def crit_threshold(self, attack_kind=None):
        """20 minus reductions (e.g. Bloodthirst -1 -> 19).

        attack_kind: if 'spell', also apply Spell Sniper feat (-1 to spell crits).
        """
        red = 0
        cat = self.catalog
        # check equipped items + feats for crit_threshold reductions
        for slot, name in self.equipped.items():
            if not name:
                continue
            for r in cat.riders_for_item(name):
                if r.get('kind') == 'crit_threshold':
                    red += abs(int(r.get('value', 0)))
        # Spell Sniper: -1 to spell-attack crit threshold (bg3.wiki Feats).
        if attack_kind == 'spell' and 'Spell Sniper' in self.feats:
            red += 1
        # Champion (Fighter subclass 3): Improved Critical Hit, -1 crit threshold.
        if self.has_subclass('Fighter', 'Champion'):
            red += 1
        return max(1, 20 - red)

    def has_subclass(self, cls_name, subclass):
        """True if the character has a subclass declaration for the class. Classes may
        carry an optional 'subclass' field (e.g. {'cls':'Fighter','level':3,'subclass':'Champion'})."""
        n = cls_name.lower()
        for c in self.classes:
            if c['cls'].lower() == n and c.get('subclass', '').lower() == subclass.lower():
                return True
        return False

    def can_cast(self, spell_name):
        """True if the character's classes can learn this spell (bg3.wiki spell_classes).
        A class matches if its level >= the spell's required level for that class; a
        subclass entry matches if the build declares that subclass on the core class.
        Returns True for spells with no class data (racial/item-granted, etc.)."""
        entries = self.catalog.spell_classes.get(spell_name)
        if not entries:
            return True  # unknown / non-class spell (racial, item, NPC)
        for e in entries:
            core = e.get('core_class', e.get('class', ''))
            lvl = e.get('level', 0)
            my_lvl = self.class_level(core)
            if my_lvl < lvl:
                continue
            sub = e.get('subclass')
            if sub:
                # subclass-specific entry: build must declare that subclass on the core class
                if self.has_subclass(core, sub):
                    return True
            else:
                # base-class entry (Magical Secrets counts as the base class)
                return True
        return False

    def spell_save_dc(self, spellcasting_ability='CHA'):
        dc = 8 + self.prof + self.ability_modifier(spellcasting_ability)
        # Arcane Acuity active_buff: +1 spell save DC (bg3.wiki).
        if any(b.get('ref') == 'Arcane Acuity' for b in self.active_buffs):
            dc += 1
        return dc

    def spell_attack_bonus(self, spellcasting_ability='CHA'):
        """Spell attack roll bonus = proficiency + spellcasting modifier.
        Plus Arcane Acuity (+1) if declared as an active_buff."""
        b = self.prof + self.ability_modifier(spellcasting_ability)
        if any(bf.get('ref') == 'Arcane Acuity' for bf in self.active_buffs):
            b += 1
        return b

    def rage_damage(self):
        """Barbarian rage bonus by level: 2 (1-8), 3 (9-15), 4 (16+)."""
        barb_lvl = sum(c['level'] for c in self.classes if c['cls'].lower() == 'barbarian')
        if barb_lvl >= 16: return 4
        if barb_lvl >= 9: return 3
        if barb_lvl >= 1: return 2
        return 0

    def rogue_level(self):
        return sum(c['level'] for c in self.classes if c['cls'].lower() == 'rogue')

    def monk_level(self):
        return sum(c['level'] for c in self.classes if c['cls'].lower() == 'monk')

    def class_level(self, cls_name):
        """Total level in a given class (case-insensitive)."""
        n = cls_name.lower()
        return sum(c['level'] for c in self.classes if c['cls'].lower() == n)

    def total_level(self):
        return sum(c.get('level', 0) for c in self.classes)

    def extra_attacks(self):
        """Number of Extra Attack features the character has (bg3.wiki class progression).

        bg3 rule: the Extra Attack feature does NOT stack across classes — a character
        with Fighter 5 + Paladin 5 still gets only ONE Extra Attack (the higher source
        wins). Fighter's level-11 feature (Improved Extra Attack) is a distinct, additive
        feature that DOES add a second attack on top. So the total is:
          +1 if ANY martial class (Barbarian/Fighter/Paladin/Ranger/Monk/Bard-Valour) is lvl 5+
          +1 more if Fighter level >= 11 (Improved Extra Attack)
        """
        out = 0
        ftr = self.class_level('Fighter')
        has_extra = (ftr >= 5 or
                     any(self.class_level(c) >= 5 for c in ('Barbarian', 'Paladin', 'Ranger', 'Monk')) or
                     self.class_level('Bard') >= 6)
        # Warlock Thirsting Blade invocation (bg3.wiki): grants Extra Attack. Same-name
        # feature, so it counts toward has_extra (doesn't stack with a martial class's EA).
        if self._has_active_buff('Thirsting Blade') and self.class_level('Warlock') >= 5:
            has_extra = True
        if has_extra:
            out += 1
        if ftr >= 11:
            out += 1  # Fighter's Improved Extra Attack (distinct feature, stacks)
        return out

    # Caster classes (bg3.wiki): full casters level up spell slots at the listed levels.
    CASTER_CLASSES = ('Bard', 'Cleric', 'Druid', 'Sorcerer', 'Wizard', 'Warlock')
    # half-casters (Paladin/Ranger) progress at half rate; Eldritch Knight/Arcane
    # Trickster at one-third. For max spell slot we use the highest single caster level.
    _SPELL_SLOT_THRESHOLDS = [(11, 6), (9, 5), (7, 4), (5, 3), (3, 2), (1, 1)]

    def max_spell_slot(self):
        """Highest spell slot level available (bg3.wiki caster progression: lvl1=1st,
        3=2nd, 5=3rd, 7=4th, 9=5th, 11=6th). Based on the highest single caster class
        level (multiclass caster rounding simplified out). 0 for non-casters."""
        full_lvl = max((self.class_level(c) for c in self.CASTER_CLASSES), default=0)
        full_slot = 0
        for threshold, slot in self._SPELL_SLOT_THRESHOLDS:
            if full_lvl >= threshold:
                full_slot = slot
                break
        # half-casters (Paladin/Ranger): 2nd-level slots at class lvl 5, 3rd at lvl 9 (BG3 cap).
        half = max(self.class_level('Paladin'), self.class_level('Ranger'))
        half_slot = 0
        if half >= 9: half_slot = 3
        elif half >= 5: half_slot = 2
        elif half >= 2: half_slot = 1
        return max(full_slot, half_slot)

    def unarmed_weapon(self):
        """Synthesize an unarmed 'weapon' dict using the monk's martial arts die.
        Monk die: 1d4@1-4, 1d6@5-8, 1d8@9-12, 1d10@13-16, 1d12@17-20 (BG3 progression).
        Non-monk unarmed = 1 (flat) + STR."""
        ml = self.monk_level()
        if ml >= 17: die = '1d12'
        elif ml >= 13: die = '1d10'
        elif ml >= 9: die = '1d8'
        elif ml >= 5: die = '1d6'
        elif ml >= 1: die = '1d4'
        else: die = None  # flat 1
        return {
            'name': 'Unarmed Strike', 'die': die, 'enchantment': 0,
            'damage_type': 'Bludgeoning', 'properties': '',
            'base_flat': 1 if die is None else 0,
        }

    def sneak_attack_dice(self):
        """Sneak Attack dice count by rogue level: 1d6@1-2, 2d6@3-4, ... (lvl+1)//2 d6. 0 if no rogue."""
        rl = self.rogue_level()
        if rl < 1:
            return 0
        return (rl + 1) // 2

    def resolver(self, attack_kind='melee', weapon=None):
        """Return a callable mapping symbolic flats to ints for this attack context."""
        amod = self.attack_ability_mod(attack_kind, weapon)

        def resolve(sym):
            mapping = {
                'ability_mod': amod,
                'str_mod': self.ability_modifier('STR'),
                'dex_mod': self.ability_modifier('DEX'),
                'con_mod': self.ability_modifier('CON'),
                'int_mod': self.ability_modifier('INT'),
                'wis_mod': self.ability_modifier('WIS'),
                'cha_mod': self.ability_modifier('CHA'),
                'prof': self.prof,
                'rage_damage': self.rage_damage(),
                'spell_mod': self.ability_modifier(self.spellcasting_ability()),
            }
            return mapping.get(sym, 0)
        return resolve

    def spellcasting_ability(self):
        """Infer the spellcasting ability from classes (for spell_mod rider resolution
        and Necklace of Elemental Augmentation). Default CHA. Mirrors round._spellcasting_ability
        but without needing a specific spell."""
        classes = {c['cls'].lower() for c in self.classes}
        if 'wizard' in classes or 'arcane trickster' in classes or 'eldritch knight' in classes:
            return 'INT'
        if 'cleric' in classes or 'druid' in classes or 'ranger' in classes:
            return 'WIS'
        return 'CHA'

    def active_riders(self, attack_kind):
        """Collect all riders that could apply: equipped items + active buffs + feat-granted.

        Returns a list of rider dicts (filtering by trigger/condition happens in rider_engine).
        """
        cat = self.catalog
        riders = []
        # equipped items
        for slot, name in self.equipped.items():
            if not name:
                continue
            for r in cat.riders_for_item(name):
                riders.append(r)
        # active buffs (by key)
        for buff in self.active_buffs:
            ref = buff.get('ref')
            r = cat.rider_by_key(ref)
            if r:
                riders.append(r)
        # feat-granted riders
        for f in self.feats:
            r = cat.rider_by_key(f + ' (unarmed)')
            if r and attack_kind == 'unarmed':
                riders.append(r)
            r = cat.rider_by_key(f + ' (thrown)')
            if r and attack_kind == 'thrown':
                riders.append(r)
        # Sneak Attack (rogue class feature): scaled by rogue level, once per turn
        sd = self.sneak_attack_dice()
        if sd > 0:
            sa = dict(cat.rider_by_key('Sneak Attack') or {
                'trigger': 'weapon_attack_hit', 'kind': 'DR',
                'damage': {'dice': '1d6', 'type': 'SameAsWeapon'},
                'condition': 'sneak_attack_eligible', 'once_per_turn': True})
            sa['damage'] = dict(sa['damage'])
            sa['damage']['dice'] = f'{sd}d6'
            sa['once_per_turn'] = True
            riders.append(sa)
        # Improved Divine Smite (Paladin 11): every melee weapon hit +1d8 Radiant.
        if self.class_level('Paladin') >= 11:
            riders.append({
                'trigger': 'melee_weapon_attack_hit', 'kind': 'DR',
                'damage': {'dice': '1d8', 'flat': 0, 'type': 'Radiant'},
                'source': 'https://bg3.wiki/wiki/Paladin',
                'notes': 'Improved Divine Smite (Paladin 11): melee weapon attacks +1d8 Radiant, no slot cost.'})
        # Empowered Evocation (Wizard Evocation subclass 10): +INT to spell damage.
        if attack_kind == 'spell' and self.class_level('Wizard') >= 10 and self.has_subclass('Wizard', 'Evocation'):
            riders.append(cat.rider_by_key('Empowered Evocation') or {
                'trigger': 'spell_damage_dealt', 'kind': 'DR',
                'damage': {'dice': None, 'flat_sym': 'int_mod', 'type': 'SameAsSpell'},
                'source': 'https://bg3.wiki/wiki/Wizard'})
        # Draconic Bloodline Elemental Affinity (Sorcerer 1+): +CHA to spell damage of
        # the ancestry element. Engine simplification: applies to all spell damage while
        # the build declares active_buff 'Draconic Bloodline' (should be ancestry-typed).
        if attack_kind == 'spell' and self.class_level('Sorcerer') >= 1 and self._has_active_buff('Draconic Bloodline'):
            riders.append(cat.rider_by_key('Draconic Bloodline') or {
                'trigger': 'spell_damage_dealt', 'kind': 'DR',
                'damage': {'dice': None, 'flat_sym': 'cha_mod', 'type': 'SameAsSpell'},
                'source': 'https://bg3.wiki/wiki/Draconic_Bloodline'})
        return riders

    def weapon_for(self, slot='main_hand', attack_kind='melee'):
        name = self.equipped.get(slot)
        if not name:
            # unarmed: synthesize monk martial-arts die when attack_kind is unarmed
            if attack_kind == 'unarmed':
                return self.unarmed_weapon()
            return None
        w = self.catalog.weapon(name)
        if w:
            return w
        # fallback: base weapon types (try exact, singular, plural)
        nm = name.strip()
        candidates = {nm, nm + 's', nm.rstrip('s')}
        for bw in self.catalog.weapons_base:
            if bw['name'] in candidates:
                return bw
        # last resort: equipment/legendary entries that carry damage info
        # (some named weapons like Lightning Jabber live only in legendary data)
        for src in (self.catalog.legendary, self.catalog.equipment):
            for e in src:
                if e.get('name', '').lower() == name.lower():
                    w = self._weapon_from_entry(e)
                    if w:
                        return w
        return None

    @staticmethod
    def _weapon_from_entry(e):
        """Synthesize a weapon dict from a legendary/equipment entry if it has
        damage info. Returns None if no parseable weapon damage is present."""
        import re
        name = e.get('name', '')
        dmg = e.get('damage', '') or ''
        m = re.match(r'\s*(\d+d\d+)\s*(?:\+\s*(\d+))?\s*(\w+)?', dmg)
        if not m:
            # try special text for a die expression
            sp = e.get('special', '') or e.get('special_weapon_actions', '') or ''
            m2 = re.search(r'(\d+d\d+)', sp)
            if not m2:
                return None
            die = m2.group(1)
            ench = 0
        else:
            die = m.group(1)
            ench = int(m.group(2)) if m.group(2) else 0
        # enchantment from name (+1/+2/+3) if not in damage
        if not ench:
            em = re.search(r'\+(\d)\b', name)
            ench = int(em.group(1)) if em else 0
        dtype = m.group(3) if (m and m.group(3)) else 'Slashing'
        return {
            'name': name, 'die': die, 'enchantment': ench,
            'damage_type': dtype, 'properties': '',
        }
