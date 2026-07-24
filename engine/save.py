"""Save-spell expected damage.

BG3 rules (verified vs bg3.wiki Saving_throw):
- spell save DC = 8 + proficiency_bonus + spellcasting_modifier (+ item bonuses)
- target rolls d20 + save_bonus vs DC
- nat 1 always fails (full effect), nat 20 always saves
- save_effect: "half" (half dmg on save), "none"/"no_damage_on_save" (0 on save)
- spells don't crit
"""
from .ev import clamp
from . import dice as dice_mod


def save_dc(proficiency_bonus: int, spellcasting_mod: int, item_bonus: int = 0) -> int:
    """Spell save DC = 8 + proficiency + spellcasting modifier (+ item bonus).

    INTENTIONALLY NOT MODELLED (bg3.wiki Saving_throw): weapon-action DC
    (8 + prof + max(STR,DEX) + inherent +2), hybrid DC (max(spell, weapon+2)), and
    fixed DCs (traps/consumables). Only spell save DC is supported.
    """
    return 8 + proficiency_bonus + spellcasting_mod + item_bonus


def p_fail(dc: int, save_bonus: int, advantage: bool = False, disadvantage: bool = False) -> float:
    """Probability the target FAILS the save (takes full effect).

    Need d20 + save_bonus >= DC to save => need roll >= (DC - save_bonus).
    Fail = roll < that. nat 1 always fails, nat 20 always saves.
    """
    need = dc - save_bonus
    need = max(2, min(20, need))  # nat1 fails, nat20 saves
    p_fail_single = clamp((need - 1) / 20.0, 0.05, 0.95)  # at least nat1(1/20) fails, at most nat20 saves

    if advantage and disadvantage:
        advantage = disadvantage = False
    if advantage:
        # target rolls twice, keep better (save) -> fail less
        return clamp(p_fail_single ** 2, 0.0, 1.0)
    if disadvantage:
        return clamp(1 - (1 - p_fail_single) ** 2, 0.0, 1.0)
    return p_fail_single


def save_spell_ev(dice_expr, dc: int, save_bonus: int, save_effect: str = "half",
                  advantage: bool = False, disadvantage: bool = False,
                  resistances=None) -> float:
    """EV of a save spell's damage (single target, pre-resistance unless given).

    dice_expr: die expression string for full damage.
    save_effect: "half" | "none" | "no_damage_on_save" (last two = 0 on save).
    """
    pf = p_fail(dc, save_bonus, advantage, disadvantage)
    ps = 1 - pf
    full = dice_mod.ev(dice_expr)  # spells don't crit
    if save_effect in ("none", "no_damage_on_save"):
        return pf * full
    elif save_effect == "half":
        return pf * full + ps * full / 2.0
    elif save_effect == "full":  # no save benefit
        return full
    return pf * full + ps * full / 2.0  # default half
