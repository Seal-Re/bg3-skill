---
name: bg3
description: 博德之门3（BG3）专业知识 + 本地伤害期望值引擎。当用户问 BG3 的装备/法术/专长/状态/种族/机制/伤害计算/流派 build 时使用。能用本地 bg3.wiki 数据准确回答，并用引擎算出可验证的伤害期望值，而非凭记忆。触发词：BG3、博德之门、伤害期望、附伤、暴击、抗性、build、配点、圣击、投掷、法术环阶、种族特性、元素反应等。
when_to_use: 用户提到 BG3/博德之门3 的任何机制或数值问题；要算"某 build 一回合打多少伤害"/"附伤怎么叠"/"暴击/抗性怎么算"；要查装备/法术/专长/状态的精确效果；要核对 bg3.wiki 机制原文。
allowed-tools: Bash(python *) Bash(python -m engine *) Bash(pytest *) Read Grep Glob
paths: data/**, raw/**, engine/**, tests/**, docs/**, *.md, *.json
---

# BG3 专业知识 + 伤害引擎

本工作区（`E:\Seal\bg3`）具备 BG3 专业知识与本地伤害期望值引擎。回答 BG3 问题时**优先用本地库与引擎**，而非凭记忆。

## 何时用这个 skill

- 用户问 BG3 装备/法术/专长/状态/种族/机制的**精确效果**
- 要**算伤害**："某 build 打多少"/"附伤怎么叠"/"暴击/抗性怎么算"
- 要**核对 bg3.wiki 原文**机制（DS/DR/DRS、攻击检定、豁免、暴击、抗性、元素反应）

## 核心工作方式（三步）

1. **查本地库优先**：装备/法术/专长/状态问题，先在对应 JSON 检索（带 bg3.wiki source URL 可追溯）。数据全部在 `data/`（见 [reference/knowledge-base.md](reference/knowledge-base.md)）。
2. **伤害问题用引擎**：涉及"某 build 打多少伤害/附伤怎么叠/暴击/抗性"时，构造或复用 `data/builds/*.json`，跑 `python -m engine <build.json>` 得出**可验证的数值**，而非估算。引擎机制见 [reference/engine.md](reference/engine.md)。
3. **机制解释以 bg3.wiki 为准**：DS/DR/DRS、攻击/豁免/暴击/抗性等，引用 `raw/` 中的原文核对（`grep -ril <关键词> raw/` 搜内容，**不要只看文件名**——机制常散在脚注里）。

## 引擎使用

```bash
# 计算某 build 一回合期望伤害（按类型 + 总值）
python -m engine data/builds/fireball_test.json

# 跑全部测试（验证引擎正确性）
python tests/run_all.py

# 跑单个测试文件
python tests/test_golden_wiki.py
```

引擎核心是 DS/DR/DRS 展开（bg3.wiki Damage_mechanics 核对，golden 测试 36.0 端到端一致）。详见 [reference/engine.md](reference/engine.md)。

## 回答时的关键原则

- **标注不确定性**：自动分类的 rider（Tier2）标 medium 置信度；引擎已知简化假设（专注不中断、充能无限、条件由 build 显式声明、AoE 不模拟命中数）需在回答中说明。完整清单见 [reference/coverage.md](reference/coverage.md)。
- **数据可追溯**：每条结构化数据带 `source` 字段指向 bg3.wiki URL，回答中引用装备/法术效果时可附 URL 供用户核对。
- **改数据/引擎后跑测试**：`python tests/run_all.py` 确认无回归。

## 数据覆盖范围（已核对完整）

本地已对照 bg3.wiki 逐条核对并接入引擎：核心伤害机制（DS/DR/DRS/暴击/抗性）、攻击检定/豁免/AC、种族机制（抗性/Savage Attacks/Halfling Luck/吐息/Enlarge）、元素反应（Wet/Chilled/Frozen/Burning/Reverberation）、专长（12 个影响伤害的）、装备（541 常规+193 武器+28 传奇，影响伤害的全接入）。详见 [reference/coverage.md](reference/coverage.md)。

## reference 文件（按需加载）

- [reference/knowledge-base.md](reference/knowledge-base.md) — 本地知识库结构：data/ raw/ docs/ tools/ 各文件表
- [reference/engine.md](reference/engine.md) — 引擎机制：DS/DR/DRS 模型、模块、build/rider schema、使用
- [reference/coverage.md](reference/coverage.md) — 已建模/未建模清单、已知简化假设
- [reference/verification.md](reference/verification.md) — 验证（golden 测试/单元测试）+ 数据可追溯性
