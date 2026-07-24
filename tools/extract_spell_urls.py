import re, html, json, sys
sys.stdout.reconfigure(encoding='utf-8')

data = open('raw_mechanics/list_spells.html', encoding='utf-8').read()

LEVEL_SECTIONS = ['Cantrips', 'Level_1_spells', 'Level_2_spells', 'Level_3_spells',
                  'Level_4_spells', 'Level_5_spells', 'Level_6_spells', 'Level_9_spells']
LEVEL_MAP = {'Cantrips': 0, 'Level_1_spells': 1, 'Level_2_spells': 2, 'Level_3_spells': 3,
             'Level_4_spells': 4, 'Level_5_spells': 5, 'Level_6_spells': 6, 'Level_9_spells': 9}
# Section ids that act as terminators (stop capturing a level chunk here)
TERMINATORS = ['Cantrips', 'Level_1_spells', 'Level_2_spells', 'Level_3_spells',
               'Level_4_spells', 'Level_5_spells', 'Level_6_spells', 'Level_9_spells',
               'Special_NPC_Spells', 'Special_Item_Spells', 'See_also']

# Find positions of each terminator section id in the body
positions = {}
for sec in TERMINATORS:
    m = re.search(r'id="' + sec + r'"', data)
    positions[sec] = m.start() if m else None

EXCLUDE_PREFIX = ('File:', 'Special:', 'Category:', 'Help:', 'bg3wiki:', 'List_of', 'Template:',
                  'Edit_section', 'VisualEditor')
seen = {}
for i, sec in enumerate(LEVEL_SECTIONS):
    start = positions[sec]
    if start is None:
        continue
    # end = next TERMINATOR section start, else end of file
    later = [positions[s] for s in TERMINATORS[i+1:] if positions.get(s) is not None and positions[s] > start]
    end = min(later) if later else len(data)
    chunk = data[start:end]
    lvl = LEVEL_MAP[sec]
    for href, pagename, title in re.findall(
            r'<a [^>]*href="(/wiki/([^"#]+))"[^>]*title="([^"]+)"[^>]*>', chunk):
        if any(pagename.startswith(p) for p in EXCLUDE_PREFIX):
            continue
        if ':' in pagename:
            continue
        name = html.unescape(title).strip()
        if not name or name in ('Spells', 'Cantrip', 'Spell', 'Upcast', 'Upcasting',
                                'Concentration', 'Range', 'School', 'Level'):
            continue
        if pagename not in seen:
            seen[pagename] = {'name': name, 'url': 'https://bg3.wiki' + href,
                              'page': pagename, 'level': lvl}

spells = sorted(seen.values(), key=lambda s: (s['level'], s['name'].lower()))
json.dump(spells, open('data/spell_urls.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f'Total spells: {len(spells)}')
from collections import Counter
c = Counter(s['level'] for s in spells)
for lvl in sorted(c):
    print(f'  Level {lvl}: {c[lvl]}')
print('Cantrips sample:', [s['name'] for s in spells if s['level'] == 0][:12])
print('L3 sample:', [s['name'] for s in spells if s['level'] == 3][:8])
