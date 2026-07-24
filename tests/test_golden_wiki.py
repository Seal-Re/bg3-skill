"""GOLDEN regression test: reproduce bg3.wiki Damage_mechanics worked example.

Wiki example (verbatim breakdown, DRS case ~36 avg damage on a hit):
  20 Str (+5), Tavern Brawler, Lightning Charges (+1 lightning DR), Ring of Flinging
  (+1d4 piercing DR), Hex (+1d6 necrotic DR), Lightning Jabber thrown weapon
  (1d6 + 1 enchant + 5 str piercing DS; +1d4 lightning DRS from weapon passive).

Sources and DRs per source:
  Source 1 (DS): 1d6+1+5=9.5 piercing
    + 1d4(2.5) piercing [Ring of Flinging, DR]
    + 1 lightning [Lightning Charges, DR]
    + 1d6(3.5) necrotic [Hex, DR]
    + 5 piercing [Tavern Brawler, DR]
    => 9.5 + 2.5 + 1 + 3.5 + 5 = 21.5
  Source 2 (DRS): 1d4(2.5) lightning [Lightning Jabber weapon passive, DRS]
    + 1d4(2.5) piercing [Ring of Flinging, DR]
    + 1 lightning [Lightning Charges, DR]
    + 1d6(3.5) necrotic [Hex, DR]
    + 5 piercing [Tavern Brawler, DR]
    => 2.5 + 2.5 + 1 + 3.5 + 5 = 14.5
  Total = 21.5 + 14.5 = 36.0

This test builds the riders explicitly and asserts the expanded pool EV == 36.0
(at crit=False, i.e. per-hit damage ignoring hit probability — matching the wiki
example which is "on average" per damage roll, pre hit-chance).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import rider_engine as re
from engine.damage import DamagePool

class T:
    conditions = ["Hex"]
    flags = []
    resistances = []
    immunities = []
    vulnerabilities = []

def resolver(sym):
    return {"ability_mod": 5, "str_mod": 5, "dex_mod": 2, "prof": 3}.get(sym, 0)

# Weapon: Lightning Jabber thrown. DS = 1d6 + 1 enchant + 5 str piercing.
WEAPON = {"die": "1d6", "enchantment": 1, "damage_type": "Piercing"}

# Riders for this exact example:
RING_FLINGING = {"trigger": "thrown_attack_hit", "kind": "DR",
                 "damage": {"dice": "1d4", "flat": 0, "type": "Piercing"}}
LIGHTNING_CHARGES_WIKI = {"trigger": "thrown_attack_hit|weapon_attack_hit", "kind": "DR",
                          "damage": {"dice": None, "flat": 1, "type": "Lightning"}}
HEX = {"trigger": "weapon_attack_hit|thrown_attack_hit", "kind": "DR",
       "damage": {"dice": "1d6", "flat": 0, "type": "Necrotic"},
       "condition": "target_has:Hex"}
TAVERN_BRAWLER_THROWN = {"trigger": "thrown_attack_hit", "kind": "DR",
                         "damage": {"dice": None, "flat_sym": "str_mod", "type": "Piercing"}}
# Lightning Jabber weapon passive: +1d4 lightning as a DRS (new source)
LIGHTNING_JABBER_DRS = {"trigger": "thrown_attack_hit", "kind": "DRS",
                        "damage": {"dice": "1d4", "flat": 0, "type": "Lightning"}}

RIDERS = [RING_FLINGING, LIGHTNING_CHARGES_WIKI, HEX, TAVERN_BRAWLER_THROWN, LIGHTNING_JABBER_DRS]


def test_wiki_example_36():
    pool = re.expand_attack(WEAPON, "thrown", RIDERS, T(), resolver)
    by = pool.ev_by_type(crit=False, resolver=resolver)
    total = sum(by.values())
    # Verify per-type breakdown
    assert abs(by["Piercing"] - (9.5 + 2.5 + 5 + 2.5 + 5)) < 0.001, by  # 24.5
    assert abs(by["Lightning"] - (1 + 2.5 + 1)) < 0.001, by             # 4.5
    assert abs(by["Necrotic"] - (3.5 + 3.5)) < 0.001, by               # 7.0
    # Golden: total == 36.0
    assert abs(total - 36.0) < 0.05, f"expected ~36.0, got {total}"
    print(f"  per-type: {by}")
    print(f"  total: {total}")


def test_wiki_example_drs_vs_dr_difference():
    """If Lightning Jabber's +1d4 lightning were a DR (not DRS), total = 24.0 (wiki hypothetical)."""
    jabber_as_dr = dict(LIGHTNING_JABBER_DRS)
    jabber_as_dr["kind"] = "DR"
    riders = [RING_FLINGING, LIGHTNING_CHARGES_WIKI, HEX, TAVERN_BRAWLER_THROWN, jabber_as_dr]
    pool = re.expand_attack(WEAPON, "thrown", riders, T(), resolver)
    total = sum(pool.ev_by_type(crit=False, resolver=resolver).values())
    assert abs(total - 24.0) < 0.05, f"expected ~24.0, got {total}"


def test_end_to_end_lightning_thrower_build():
    """END-TO-END: the data/builds/lightning_thrower.json build must resolve through
    Catalog -> Character -> active_riders -> expand_attack and reproduce the wiki
    single-hit pool EV of 36.0. This guards the full pipeline (weapon lookup, rider
    resolution, condition filtering) that the unit-level test above bypasses."""
    from engine.character import Character
    build_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'builds',
                              'lightning_thrower.json')
    char = Character.from_file(build_path)

    class T2:
        conditions = ["Hex"]
        flags = []
        resistances = []
        immunities = []
        vulnerabilities = []

    weapon = char.weapon_for("main_hand", "thrown")
    assert weapon is not None and weapon["name"] == "Lightning Jabber", weapon
    riders = list(char.active_riders("thrown"))
    pool = re.expand_attack(weapon, "thrown", riders, T2(), char.resolver("thrown", weapon))
    by = pool.ev_by_type(crit=False, resolver=char.resolver("thrown", weapon))
    total = sum(by.values())
    assert abs(total - 36.0) < 0.05, f"end-to-end single-hit EV expected ~36.0, got {total} ({by})"
    # per-type breakdown must match the wiki worked example
    assert abs(by["Piercing"] - 24.5) < 0.05, by
    assert abs(by["Necrotic"] - 7.0) < 0.05, by
    assert abs(by["Lightning"] - 4.5) < 0.05, by
    print(f"  end-to-end per-type: {by}  total: {total}")


def test_end_to_end_honour_mode_downgrades_drs():
    """Honour mode: DRS effects become plain DR (bg3.wiki Damage_mechanics Honour Mode
    exception). The Lightning Jabber DRS no longer re-triggers DRs, so the single-hit
    pool drops from 36.0 -> 24.0 (the wiki's hypothetical DR-only figure)."""
    from engine.character import Character
    build_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'builds',
                              'lightning_thrower.json')
    char = Character.from_file(build_path)
    char.honour_mode = True

    class T2:
        conditions = ["Hex"]
        flags = []
        resistances = []
        immunities = []
        vulnerabilities = []

    weapon = char.weapon_for("main_hand", "thrown")
    riders = list(char.active_riders("thrown"))
    res = char.resolver("thrown", weapon)
    pool = re.expand_attack(weapon, "thrown", riders, T2(), res, honour_mode=True)
    total = sum(pool.ev_by_type(crit=False, resolver=res).values())
    assert abs(total - 24.0) < 0.05, f"honour-mode EV expected ~24.0, got {total}"
    print(f"  honour-mode single-hit EV: {total}")


def test_on_crit_riders_fire_only_on_crit():
    """bg3.wiki Critical_hit: Craterflesh Gloves add 1d6 Force on crit (the added die
    is itself doubled -> 2d6); Sword of Life Stealing adds +10 Necrotic flat on crit
    (flat, NOT doubled). Both fire only on the crit branch (weighted by p_crit).

    Longsword 1d8 +5 str (+0 enchant), AC 15, atk +6: p_normal=0.55, p_crit=0.05.
    Non-crit hit = 1d8+5 = 9.5 Slashing.
    Crit hit = 2d8+5 = 14 Slashing + 2d6(7) Force + 10 Necrotic = 31.
    EV = 0.55*9.5 + 0.05*31 = 5.225 + 1.55 = 6.775.
    """
    from engine.character import Character
    build = {
        "name": "crit-rider unit", "classes": [{"cls": "Fighter", "level": 4}],
        "abilities": {"STR": 20, "DEX": 14, "CON": 14, "INT": 8, "WIS": 10, "CHA": 8},
        "proficiency_bonus": 2, "attack_ability": "STR", "feats": [],
        "equipped": {"main_hand": "Longsword", "gloves": "Craterflesh Gloves"},
        "active_buffs": [],
        "target": {"ac": 15, "save_bonus": {}, "resistances": [], "immunities": [],
                   "vulnerabilities": [], "conditions": [], "flags": []},
        "round_actions": [{"type": "attack", "weapon": "main_hand",
                           "attack_kind": "melee", "count": 1}],
    }
    # inject a flat +10 Necrotic on_crit rider (Life Stealing) directly
    char = Character(build)
    weapon = char.weapon_for("main_hand", "melee")
    riders = list(char.active_riders("melee")) + [{
        "trigger": "melee_weapon_attack_hit", "kind": "DR", "condition": "on_crit",
        "damage": {"dice": None, "flat": 10, "type": "Necrotic"}}]
    res = char.resolver("melee", weapon)
    r = re.attack_ev(weapon, "melee", riders, type("T", (), {
        "conditions": [], "flags": [], "resistances": [], "immunities": [],
        "vulnerabilities": [], "crit_immune": False, "auto_crit": False})(),
        res, 6, 15, crit_threshold_val=20)
    assert abs(r["p_crit"] - 0.05) < 0.001, r
    assert abs(r["p_normal"] - 0.55) < 0.001, r
    # Force: only on crit, 2d6 = 7, weighted by 0.05 -> 0.35
    assert abs(r["per_type_ev"]["Force"] - 0.35) < 0.01, r["per_type_ev"]
    # Necrotic: only on crit, +10 flat (not doubled), weighted by 0.05 -> 0.50
    assert abs(r["per_type_ev"]["Necrotic"] - 0.50) < 0.01, r["per_type_ev"]
    # Slashing: 0.55*9.5 + 0.05*14 = 5.225 + 0.70 = 5.925
    assert abs(r["per_type_ev"]["Slashing"] - 5.925) < 0.01, r["per_type_ev"]
    print(f"  on_crit per_type: {r['per_type_ev']}")


def test_wet_condition_applies_vulnerability_not_just_resistance():
    """bg3.wiki Wet: Fire resistance AND Cold/Lightning vulnerability. Regression for
    a bug where _apply_target_condition_effects read resistances but not vulnerabilities,
    so the elemental-reaction damage multiplier (the core of Wet) was silently dropped."""
    from engine.character import Character, Target
    from engine.round import _apply_target_condition_effects
    build = {"classes": [{"cls": "Wizard", "level": 4}],
             "abilities": {"STR": 8, "DEX": 14, "CON": 14, "INT": 18, "WIS": 10, "CHA": 8},
             "proficiency_bonus": 2, "equipped": {},
             "target": {"ac": 15, "conditions": ["Wet"]}}
    char = Character(build)
    tgt = Target(build["target"])
    _apply_target_condition_effects(char, tgt)
    assert "Fire" in tgt.resistances, tgt.resistances
    assert "Cold" in tgt.vulnerabilities, tgt.vulnerabilities
    assert "Lightning" in tgt.vulnerabilities, tgt.vulnerabilities
    print(f"  Wet -> resistances={tgt.resistances} vulnerabilities={tgt.vulnerabilities}")


def test_species_resistance_halves_damage():
    """bg3.wiki raw_races/: a Tiefling target (Hellish Resistance) takes half Fire.
    Dragonborn:Black resists Acid. End-to-end via target.species."""
    from engine.round import expected_round_damage
    base = {"name": "sp", "classes": [{"cls": "Fighter", "level": 4}],
            "abilities": {"STR": 10, "DEX": 14, "CON": 14, "INT": 8, "WIS": 10, "CHA": 8},
            "proficiency_bonus": 2, "equipped": {}, "active_buffs": [],
            "target": {"ac": 15, "save_bonus": {}, "resistances": [], "immunities": [],
                       "vulnerabilities": [], "conditions": [], "flags": []},
            "round_actions": [{"type": "spell", "ref": "Fire Bolt", "upcast_level": 0, "n_targets": 1}]}
    import copy
    full = copy.deepcopy(base)
    tiefling = copy.deepcopy(base)
    tiefling["target"]["species"] = "Tiefling"
    r_full = expected_round_damage(full)["total_ev"]
    r_tief = expected_round_damage(tiefling)["total_ev"]
    assert abs(r_tief / r_full - 0.5) < 0.01, (r_full, r_tief)
    print(f"  Tiefling fire {r_tief:.3f} = 0.5 * {r_full:.3f}")


def test_end_of_turn_burning_damage():
    """bg3.wiki raw_conditions/Burning: target takes 1d4 Fire at end of turn (2.5 EV)."""
    from engine.round import expected_round_damage
    build = {"name": "burn", "classes": [{"cls": "Fighter", "level": 4}],
             "abilities": {"STR": 10, "DEX": 14, "CON": 14, "INT": 8, "WIS": 10, "CHA": 8},
             "proficiency_bonus": 2, "equipped": {}, "active_buffs": [],
             "target": {"ac": 15, "save_bonus": {}, "resistances": [], "immunities": [],
                        "vulnerabilities": [], "conditions": ["Burning"], "flags": []},
             "round_actions": []}
    r = expected_round_damage(build)
    eot = [a for a in r["per_action"] if a.get("type") == "end_of_turn"]
    assert eot, "expected end_of_turn action"
    assert abs(eot[0]["total_ev"] - 2.5) < 0.01, eot[0]["total_ev"]
    print(f"  Burning EoT fire = {eot[0]['total_ev']}")


def test_tavern_brawler_adds_str_to_attack_roll():
    """bg3.wiki Feats: Tavern Brawler adds STR mod twice to damage AND Attack Roll on
    unarmed/thrown. A thrown javelin with TB has +STR mod extra attack bonus."""
    from engine.character import Character
    base = {"classes": [{"cls": "Fighter", "level": 4}],
            "abilities": {"STR": 18, "DEX": 14, "CON": 14, "INT": 8, "WIS": 10, "CHA": 8},
            "proficiency_bonus": 2, "attack_ability": "STR", "feats": [],
            "equipped": {"main_hand": "Javelins"}, "active_buffs": []}
    no_tb = Character(dict(base))
    tb = Character(dict(base)); tb.feats = ["Tavern Brawler"]
    w = tb.weapon_for("main_hand", "thrown")
    assert tb.attack_bonus(w, "thrown") - no_tb.attack_bonus(w, "thrown") == 4, "TB should add STR mod (+4) to attack"
    # melee should NOT get the bonus
    wm = tb.weapon_for("main_hand", "melee")
    assert tb.attack_bonus(wm, "melee") == no_tb.attack_bonus(wm, "melee")
    print(f"  TB thrown atk {tb.attack_bonus(w,'thrown')} vs no-TB {no_tb.attack_bonus(w,'thrown')}")


def test_spell_sniper_lowers_spell_crit_threshold():
    """bg3.wiki Feats: Spell Sniper reduces spell-attack crit threshold by 1 (20->19),
    weapon attacks unaffected."""
    from engine.character import Character
    base = {"classes": [{"cls": "Wizard", "level": 4}],
            "abilities": {"STR": 8, "DEX": 14, "CON": 14, "INT": 18, "WIS": 10, "CHA": 8},
            "proficiency_bonus": 2, "feats": [], "equipped": {}, "active_buffs": []}
    ss = Character(dict(base)); ss.feats = ["Spell Sniper"]
    assert ss.crit_threshold(attack_kind="spell") == 19
    assert ss.crit_threshold(attack_kind="melee") == 20  # weapon unaffected
    print(f"  Spell Sniper spell crit {ss.crit_threshold('spell')}, weapon {ss.crit_threshold('melee')}")


def test_spineshudder_inflicts_reverberation_triggers_thunder():
    """bg3.wiki: Spineshudder Amulet inflicts 2 Reverberation per ranged spell hit.
    At caster lvl 11, Eldritch Blast has 3 beams -> 6 stacks >= 5 -> 1d4 Thunder DRS
    at end of turn (2.5 EV)."""
    from engine.round import expected_round_damage
    build = {"name": "spine", "classes": [{"cls": "Warlock", "level": 11}],
             "abilities": {"STR": 8, "DEX": 14, "CON": 14, "INT": 8, "WIS": 10, "CHA": 20},
             "proficiency_bonus": 4, "feats": [], "equipped": {"neck": "Spineshudder Amulet"},
             "active_buffs": [],
             "target": {"ac": 12, "save_bonus": {}, "resistances": [], "immunities": [],
                        "vulnerabilities": [], "conditions": [], "flags": []},
             "round_actions": [{"type": "spell", "ref": "Eldritch Blast",
                                "upcast_level": 0, "n_targets": 1}]}
    r = expected_round_damage(build)
    eot = [a for a in r["per_action"] if a.get("type") == "end_of_turn"]
    assert eot, "expected end_of_turn Reverberation trigger"
    assert abs(eot[0]["total_ev"] - 2.5) < 0.01, eot[0]["total_ev"]
    print(f"  Spineshudder 6-stack -> {eot[0]['total_ev']} Thunder")


def test_adamantine_target_is_crit_immune():
    """bg3.wiki: Adamantine armour — attackers can't land critical hits on the wearer.
    A target wearing Adamantine Scale Mail has crit_immune derived."""
    from engine.character import Character, Target
    from engine.round import expected_round_damage
    build = {"name": "adam", "classes": [{"cls": "Fighter", "level": 4}],
             "abilities": {"STR": 16, "DEX": 14, "CON": 14, "INT": 8, "WIS": 10, "CHA": 8},
             "proficiency_bonus": 2, "attack_ability": "STR", "feats": [],
             "equipped": {"main_hand": "Longsword"},
             "active_buffs": [],
             "target": {"ac": 15, "save_bonus": {}, "resistances": [], "immunities": [],
                        "vulnerabilities": [], "conditions": [], "flags": [],
                        "equipped": {"armor": "Adamantine Scale Mail"}},
             "round_actions": [{"type": "attack", "weapon": "main_hand",
                                "attack_kind": "melee", "count": 1}]}
    r = expected_round_damage(build)
    a = r["per_action"][0]
    assert a["p_crit"] == 0.0, "Adamantine target should have p_crit=0"
    print(f"  Adamantine target p_crit={a['p_crit']} (crit folded into normal {a['p_normal']:.2f})")


def test_necklace_of_elemental_augmentation_adds_spell_mod():
    """bg3.wiki: cantrips add Spellcasting Modifier to damage. A Wizard (INT 18 -> +4)
    casting Fire Bolt deals +4 Fire per hit with the necklace."""
    from engine.round import expected_round_damage
    import copy
    base = {"name": "neck", "classes": [{"cls": "Wizard", "level": 4}],
            "abilities": {"STR": 8, "DEX": 14, "CON": 14, "INT": 18, "WIS": 10, "CHA": 8},
            "proficiency_bonus": 2, "feats": [], "equipped": {}, "active_buffs": [],
            "target": {"ac": 15, "save_bonus": {}, "resistances": [], "immunities": [],
                       "vulnerabilities": [], "conditions": [], "flags": []},
            "round_actions": [{"type": "spell", "ref": "Fire Bolt", "upcast_level": 0, "n_targets": 1}]}
    no_n = copy.deepcopy(base)
    n = copy.deepcopy(base); n["equipped"]["neck"] = "Necklace of Elemental Augmentation"
    r1 = expected_round_damage(no_n)["total_ev"]
    r2 = expected_round_damage(n)["total_ev"]
    # +4 INT mod per hit, weighted by spell-attack hit chance (~0.6)
    assert 1.5 < (r2 - r1) < 3.0, (r1, r2)
    print(f"  Necklace +{(r2-r1):.2f} (= INT mod 4 * p_hit)")


def test_everburn_blade_damage_parsing():
    """bg3.wiki: Everburn Blade = 2d6 Slashing + 1d4 Fire. weapons_named.json fuses this
    as '2d61d4'; the engine must parse the base die as 2d6 (not a bogus 2d61) and model
    the 1d4 Fire as a rider."""
    from engine.catalog import Catalog
    c = Catalog.get()
    w = c.weapon("Everburn Blade")
    assert w["die"] == "2d6", w["die"]
    riders = c.riders_for_item("Everburn Blade")
    fire = [r for r in riders if r.get("damage", {}).get("type") == "Fire"]
    assert fire and fire[0]["damage"]["dice"] == "1d4", riders
    print(f"  Everburn die={w['die']}, fire rider={fire[0]['damage']}")


def test_crimson_mischief_auto_advantage_flag():
    """bg3.wiki: Crimson Mischief Redvein Savagery needs Advantage. The engine auto-sets
    the attacker_has_advantage flag from the action's advantage, so +7 Piercing fires
    without the build declaring the flag. Flag must not leak to a later no-adv attack."""
    from engine.round import expected_round_damage
    build = {"name": "crimson", "classes": [{"cls": "Fighter", "level": 4}],
             "abilities": {"STR": 16, "DEX": 14, "CON": 14, "INT": 8, "WIS": 10, "CHA": 8},
             "proficiency_bonus": 2, "attack_ability": "STR", "feats": [],
             "equipped": {"main_hand": "Crimson Mischief"}, "active_buffs": [],
             "target": {"ac": 15, "save_bonus": {}, "resistances": [], "immunities": [],
                        "vulnerabilities": [], "conditions": [], "flags": []},
             "round_actions": [
                 {"type": "attack", "weapon": "main_hand", "attack_kind": "melee", "count": 1, "advantage": True},
                 {"type": "attack", "weapon": "main_hand", "attack_kind": "melee", "count": 1}]}
    r = expected_round_damage(build)
    a1, a2 = r["per_action"][0], r["per_action"][1]
    # adv attack has +7 Piercing DRS (Redvein Savagery) on top of the higher hit rate
    assert a1["total_ev"] > a2["total_ev"] + 6, (a1["total_ev"], a2["total_ev"])
    assert abs(a2["total_ev"] - 7.45) < 0.1, a2["total_ev"]  # no leak: 2nd attack has no +7
    print(f"  adv atk {a1['total_ev']:.2f} > no-adv atk {a2['total_ev']:.2f} (no flag leak)")


def test_adamantine_crit_immune_defense():
    """bg3.wiki: Adamantine armour = attackers can't land crits. A PC target wearing
    Adamantine Splint Armour has p_crit=0 and takes flat -2 to all damage."""
    from engine.round import expected_round_damage
    import copy
    base = {"name": "def", "classes": [{"cls": "Fighter", "level": 4}],
            "abilities": {"STR": 16, "DEX": 14, "CON": 14, "INT": 8, "WIS": 10, "CHA": 8},
            "proficiency_bonus": 2, "attack_ability": "STR", "feats": [],
            "equipped": {"main_hand": "Longsword"}, "active_buffs": [],
            "target": {"ac": 15, "save_bonus": {}, "resistances": [], "immunities": [],
                       "vulnerabilities": [], "conditions": [], "flags": []},
            "round_actions": [{"type": "attack", "weapon": "main_hand", "attack_kind": "melee", "count": 1}]}
    no_def = copy.deepcopy(base)
    adam = copy.deepcopy(base); adam["target"]["equipped"] = {"armor": "Adamantine Splint Armour"}
    r1 = expected_round_damage(no_def); r2 = expected_round_damage(adam)
    assert r2["per_action"][0]["p_crit"] == 0.0, "Adamantine should negate crits"
    assert r2["total_ev"] < r1["total_ev"], "flat reduction should lower damage"
    print(f"  Adamantine p_crit=0, dmg {r1['total_ev']:.2f}->{r2['total_ev']:.2f}")


def test_proficiency_bonus_auto_derived():
    """bg3.wiki: proficiency bonus = (total_level-1)//4 + 2. 1-4=2, 5-8=3, 9-12=4.
    Auto-derived when the build omits proficiency_bonus."""
    from engine.character import Character
    for lv, prof in [(1, 2), (4, 2), (5, 3), (8, 3), (9, 4), (12, 4), (13, 5), (17, 6)]:
        c = Character({"classes": [{"cls": "Fighter", "level": lv}]})
        assert c.prof == prof, (lv, c.prof)
    print("  proficiency auto-derived 1-4=2,5-8=3,9-12=4,13-16=5,17-20=6")


def test_extra_attack_doubles_attacks():
    """bg3.wiki: Extra Attack (Fighter 5) adds one attack to the Attack action.
    A Fighter 5 with extra_attack:true makes 2 attacks; Fighter 11 makes 3."""
    from engine.character import Character
    from engine.round import expected_round_damage
    assert Character({"classes": [{"cls": "Fighter", "level": 5}]}).extra_attacks() == 1
    assert Character({"classes": [{"cls": "Fighter", "level": 11}]}).extra_attacks() == 2
    assert Character({"classes": [{"cls": "Fighter", "level": 4}]}).extra_attacks() == 0
    assert Character({"classes": [{"cls": "Rogue", "level": 5}]}).extra_attacks() == 0
    build = {"name": "ea", "classes": [{"cls": "Fighter", "level": 5}],
             "abilities": {"STR": 16, "DEX": 14, "CON": 14, "INT": 8, "WIS": 10, "CHA": 8},
             "attack_ability": "STR", "feats": [], "equipped": {"main_hand": "Longsword"},
             "active_buffs": [],
             "target": {"ac": 15, "save_bonus": {}, "resistances": [], "immunities": [],
                        "vulnerabilities": [], "conditions": [], "flags": []},
             "round_actions": [{"type": "attack", "weapon": "main_hand",
                                "attack_kind": "melee", "count": 1, "extra_attack": True}]}
    r = expected_round_damage(build)
    a = r["per_action"][0]
    assert a["count"] == 2, a["count"]  # base 1 + 1 Extra Attack
    print(f"  Fighter 5 Extra Attack: count={a['count']}")


def test_multiclass_extra_attack_does_not_stack():
    """bg3.wiki: the Extra Attack feature does NOT stack across classes — Fighter 5 +
    Paladin 5 gets ONE Extra Attack (not two). Fighter 11's Improved Extra Attack is a
    distinct feature that still adds a second."""
    from engine.character import Character
    assert Character({"classes": [{"cls": "Fighter", "level": 5}, {"cls": "Paladin", "level": 5}]}).extra_attacks() == 1
    assert Character({"classes": [{"cls": "Fighter", "level": 11}, {"cls": "Paladin", "level": 5}]}).extra_attacks() == 2
    assert Character({"classes": [{"cls": "Barbarian", "level": 5}, {"cls": "Rogue", "level": 4}]}).extra_attacks() == 1
    print("  Extra Attack doesn't stack across Fighter5+Paladin5 (=1); Fighter11+Pal5 (=2)")


def test_multiclass_proficiency_and_spell_slot():
    """bg3.wiki multiclass: proficiency from TOTAL level; spell slot from highest
    caster class; per-class features (Rage/Sneak/Smite) coexist."""
    from engine.character import Character
    # total 9 -> prof 4
    c = Character({"classes": [{"cls": "Cleric", "level": 5}, {"cls": "Fighter", "level": 4}]})
    assert c.prof == 4
    # Cleric5 -> 3rd-level slots
    assert c.max_spell_slot() == 3
    # Barb5+Rogue3+Pal2: Rage + Sneak + Smite-eligible all present
    c2 = Character({"classes": [{"cls": "Barbarian", "level": 5}, {"cls": "Rogue", "level": 3}, {"cls": "Paladin", "level": 2}],
                    "abilities": {"STR": 16, "DEX": 14, "CON": 14, "INT": 8, "WIS": 10, "CHA": 12},
                    "equipped": {"main_hand": "Longsword"}, "active_buffs": [{"ref": "Rage (Barbarian)"}]})
    riders = list(c2.active_riders("melee"))
    assert any(r.get("damage", {}).get("flat_sym") == "rage_damage" for r in riders)  # Barb Rage
    assert any(r.get("once_per_turn") for r in riders)  # Rogue Sneak Attack
    assert c2.class_level("Paladin") >= 2  # Smite-eligible
    print("  multiclass prof/slot/features all coexist correctly")


def test_max_spell_slot_progression():
    """bg3.wiki caster progression: lvl1=1st, 3=2nd, 5=3rd, 7=4th, 9=5th, 11=6th.
    Half-casters (Paladin/Ranger) cap at 3rd-level slots (class lvl 9)."""
    from engine.character import Character
    cases = [(("Wizard", 1), 1), (("Wizard", 5), 3), (("Wizard", 11), 6),
             (("Fighter", 5), 0), (("Paladin", 5), 2), (("Paladin", 9), 3)]
    for (cls, lv), slot in cases:
        c = Character({"classes": [{"cls": cls, "level": lv}]})
        assert c.max_spell_slot() == slot, (cls, lv, c.max_spell_slot())
    print("  max_spell_slot: Wizard 1/5/11 = 1/3/6, Fighter 5 = 0, Paladin 5/9 = 2/3")


def test_improved_divine_smite_paladin_11():
    """bg3.wiki: Paladin 11 Improved Divine Smite — every melee weapon hit +1d8 Radiant
    (no slot cost). The rider is auto-injected from class level."""
    from engine.character import Character
    c = Character({"classes": [{"cls": "Paladin", "level": 11}],
                   "abilities": {"STR": 16, "DEX": 10, "CON": 14, "INT": 8, "WIS": 10, "CHA": 16},
                   "equipped": {"main_hand": "Longsword"}})
    riders = list(c.active_riders("melee"))
    ids = [r for r in riders if r.get("damage", {}).get("type") == "Radiant" and r.get("damage", {}).get("dice") == "1d8"]
    assert ids, "Paladin 11 should grant Improved Divine Smite (+1d8 Radiant)"
    c10 = Character({"classes": [{"cls": "Paladin", "level": 10}],
                     "abilities": {"STR": 16}, "equipped": {"main_hand": "Longsword"}})
    assert not any(r.get("damage", {}).get("type") == "Radiant" for r in c10.active_riders("melee"))
    print("  Paladin 11 Improved Divine Smite +1d8 Radiant injected")


def test_champion_subclass_crit_threshold():
    """bg3.wiki: Fighter Champion (subclass 3) Improved Critical Hit — crit on 19-20."""
    from engine.character import Character
    champ = Character({"classes": [{"cls": "Fighter", "level": 3, "subclass": "Champion"}]})
    plain = Character({"classes": [{"cls": "Fighter", "level": 3}]})
    assert champ.crit_threshold("melee") == 19
    assert plain.crit_threshold("melee") == 20
    print("  Champion crit 19, plain Fighter crit 20")


def test_spell_class_eligibility_check():
    """bg3.wiki: spells are class-restricted. A Fighter casting Fireball gets a mismatch
    note; a Wizard casting Fireball is fine; a Warlock casting Eldritch Blast is fine."""
    from engine.round import expected_round_damage
    base = {"name": "sp", "classes": [{"cls": "Fighter", "level": 6}],
            "abilities": {"STR": 16, "DEX": 14, "CON": 14, "INT": 8, "WIS": 10, "CHA": 8},
            "proficiency_bonus": 3, "feats": [], "equipped": {}, "active_buffs": [],
            "target": {"ac": 15, "save_bonus": {"DEX": 2}, "resistances": [], "immunities": [],
                       "vulnerabilities": [], "conditions": [], "flags": []},
            "round_actions": [{"type": "spell", "ref": "Fireball", "upcast_level": 3, "n_targets": 1}]}
    import copy
    # Fighter + Fireball -> mismatch note
    r = expected_round_damage(copy.deepcopy(base))
    notes = r["per_action"][0].get("notes", [])
    assert any("mismatch" in n for n in notes), notes
    # Wizard 5 + Fireball upcast 6 -> clamped to max slot 3
    w = copy.deepcopy(base); w["classes"] = [{"cls": "Wizard", "level": 5}]
    w["round_actions"][0]["upcast_level"] = 6
    rw = expected_round_damage(w)
    assert rw["per_action"][0]["upcast"] == 3, rw["per_action"][0]["upcast"]
    assert not any("mismatch" in n for n in rw["per_action"][0].get("notes", []))
    # Warlock 1 + Eldritch Blast -> fine
    wl = copy.deepcopy(base); wl["classes"] = [{"cls": "Warlock", "level": 1}]
    wl["round_actions"] = [{"type": "spell", "ref": "Eldritch Blast", "upcast_level": 0, "n_targets": 1}]
    assert not expected_round_damage(wl)["per_action"][0].get("notes", [])
    print("  spell class check: Fighter+Fireball warned, Wizard ok, Warlock+EB ok")


def test_metamagic_twinned_doubles_targets():
    """bg3.wiki Sorcerer Metamagic: Twinned Spell hits an additional target (n_targets x2);
    Heightened gives target save disadvantage (more damage); Empowered rerolls dice."""
    from engine.round import expected_round_damage
    import copy
    base = {"name": "sorc", "classes": [{"cls": "Sorcerer", "level": 6}],
            "abilities": {"STR": 8, "DEX": 14, "CON": 14, "INT": 8, "WIS": 10, "CHA": 18},
            "proficiency_bonus": 3, "feats": [], "equipped": {}, "active_buffs": [],
            "target": {"ac": 15, "save_bonus": {"DEX": 2}, "resistances": [], "immunities": [],
                       "vulnerabilities": [], "conditions": [], "flags": []},
            "round_actions": [{"type": "spell", "ref": "Fireball", "upcast_level": 3, "n_targets": 1}]}
    r0 = expected_round_damage(copy.deepcopy(base))["total_ev"]
    tw = copy.deepcopy(base); tw["active_buffs"] = [{"ref": "Metamagic: Twinned"}]
    r_tw = expected_round_damage(tw)["total_ev"]
    assert abs(r_tw - 2 * r0) < 0.01, (r0, r_tw)
    he = copy.deepcopy(base); he["active_buffs"] = [{"ref": "Metamagic: Heightened"}]
    assert expected_round_damage(he)["total_ev"] > r0
    em = copy.deepcopy(base); em["active_buffs"] = [{"ref": "Metamagic: Empowered"}]
    assert expected_round_damage(em)["total_ev"] > r0
    print(f"  Metamagic: Twinned {r0:.1f}->{r_tw:.1f} (x2), Heightened/Empowered raise dmg")


def test_rage_grants_physical_resistance_and_reckless_advantage():
    """bg3.wiki Barbarian: Rage grants resistance to physical damage (承受侧); Reckless
    Attack (level 2) grants Advantage on melee attacks."""
    from engine.character import Character
    from engine.round import expected_round_damage
    c = Character({"classes": [{"cls": "Barbarian", "level": 5}], "abilities": {"STR": 16},
                   "species": "Tiefling", "active_buffs": [{"ref": "Rage (Barbarian)"}], "equipped": {}})
    assert set(("Bludgeoning", "Piercing", "Slashing")).issubset(set(c.self_resistances()))
    # Reckless Attack on a Barb 2 melee attack -> advantage (higher hit than without)
    base = {"name": "rk", "classes": [{"cls": "Barbarian", "level": 2}],
            "abilities": {"STR": 16, "DEX": 14, "CON": 14, "INT": 8, "WIS": 10, "CHA": 8},
            "attack_ability": "STR", "feats": [], "equipped": {"main_hand": "Longsword"}, "active_buffs": [],
            "target": {"ac": 15, "save_bonus": {}, "resistances": [], "immunities": [],
                       "vulnerabilities": [], "conditions": [], "flags": []},
            "round_actions": [{"type": "attack", "weapon": "main_hand", "attack_kind": "melee", "count": 1}]}
    import copy
    no = copy.deepcopy(base); re = copy.deepcopy(base); re["round_actions"][0]["reckless"] = True
    assert expected_round_damage(re)["total_ev"] > expected_round_damage(no)["total_ev"]
    print("  Rage physical resistance + Reckless Attack advantage verified")


def test_fighting_style_archery_and_dueling():
    """bg3.wiki Fighter: Archery +2 ranged attack; Dueling +2 melee damage (no off-hand)."""
    from engine.character import Character
    arc = Character({"classes": [{"cls": "Fighter", "level": 1}], "abilities": {"STR": 10, "DEX": 16},
                     "fighting_style": "Archery", "equipped": {"main_hand": "Shortbow"}})
    w = arc.weapon_for("main_hand", "ranged")
    assert arc.attack_bonus(w, "ranged") == 7  # prof2 + DEX3 + Archery2
    duel = Character({"classes": [{"cls": "Fighter", "level": 1}], "abilities": {"STR": 16},
                      "fighting_style": "Dueling", "equipped": {"main_hand": "Longsword"}})
    assert duel.damage_bonus("melee") == 2
    # off-hand present -> no Dueling bonus
    duel_off = Character({"classes": [{"cls": "Fighter", "level": 1}], "abilities": {"STR": 16},
                          "fighting_style": "Dueling", "equipped": {"main_hand": "Longsword", "off_hand": "Dagger"}})
    assert duel_off.damage_bonus("melee") == 0
    print("  Fighting Style: Archery +2 atk, Dueling +2 dmg (no off-hand)")


def test_monk_ki_empowered_bypasses_physical_resistance():
    """bg3.wiki Monk 6 Ki-Empowered Strikes: unarmed strikes count as magical, bypassing
    non-magical physical resistance. Monk 5 does not."""
    from engine.round import _attack_bypass_types
    from engine.character import Character
    m6 = Character({"classes": [{"cls": "Monk", "level": 6}], "abilities": {"STR": 10, "DEX": 16}, "equipped": {}})
    m5 = Character({"classes": [{"cls": "Monk", "level": 5}], "abilities": {"STR": 10, "DEX": 16}, "equipped": {}})
    assert "Bludgeoning" in _attack_bypass_types(m6, "unarmed")
    assert "Bludgeoning" not in _attack_bypass_types(m5, "unarmed")
    print("  Ki-Empowered Strikes (Monk6) bypass Bludgeoning resistance")


def test_warlock_subclass_spell_features():
    """bg3.wiki: Agonizing Blast (+CHA to EB), Thirsting Blade (Extra Attack invocation),
    Draconic Elemental Affinity (+CHA), Evocation Empowered Evocation (+INT)."""
    from engine.character import Character
    from engine.catalog import Catalog
    c = Catalog.get()
    assert c.rider_by_key("Agonizing Blast")
    # Thirsting Blade grants Extra Attack
    wl = Character({"classes": [{"cls": "Warlock", "level": 5}], "abilities": {"STR": 10},
                    "active_buffs": [{"ref": "Thirsting Blade"}], "equipped": {}})
    assert wl.extra_attacks() == 1
    # Evocation auto-inject at Wizard 10 Evocation
    wiz = Character({"classes": [{"cls": "Wizard", "level": 10, "subclass": "Evocation"}],
                     "abilities": {"STR": 8, "INT": 18}, "equipped": {}})
    assert any(r.get("damage", {}).get("flat_sym") == "int_mod" for r in wiz.active_riders("spell"))
    # Draconic Bloodline active_buff injects +CHA
    sorc = Character({"classes": [{"cls": "Sorcerer", "level": 6}], "abilities": {"STR": 8, "CHA": 18},
                      "active_buffs": [{"ref": "Draconic Bloodline"}], "equipped": {}})
    assert any(r.get("damage", {}).get("flat_sym") == "cha_mod" for r in sorc.active_riders("spell"))
    print("  Agonizing Blast / Thirsting Blade / Draconic / Evocation all modelled")


def test_gwm_not_double_counted_via_feat_and_buff():
    """A build declaring both the GWM feat and the 'Great Weapon Master (active)' buff
    must apply the -5/+10 modifier ONCE (not twice). Regression for a double-count bug
    surfaced by the Fighter-12 hot-build benchmark."""
    from engine.character import Character
    c = Character({"classes": [{"cls": "Fighter", "level": 12}],
                   "abilities": {"STR": 20, "DEX": 14, "CON": 14, "INT": 8, "WIS": 10, "CHA": 8},
                   "attack_ability": "STR", "feats": ["Great Weapon Master"],
                   "equipped": {"main_hand": "Longsword"},
                   "active_buffs": [{"ref": "Great Weapon Master (active)"}]})
    mods = c._attack_modifiers()
    gwm = [m for m in mods if m.get("attack_bonus") == -5 and m.get("damage_bonus") == 10]
    assert len(gwm) == 1, f"GWM counted {len(gwm)} times: {mods}"
    assert c.damage_bonus("melee") == 10
    print("  GWM feat + active_buff applies -5/+10 exactly once")


def test_tempest_destructive_wrath_maximizes_lightning():
    """bg3.wiki: Cleric Tempest Domain Destructive Wrath (Channel Divinity) deals MAXIMUM
    Lightning/Thunder damage. Call Lightning 3d10 (EV 16.5, max 30) -> maximized."""
    from engine.round import expected_round_damage
    import copy
    base = {"name": "storm", "classes": [{"cls": "Cleric", "level": 6, "subclass": "Tempest Domain"},
                                          {"cls": "Sorcerer", "level": 6}],
            "abilities": {"STR": 8, "DEX": 14, "CON": 14, "INT": 8, "WIS": 18, "CHA": 14},
            "attack_ability": "WIS", "feats": [], "equipped": {}, "active_buffs": [],
            "target": {"ac": 16, "save_bonus": {"DEX": 2}, "resistances": [], "immunities": [],
                       "vulnerabilities": [], "conditions": [], "flags": []},
            "round_actions": [{"type": "spell", "ref": "Call Lightning", "upcast_level": 3, "n_targets": 1}]}
    r_normal = expected_round_damage(copy.deepcopy(base))["total_ev"]
    dw = copy.deepcopy(base); dw["active_buffs"] = [{"ref": "Destructive Wrath"}]
    r_max = expected_round_damage(dw)["total_ev"]
    assert r_max > r_normal + 10, (r_normal, r_max)  # maximized dice roughly double the EV
    # 3d10 max=30; DC16 vs DEX+2 (fail 0.65): 0.65*30 + 0.35*15 = 24.75
    assert abs(r_max - 24.75) < 0.5, r_max
    print(f"  Destructive Wrath: Call Lightning {r_normal:.1f} -> {r_max:.1f} (maximized)")


def test_assassin_surprised_auto_crit():
    """bg3.wiki: Rogue Assassin (subclass 3) Assassinate — vs a Surprised target, attacks
    have Advantage and are automatic critical hits. p_normal=0, p_crit=p_hit."""
    from engine.round import expected_round_damage
    import copy
    base = {"name": "asn", "classes": [{"cls": "Rogue", "level": 5, "subclass": "Assassin"},
                                       {"cls": "Fighter", "level": 4}, {"cls": "Barbarian", "level": 3}],
            "abilities": {"STR": 8, "DEX": 20, "CON": 14, "INT": 8, "WIS": 10, "CHA": 8},
            "attack_ability": "DEX", "feats": [], "equipped": {"main_hand": "Dagger"},
            "active_buffs": [{"ref": "Rage (Barbarian)"}],
            "target": {"ac": 16, "save_bonus": {}, "resistances": [], "immunities": [],
                       "vulnerabilities": [], "conditions": [], "flags": ["sneak_attack_eligible"]},
            "round_actions": [{"type": "attack", "weapon": "main_hand", "attack_kind": "melee",
                               "count": 1, "extra_attack": True}]}
    r_plain = expected_round_damage(copy.deepcopy(base))
    surprised = copy.deepcopy(base); surprised["target"]["flags"].append("surprised")
    r_surp = expected_round_damage(surprised)
    a = r_surp["per_action"][0]
    assert a["p_normal"] == 0.0, a["p_normal"]  # all hits are crits
    assert a["p_crit"] > 0.5
    assert r_surp["total_ev"] > r_plain["total_ev"] * 1.5  # crits roughly double weapon+sneak dice
    print(f"  Assassin surprised: p_crit={a['p_crit']:.2f}, dmg {r_plain['total_ev']:.1f}->{r_surp['total_ev']:.1f}")


def test_wild_shape_owlbear_attacks():
    """bg3.wiki: Moon Druid Wild Shape into Owlbear — 2 attacks (Beak 1d8+4 Piercing +
    Talons 1d6+4 Slashing). Non-Moon druid cannot use Moon-only forms."""
    from engine.round import expected_round_damage
    moon = {"name": "ws", "classes": [{"cls": "Druid", "level": 6, "subclass": "Circle of the Moon"}],
            "abilities": {"STR": 8, "DEX": 14, "CON": 14, "INT": 8, "WIS": 16, "CHA": 8},
            "attack_ability": "WIS", "feats": [], "equipped": {}, "active_buffs": [],
            "target": {"ac": 16, "save_bonus": {}, "resistances": [], "immunities": [],
                       "vulnerabilities": [], "conditions": [], "flags": []},
            "round_actions": [{"type": "wild_shape", "form": "Owlbear"}]}
    r = expected_round_damage(moon)
    a = r["per_action"][0]
    assert "Piercing" in a["per_type_ev"] and "Slashing" in a["per_type_ev"]
    assert a["count"] == 2
    # Non-Moon druid cannot use Owlbear (Moon-only)
    land = dict(moon); land["classes"] = [{"cls": "Druid", "level": 6, "subclass": "Circle of the Land"}]
    r2 = expected_round_damage(land)
    assert "note" in r2["per_action"][0] or r2["total_ev"] == 0
    print(f"  Owlbear Wild Shape: {a['per_type_ev']} (Moon only enforced)")


def test_summon_and_defense_features():
    """bg3.wiki: Skeleton summon deals 1d6+3 Piercing + 1d10 Necrotic; Evasion negates
    DEX-save half damage; Uncanny Dodge halves one hit."""
    from engine.round import expected_round_damage
    import copy
    # Skeleton summon
    sk = {"name": "sk", "classes": [{"cls": "Wizard", "level": 6}],
          "abilities": {"STR": 8, "DEX": 14, "CON": 14, "INT": 18, "WIS": 10, "CHA": 8},
          "feats": [], "equipped": {}, "active_buffs": [],
          "target": {"ac": 16, "save_bonus": {}, "resistances": [], "immunities": [],
                     "vulnerabilities": [], "conditions": [], "flags": []},
          "round_actions": [{"type": "summon", "summon": "Skeleton"}]}
    r = expected_round_damage(sk)["per_action"][0]
    assert "Piercing" in r["per_type_ev"] and "Necrotic" in r["per_type_ev"]
    # Evasion: Fireball vs DEX-save target with Evasion -> lower dmg
    fb = {"name": "fb", "classes": [{"cls": "Wizard", "level": 6}],
          "abilities": {"STR": 8, "DEX": 14, "CON": 14, "INT": 18, "WIS": 10, "CHA": 8},
          "attack_ability": "INT", "feats": [], "equipped": {}, "active_buffs": [],
          "target": {"ac": 16, "save_bonus": {"DEX": 5}, "resistances": [], "immunities": [],
                     "vulnerabilities": [], "conditions": [], "flags": []},
          "round_actions": [{"type": "spell", "ref": "Fireball", "upcast_level": 3, "n_targets": 1}]}
    r_no = expected_round_damage(copy.deepcopy(fb))["total_ev"]
    ev = copy.deepcopy(fb); ev["target"]["evasion"] = True
    r_ev = expected_round_damage(ev)["total_ev"]
    assert r_ev < r_no
    # Uncanny Dodge: attack halved
    atk = {"name": "atk", "classes": [{"cls": "Fighter", "level": 8}],
           "abilities": {"STR": 18, "DEX": 14, "CON": 14, "INT": 8, "WIS": 10, "CHA": 8},
           "attack_ability": "STR", "feats": [], "equipped": {"main_hand": "Longsword"}, "active_buffs": [],
           "target": {"ac": 16, "save_bonus": {}, "resistances": [], "immunities": [],
                      "vulnerabilities": [], "conditions": [], "flags": []},
           "round_actions": [{"type": "attack", "weapon": "main_hand", "attack_kind": "melee", "count": 1}]}
    r_noatk = expected_round_damage(copy.deepcopy(atk))["total_ev"]
    ud = copy.deepcopy(atk); ud["target"]["uncanny_dodge"] = True
    r_ud = expected_round_damage(ud)["total_ev"]
    assert abs(r_ud - r_noatk * 0.5) < 0.1
    print(f"  Skeleton summon OK; Evasion {r_no:.1f}->{r_ev:.1f}; Uncanny Dodge {r_noatk:.1f}->{r_ud:.1f}")


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    passed = 0
    for t in tests:
        try:
            t(); print(f'PASS {t.__name__}'); passed += 1
        except AssertionError as e:
            print(f'FAIL {t.__name__}: {e}')
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f'ERROR {t.__name__}: {type(e).__name__}: {e}')
    print(f'\n{passed}/{len(tests)} golden tests passed')
    sys.exit(0 if passed == len(tests) else 1)
