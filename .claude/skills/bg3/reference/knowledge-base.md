# 本地知识库结构

## 数据文件（全部在 `data/`）

| 文件 | 内容 | 用途 |
|------|------|------|
| `data/spells.json` | 217 个法术结构化（level/school/damage dice+type/save/attack_type/upcast/aoe） | 法术问答 + 引擎输入 |
| `data/riders.json` | 手工核对的核心附伤定义（Tier3，最高优先级；80 条） | 引擎正确性基石 |
| `data/riders.auto.json` | 38 件装备自动分类的附伤（Tier1标签+Tier2正则） | 覆盖补充 |
| `data/conditions.json` | 29 个伤害相关状态（Wet/Burning/Blessed/Rage/Frozen/Chilled 等） | 状态问答 + 引擎 |
| `data/feats.json` | 41 个专长（name+描述） | 专长问答 |
| `data/spell_urls.json` | 217 法术 URL 清单（带 level） | 索引 |
| `data/spell_classes.json` | 210 法术的职业归属（class/core_class/level/subclass/via） | 法术职业校验 |
| `data/builds/*.json` | build 定义（职业/属性/专长/装备/buff/目标/回合动作） | 引擎输入 |
| `data/equipment.json` | 541 件常规装备（name/weight/price/special 效果） | 装备问答 |
| `data/legendary_effects.json` | 28 件传奇全文效果 | 传奇问答 |
| `data/legendary_list.json` | 传奇物品 URL 清单 | 索引 |
| `data/weapons_named.json` | 193 件具名武器（name/enchantment/damage） | 武器问答 |
| `data/weapons_base.json` | 31 种基础武器（die/range/properties） | 武器问答 |

## 原始抓取（全部在 `raw/`，可重新解析）

- `raw/mechanics/*.html`：核心机制页（Damage_mechanics/Attack_roll/Critical_hit/Saving_throw/Armour_Class/Resistance/Conditions/Feats/Spells list/Surfaces/Clouds）
- `raw/races/*.html`：13 个种族页 + 6 个吐息页 + Enlarge/Halfling_Luck/Savage_Attacks（种族机制原文）
- `raw/classes/*.html`：12 基础职业页 + 子类页（职业等级进度原文）
- `raw/conditions/*.html`：Wet/Chilled/Frozen/Encrusted/Burning/Reverberation/Brittle/Electrocuted/Drenched/Prone 等状态页（元素反应原文）
- `raw/surfaces/*.html`：Water/Ice/Fire/Acid/Poison Surface/Steam/Clouds 等地表页
- `raw/spells/*.html`：217 个法术页

**核对本地机制时用 `grep -ril <关键词> raw/` 搜文件内容，不要只看文件名**——很多机制（尤其种族特性）散在机制页脚注里，文件名匹配会漏。

## 成果文档（`docs/`）

- `docs/01_博德之门3_流派Build大全.md`：36 个流派 BD
- `docs/02_博德之门3_装备效果大全.md`：全装备效果汇总

## 工具脚本（`tools/`）

- `extract_spell_urls.py` — 从法术列表页提取 URL
- `fetch_spells.py` / `fetch_races.py` / `fetch_classes.py` — 批量抓取法术/种族/职业页
- `parse_spells.py` — 解析法术页→`spells.json`
- `parse_feats_conditions.py` — 解析专长/状态
- `classify_riders.py` — 附伤自动分类（Tier1/2）→`riders.auto.json`
- `parse_equipment.py` / `gen_equipment_md.py` — 装备解析/生成 md
- `extract_spell_classes.py` — 法术职业归属
