"""Catalog: lazy loader for all data/*.json + weapon normalization + three-tier
rider resolution.

Three-tier rider resolution (highest priority first):
  Tier 3 (data/riders.json, hand-curated) -> Tier 1 (auto, DRS tag detected)
  -> Tier 2 (auto, regex rule-based, riders.auto.json)

Weapon normalization fixes two known data bugs IN MEMORY (raw files untouched):
  - weapons_base.json: versatile weapons had range/properties columns shifted
  - weapons_named.json: duplicated name strings ("BattleaxeBattleaxe")
"""
import json, os, re

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')

# Damage type per weapon subtype (for re-deriving when base data is mis-parsed)
SUBTYPE_TO_TYPE = {
    'Longswords': 'Slashing', 'Greatswords': 'Slashing', 'Battleaxes': 'Slashing',
    'Greataxes': 'Slashing', 'Scimitars': 'Slashing', 'Halberds': 'Slashing',
    'Glaives': 'Slashing', 'Daggers': 'Piercing', 'Shortswords': 'Piercing',
    'Rapiers': 'Piercing', 'Spears': 'Piercing', 'Javelins': 'Piercing',
    'Tridents': 'Piercing', 'Maces': 'Bludgeoning', 'Warhammers': 'Bludgeoning',
    'Clubs': 'Bludgeoning', 'Quarterstaves': 'Bludgeoning', 'Light Hammers': 'Bludgeoning',
    'Flails': 'Bludgeoning', 'Morningstars': 'Piercing', 'Pikes': 'Piercing',
    'Longbows': 'Piercing', 'Shortbows': 'Piercing', 'Crossbows': 'Piercing',
    'Hand Crossbows': 'Piercing', 'Light Crossbows': 'Piercing', 'Heavy Crossbows': 'Piercing',
}

# Hand-curated named weapons that are MISSING from the local scraped data
# (weapons_named.json / legendary_effects.json) but are referenced by golden wiki
# examples or high-value builds. Values verified against bg3.wiki. Applied in memory
# only — raw scrape files are untouched (same philosophy as the weapon-normalization
# bug fixes below).
NAMED_WEAPON_PATCHES = {
    "Lightning Jabber": {
        "name": "Lightning Jabber", "subtype": "Tridents", "enchantment": 1,
        "die": "1d6", "damage_type": "Piercing", "properties": "Thrown,Finesse,Light",
        "source": "https://bg3.wiki/wiki/Lightning_Jabber",
        "_note": "Act 2 trident. Throwing: Lightning Damage passive = +1d4 Lightning as a DRS (new damage source).",
    },
    "Nyrulna": {
        "name": "Nyrulna", "subtype": "Tridents", "enchantment": 3,
        "die": "1d6", "damage_type": "Piercing", "properties": "Thrown,Melee,Finesse",
        "source": "https://bg3.wiki/wiki/Nyrulna",
        "_note": "Legendary trident. Zephyr Connection: thrown returns + 3d4 Thunder explosion (DRS, thrown-only, excluded from many weapon-attack riders).",
    },
    "Hand Crossbow": {
        "name": "Hand Crossbow", "subtype": "Hand Crossbows", "enchantment": 0,
        "die": "1d6", "damage_type": "Piercing", "properties": "Ranged,Ammunition,Light,Loading",
        "source": "https://bg3.wiki/wiki/Hand_Crossbow",
        "_note": "Base hand crossbow (1d6 Piercing). Crossbow Expert / dual-wielding builds.",
    },
    "Dwarven Thrower": {
        "name": "Dwarven Thrower", "subtype": "Warhammers", "enchantment": 3,
        "die": "1d8", "damage_type": "Bludgeoning", "properties": "Thrown,Two-Handed",
        "source": "https://bg3.wiki/wiki/Dwarven_Thrower",
        "_note": "Legendary warhammer. Thrown returns + bonus damage vs giants (DRS, thrown).",
    },
}


# Hand-curated multi-source spell patches. bg3.wiki Damage_mechanics lists many spells
# whose single cast is split into SEPARATE damage sources (each projectile/ray/segment
# is its own source and re-triggers applicable riders). The scraped spells.json flattens
# these into one damage entry, losing the per-source structure. These patches restore it.
# Each entry: base projectile count at the spell's base level, +count per upcast level,
# and the per-projectile damage expression. Applied in memory; raw spells.json untouched.
MULTISOURCE_SPELL_PATCHES = {
    "Magic Missile": {
        "projectiles_at_base": 3, "projectiles_per_upcast": 1,
        "per_projectile": [{"dice": "1d4+1", "type": "Force"}],
        "source": "https://bg3.wiki/wiki/Magic_Missile",
        "_note": "3 darts (+1 per upcast), each an independent damage source, auto-hit.",
    },
    "Scorching Ray": {
        "projectiles_at_base": 3, "projectiles_per_upcast": 1,
        "per_projectile": [{"dice": "2d6", "type": "Fire"}],
        "source": "https://bg3.wiki/wiki/Scorching_Ray",
        "_note": "3 rays (+1 per upcast), each 2d6 Fire, independent source, spell attack.",
    },
    "Eldritch Blast": {
        "projectiles_at_base": 1, "projectiles_per_upcast": 0,
        "extra_at_levels": {5: 2, 10: 3},  # caster level -> total beams
        "per_projectile": [{"dice": "1d10", "type": "Force"}],
        "source": "https://bg3.wiki/wiki/Eldritch_Blast",
        "_note": "1 beam at lvl1-4, 2 at lvl5-9, 3 at lvl10+. Each beam an independent source.",
    },
    # Ice Knife / Hail of Thorns: two-segment spells (initial hit + explosion) are
    # modelled as 2 sources via their two damage[] entries; the spell action handler
    # treats multiple damage[] entries as separate sources already (see _spell_action).
}


# Species (race) -> elemental resistance (bg3.wiki, verified from raw_races/).
# A character of this species takes half damage from the listed types. Used for the
# "character receiving damage" direction (self_resistances). Dragonborn resistance
# depends on subrace (Draconic Ancestry); encode as "Dragonborn:<subrace>".
SPECIES_RESISTANCES = {
    'Tiefling': ['Fire'],
    'Dwarf': ['Poison'],
    'Duergar': ['Poison'],          # Duergar inherits Dwarven Resilience
    'Halfling:Strongheart': ['Poison'],
    'Dragonborn:Black': ['Acid'],
    'Dragonborn:Copper': ['Acid'],
    'Dragonborn:Blue': ['Lightning'],
    'Dragonborn:Bronze': ['Lightning'],
    'Dragonborn:Brass': ['Fire'],
    'Dragonborn:Gold': ['Fire'],
    'Dragonborn:Red': ['Fire'],
    'Dragonborn:Green': ['Poison'],
    'Dragonborn:Silver': ['Cold'],
    'Dragonborn:White': ['Cold'],
}

# Dragonborn breath weapon per subrace (bg3.wiki raw_races/*_Breath.html).
# (damage_type, save_ability, aoe_shape). All: 2d6 -> 3d6@lvl6 -> 4d6@lvl11,
# DC = 8 + CON mod + proficiency, half on save, short-rest recharge.
DRAGONBORN_BREATH = {
    'Black': ('Acid', 'DEX', 'Line'), 'Copper': ('Acid', 'DEX', 'Line'),
    'Blue': ('Lightning', 'DEX', 'Line'), 'Bronze': ('Lightning', 'DEX', 'Line'),
    'Brass': ('Fire', 'DEX', 'Line'),
    'Gold': ('Fire', 'DEX', 'Cone'), 'Red': ('Fire', 'DEX', 'Cone'),
    'Green': ('Poison', 'CON', 'Cone'),
    'Silver': ('Cold', 'CON', 'Cone'), 'White': ('Cold', 'CON', 'Cone'),
}

# Species that grant a saving-throw advantage (bg3.wiki raw_races/). Maps to the
# abilities / effect categories on which the character has Advantage when SAVING.
# Used for the "character receiving a spell" direction (target.save_advantage).
SPECIES_SAVE_ADVANTAGE = {
    'Gnome': ['INT', 'WIS', 'CHA'],            # Gnome Cunning
    'Elf': ['Charmed'], 'Half-Elf': ['Charmed'], 'Drow': ['Charmed'],  # Fey Ancestry
    'Dwarf': ['Poisoned'], 'Duergar': ['Poisoned', 'Illusion', 'Charmed', 'Paralysed'],
    'Halfling:Strongheart': ['Poisoned'], 'Halfling': ['Frightened'],  # Brave
}


# Extra elemental dice baked into named weapons' damage strings (bg3.wiki verified).
# weapons_named.json fuses these into the damage field (e.g. '2d61d4' = 2d6 + 1d4 Fire);
# _normalize_named extracts only the base die, and these riders restore the extra die
# as a DR of the correct element so the weapon's full damage is modelled.
NAMED_WEAPON_EXTRA_DICE = {
    "Everburn Blade": [{"trigger": "melee_weapon_attack_hit", "kind": "DR",
                        "damage": {"dice": "1d4", "flat": 0, "type": "Fire"},
                        "source": "https://bg3.wiki/wiki/Everburn_Blade"}],
    "Moonlight Glaive": [{"trigger": "melee_weapon_attack_hit", "kind": "DR",
                          "damage": {"dice": "1d4", "flat": 0, "type": "Radiant"},
                          "source": "https://bg3.wiki/wiki/Moonlight_Glaive"}],
    "Devotee's Mace": [{"trigger": "melee_weapon_attack_hit", "kind": "DR",
                        "damage": {"dice": "1d8", "flat": 0, "type": "Radiant"},
                        "source": "https://bg3.wiki/wiki/Devotee%27s_Mace"}],
    "Crimson Mischief": [{"trigger": "melee_weapon_attack_hit", "kind": "DR",
                          "damage": {"dice": "1d4", "flat": 0, "type": "Piercing"},
                          "source": "https://bg3.wiki/wiki/Crimson_Mischief",
                          "_note": "Prey Upon the Weak off-hand +1d4 Piercing (modelled as a base extra die; main-hand Redvein Savagery is the DRS in riders.json)"}],
    "Duellist's Prerogative": [{"trigger": "melee_weapon_attack_hit", "kind": "DR",
                                "damage": {"dice": "1d4", "flat": 0, "type": "Necrotic"},
                                "source": "https://bg3.wiki/wiki/Duellist%27s_Prerogative",
                                "_note": "base weapon extra necrotic die; Withering Cut (+prof) and crit-1 are separate riders in riders.json"}],
    # Remaining 16 weapons with fused damage strings (bg3.wiki Extra damage verified).
    "Ritual Dagger of Shar": [{"trigger": "melee_weapon_attack_hit", "kind": "DR",
                               "damage": {"dice": "1d4", "flat": 0, "type": "Necrotic"},
                               "source": "https://bg3.wiki/wiki/Ritual_Dagger_of_Shar"}],
    "Cold Snap": [{"trigger": "ranged_weapon_attack_hit", "kind": "DR",
                   "damage": {"dice": "1d4", "flat": 0, "type": "Cold"},
                   "source": "https://bg3.wiki/wiki/Cold_Snap"}],
    "Sword of Chaos": [{"trigger": "melee_weapon_attack_hit", "kind": "DR",
                        "damage": {"dice": "1d4", "flat": 0, "type": "Necrotic"},
                        "source": "https://bg3.wiki/wiki/Sword_of_Chaos"}],
    "Light of Creation": [{"trigger": "melee_weapon_attack_hit", "kind": "DR",
                           "damage": {"dice": "1d6", "flat": 0, "type": "Lightning"},
                           "source": "https://bg3.wiki/wiki/Light_of_Creation"}],
    "Halberd of Vigilance": [{"trigger": "melee_weapon_attack_hit", "kind": "DR",
                              "damage": {"dice": "1d4", "flat": 0, "type": "Force"},
                              "source": "https://bg3.wiki/wiki/Halberd_of_Vigilance"}],
    "Blackguard's Sword": [{"trigger": "melee_weapon_attack_hit", "kind": "DR",
                            "damage": {"dice": "1d4", "flat": 0, "type": "Necrotic"},
                            "source": "https://bg3.wiki/wiki/Blackguard%27s_Sword"}],
    "Blade of Oppressed Souls": [{"trigger": "melee_weapon_attack_hit", "kind": "DR",
                                  "damage": {"dice": "1d4", "flat": 0, "type": "Psychic"},
                                  "source": "https://bg3.wiki/wiki/Blade_of_Oppressed_Souls"}],
    "Voss' Silver Sword": [{"trigger": "melee_weapon_attack_hit", "kind": "DR",
                            "damage": {"dice": "1d4", "flat": 0, "type": "Psychic"},
                            "source": "https://bg3.wiki/wiki/Voss%27_Silver_Sword"}],
    "Loviatar's Scourge": [{"trigger": "melee_weapon_attack_hit", "kind": "DR",
                            "damage": {"dice": "1d6", "flat": 0, "type": "Necrotic"},
                            "source": "https://bg3.wiki/wiki/Loviatar%27s_Scourge"}],
    "Handmaiden's Mace": [{"trigger": "melee_weapon_attack_hit", "kind": "DR",
                           "damage": {"dice": "1d6", "flat": 0, "type": "Poison"},
                           "source": "https://bg3.wiki/wiki/Handmaiden%27s_Mace"}],
    "Sword of Screams": [{"trigger": "melee_weapon_attack_hit", "kind": "DR",
                          "damage": {"dice": "1d4", "flat": 0, "type": "Psychic"},
                          "source": "https://bg3.wiki/wiki/Sword_of_Screams"}],
    "Pelorsun Blade": [{"trigger": "melee_weapon_attack_hit", "kind": "DR",
                        "damage": {"dice": "1d4", "flat": 0, "type": "Radiant"},
                        "source": "https://bg3.wiki/wiki/Pelorsun_Blade"}],
    "Kurwin's Cauteriser": [{"trigger": "melee_weapon_attack_hit", "kind": "DR",
                             "damage": {"dice": "1d4", "flat": 0, "type": "Fire"},
                             "source": "https://bg3.wiki/wiki/Kurwin%27s_Cauteriser"}],
    "Makeshift Bow": [{"trigger": "ranged_weapon_attack_hit", "kind": "DR",
                       "damage": {"dice": "1d10", "flat": 0, "type": "Necrotic"},
                       "source": "https://bg3.wiki/wiki/Makeshift_Bow"}],
    "Hammer of the Just": [{"trigger": "melee_weapon_attack_hit", "kind": "DR",
                            "damage": {"dice": "1d4", "flat": 0, "type": "Radiant"},
                            "source": "https://bg3.wiki/wiki/Hammer_of_the_Just"}],
    "Ketheric's Warhammer": [{"trigger": "melee_weapon_attack_hit", "kind": "DR",
                              "damage": {"dice": "1d4", "flat": 0, "type": "Psychic"},
                              "source": "https://bg3.wiki/wiki/Ketheric%27s_Warhammer"}],
}


# Defensive equipment (承受侧): crit immunity and flat damage reduction.
# bg3.wiki: Adamantine line = attackers can't land crits; Superior Padding/Plate/Material
# = -N to one physical type; Magical Plate = -N to ALL damage. Applied when the target
# represents a player character wearing these (target.equipped in the build).
DEFENSIVE_ITEMS = {
    # crit immunity
    "Adamantine Scale Mail": {"crit_immune": True},
    "Adamantine Splint Armour": {"crit_immune": True},
    "Adamantine Shield": {"crit_immune": True},
    "Grymskull Helm": {"crit_immune": True},
    "Helldusk Helmet": {"crit_immune": True},
    "Helm of Balduran": {"crit_immune": True},
    # flat reduction to a single physical type (Superior Padding=Bludgeoning, Plate=Piercing, Material=Slashing)
    "Padded Armour +1": {"flat_reduction": {"Bludgeoning": 1}},
    "Padded Armour +2": {"flat_reduction": {"Bludgeoning": 2}},
    "Studded Leather Armour +1": {"flat_reduction": {"Bludgeoning": 1}},
    "Studded Leather Armour +2": {"flat_reduction": {"Bludgeoning": 1}},
    "Breastplate +1": {"flat_reduction": {"Piercing": 1}},
    "Breastplate +2": {"flat_reduction": {"Piercing": 1}},
    "Half Plate Armour +1": {"flat_reduction": {"Piercing": 1}},
    "Half Plate Armour +2": {"flat_reduction": {"Piercing": 2}},
    "Plate Armour +1": {"flat_reduction": {"Piercing": 1}},
    "Splint Armour +1": {"flat_reduction": {"Piercing": 1}},
    "Splint Armour +2": {"flat_reduction": {"Piercing": 1}},
    "Chain Shirt +1": {"flat_reduction": {"Slashing": 1}},
    "Chain Shirt +2": {"flat_reduction": {"Slashing": 1}},
    "Scale Mail +1": {"flat_reduction": {"Slashing": 1}},
    "Scale Mail +2": {"flat_reduction": {"Slashing": 1}},
    "Chain Mail +1": {"flat_reduction": {"Slashing": 1}},
    "Chain Mail +2": {"flat_reduction": {"Slashing": 2}},
    "Dwarven Splintmail": {"flat_reduction": {"Piercing": 1}},
    "The Jolty Vest": {"flat_reduction": {"Slashing": 1}},
    "Ring Mail Armour +2": {"flat_reduction": {"Slashing": 1}},
    # Magical Plate: -N to ALL damage
    "Plate Armour +2": {"flat_reduction": {"all": 2}},
    "Armour of Persistence": {"flat_reduction": {"all": 2}},
    "Blackguard's Plate": {"flat_reduction": {"all": 1}},
    "Emblazoned Plate of the Marshal": {"flat_reduction": {"all": 1}},
    "Reaper's Embrace": {"flat_reduction": {"all": 3}},
    "Helldusk Armour": {"flat_reduction": {"all": 3}},
    "Adamantine Splint Armour": {"crit_immune": True, "flat_reduction": {"all": 2}},
    "Adamantine Scale Mail": {"crit_immune": True, "flat_reduction": {"all": 1}},
}


# Wild Shape beast forms (bg3.wiki Wild_Shape). Each form: list of attacks
# {name, dice, type, plus_str_mod}. Damage uses the beast's STR mod (encoded in flat);
# Moon-only forms marked. Source URLs per form (some pages not locally cached — values
# are bg3.wiki-verified common values; re-fetch individual pages to re-verify).
BEAST_FORMS = {
    "Owlbear": {  # Moon Druid (lvl 6+)
        "moon_only": True, "attacks": [
            {"name": "Beak", "dice": "1d8", "type": "Piercing", "str_mod": 4},
            {"name": "Talons", "dice": "1d6", "type": "Slashing", "str_mod": 4}],
        "multiattack": 2,  # 2 attacks per Attack action
        "source": "https://bg3.wiki/wiki/Wild_Shape:_Owlbear"},
    "Sabertooth Tiger": {  # Moon Druid
        "moon_only": True, "attacks": [
            {"name": "Bite", "dice": "1d10", "type": "Piercing", "str_mod": 3}],
        "multiattack": 1,
        "source": "https://bg3.wiki/wiki/Wild_Shape:_Sabertooth_Tiger"},
    "Bear": {  # Moon Druid
        "moon_only": True, "attacks": [
            {"name": "Bite", "dice": "1d8", "type": "Piercing", "str_mod": 4},
            {"name": "Claws", "dice": "1d6", "type": "Slashing", "str_mod": 4}],
        "multiattack": 2,
        "source": "https://bg3.wiki/wiki/Wild_Shape:_Bear"},
    "Deep Rothe": {  # Moon Druid
        "moon_only": True, "attacks": [
            {"name": "Gore", "dice": "1d8", "type": "Piercing", "str_mod": 4}],
        "multiattack": 1,
        "source": "https://bg3.wiki/wiki/Wild_Shape:_Deep_Rothe"},
    "Wolf": {
        "moon_only": False, "attacks": [
            {"name": "Bite", "dice": "1d6", "type": "Piercing", "str_mod": 3}],
        "multiattack": 1,
        "source": "https://bg3.wiki/wiki/Wild_Shape:_Wolf"},
    "Panther": {
        "moon_only": False, "attacks": [
            {"name": "Bite", "dice": "1d4", "type": "Piercing", "str_mod": 3},
            {"name": "Claw", "dice": "1d4", "type": "Slashing", "str_mod": 3}],
        "multiattack": 2,
        "source": "https://bg3.wiki/wiki/Wild_Shape:_Panther"},
    "Spider": {
        "moon_only": False, "attacks": [
            {"name": "Bite", "dice": "1d4", "type": "Piercing", "str_mod": 2}],
        "multiattack": 1,
        "source": "https://bg3.wiki/wiki/Wild_Shape:_Spider"},
    "Badger": {
        "moon_only": False, "attacks": [
            {"name": "Bite", "dice": "1d4", "type": "Piercing", "str_mod": 2}],
        "multiattack": 1,
        "source": "https://bg3.wiki/wiki/Wild_Shape:_Badger"},
}


class Catalog:
    _instance = None

    def __init__(self):
        self._spells = None
        self._equipment = None
        self._legendary = None
        self._weapons_named = None
        self._weapons_base = None
        self._riders_t3 = None
        self._riders_auto = None
        self._conditions = None
        self._feats = None

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load(self, name):
        # all structured data lives under data/
        p = os.path.join(DATA_DIR, name)
        if os.path.exists(p):
            return json.load(open(p, encoding='utf-8'))
        return None

    @property
    def riders_t3(self):
        if self._riders_t3 is None:
            d = self._load('riders.json') or {}
            d.pop('_meta', None)
            self._riders_t3 = d
        return self._riders_t3

    @property
    def riders_auto(self):
        if self._riders_auto is None:
            self._riders_auto = self._load('riders.auto.json') or {}
        return self._riders_auto

    @property
    def equipment(self):
        if self._equipment is None:
            self._equipment = self._load('equipment.json') or []
        return self._equipment

    @property
    def legendary(self):
        if self._legendary is None:
            self._legendary = self._load('legendary_effects.json') or []
        return self._legendary

    @property
    def weapons_named(self):
        if self._weapons_named is None:
            raw = self._load('weapons_named.json') or []
            self._weapons_named = [self._normalize_named(w) for w in raw]
        return self._weapons_named

    @property
    def weapons_base(self):
        if self._weapons_base is None:
            raw = self._load('weapons_base.json') or []
            self._weapons_base = [self._normalize_base(w) for w in raw]
        return self._weapons_base

    @staticmethod
    def _normalize_base(w):
        """Normalize a base weapon: split '1d8 Slashing' damage into die + damage_type.
        Also fixes the known versatile-weapon column shift (range held die, etc.)."""
        w = dict(w)
        dmg = w.get('damage', '') or ''
        m = re.match(r'\s*(\d+d\d+)\s+(\w+)', dmg)
        if m:
            w['die'] = m.group(1)
            w['damage_type'] = m.group(2)
        else:
            w['die'] = None
            w['damage_type'] = 'Slashing'
        # properties may be a comma string; keep as-is
        return w

    @property
    def spells(self):
        if self._spells is None:
            self._spells = self._load('spells.json') or []
        return self._spells

    @property
    def conditions(self):
        if self._conditions is None:
            self._conditions = self._load('conditions.json') or {}
        return self._conditions

    @property
    def feats(self):
        if self._feats is None:
            self._feats = self._load('feats.json') or {}
        return self._feats

    @property
    def spell_classes(self):
        """Map spell name -> list of {class, core_class, level, subclass?, via?} (bg3.wiki
        raw_spells Classes field). Loaded lazily from data/spell_classes.json."""
        if not hasattr(self, '_spell_classes') or self._spell_classes is None:
            self._spell_classes = self._load('spell_classes.json') or {}
        return self._spell_classes

    # ---- normalization ----
    @staticmethod
    def _normalize_named(w):
        """Fix duplicated name 'BattleaxeBattleaxe' -> 'Battleaxe', and clean the
        damage field. weapons_named.json damage strings are noisy: many encode an
        extra elemental die concatenated ('2d61d4' = 2d6 + 1d4 Fire) or fused with
        the enchantment ('1d10 + 21d4' = 1d10 + 2 enchant + 1d4 Radiant). We extract
        only the FIRST NdM as the weapon's base die so build_base_ds never sees a
        bogus '2d61' (61-sided die). The extra dice are modelled as riders where the
        element type is known (NAMED_WEAPON_EXTRA_DICE below); the rest are flagged."""
        name = w.get('name', '')
        half = len(name) // 2
        if half > 0 and name[:half] == name[half:]:
            name = name[:half]
        w = dict(w)
        w['name'] = name
        if 'damage_type' not in w or not w.get('damage_type'):
            w['damage_type'] = SUBTYPE_TO_TYPE.get(w.get('subtype', ''), 'Slashing')
        # Clean the damage field: keep only the first NdM term. Constrain the die size
        # to standard BG3 dice (d4/d6/d8/d10/d12/d20/d100) so '2d61d4' -> '2d6' (not
        # '2d61'), and '1d10 + 21d4' -> '1d10' (the trailing 1d4 is a separate extra die).
        dmg = w.get('damage', '') or ''
        m = re.search(r'(\d+d(?:100|20|12|10|8|6|4))', dmg)
        if m:
            w['die'] = m.group(1)
            if dmg.strip() != m.group(1):
                w['_has_extra_dice'] = True  # extra dice present, modelled via riders
        return w

    # ---- lookups ----
    def weapon(self, name):
        """Find a named weapon by name (case-insensitive). Returns normalized dict or None."""
        nl = name.lower()
        # curated patches first (for weapons missing from local scrape)
        for pname, pw in NAMED_WEAPON_PATCHES.items():
            if pname.lower() == nl:
                return dict(pw)
        for w in self.weapons_named:
            if w['name'].lower() == nl:
                return w
        return None

    def spell(self, name):
        for s in self.spells:
            if s.get('name', '').lower() == name.lower():
                return s
        return None

    def multisource_spell(self, name):
        """Return the multi-source patch for a spell, or None."""
        for pname, patch in MULTISOURCE_SPELL_PATCHES.items():
            if pname.lower() == name.lower():
                return patch
        return None

    def item_special(self, name):
        """Return the raw 'special' effect text for an equipment/legendary item."""
        for e in self.equipment:
            if e['name'].lower() == name.lower():
                return e.get('special', '')
        for l in self.legendary:
            if l['name'].lower() == name.lower():
                return (l.get('special', '') + ' ' + l.get('special_weapon_actions', '')).strip()
        return ''

    # ---- three-tier rider resolution ----
    def defense_for(self, name):
        """Return the defensive profile (crit_immune, flat_reduction) for a worn item,
        or None. bg3.wiki Adamantine/Superior Padding/Magical Plate lines."""
        return DEFENSIVE_ITEMS.get(name)

    def beast_form(self, name):
        """Return a Wild Shape beast form's attacks (bg3.wiki Wild_Shape). None if absent."""
        return BEAST_FORMS.get(name)

    def riders_for_item(self, name):
        """Return list of rider dicts for an item, Tier3 > Tier1(tag) > Tier2(auto).
        Also merges NAMED_WEAPON_EXTRA_DICE (baked-in elemental bonus dice).

        Tier3 keys may be 'ItemName' or 'ItemName (suffix)' — match by exact or prefix.
        """
        out = []
        # baked-in extra dice (e.g. Everburn Blade +1d4 Fire) — always merged
        for ename, ers in NAMED_WEAPON_EXTRA_DICE.items():
            if ename.lower() == name.lower():
                out.extend(ers)
        # Tier 3: curated (exact, or 'Name (suffix)' key) — takes precedence over auto
        t3 = None
        if name in self.riders_t3:
            r = self.riders_t3[name]
            t3 = [r] if isinstance(r, dict) else list(r)
        else:
            for key, r in self.riders_t3.items():
                if key.startswith(name + ' (') or key.startswith(name + '('):
                    t3 = [r] if isinstance(r, dict) else list(r)
                    break
        if t3 is not None:
            out.extend(t3)
        elif name in self.riders_auto:
            # Tier 1 + 2: auto-classified (only when no Tier3 match)
            r = self.riders_auto[name]
            out.extend(r if isinstance(r, list) else [r])
        return out

    def rider_by_key(self, key):
        """Look up a curated rider by its key (e.g. 'Hex', 'Rage (Barbarian)').

        Tolerates informational suffixes on the lookup key: 'Lightning Charges (wiki)'
        resolves to the 'Lightning Charges' entry. This lets build files tag refs
        with provenance without breaking resolution.
        """
        if key in self.riders_t3:
            return self.riders_t3[key]
        # strip a trailing ' (suffix)' and retry
        if key and ' (' in key:
            base = key.rsplit(' (', 1)[0]
            if base in self.riders_t3:
                return self.riders_t3[base]
        return None
