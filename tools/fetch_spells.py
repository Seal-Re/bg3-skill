import json, urllib.request, ssl, time, os, sys, re
sys.stdout.reconfigure(encoding='utf-8')

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

spells = json.load(open('data/spell_urls.json', encoding='utf-8'))
os.makedirs('raw_spells', exist_ok=True)

ok = fail = skip = 0
for i, s in enumerate(spells):
    fn = 'raw_spells/' + re.sub(r'[^\w]', '_', s['page']) + '.html'
    if os.path.exists(fn) and os.path.getsize(fn) > 2000:
        skip += 1
        continue
    try:
        req = urllib.request.Request(s['url'], headers={'User-Agent': 'Mozilla/5.0'})
        d = urllib.request.urlopen(req, timeout=25, context=ctx).read()
        open(fn, 'wb').write(d)
        ok += 1
    except Exception as e:
        fail += 1
        print('FAIL', s['name'], e)
    if i % 30 == 0:
        print(f'progress {i+1}/{len(spells)} ok={ok} skip={skip} fail={fail}')
    time.sleep(0.2)

print(f'DONE ok={ok} skip={skip} fail={fail} total={len(spells)}')
