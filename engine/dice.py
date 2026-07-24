"""Die-expression parsing and expected-value (EV) computation.

BG3 crit rule: a critical hit doubles the NUMBER of damage dice, but NOT flat
modifiers (enchantment, ability modifier). So ev("1d8 + 1", crit=False) = 5.5,
ev("1d8 + 1", crit=True) = 9.5 (the die doubles to 2d8=9, the +1 stays).

Expressions supported: "8d6", "1d8 + 1", "2d6 + 3", "1d4", plain "5" (flat).
A component is either a die term (NdM) or a flat integer.
"""
import re
from dataclasses import dataclass


@dataclass
class DieTerm:
    count: int
    sides: int

    @property
    def ev(self) -> float:
        return self.count * (self.sides + 1) / 2.0

    def doubled(self) -> "DieTerm":
        return DieTerm(self.count * 2, self.sides)


@dataclass
class DiceExpr:
    dice: list  # list[DieTerm]
    flat: int   # integer modifier (NOT doubled on crit)

    def ev(self, crit: bool = False) -> float:
        total = self.flat
        for d in self.dice:
            total += (d.doubled() if crit else d).ev
        return float(total)


_DIE_RE = re.compile(r'(\d+)\s*d\s*(\d+)', re.I)
_FLAT_RE = re.compile(r'([+-]\s*\d+)(?!\s*d)', re.I)


def parse(expr) -> DiceExpr:
    """Parse a die expression string (or int) into DiceExpr.

    Accepts "8d6", "1d8 + 1", "2d6+3", "5", 5, None (-> 0).
    """
    if expr is None or expr == '':
        return DiceExpr([], 0)
    if isinstance(expr, (int, float)):
        return DiceExpr([], int(expr))
    s = str(expr).strip().lower()
    dice = []
    for cnt, sides in _DIE_RE.findall(s):
        dice.append(DieTerm(int(cnt), int(sides)))
    flat = 0
    # Remove die terms first, then sum signed flat ints
    s_no_dice = _DIE_RE.sub('', s)
    for m in _FLAT_RE.findall(s_no_dice):
        flat += int(m.replace(' ', ''))
    # If no signed flats but bare number remains, capture it
    if flat == 0:
        bare = re.findall(r'\d+', s_no_dice)
        for b in bare:
            flat += int(b)
    return DiceExpr(dice, flat)


def ev(expr, crit: bool = False) -> float:
    """Convenience: EV of a die expression."""
    return parse(expr).ev(crit=crit)


def min_roll(expr) -> int:
    p = parse(expr)
    return sum(d.count for d in p.dice) + p.flat  # each die min = 1


def max_roll(expr) -> int:
    p = parse(expr)
    return sum(d.count * d.sides for d in p.dice) + p.flat


def die_max2_ev(sides: int) -> float:
    """Expected value of 'roll 2, keep higher' for a single die of given sides.
    Used by Savage Attacker (reroll weapon damage dice, keep higher).
    E[max(d1,d2)] = sum over k of k * P(max=k) = sum_{k=1..s} k*( (k/s)^2 - ((k-1)/s)^2 ).
    Simplifies to (1/s^2) * sum_{k=1..s} (2k-1)*k.
    """
    s = sides
    total = sum((2 * k - 1) * k for k in range(1, s + 1))
    return total / (s * s)


def upgrade_savage(dice_expr) -> float:
    """Extra EV from Savage Attacker on a die expression (reroll dice keep higher).

    Returns the ADDITIONAL EV (max2_ev - normal_ev) summed over all die terms.
    Flat modifiers are unaffected.
    """
    p = parse(dice_expr)
    extra = 0.0
    for d in p.dice:
        normal = d.ev
        max2 = d.count * die_max2_ev(d.sides)
        extra += (max2 - normal)
    return extra


def die_min2_ev(sides: int) -> float:
    """EV of a single die where a roll of 1 is treated as 2 (Elemental Adept:
    'cannot roll a 1'). = (2 + 3 + ... + sides) / sides = (sides*(sides+1)/2 - 1 + 2)/sides."""
    s = sides
    total = sum(range(2, s + 1)) + 2  # faces 2..s each once, and face 1 -> 2
    return total / s


def upgrade_min2(dice_expr) -> float:
    """Additional EV from treating 1s as 2s on a die expression (Elemental Adept).
    Returns the ADDITIONAL EV over the normal EV."""
    p = parse(dice_expr)
    extra = 0.0
    for d in p.dice:
        normal = d.ev
        min2 = d.count * die_min2_ev(d.sides)
        extra += (min2 - normal)
    return extra


def die_reroll_low2_ev(sides: int) -> float:
    """EV of a single die where a roll of 1 or 2 is rerolled once, keep higher
    (Hat of the Sharp Caster: reroll spell-attack damage dice of 1 or 2).
    For face 1: new = max(1, r), r~U{1..s} -> E = s-mean (since max(1,r)=r as r>=1).
    For face 2: new = max(2, r). For face 3..s: unchanged (=k)."""
    s = sides
    # E[max(1,r)] over r~U{1..s} = E[r] = (s+1)/2  (r>=1 always)
    e_face1 = (s + 1) / 2.0
    # E[max(2,r)] = (1/s) * ( sum_{r=1..s} max(2,r) ) = (1/s)*( 2 + sum_{r=3..s} r )
    #   = (1/s)*( 2 + (s(s+1)/2 - 1 - 2) ) = (1/s)*( 2 + s(s+1)/2 - 3 )
    e_face2 = (2 + s * (s + 1) / 2.0 - 3) / s
    # faces 3..s contribute themselves
    total = e_face1 + e_face2 + sum(range(3, s + 1))
    return total / s


def upgrade_reroll_low2(dice_expr) -> float:
    """Additional EV from rerolling 1s and 2s once keep higher (Hat of the Sharp Caster,
    spell-attack damage dice). Returns the ADDITIONAL EV over the normal EV."""
    p = parse(dice_expr)
    extra = 0.0
    for d in p.dice:
        normal = d.ev
        reroll = d.count * die_reroll_low2_ev(d.sides)
        extra += (reroll - normal)
    return extra
