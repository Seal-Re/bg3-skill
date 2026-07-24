"""Tests for the rider engine DS/DR/DRS expansion.

Verified against bg3.wiki Damage_mechanics model. Uses a stub resolver and a
simple weapon + curated rider dicts.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import rider_engine as re
from engine.damage import DamagePool

class StubTarget:
    def __init__(self, conditions=None, flags=None, resistances=None, immunities=None, vulnerabilities=None):
        self.conditions = conditions or []
        self.flags = flags or []
        self.resistances = resistances or []
        self.immunities = immunities or []
        self.vulnerabilities = vulnerabilities or []

def approx(a, b, eps=0.001):
    return abs(a - b) < eps

# ---- Rider definitions (mirrors data/riders.json entries) ----
CAUSTIC = {"trigger": "weapon_attack_hit", "kind": "DR",
           "damage": {"dice": None, "flat": 2, "type": "Acid"}}
HEX = {"trigger": "weapon_attack_hit", "kind": "DR",
       "damage": {"dice": "1d6", "flat": 0, "type": "Necrotic"},
       "condition": "target_has:Hex"}
LIGHTNING_CHARGES = {"trigger": "weapon_attack_hit", "kind": "DRS",
                     "damage": {"dice": "1d8", "flat": 0, "type": "Lightning"},
                     "consume": "lightning_charges"}
TAVERN_BRAWLER = {"trigger": "unarmed_attack_hit", "kind": "DR",
                  "damage": {"dice": None, "flat_sym": "str_mod", "type": "Bludgeoning"}}

def resolver(sym):
    return {"ability_mod": 5, "str_mod": 5, "dex_mod": 3, "prof": 3}.get(sym, 0)

def test_basic_ds():
    # Longsword 1d8 slashing +3 enchant, +5 str mod, melee
    weapon = {"die": "1d8", "enchantment": 0, "damage_type": "Slashing"}
    pool = re.expand_attack(weapon, "melee", [], StubTarget(), resolver)
    # 1d8(4.5) + 5 str = 9.5 slashing
    assert approx(pool.ev(crit=False, resolver=resolver), 9.5), pool.ev(crit=False, resolver=resolver)

def test_dr_per_source():
    # Weapon DS + Caustic Band DR (+2 acid). Hex requires target_has:Hex -> not set, skipped.
    weapon = {"die": "1d8", "enchantment": 0, "damage_type": "Slashing"}
    riders = [CAUSTIC, HEX]
    pool = re.expand_attack(weapon, "melee", riders, StubTarget(), resolver)
    by = pool.ev_by_type(crit=False, resolver=resolver)
    assert approx(by["Slashing"], 9.5)
    assert approx(by["Acid"], 2.0)   # Caustic fires once on the DS
    assert "Necrotic" not in by       # Hex skipped (no condition)

def test_hex_with_condition():
    weapon = {"die": "1d8", "enchantment": 0, "damage_type": "Slashing"}
    riders = [CAUSTIC, HEX]
    target = StubTarget(conditions=["Hex"])
    pool = re.expand_attack(weapon, "melee", riders, target, resolver)
    by = pool.ev_by_type(crit=False, resolver=resolver)
    assert approx(by["Necrotic"], 3.5)  # 1d6 = 3.5

def test_drs_triggers_dr_again():
    """The canonical multiplicative case: Lightning Charges (DRS) re-triggers DRs.

    Setup: weapon 1d8 slashing +0 +5 str. Caustic Band (+2 acid, DR).
    Lightning Charges (+1d8 lightning, DRS).
    Sources = [DS(1d8+5 slashing), DRS(1d8 lightning)]
    Each source gets Caustic +2 acid once -> 2 sources * 2 acid = 4 acid total.
    """
    weapon = {"die": "1d8", "enchantment": 0, "damage_type": "Slashing"}
    riders = [CAUSTIC, LIGHTNING_CHARGES]
    pool = re.expand_attack(weapon, "melee", riders, StubTarget(), resolver)
    by = pool.ev_by_type(crit=False, resolver=resolver)
    assert approx(by["Slashing"], 9.5), by      # base DS
    assert approx(by["Lightning"], 4.5), by     # DRS 1d8 = 4.5
    assert approx(by["Acid"], 4.0), by          # Caustic fires on BOTH DS and DRS = 2+2
    total = pool.ev(crit=False, resolver=resolver)
    assert approx(total, 9.5 + 4.5 + 4.0), total

def test_crit_doubles_dice_riders_not_flat():
    """Crit doubles dice components (weapon die, Hex 1d6) but not flat (Caustic +2)."""
    weapon = {"die": "1d8", "enchantment": 0, "damage_type": "Slashing"}
    riders = [CAUSTIC, HEX]
    target = StubTarget(conditions=["Hex"])
    base = re.expand_attack(weapon, "melee", riders, target, resolver)
    crit = base.with_doubled_dice()
    bc = base.ev_by_type(crit=False, resolver=resolver)
    # crit_pool dice are physically doubled, so evaluate at crit=False
    cc = crit.ev_by_type(crit=False, resolver=resolver)
    assert approx(cc["Slashing"], 9.0 + 5)   # 2d8=9 + 5 str (flat unchanged)
    assert approx(cc["Necrotic"], 7.0)        # 2d6 = 7
    assert approx(cc["Acid"], 2.0)            # flat +2 unchanged

def test_unarmed_tavern_brawler():
    """Unarmed: base 1 + str. Tavern Brawler adds str again (flat rider)."""
    weapon = {"die": None, "enchantment": 0, "damage_type": "Bludgeoning"}
    # Unarmed base DS = ability mod (str=5). Tavern Brawler adds str_mod again (5).
    # Total Bludgeoning = 5 + 5 = 10. (The flat base '1' of unarmed is added by the
    # character layer, not modeled in build_base_ds.)
    pool = re.expand_attack(weapon, "unarmed", [TAVERN_BRAWLER], StubTarget(), resolver)
    by = pool.ev_by_type(crit=False, resolver=resolver)
    # tavern brawler adds str_mod (5) on top of base DS ability_mod (5)
    assert approx(by["Bludgeoning"], 10.0), by

def test_multisource_spell_riders_per_source():
    """bg3.wiki Damage_mechanics: each projectile of a multi-source spell is an
    independent damage source and re-triggers applicable riders (DamageBonus type).

    Model 3 Magic-Missile-like darts (1d4+1=3.5 Force each) with a +2 Radiant DR
    that fires on spell damage. Each dart is a separate source, so Radiant should
    fire 3 times (6.0), not once. expand_sources is the shared core.
    """
    from engine.damage import DamageComponent
    # 3 source pools (3 darts), each 1d4+1 Force
    sources = [DamagePool([DamageComponent(type="Force", dice="1d4+1")]) for _ in range(3)]
    # a spell-side DR: +2 Radiant per source (DamageBonus semantics)
    radiant_dr = {"damage": {"dice": None, "flat": 2, "type": "Radiant"}}
    pool = re.expand_sources(sources, [radiant_dr], "Force", resolver)
    by = pool.ev_by_type(crit=False, resolver=resolver)
    assert approx(by["Force"], 10.5), by      # 3 * 3.5
    assert approx(by["Radiant"], 6.0), by     # 3 * 2 (per source, not once)

def test_multisource_spell_honour_mode():
    """Honour mode downgrades DRS to DR for spell sources too."""
    from engine.damage import DamageComponent
    sources = [DamagePool([DamageComponent(type="Force", dice="1d4+1")]) for _ in range(3)]
    # a DRS on a spell source; in honour mode it must behave as DR (applied once per
    # source, no new source). Here we model it by passing it in the dr_list directly
    # (the round layer does this remapping); expand_sources just applies dr_list per source.
    drs_as_dr = {"damage": {"dice": "1d4", "flat": 0, "type": "Lightning"}}
    pool = re.expand_sources(sources, [drs_as_dr], "Force", resolver)
    by = pool.ev_by_type(crit=False, resolver=resolver)
    assert approx(by["Force"], 10.5), by
    assert approx(by["Lightning"], 7.5), by    # 3 * 2.5 (once per source, no re-trigger chain)


def test_bypass_resistance_ignores_resist_and_immune():
    """bg3.wiki Resistance: Hellfire ignores Fire resistance AND immunity. A bypass
    component skips both but vulnerability still doubles."""
    from engine.damage import DamageComponent
    # 2d6 Fire = 7.0
    normal = DamagePool([DamageComponent(type="Fire", dice="2d6")])
    hellfire = DamagePool([DamageComponent(type="Fire", dice="2d6", bypass_resistance=True)])
    immune_tgt = StubTarget(immunities=["Fire"])
    vuln_tgt = StubTarget(vulnerabilities=["Fire"])
    ev_normal = normal.ev_by_type(False, resolver)
    ev_hell = hellfire.ev_by_type(False, resolver)
    # normal fire vs immune -> 0; hellfire vs immune -> full 7
    assert approx(normal.apply_resistances(ev_normal, immune_tgt)["Fire"], 0.0)
    assert approx(hellfire.apply_resistances(ev_hell, immune_tgt)["Fire"], 7.0)
    # hellfire vs vulnerable -> still doubles (vuln applies, bypass only skips res/imm)
    assert approx(hellfire.apply_resistances(ev_hell, vuln_tgt)["Fire"], 14.0)


def test_savage_attacks_extra_die_on_crit():
    """bg3.wiki Savage_Attacks (Half-Orc): melee weapon crit adds ONE extra weapon die.
    greatsword 2d6 -> crit 5d6 (not 4d6); greataxe 1d12 -> crit 3d12 (not 2d12)."""
    from engine.damage import DamageComponent
    gs = DamageComponent(type="Slashing", dice="2d6", savage_attacks=True)
    assert gs.doubled_dice().dice == "5d6", gs.doubled_dice().dice
    ga = DamageComponent(type="Slashing", dice="1d12", savage_attacks=True)
    assert ga.doubled_dice().dice == "3d12", ga.doubled_dice().dice
    # without the flag, normal doubling (no extra die)
    plain = DamageComponent(type="Slashing", dice="2d6")
    assert plain.doubled_dice().dice == "4d6"


def test_elemental_adept_bypass_and_min2():
    """bg3.wiki Elemental Adept: chosen type ignores resistance, and dice cannot roll 1
    (min treated as 2). bypass_resistance skips res/imm; upgrade_min2 raises EV."""
    from engine.damage import DamagePool, DamageComponent
    from engine import dice
    # min2: d6 EV 3.5 -> faces {2,2,3,4,5,6} = 22/6 = 3.6667, so upgrade = 0.1667
    assert approx(dice.upgrade_min2("1d6"), 0.16667), dice.upgrade_min2("1d6")
    # bypass: Fire vs Fire-resistant target -> 0 normally, full with bypass
    pool = DamagePool([DamageComponent(type="Fire", dice="2d6")])
    tgt = StubTarget(resistances=["Fire"])
    ev = pool.ev_by_type(False, resolver)
    assert approx(pool.apply_resistances(ev, tgt)["Fire"], 3.5)  # 7 * 0.5
    assert approx(pool.apply_resistances(ev, tgt, bypass_types={"Fire"})["Fire"], 7.0)


def test_bonespike_bypass_physical_resistance():
    """bg3.wiki Bonespike Gloves: attacks ignore S/P/B resistance. End-to-end: a slashing
    attack vs a Slashing-resistant target deals full damage with Bonespike, half without."""
    from engine.round import expected_round_damage
    import copy
    base = {"name": "bone", "classes": [{"cls": "Fighter", "level": 4}],
            "abilities": {"STR": 16, "DEX": 14, "CON": 14, "INT": 8, "WIS": 10, "CHA": 8},
            "proficiency_bonus": 2, "attack_ability": "STR", "feats": [],
            "equipped": {"main_hand": "Longsword"}, "active_buffs": [],
            "target": {"ac": 15, "save_bonus": {}, "resistances": ["Slashing"],
                       "immunities": [], "vulnerabilities": [], "conditions": [], "flags": []},
            "round_actions": [{"type": "attack", "weapon": "main_hand", "attack_kind": "melee", "count": 1}]}
    no_bone = copy.deepcopy(base)
    bone = copy.deepcopy(base); bone["equipped"]["gloves"] = "Bonespike Gloves"
    r1 = expected_round_damage(no_bone)["total_ev"]
    r2 = expected_round_damage(bone)["total_ev"]
    assert abs(r2 / r1 - 2.0) < 0.05, (r1, r2)  # bypass doubles vs resistance
    print(f"  Bonespike bypass ratio {r2/r1:.2f}")

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
    print(f'\n{passed}/{len(tests)} rider tests passed')
    sys.exit(0 if passed == len(tests) else 1)
