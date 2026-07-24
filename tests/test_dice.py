"""Unit tests for dice EV + crit doubling. Pure math, no data deps."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import dice

def approx(a, b, eps=0.001):
    return abs(a - b) < eps

def test_basic_ev():
    assert approx(dice.ev("8d6"), 28.0)        # 8 * 3.5
    assert approx(dice.ev("1d8"), 4.5)
    assert approx(dice.ev("1d8 + 1"), 5.5)
    assert approx(dice.ev("2d6 + 3"), 10.0)    # 7 + 3
    assert approx(dice.ev("5"), 5.0)
    assert approx(dice.ev(None), 0.0)
    assert approx(dice.ev(""), 0.0)

def test_crit_doubles_dice_not_flat():
    assert approx(dice.ev("8d6", crit=True), 56.0)   # dice double
    assert approx(dice.ev("1d8 + 1", crit=True), 10.0)  # 2d8=9, +1 stays
    assert approx(dice.ev("1d8", crit=True), 9.0)
    assert approx(dice.ev("5", crit=True), 5.0)      # flat unchanged
    assert approx(dice.ev("2d6 + 3", crit=True), 17.0)  # 4d6=14 + 3

def test_min_max():
    assert dice.min_roll("8d6") == 8
    assert dice.max_roll("8d6") == 48
    assert dice.min_roll("1d8 + 1") == 2
    assert dice.max_roll("1d8 + 1") == 9

def test_int_input():
    assert approx(dice.ev(5), 5.0)

if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f'PASS {t.__name__}')
            passed += 1
        except AssertionError as e:
            print(f'FAIL {t.__name__}: {e}')
        except Exception as e:
            print(f'ERROR {t.__name__}: {type(e).__name__}: {e}')
    print(f'\n{passed}/{len(tests)} dice tests passed')
    sys.exit(0 if passed == len(tests) else 1)
