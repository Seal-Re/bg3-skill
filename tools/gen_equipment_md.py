import json, sys
sys.stdout.reconfigure(encoding='utf-8')

eq = json.load(open('../data/equipment.json', encoding='utf-8'))
leg = json.load(open('../data/legendary_effects.json', encoding='utf-8'))
wpn = json.load(open('../data/weapons_named.json', encoding='utf-8'))
wbase = json.load(open('../data/weapons_base.json', encoding='utf-8'))

def esc(s):
    return (s or '').replace('|', '/').replace('\n', ' / ').strip()

out = []
out.append('# 博德之门3（Baldur\'s Gate 3）全装备效果大全\n')
out.append('> **数据来源**：bg3.wiki（社区权威 Wiki），按装备类目全量抓取核对。')
out.append('> **统计**：常规装备 541 件（其中 400 件含特殊效果）/ 传奇物品 28 件（全文效果）/ 具名武器 193 件 / 基础武器类型 31 种。\n')
out.append('> 同目录可查结构化数据：`equipment.json`、`legendary_effects.json`、`weapons_named.json`、`weapons_base.json`。\n')

# ---- Legendary ----
out.append('## 一、传奇装备（Legendary，28 件，全文效果）\n')
out.append('| 名称 | 特殊效果 | 特殊武器动作 |')
out.append('|------|----------|--------------|')
for l in leg:
    sp = esc(l.get('special', ''))
    swa = esc(l.get('special_weapon_actions', ''))
    out.append(f"| [{l['name']}]({l['link']}) | {sp[:500]} | {swa[:300]} |")
out.append('')

# ---- Base weapons ----
out.append('## 二、基础武器类型（31 种，伤害与属性）\n')
out.append('| 武器 | 伤害 | 射程 | 属性 |')
out.append('|------|------|------|------|')
for w in wbase:
    out.append(f"| {esc(w['name'])} | {esc(w.get('damage',''))} | {esc(w.get('range',''))} | {esc(w.get('properties',''))} |")
out.append('')

# ---- Named weapons ----
out.append('## 三、具名武器（193 件，含附魔与伤害）\n')
out.append('> 按武器子类型分组。完整特殊效果详见各物品 bg3.wiki 页面链接。\n')
by_sub = {}
for w in wpn:
    by_sub.setdefault(w.get('subtype', ''), []).append(w)
for sub in sorted(by_sub.keys()):
    out.append(f'### {sub}')
    out.append('| 名称 | 附魔 | 伤害 |')
    out.append('|------|------|------|')
    for w in by_sub[sub]:
        out.append(f"| [{esc(w['name'])}]({w.get('link','')}) | {esc(w.get('enchantment',''))} | {esc(w.get('damage',''))} |")
    out.append('')

# ---- Equipment by category ----
out.append('## 四、常规装备（按类目，541 件）\n')
by_cat = {}
for e in eq:
    by_cat.setdefault(e['category'], []).append(e)

CAT_ORDER = ['Weapons', 'Armour', 'Shields', 'Amulets', 'Rings', 'Cloaks', 'Headwear', 'Handwear', 'Footwear']
CAT_CN = {'Weapons':'武器','Armour':'护甲','Shields':'盾牌','Amulets':'项链','Rings':'戒指','Cloaks':'披风','Headwear':'头部','Handwear':'手套','Footwear':' footwear/靴'}
for cat in CAT_ORDER:
    if cat not in by_cat: continue
    items = by_cat[cat]
    out.append(f'### {cat}（{CAT_CN.get(cat,cat)}，{len(items)} 件）\n')
    out.append('| 名称 | 重量 | 价格 | 特殊效果 |')
    out.append('|------|------|------|----------|')
    for e in items:
        sp = esc(e.get('special', ''))
        nm = esc(e.get('name', ''))
        if e.get('link'):
            nm = f"[{nm}]({e['link']})"
        out.append(f"| {nm} | {esc(e.get('weight',''))} | {esc(e.get('price',''))} | {sp[:400]} |")
    out.append('')

open('../docs/02_博德之门3_装备效果大全.md', 'w', encoding='utf-8').write('\n'.join(out))
print('Wrote 02_博德之门3_装备效果大全.md, lines:', len(out))
