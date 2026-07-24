"""Parse raw_mechanics/Feats.html -> data/feats.json (name + description).
Also parse Conditions.html -> data/conditions.json (name + summary) for
damage-relevant status effects.
"""
import re, html, json, sys, os
sys.stdout.reconfigure(encoding='utf-8')


def clean(s):
    s = re.sub(r'<picture>.*?</picture>', '', s, flags=re.S)
    s = re.sub(r'<a [^>]*href="(/wiki/[^"]+)"[^>]*>(.*?)</a>',
               lambda m: re.sub(r'<[^>]+>', '', m.group(2)), s, flags=re.S)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html.unescape(s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def parse_feats():
    data = open('raw_mechanics/Feats.html', encoding='utf-8').read()
    tables = re.findall(r'<table[^>]*>(.*?)</table>', data, re.S)
    feats = []
    for t in tables:
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S)
        if not rows:
            continue
        hdr = [clean(c) for c in re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', rows[0], re.S)]
        if hdr[:2] != ['Name', 'Description']:
            continue
        for r in rows[1:]:
            cells = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', r, re.S)
            if len(cells) < 2:
                continue
            name = clean(cells[0])
            desc = clean(cells[1])
            if not name:
                continue
            # extract link
            lm = re.search(r'href="(/wiki/[^"]+)"', cells[0])
            feats.append({
                'name': name,
                'source': 'https://bg3.wiki' + lm.group(1) if lm else 'https://bg3.wiki/wiki/Feats',
                'description': desc,
            })
    return feats


def parse_conditions():
    data = open('raw_mechanics/Conditions.html', encoding='utf-8').read()
    tables = re.findall(r'<table[^>]*>(.*?)</table>', data, re.S)
    conds = {}
    for t in tables:
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S)
        if not rows:
            continue
        hdr = [clean(c) for c in re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', rows[0], re.S)]
        # Conditions table has Name + Effect/Description columns
        if 'Name' not in hdr:
            continue
        name_idx = hdr.index('Name')
        desc_idx = hdr.index('Description') if 'Description' in hdr else (hdr.index('Effect') if 'Effect' in hdr else 1)
        for r in rows[1:]:
            cells = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', r, re.S)
            if len(cells) <= max(name_idx, desc_idx):
                continue
            name = clean(cells[name_idx])
            desc = clean(cells[desc_idx])
            if not name:
                continue
            conds[name] = {'description': desc, 'source': 'https://bg3.wiki/wiki/Conditions'}
    return conds


def main():
    feats = parse_feats()
    json.dump(feats, open('data/feats.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'Parsed {len(feats)} feats -> data/feats.json')
    for f in feats[:5]:
        print(f"  {f['name']}: {f['description'][:60]}")

    conds = parse_conditions()
    json.dump(conds, open('data/conditions.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'Parsed {len(conds)} conditions -> data/conditions.json')
    for n in list(conds)[:8]:
        print(f"  {n}: {conds[n]['description'][:50]}")


if __name__ == '__main__':
    main()
