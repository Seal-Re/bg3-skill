"""Tier-1/2 auto rider classifier.

Scans equipment.json + legendary_effects.json 'special' text and classifies
damage riders:
  Tier 1 (high precision): literal tag 'Damage rider as source damage' or
        'DRS' + 'Damage_rider_as_source' -> kind DRS. 'Damage rider' (no 'as source') -> DR.
  Tier 2 (rule-based): regex for '(NdM|N) <DamageType>' near trigger keywords ->
        kind DR by default.

Output: data/riders.auto.json — keyed by item name, list of rider dicts.
Items already in the curated data/riders.json (Tier 3) are SKIPPED here (Tier 3 wins).
"""
import re, html, json, os, sys
sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAMAGE_TYPES = ['Slashing', 'Piercing', 'Bludgeoning', 'Fire', 'Cold', 'Lightning',
                'Thunder', 'Poison', 'Acid', 'Necrotic', 'Radiant', 'Psychic', 'Force']

# Strip wiki-link noise: "2[/wiki/Acid] Acid[/wiki/Acid]" -> "2 Acid"
def denoise(s):
    s = re.sub(r'\[/wiki/[^\]]+\]', '', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = html.unescape(s)
    # strip word-joiner / zero-width chars (bg3.wiki uses U+2060 between dice and damage type)
    s = s.replace('⁠', ' ').replace('​', '').replace('﻿', '')
    s = re.sub(r'\s+', ' ', s).strip()
    return s

DAMAGE_RE = re.compile(r'(\d+d\d+|\d+)\s*(' + '|'.join(DAMAGE_TYPES) + r')')
DRS_TAG_RE = re.compile(r'damage rider as source|DRS\s*\[/wiki/Damage_rider_as_source\]', re.I)
DR_TAG_RE = re.compile(r'damage rider(?! as source)', re.I)

TRIGGER_KW = [
    (r'unarmed (attack|strike)', 'unarmed_attack_hit'),
    (r'thrown', 'thrown_attack_hit'),
    (r'ranged weapon attack', 'ranged_weapon_attack_hit'),
    (r'melee weapon attack', 'melee_weapon_attack_hit'),
    (r'spell damage', 'spell_damage_dealt'),
    (r'weapon attack', 'weapon_attack_hit'),
    (r'weapon attacks also deal', 'weapon_attack_hit'),
    (r'attacks also deal', 'weapon_attack_hit'),
]


def classify(text):
    """Return list of rider dicts parsed from text, or []."""
    text = denoise(text)
    if not text:
        return []
    riders = []
    # Tier 1: explicit DRS / DR tags
    is_drs = bool(DRS_TAG_RE.search(text))
    # Find damage+type runs
    matches = DAMAGE_RE.findall(text)
    if not matches:
        return []
    # Determine trigger
    trigger = 'weapon_attack_hit'  # default
    for pat, trig in TRIGGER_KW:
        if re.search(pat, text, re.I):
            trigger = trig
            break
    kind = 'DRS' if is_drs else 'DR'
    for amount, dtype in matches:
        # parse amount: "1d6" -> dice; "2" -> flat
        if 'd' in amount.lower():
            riders.append({
                'trigger': trigger, 'kind': kind,
                'damage': {'dice': amount, 'flat': 0, 'type': dtype},
                'confidence': 'high' if is_drs else 'medium',
            })
        else:
            riders.append({
                'trigger': trigger, 'kind': kind,
                'damage': {'dice': None, 'flat': int(amount), 'type': dtype},
                'confidence': 'high' if is_drs else 'medium',
            })
    return riders


def main():
    # Load curated Tier 3 names to skip
    t3 = json.load(open(os.path.join(ROOT, 'data', 'riders.json'), encoding='utf-8'))
    t3_names = {k for k in t3 if k != '_meta'}

    auto = {}
    # equipment.json
    eq = json.load(open(os.path.join(ROOT, 'equipment.json'), encoding='utf-8'))
    for e in eq:
        name = e['name']
        if name in t3_names:
            continue
        riders = classify(e.get('special', ''))
        if riders:
            auto[name] = riders
    # legendary_effects.json
    leg = json.load(open(os.path.join(ROOT, 'legendary_effects.json'), encoding='utf-8'))
    for l in leg:
        name = l['name']
        if name in t3_names:
            continue
        text = (l.get('special', '') or '') + ' ' + (l.get('special_weapon_actions', '') or '')
        riders = classify(text)
        if riders:
            auto[name] = riders

    json.dump(auto, open(os.path.join(ROOT, 'data', 'riders.auto.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f'Auto-classified {len(auto)} items -> data/riders.auto.json')
    drs = sum(1 for v in auto.values() for r in v if r['kind'] == 'DRS')
    dr = sum(1 for v in auto.values() for r in v if r['kind'] == 'DR')
    print(f'  DRS riders: {drs}, DR riders: {dr}')
    # golden-set check: items that SHOULD be DRS
    for g in ['Balduran\'s Giantslayer', 'Crimson Mischief', 'Nyrulna']:
        if g in auto:
            kinds = [r['kind'] for r in auto[g]]
            print(f'  GOLDEN {g}: {kinds}')


if __name__ == '__main__':
    main()
