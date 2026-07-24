# 伤害期望值引擎（`engine/`）

## 核心机制模型（bg3.wiki Damage_mechanics 核对）

- **DS（伤害源）**：一次攻击/法术直接造成的伤害（武器骰+附魔+属性调整值）
- **DR（附伤）**：骑在 DS 上的附加伤害，**每个 DS 触发一次**
- **DRS（被当作新伤害源的附伤）**：作为新 DS，**再触发一轮所有 DR**——这是"附伤套附伤"乘法效应的来源
- **暴击**：翻倍**骰数**（不含固定+加值如附魔/属性）
- **抗性/免疫/易伤**：按伤害类型在最后应用（减半/归零/翻倍）

## 模块

| 模块 | 职责 |
|------|------|
| `engine/dice.py` | 骰表达式 EV + 暴击翻倍（`ev("8d6")=28`, `ev("8d6",crit=True)=56`） |
| `engine/damage.py` | DamageComponent/Pool，按类型分组 EV，抗性应用 |
| `engine/attack.py` | 命中/暴击/未命中概率（d20+加值 vs AC，优劣势） |
| `engine/save.py` | 豁免法术期望（DC=8+熟练+施法属性，半伤/无伤） |
| `engine/rider_engine.py` | **核心**：DS/DR/DRS 展开 |
| `engine/character.py` | 加载 build、派生属性（攻击加值/DC/暴击阈值） |
| `engine/catalog.py` | 数据加载+武器规范化（修复现有 JSON bug，内存中）+ 三层 rider 解析 |
| `engine/round.py` | 编排：一回合→期望伤害 |
| `engine/__main__.py` | CLI 入口 |

## 使用

```bash
# 计算某 build 一回合期望伤害（按类型 + 总值）
python -m engine data/builds/fireball_test.json
python -m engine data/builds/fighter_test.json
python -m engine data/builds/lightning_thrower.json

# 跑全部测试（60 个：dice/attack_save/rider_engine/golden_wiki）
python tests/run_all.py

# 跑单个测试文件（直接执行，自带 __main__）
python tests/test_rider_engine.py
python tests/test_golden_wiki.py
```

## Build / action schema（编辑 `data/builds/*.json` 必读）

Build 顶层字段：`classes:[{cls,level}]`、`abilities:{STR..CHA}`、`proficiency_bonus`、`attack_ability`、`feats:[name]`、`equipped:{main_hand,off_hand,armor,ring1,...}`、`active_buffs:[{ref}]`、`target:{...}`、`round_actions:[...]`、`species`、`honour_mode`。

`round_actions` 中每个 action 的 `type` 决定分发：
- **attack**：`weapon`(slot名,默认`main_hand`)、`attack_kind`(`melee`/`ranged`/`thrown`/`unarmed`)、`count`、`advantage`/`disadvantage`、`smite:{slot_level,attack_index}`、隐式偷袭(由 rider 的 `once_per_turn` 标记)。
- **spell**：`ref`(法术名)、`upcast_level`、`n_targets`、`count`(攻击型法术的弹数,如灼热射线=3)。
- **racial_breath**：Dragonborn 吐息（按 species 子种族）。
- **bonus_attack**：`feat`(Polearm Master/Great Weapon Master) 附赠攻击。

## Rider dict schema（编辑 `riders.json` / `riders.auto.json` 必读）

每个 rider：`trigger`(可 `|` 多选)、`kind`(`DR`/`DRS`/`attack_modifier`/`crit_threshold`/`target_vulnerability`/`inflicts_condition`/`special_savage` 等)、`damage:{dice,flat,flat_sym,type}`(`type` 可为 `SameAsWeapon`/`SameAsSpell`)、可选 `condition`、可选 `once_per_turn`。

**trigger 分类法**（`attack_kind` → 生效的 trigger 集合）：
- `melee` → `weapon_attack_hit` + `melee_weapon_attack_hit`
- `ranged` → `weapon_attack_hit` + `ranged_weapon_attack_hit`
- `thrown` → `thrown_attack_hit` + `weapon_attack_hit`
- `unarmed` → `unarmed_attack_hit`
- `spell` → `spell_attack_hit` + `spell_damage_dealt`

`condition` 支持：`target_has:<ConditionName>`（查 `target.conditions`）或任意 flag 名（查 `target.flags`，如 `sneak_attack_eligible`/`target_le_half_hp`/`target_illuminated`/`attacker_has_advantage`）；未设 flag → rider 不触发。

## 进攻侧触发的目标属性

- `target_vulnerabilities()`（如 Bhaalist Armour：3m 内敌人对穿刺易伤；Bloodthirst Exploit Weakness）——在 `round.py` 开头把易伤类型并入 `target.vulnerabilities`。
- `target.creature_type`（`undead`/`fiend`）——圣击额外 +1d8。
- 圣击自身建模为 **DRS**，骰数 = `2 + max(0,slot-1)`，封顶 5d8。

## 三层附伤识别（优先级高→低）

1. **Tier3** `data/riders.json`：手工核对——**引擎正确性来源**
2. **Tier1** 自动：源文本字面标记 `Damage rider as source damage` → DRS
3. **Tier2** 自动：正则规则（dice+type+触发关键词）→ DR，标 medium 置信度

> `catalog.py` 加载时会**在内存中修正**现有 JSON 的已知 bug（字段名/武器规范化等），但**不回写文件**。调试数据时若发现运行值与 JSON 原文不符，先查 `catalog.py` 的规范化逻辑，而非怀疑引擎算错。
