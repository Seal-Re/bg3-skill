"""DamageComponent and DamagePool: typed damage, crit-aware EV, resistance application.

A DamageComponent is one chunk of damage: a die expression + a damage type, OR a
flat value + type. Crit handling lives at the component level (dice double, flat
doesn't) via with_doubled_dice().

A DamagePool is a collection of components. EV sums components; resistance is
applied per-type at the end.
"""
from dataclasses import dataclass, field
from typing import List, Optional
from . import dice as dice_mod

DAMAGE_TYPES = {
    'Slashing', 'Piercing', 'Bludgeoning',
    'Fire', 'Cold', 'Lightning', 'Thunder', 'Poison', 'Acid',
    'Necrotic', 'Radiant', 'Psychic', 'Force',
    'Healing',  # healing skips resistance
}


@dataclass
class DamageComponent:
    type: str
    dice: Optional[str] = None   # e.g. "1d8", "2d6"
    flat: int = 0                # e.g. +1 enchantment, +5 ability mod
    # flat may be a symbolic string resolved at eval time: "str_mod","dex_mod","prof","ability_mod"
    flat_sym: Optional[str] = None
    # bypass_resistance: this component ignores the target's resistance AND immunity
    # to its damage type (bg3.wiki: Hellfire Greataxe ignores Fire resistance/immunity).
    # Vulnerability still applies. If ANY component of a type is bypass, the whole
    # type is treated as bypass at resistance-application time.
    bypass_resistance: bool = False
    # savage_attacks: Half-Orc racial — on a crit this weapon-die component gains
    # ONE extra die (count*2 + 1) instead of just count*2. bg3.wiki Savage_Attacks:
    # greatsword crit 4d6 -> 5d6, greataxe crit 2d12 -> 3d12. Only the base weapon die.
    savage_attacks: bool = False

    def resolved_flat(self, resolver) -> float:
        """resolver: callable(str)->number that maps symbolic flats to numbers.
        Returns float to support fractional bonuses (e.g. Savage Attacker EV)."""
        if self.flat_sym:
            return float(resolver(self.flat_sym))
        return float(self.flat)

    def ev(self, crit: bool, resolver) -> float:
        d = dice_mod.parse(self.dice).ev(crit=crit) if self.dice else 0.0
        return d + self.resolved_flat(resolver)

    def doubled_dice(self) -> "DamageComponent":
        """Return a copy with dice doubled (for crit). Flat unchanged.

        If savage_attacks is set, each die term gains ONE extra die on top of the
        doubling (Half-Orc Savage Attacks: count*2 + 1)."""
        if not self.dice:
            return DamageComponent(type=self.type, dice=None, flat=self.flat,
                                   flat_sym=self.flat_sym,
                                   bypass_resistance=self.bypass_resistance,
                                   savage_attacks=self.savage_attacks)
        p = dice_mod.parse(self.dice)
        if self.savage_attacks:
            new_dice = '+'.join(f'{d.count*2 + 1}d{d.sides}' for d in p.dice)
        else:
            new_dice = '+'.join(f'{d.count*2}d{d.sides}' for d in p.dice)
        flat = p.flat + self.flat
        if flat:
            new_dice += f'{flat:+d}'.replace(' ', '')
        return DamageComponent(type=self.type, dice=new_dice if new_dice else None,
                                flat=0, flat_sym=self.flat_sym,
                                bypass_resistance=self.bypass_resistance,
                                savage_attacks=self.savage_attacks)


@dataclass
class DamagePool:
    components: List[DamageComponent] = field(default_factory=list)

    def add(self, comp: DamageComponent) -> None:
        self.components.append(comp)

    def __iadd__(self, other: "DamagePool") -> "DamagePool":
        self.components.extend(other.components)
        return self

    def __add__(self, other: "DamagePool") -> "DamagePool":
        return DamagePool(self.components + other.components)

    def ev_by_type(self, crit: bool, resolver) -> dict:
        """Return {damage_type: ev}."""
        out = {}
        for c in self.components:
            out[c.type] = out.get(c.type, 0.0) + c.ev(crit, resolver)
        return out

    def ev(self, crit: bool, resolver) -> float:
        return sum(self.ev_by_type(crit, resolver).values())

    def with_doubled_dice(self) -> "DamagePool":
        return DamagePool([c.doubled_dice() for c in self.components])

    def bypass_types(self) -> set:
        """Damage types for which at least one component bypasses resistance/immunity."""
        return {c.type for c in self.components if c.bypass_resistance}

    def apply_resistances(self, per_type_ev: dict, target, bypass_types=None) -> dict:
        """Apply target resistance/immunity/vulnerability per type, then flat reduction.

        Types flagged as bypass (via self.bypass_types() or the bypass_types arg)
        skip resistance AND immunity but still take vulnerability (bg3.wiki: Hellfire
        ignores Fire resistance/immunity; Elemental Adept ignores chosen type's res).
        target.flat_reduction (dict {type: flat} or {'all': flat}) subtracts a flat
        amount per type (min 0), applied AFTER res/imm/vuln (bg3.wiki Heavy Armour
        Master / Magical Plate / Superior Padding).
        """
        out = {}
        res = set(getattr(target, 'resistances', []) or [])
        imm = set(getattr(target, 'immunities', []) or [])
        vuln = set(getattr(target, 'vulnerabilities', []) or [])
        flat_red = getattr(target, 'flat_reduction', {}) or {}
        all_red = flat_red.get('all', 0)
        bypass = self.bypass_types() | set(bypass_types or [])
        for dtype, val in per_type_ev.items():
            if dtype == 'Healing':
                out[dtype] = val
            elif dtype in vuln:
                out[dtype] = val * 2
            elif dtype in bypass:
                out[dtype] = val          # ignores resistance AND immunity
            elif dtype in imm:
                out[dtype] = 0.0
            elif dtype in res:
                out[dtype] = val * 0.5
            else:
                out[dtype] = val
            # flat reduction (min 0): per-type + 'all' (Magical Plate reduces everything)
            red = flat_red.get(dtype, 0) + all_red
            if red and out[dtype] > 0:
                out[dtype] = max(0.0, out[dtype] - red)
        return out
