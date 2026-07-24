"""CLI: python -m engine <build.json>  -> prints expected damage breakdown.

Examples:
  python -m engine data/builds/fireball_test.json
  python -m engine data/builds/fighter_test.json
  python -m engine data/builds/lightning_thrower.json
"""
import sys, json
from .round import expected_round_damage


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m engine <build.json>")
        print("Builds: data/builds/*.json")
        sys.exit(1)
    path = sys.argv[1]
    r = expected_round_damage(path)
    print(f"Build: {r['build']}")
    print(f"Total expected damage/round: {r['total_ev']:.2f}")
    print("Per damage type (post-resistance):")
    for dt, v in sorted(r['total_per_type'].items(), key=lambda x: -x[1]):
        print(f"  {dt:14s}: {v:.2f}")
    print("Per action:")
    for a in r['per_action']:
        if a.get('type') == 'attack':
            print(f"  [attack] {a.get('weapon')} x{a.get('count')} "
                  f"(atk+{a.get('attack_bonus')}, crit{a.get('crit_threshold')}-20): "
                  f"{a['total_ev']:.2f}  p_hit={a['p_normal']:.2f} p_crit={a['p_crit']:.2f}")
        elif a.get('type') == 'spell':
            print(f"  [spell]  {a.get('spell')} (upcast {a.get('upcast')}, "
                  f"x{a.get('n_targets')}): {a['total_ev']:.2f}")
        else:
            print(f"  [{a.get('type','?')}] {a.get('note','')}: {a['total_ev']:.2f}")


if __name__ == '__main__':
    main()
