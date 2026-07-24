"""Parse raw_spells/*.html into data/spells.json (structured).

Extracts per spell: name, source, level, school, casting_time, concentration,
range_m, aoe_m, aoe_shape, action_cost, upcast_per_level, damage (dice+type list),
save (ability + save_effect), attack_type, tags.

Pure stdlib re/html, matches the project's parse_equipment.py style.
"""
import re, html, json, os, glob, sys
sys.stdout.reconfigure(encoding='utf-8')

RAW_DIR = 'raw_spells'
OUT = 'data/spells.json'

DAMAGE_TYPES = ['Slashing', 'Piercing', 'Bludgeoning', 'Fire', 'Cold', 'Lightning',
                'Thunder', 'Poison', 'Acid', 'Necrotic', 'Radiant', 'Psychic', 'Force', 'Healing']


def clean(s):
    s = re.sub(r'<picture>.*?</picture>', '', s, flags=re.S)
    s = re.sub(r'<img[^>]*>', '', s)
    s = re.sub(r'<a [^>]*href="(/wiki/[^"]+)"[^>]*>(.*?)</a>',
               lambda m: re.sub(r'<[^>]+>', '', m.group(2)), s, flags=re.S)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html.unescape(s)
    # strip word-joiner / zero-width chars that break regex matching
    s = s.replace('⁠', ' ').replace('​', '').replace('﻿', '')
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def full_text(data):
    s = re.sub(r'<script.*?</script>', '', data, flags=re.S)
    s = re.sub(r'<style.*?</style>', '', s, flags=re.S)
    s = re.sub(r'<picture>.*?</picture>', '', s, flags=re.S)
    s = re.sub(r'<a [^>]*>(.*?)</a>', lambda m: re.sub(r'<[^>]+>', '', m.group(1)), s, flags=re.S)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html.unescape(s)
    s = s.replace('⁠', ' ').replace('​', '').replace('﻿', '')
    s = re.sub(r'\s+', ' ', s)
    return s


def parse_spell(filepath):
    data = open(filepath, encoding='utf-8').read()
    t = full_text(data)
    name_match = re.search(r'From bg3\.wiki\s+(.+?)(?:is a|Jump to)', t)
    name = os.path.basename(filepath).replace('.html', '').replace('_', ' ')
    # try to get the real title
    mt = re.search(r'<title>([^<]+) - bg3', data)
    if mt:
        name = html.unescape(mt.group(1)).strip()

    rec = {
        'name': name,
        'source': 'https://bg3.wiki/wiki/' + name.replace(' ', '_'),
        'level': None, 'school': None, 'casting_time': None,
        'concentration': False, 'range_m': None, 'aoe_m': None, 'aoe_shape': None,
        'action_cost': None, 'upcast_per_level': 0,
        'damage': [], 'save': None, 'attack_type': None, 'tags': [], 'raw_damage_text': ''
    }

    # Level: "Level X Spell Slot" (Properties block) or "level X ... spell" (desc) or Cantrip
    if re.search(r'\bcantrip\b', t[:2000], re.I):
        rec['level'] = 0
        rec['action_cost'] = 'cantrip'
    else:
        m = re.search(r'Level (\d+) Spell Slot', t[:3000]) or re.search(r'level (\d+) [a-z]+ spell', t[:1500])
        if m:
            rec['level'] = int(m.group(1))
            rec['action_cost'] = f'spell_slot_{m.group(1)}'

    # School (from "level X <school> spell" or Properties)
    m = re.search(r'level \d+ ([a-z]+) spell', t[:1500]) or \
        re.search(r'(Abjuration|Conjuration|Divination|Enchantment|Evocation|Illusion|Necromancy|Transmutation)', t[:3000])
    if m:
        rec['school'] = m.group(1).capitalize()

    # Concentration
    rec['concentration'] = 'Concentration' in t[:3000]

    # Casting time: Action / Bonus action / Reaction
    if 'Bonus action' in t[:3000]:
        rec['casting_time'] = 'bonus_action'
    elif 'Reaction' in t[:3000]:
        rec['casting_time'] = 'reaction'
    else:
        rec['casting_time'] = 'action'

    # Damage: find pattern like "8d6 Fire" or "1d10 Force" near "Damage"
    dmg_pieces = []
    # Match "NdM [type]" or "NdM + N [type]" with a damage type
    dmg_re = re.compile(r'(\d+d\d+(?:\s*\+\s*\d+)?|\d+d\d+)\s+(' + '|'.join(DAMAGE_TYPES) + r')')
    for m in dmg_re.finditer(t[:4000]):
        dice = m.group(1).replace(' ', '')
        dtype = m.group(2)
        dmg_pieces.append({'dice': dice, 'type': dtype, 'modifier': 0})
        if len(dmg_pieces) >= 6:
            break
    # Dedupe: keep only the FIRST damage entry per type (base die; drop higher-level scaling)
    seen_types = set()
    uniq = []
    for d in dmg_pieces:
        if d['type'] not in seen_types:
            seen_types.add(d['type'])
            uniq.append(d)
    rec['damage'] = uniq
    rec['raw_damage_text'] = ' '.join(f"{d['dice']} {d['type']}" for d in uniq)

    # Buff/rider spells (Hex, Hunter's Mark, etc.) deal damage "per attack" — not a
    # direct-damage spell. Flag so attack_type detection skips them.
    rec['is_buff'] = bool(re.search(r'[Pp]er (weapon )?attack', t[:5000])) and len(uniq) <= 1

    # Save: look for "<ABILITY> Save" specifically in the Properties/Details block,
    # not in descriptive prose. The infobox phrase is like "Details DEX Save" or
    # "Spell save DC" / "(On Save: ...)".
    save_m = re.search(r'(?:Details|Save|Saving throw)\s*[: ]\s*(STR|DEX|CON|INT|WIS|CHA)\s+Save', t[:5000])
    if not save_m:
        save_m = re.search(r'\b(STR|DEX|CON|INT|WIS|CHA)\s+Save\s*\(', t[:5000])  # "DEX Save (On Save: ...)"
    if not save_m:
        # Fallback: "Saving Throw: DEX"
        save_m = re.search(r'Saving Throw[s]?\s*:?\s*(STR|DEX|CON|INT|WIS|CHA)', t[:5000])
    if save_m:
        ability = save_m.group(1)
        low = t[:5000].lower()
        if 'on save: damage is halved' in low or 'half damage' in low or 'targets still take half' in low:
            effect = 'half'
        elif 'on save: no damage' in low or 'no damage on save' in low or 'damage is negated' in low or 'negates' in low:
            effect = 'no_damage_on_save'
        else:
            effect = 'half'  # default for save spells
        rec['save'] = {'ability': ability, 'save_effect': effect}
        rec['tags'].append('save')

    # Attack-roll spell: has "Attack Roll" as a property (e.g. "Details Attack Roll") and no save.
    if not rec['save'] and uniq and re.search(r'Attack Roll', t[:5000]) and not rec.get('is_buff'):
        rec['attack_type'] = 'spell_attack'
        rec['tags'].append('attack')
    elif not rec['save'] and uniq and ('Magic Missile' in name):
        rec['attack_type'] = 'auto'
        rec['tags'].append('auto')

    # AoE
    aoe_m = re.search(r'(\d+)\s*m\s*\(\d+\s*ft\)\s*(Radius|Cone|Line|Cylinder)', t[:4000])
    if aoe_m:
        rec['aoe_m'] = int(aoe_m.group(1))
        rec['aoe_shape'] = aoe_m.group(2).lower()
        rec['tags'].append('aoe')

    # Range
    rng_m = re.search(r'Range:\s*(\d+)\s*m', t[:4000])
    if rng_m:
        rec['range_m'] = int(rng_m.group(1))

    return rec


def main():
    files = sorted(glob.glob(os.path.join(RAW_DIR, '*.html')))
    out = []
    for f in files:
        try:
            rec = parse_spell(f)
            out.append(rec)
        except Exception as e:
            print('ERR', f, e)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'Parsed {len(out)} spells -> {OUT}')
    dmg = [s for s in out if s['damage']]
    save = [s for s in out if s['save']]
    atk = [s for s in out if s['attack_type']]
    print(f'  with damage: {len(dmg)}, save-spells: {len(save)}, attack-spells: {len(atk)}')
    # sample
    for s in out[:3]:
        print(f"  {s['name']}: lvl={s['level']} dmg={s['raw_damage_text']} save={s['save']} atk={s['attack_type']}")


if __name__ == '__main__':
    main()
