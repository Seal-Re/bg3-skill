"""Attack-roll hit / crit / miss probability.

BG3 rules (verified vs bg3.wiki Attack_roll):
- attack roll = d20 + attack_bonus vs target AC
- natural 20 = critical hit (always hits, doubles damage dice)
- natural 1 = always miss
- crit_threshold can be reduced (e.g. Bloodthirst -1 -> crit on 19-20)
- advantage: roll 2d20 keep highest; disadvantage: keep lowest
"""
from .ev import clamp


def crit_threshold(reductions=0) -> int:
    """Effective crit threshold on a d20 (20 = crit only on 20)."""
    return max(1, 20 - int(reductions))


def p_hit(attack_bonus: int, ac: int, crit_threshold_val: int = 20,
          advantage: bool = False, disadvantage: bool = False,
          crit_immune: bool = False, auto_crit: bool = False,
          halfling_luck: bool = False) -> tuple:
    """Return (p_normal_hit, p_crit, p_miss).

    p_normal_hit excludes crits. p_miss = 1 - p_normal - p_crit.

    crit_immune: target cannot be crit (Adamantine etc.) — nat20 is a plain hit,
        so p_crit = 0 and that probability folds into p_normal.
    auto_crit: target is Paralysed/Sleeping — every hit is a crit (p_crit = p_hit,
        p_normal = 0). Melee attacks vs such targets auto-crit per bg3.wiki.
    halfling_luck: reroll a natural 1 once, keep the new roll (bg3.wiki Halfling Luck).
        Only the nat1 face is re-rolled; other faces keep their outcome. This raises
        hit/crit probability and lowers miss probability.
    """
    if auto_crit:
        # Compute base hit probability (no crit distinction), then all hits are crits.
        k = ac - attack_bonus
        k = max(2, min(20, k))
        p_hit_single = clamp((21 - k) / 20.0, 0.0, 1.0)
        if halfling_luck:
            # nat1 reroll: miss only if both rolls miss.
            p_miss_single = clamp(1.0 - p_hit_single, 0.0, 1.0)
            p_hit_single = 1.0 - p_miss_single ** 2
        if advantage and disadvantage:
            advantage = disadvantage = False
        if advantage:
            p_hit_tot = 1 - (1 - p_hit_single) ** 2
        elif disadvantage:
            p_hit_tot = p_hit_single ** 2
        else:
            p_hit_tot = p_hit_single
        return (0.0, clamp(p_hit_tot, 0.0, 1.0), clamp(1 - p_hit_tot, 0.0, 1.0))

    # Probability a single d20 crits
    p_crit_single = (21 - crit_threshold_val) / 20.0  # threshold 20 -> 1/20; 19 -> 2/20
    p_crit_single = clamp(p_crit_single, 0.0, 1.0)
    if crit_immune:
        p_crit_single = 0.0

    # Minimum roll on the d20 (before bonus) needed to hit: k such that k + bonus >= AC
    # k = AC - bonus. nat 1 always misses (so need k>=2), nat 20 always hits.
    k = ac - attack_bonus
    k = max(2, min(20, k))
    # P(single roll hits) = (21 - k)/20 ; P(single roll crits) = p_crit_single
    p_hit_single = clamp((21 - k) / 20.0, 0.0, 1.0)
    p_normal_single = clamp(p_hit_single - p_crit_single, 0.0, 1.0)
    p_miss_single = clamp(1.0 - p_hit_single, 0.0, 1.0)

    if halfling_luck:
        # nat1 (prob 1/20) is rerolled once, keep new roll (no second luck reroll).
        # The nat1 face is replaced by a fresh single-roll draw: so the nat1 mass
        # (1/20) is redistributed across {miss, normal, crit} per the single-roll
        # distribution, rather than all landing on miss.
        p1 = 1.0 / 20.0
        # single-roll distribution EXCLUDING the nat1 face already accounts for nat1
        # within p_miss_single (nat1 is a miss). Remove it, then re-add it distributed.
        p_miss_no1 = clamp(p_miss_single - p1, 0.0, 1.0)   # non-nat1 misses
        p_normal_no1 = p_normal_single                      # nat1 is not a normal hit
        p_crit_no1 = p_crit_single                           # nat1 is not a crit
        # the rerolled nat1 mass takes a fresh single-roll distribution:
        p_miss_single = clamp(p_miss_no1 + p1 * p_miss_single, 0.0, 1.0)
        p_normal_single = clamp(p_normal_no1 + p1 * p_normal_single, 0.0, 1.0)
        p_crit_single = clamp(p_crit_no1 + p1 * p_crit_single, 0.0, 1.0)

    if advantage and disadvantage:
        # cancel out
        advantage = disadvantage = False
    if advantage:
        # hit = 1 - P(both miss); crit = 1 - P(both non-crit)
        p_hit = 1 - p_miss_single ** 2
        p_crit = 1 - (1 - p_crit_single) ** 2
        p_normal = clamp(p_hit - p_crit, 0.0, 1.0)
        p_miss = clamp(1 - p_hit, 0.0, 1.0)
    elif disadvantage:
        # hit = P(both hit); crit = P(both crit)
        p_hit = p_hit_single ** 2
        p_crit = p_crit_single ** 2
        p_normal = clamp(p_hit - p_crit, 0.0, 1.0)
        p_miss = clamp(1 - p_hit, 0.0, 1.0)
    else:
        p_normal, p_crit, p_miss = p_normal_single, p_crit_single, p_miss_single

    if crit_immune:
        # crit probability folds into normal hits
        p_normal = clamp(p_normal + p_crit, 0.0, 1.0)
        p_crit = 0.0

    return (p_normal, p_crit, p_miss)
