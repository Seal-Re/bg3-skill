"""Unit tests for attack + save probability modules."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import attack, save

def approx(a, b, eps=0.001):
    return abs(a - b) < eps

def test_attack_basic():
    # bonus +7 vs AC 15: need roll >= 8 -> 13/20 hit; crit 1/20
    pn, pc, pm = attack.p_hit(7, 15)
    assert approx(pn, 0.60), pn   # (21-8)/20 - 1/20 = 13/20 - 1/20 = 12/20 = 0.60
    assert approx(pc, 0.05), pc
    assert approx(pm, 0.35), pm

def test_attack_crit_threshold():
    # Bloodthurst -1 -> crit on 19-20 = 2/20 = 0.10
    pn, pc, pm = attack.p_hit(7, 15, crit_threshold_val=19)
    assert approx(pc, 0.10), pc

def test_attack_always_miss_low_bonus():
    # bonus +0 vs AC 25: only nat20 hits (and crits)
    pn, pc, pm = attack.p_hit(0, 25)
    assert approx(pc, 0.05)
    assert approx(pn, 0.0)  # nat20 is crit, not normal

def test_attack_advantage():
    pn, pc, pm = attack.p_hit(7, 15, advantage=True)
    # p_miss_single = 0.35 -> adv miss = 0.1225 ; p_hit = 0.8775
    assert approx(pm, 0.1225), pm
    # crit adv = 1 - 0.95^2 = 0.0975
    assert approx(pc, 0.0975), pc

def test_save_fail():
    # DC 15, save +2: need roll >= 13 to save -> fail = 12/20 = 0.60... wait
    # need = 15-2 = 13; fail = (13-1)/20 = 12/20 = 0.60
    pf = save.p_fail(15, 2)
    assert approx(pf, 0.60), pf

def test_save_spell_fireball():
    # Fireball 8d6 fire (avg 28), DEX save half. DC 15, save +2 -> p_fail 0.60
    ev = save.save_spell_ev("8d6", dc=15, save_bonus=2, save_effect="half")
    # 0.60*28 + 0.40*14 = 16.8 + 5.6 = 22.4
    assert approx(ev, 22.4), ev

def test_save_spell_no_save_dmg():
    # Sacred Flame: 1d8, no damage on save. DC 13, save +0 -> need 13, fail=12/20=0.60
    ev = save.save_spell_ev("1d8", dc=13, save_bonus=0, save_effect="no_damage_on_save")
    assert approx(ev, 0.60 * 4.5), ev

def test_attack_crit_immune():
    # Adamantine: nat20 is a plain hit, no crit. p_crit folds into p_normal.
    pn, pc, pm = attack.p_hit(7, 15, crit_immune=True)
    assert approx(pc, 0.0), pc
    assert approx(pn, 0.65), pn   # 0.60 normal + 0.05 former-crit
    assert approx(pm, 0.35), pm

def test_attack_auto_crit():
    # Paralysed/Sleeping: every hit is a crit. p_normal = 0, p_crit = p_hit.
    pn, pc, pm = attack.p_hit(7, 15, auto_crit=True)
    assert approx(pn, 0.0), pn
    assert approx(pc, 0.65), pc   # all hits are crits
    assert approx(pm, 0.35), pm

def test_attack_halfling_luck():
    # Halfling Luck: nat1 (0.05) rerolled once, keep new roll (no second luck reroll).
    # atk+6 vs AC15: single = miss 0.40, normal 0.55, crit 0.05.
    # nat1 mass (0.05 of the miss) is rerolled on the single-roll distribution.
    # final miss = 0.35 + 0.05*0.40 = 0.37 ; crit = 0.05 + 0.05*0.05 = 0.0525
    # final normal = 0.55 + 0.05*0.55 = 0.5775
    pn, pc, pm = attack.p_hit(6, 15, halfling_luck=True)
    assert approx(pm, 0.37), pm
    assert approx(pc, 0.0525), pc
    assert approx(pn, 0.5775), pn

if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    passed = 0
    for t in tests:
        try:
            t(); print(f'PASS {t.__name__}'); passed += 1
        except AssertionError as e:
            print(f'FAIL {t.__name__}: {e}')
        except Exception as e:
            print(f'ERROR {t.__name__}: {type(e).__name__}: {e}')
    print(f'\n{passed}/{len(tests)} attack/save tests passed')
    sys.exit(0 if passed == len(tests) else 1)
