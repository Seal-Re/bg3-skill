"""Top-level expected-value math, decoupled from BG3 specifics."""


def ev_outcome(outcomes) -> float:
    """outcomes: list of (probability, value) tuples. Returns sum(p * v)."""
    return sum(p * v for p, v in outcomes)


def clamp(x, lo, hi):
    return max(lo, min(hi, x))
