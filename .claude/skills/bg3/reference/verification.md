# 验证 + 数据可追溯性

## 验证

- **黄金回归测试**：`tests/test_golden_wiki.py` 复现 bg3.wiki Damage_mechanics 标准算例（20力+酒馆斗殴+闪电充能+投掷戒+Hex+闪电投掷器）。**端到端**（Catalog→Character→active_riders→expand_attack）单次命中=36.0、DR 情形=24.0、荣耀模式=24.0，与 wiki 完全一致。另含 on_crit rider、Wet 易伤、种族抗性、Burning 回合末测试。
- 单元测试：dice/attack/save/rider_engine 共 60 个测试全过（含全部 10 子系统 + 防御侧 + 状态触发装备 + Arcane Acuity）。
- 集成测试：Fireball(DC15,DEX+2)=22.4；全部 15 个 build 端到端跑通。
- **运行全部测试**：`python tests/run_all.py`；**单文件**：`python tests/test_<name>.py`。

## 数据可追溯性

每条结构化数据带 `source` 字段指向 bg3.wiki URL。回答中引用装备/法术效果时，可附该 URL 供用户核对。`catalog.py` 的内存补丁表（`NAMED_WEAPON_PATCHES`/`MULTISOURCE_SPELL_PATCHES`/`NAMED_WEAPON_EXTRA_DICE`）收录本地抓取缺失或异常的武器/多 source 法术/武器额外骰，均带 `source`/`_note`。
