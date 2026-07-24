"""Fetch bg3.wiki race + remaining elemental-reaction pages so the local knowledge
base has authoritative source text for every mechanism the engine models.

Rationale: a content-level grep (NOT filename grep) showed the local raw_mechanics/
has NO standalone race pages — race traits (Hellish Resistance, Breath Weapon,
Dwarven Resilience, Gnome Cunning, Sunlight Sensitivity, ...) only appear as
scattered footnotes/examples or are entirely absent. This script fetches the
canonical bg3.wiki pages so race mechanics are traceable to local source files,
matching the workspace's "bg3.wiki original text is the source of truth" rule.

Pages go to raw_races/ (race pages) and raw_conditions/ (missing condition pages).
Idempotent: skips files already >2KB.
"""
import urllib.request, ssl, os, re, time

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

BASE = 'https://bg3.wiki/wiki/'

# (page_slug, output_dir)
PAGES = [
    # Race overview + each race (canonical pages)
    ('Races', 'raw_races'),
    ('Tiefling', 'raw_races'),
    ('Dragonborn', 'raw_races'),
    ('Dwarf', 'raw_races'),
    ('Duergar', 'raw_races'),
    ('Halfling', 'raw_races'),
    ('Gnome', 'raw_races'),
    ('Githyanki', 'raw_races'),
    ('Half-Orc', 'raw_races'),
    ('Elf', 'raw_races'),
    ('Half-Elf', 'raw_races'),
    ('Human', 'raw_races'),
    ('Drow', 'raw_races'),
    # Race-granted spells / features that need their own page
    ('Enlarge', 'raw_races'),
    ('Halfling_Luck', 'raw_races'),
    ('Savage_Attacks', 'raw_races'),
    # Dragonborn breath weapons (each is its own page)
    ('Acid_Breath', 'raw_races'),
    ('Fire_Breath_(Line)', 'raw_races'),
    ('Fire_Breath_(Cone)', 'raw_races'),
    ('Lightning_Breath', 'raw_races'),
    ('Frost_Breath', 'raw_races'),
    ('Poison_Breath', 'raw_races'),
    # Missing elemental-reaction condition pages
    ('Drenched_(Condition)', 'raw_conditions'),
    ('Electrocuted_(Condition)', 'raw_conditions'),
    ('Brittle_(Condition)', 'raw_conditions'),
    ('Wet_(Condition)', 'raw_conditions'),
    ('Chilled_(Condition)', 'raw_conditions'),
    ('Frozen_(Condition)', 'raw_conditions'),
    ('Encrusted_with_Frost_(Condition)', 'raw_conditions'),
    ('Burning_(Condition)', 'raw_conditions'),
    ('Reverberation_(Condition)', 'raw_conditions'),
]

ok = fail = skip = 0
for slug, d in PAGES:
    os.makedirs(d, exist_ok=True)
    fn = os.path.join(d, re.sub(r'[^\w]', '_', slug) + '.html')
    if os.path.exists(fn) and os.path.getsize(fn) > 2000:
        skip += 1
        continue
    url = BASE + slug
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = urllib.request.urlopen(req, timeout=25, context=ctx).read()
        if len(data) < 500:
            fail += 1
            print(f'EMPTY {slug} ({len(data)} bytes)')
            continue
        open(fn, 'wb').write(data)
        ok += 1
        print(f'OK   {slug} -> {fn} ({len(data)} bytes)')
    except Exception as e:
        fail += 1
        print(f'FAIL {slug}: {e}')
    time.sleep(0.25)

print(f'\nDONE ok={ok} skip={skip} fail={fail} total={len(PAGES)}')
