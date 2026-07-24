import re, html, sys, json, os
sys.stdout.reconfigure(encoding='utf-8')

PAGES = {
    'Weapon': 'Weapons', 'Armour': 'Armour', 'Shields': 'Shields',
    'Amulets': 'Amulets', 'Rings': 'Rings', 'Cloaks': 'Cloaks',
    'Headwear': 'Headwear', 'Handwear': 'Handwear', 'Footwear': 'Footwear',
}

def clean(s):
    s = re.sub(r'<br\s*/?>', ' / ', s, flags=re.I)
    s = re.sub(r'</?(?:sup|sub|small|span|div|p)[^>]*>', '', s)
    s = re.sub(r'<a [^>]*href="(/wiki/[^"]+)"[^>]*>(.*?)</a>', r'\2[\1]', s, flags=re.S)
    s = re.sub(r'<[^>]+>', '', s)
    s = html.unescape(s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def first_link(cell):
    m = re.search(r'<a [^>]*href="(/wiki/[^"]+)"[^>]*title="([^"]*)"', cell)
    if m:
        return m.group(2), m.group(1)
    m = re.search(r'<a [^>]*href="(/wiki/[^"]+)"[^>]*>(.*?)</a>', cell, re.S)
    if m:
        return clean(m.group(2)), m.group(1)
    return None, None

all_items = []
for fname, cat_label in PAGES.items():
    path = '../raw/mechanics/' + fname + '.html'
    if not os.path.exists(path):
        continue
    data = open(path, encoding='utf-8').read()
    tables = re.findall(r'<table[^>]*>(.*?)</table>', data, re.S)
    for t in tables:
        # skip navbox/infobox
        if 'navbox' in t[:300].lower() or 'infobox' in t[:300].lower():
            continue
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S)
        if not rows:
            continue
        header = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', rows[0], re.S)
        header_clean = [clean(h).lower() for h in header]
        if not any('item' in h or 'name' in h for h in header_clean):
            continue
        # find column indices
        col_map = {}
        for i, h in enumerate(header_clean):
            if 'item' in h or 'name' in h: col_map['item'] = i
            elif 'special' in h or 'effect' in h or 'enchant' in h or 'propert' in h: col_map['special'] = i
            elif 'weight' in h: col_map['weight'] = i
            elif 'price' in h or 'value' in h: col_map['price'] = i
            elif 'rarity' in h: col_map['rarity'] = i
            elif 'type' in h or 'subclass' in h: col_map['type'] = i
        for r in rows[1:]:
            cells = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', r, re.S)
            if len(cells) < 2:
                continue
            ic = col_map.get('item', 0)
            if ic >= len(cells):
                continue
            name, link = first_link(cells[ic])
            if not name:
                name = clean(cells[ic])
            if not name:
                continue
            rec = {
                'category': cat_label,
                'name': name,
                'link': 'https://bg3.wiki' + link if link else '',
                'weight': clean(cells[col_map['weight']]) if 'weight' in col_map and col_map['weight'] < len(cells) else '',
                'price': clean(cells[col_map['price']]) if 'price' in col_map and col_map['price'] < len(cells) else '',
                'special': clean(cells[col_map['special']]) if 'special' in col_map and col_map['special'] < len(cells) else '',
                'type': clean(cells[col_map['type']]) if 'type' in col_map and col_map['type'] < len(cells) else '',
            }
            all_items.append(rec)

# dedupe by (category, name, special) keeping first
seen = set()
deduped = []
for it in all_items:
    key = (it['category'], it['name'], it['special'])
    if key in seen:
        continue
    seen.add(key)
    deduped.append(it)

print('TOTAL RAW:', len(all_items), 'DEDUPED:', len(deduped))
by_cat = {}
for it in deduped:
    by_cat.setdefault(it['category'], 0)
    by_cat[it['category']] += 1
for c, n in by_cat.items():
    print(f'  {c}: {n}')

json.dump(deduped, open('../data/equipment.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('Saved ../data/equipment.json')
