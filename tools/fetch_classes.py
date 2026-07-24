"""Fetch bg3.wiki class pages (12 base classes) so class progression (Features by
level) is traceable to local source — same pattern as fetch_races.py.
Pages go to raw_classes/. Idempotent: skips files >2KB.
"""
import urllib.request, ssl, os, re, time

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
BASE = 'https://bg3.wiki/wiki/'

PAGES = [
    'Barbarian', 'Bard', 'Cleric', 'Druid', 'Fighter', 'Monk',
    'Paladin', 'Ranger', 'Rogue', 'Sorcerer', 'Warlock', 'Wizard',
    # subclass pages with damage-relevant progression (some already in raw_mechanics)
    'Hunter', 'Champion', 'Battle_Master', 'Eldritch_Knight',
    'Oath_of_Devotion', 'Oath_of_the_Ancients', 'Oath_of_Vengeance',
    'Way_of_the_Open_Hand', 'Way_of_Shadow', 'Way_of_the_Four_Elements',
    'Circle_of_the_Land', 'Circle_of_Spores', 'Circle_of_the_Moon',
    'Draconic_Bloodline', 'Wild_Magic_(Sorcerer)', 'Storm_Sorcery',
    'The_Great_Old_Patron', 'The_Fiend_Patron', 'Archfey_Patron',
    'School_of_Evocation', 'College_of_Lore', 'College_of_Valour',
    'Path_of_the_Berserker', 'Path_of_the_Wild_Magic', 'Path_of_Storm_Heart',
]

ok = fail = skip = 0
os.makedirs('raw_classes', exist_ok=True)
for slug in PAGES:
    fn = os.path.join('raw_classes', re.sub(r'[^\w]', '_', slug) + '.html')
    if os.path.exists(fn) and os.path.getsize(fn) > 2000:
        skip += 1
        continue
    try:
        req = urllib.request.Request(BASE + slug, headers={'User-Agent': 'Mozilla/5.0'})
        data = urllib.request.urlopen(req, timeout=25, context=ctx).read()
        if len(data) < 500:
            fail += 1
            print(f'EMPTY {slug} ({len(data)}b)')
            continue
        open(fn, 'wb').write(data)
        ok += 1
        print(f'OK   {slug} ({len(data)}b)')
    except Exception as e:
        fail += 1
        print(f'FAIL {slug}: {e}')
    time.sleep(0.25)
print(f'\nDONE ok={ok} skip={skip} fail={fail} total={len(PAGES)}')
