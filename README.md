# 博德之门3 索引

> 本仓库已封装为 Claude Code **project skill**（`.claude/skills/bg3/`）。在本仓库目录下启动 Claude Code，问任何 BG3 机制/伤害问题时，agent 会自动加载该 skill：用本地 bg3.wiki 数据回答，并用 `engine/` 伤害期望值引擎算出可验证数值（而非凭记忆）。也可手动 `/bg3` 调用。skill 入口 `SKILL.md`（55 行常驻），详细资料在 `.claude/skills/bg3/reference/` 按需加载。

## 一、调研方法

### 真实性方案
- **标准源**：[bg3.wiki](https://bg3.wiki)（社区维护、数值与游戏内一致、标注来源版本）。所有**机制数值**（职业特性、专长、装备伤害/附魔/效果）均取自该 Wiki 原始数据页，不做二次转述。
- **交叉核对**：传奇物品逐条抓取其独立页面"Special / Special weapon actions"段落，保留全文效果；常规装备逐条保留 bg3.wiki 表格中的"Special"列原文。
- **社区源仅用于"流派命名与配点思路"**（Reddit r/BG3Builds、WolfheartFPS、Prestige Please），不作为数值依据，避免攻略过时/失真。

### 全面性方案
- **流派**：分层覆盖 12 个基础职业 → 纯职流 → 双职流 → 三职流，并补足特殊机制流（投掷、核弹、咖啡锁、骰子改命等），共 **36 个**，超过"30 种"要求。
- **装备**：按 9 大类目（武器/护甲/盾/项链/戒指/披风/头/手/脚）全量抓取 Wiki 类目页；武器额外抓取 14 个子类型页取具名武器；传奇物品抓取全部 28 件独立页面取全文效果。
- **可追溯**：每个 Build 推荐的核心装备均可在装备数据集中按名检索，做到"流派—装备"闭环。

### 执行路径
1. `curl` 抓取 bg3.wiki 的 Equipment / Weapon / Armour / Shields / Amulets / Rings / Cloaks / Headwear / Handwear / Footwear 页 + Legendary 页 + 14 个武器子类型页 + 28 个传奇物品页 + Classes/Feats 页。
2. Python 正则解析 HTML 表格 → 结构化 JSON。
3. 人工撰写流派 BD（机制核对 Wiki，配点综合社区共识）。
4. 汇总生成 Markdown 成果文件。

## 二、成果文件

| 文件 | 内容 | 规模 |
|------|------|------|
| `docs/01_博德之门3_流派Build大全.md` | 36 个流派 BD：配点、核心机制、关键专长、推荐装备、定位 | 36 个 |
| `docs/02_博德之门3_装备效果大全.md` | 全装备效果：传奇全文 + 基础武器 + 具名武器 + 9 类目常规装备 | 541+193+28+31 件 |
| `data/equipment.json` | 常规装备结构化数据（名称/链接/重量/价格/效果） | 541 件 |
| `data/legendary_effects.json` | 28 件传奇物品全文效果 | 28 件 |
| `data/weapons_named.json` | 具名武器（名称/附魔/伤害） | 193 件 |
| `data/weapons_base.json` | 31 种基础武器类型（伤害/射程/属性） | 31 种 |
| `data/legendary_list.json` | 传奇物品 URL 清单 | 28 条 |

## 三、来源链接

- [bg3.wiki 首页](https://bg3.wiki)
- [bg3.wiki - Classes](https://bg3.wiki/wiki/Classes)
- [bg3.wiki - Equipment](https://bg3.wiki/wiki/Equipment)
- [bg3.wiki - Legendary](https://bg3.wiki/wiki/Legendary)
- [bg3.wiki - Feats](https://bg3.wiki/wiki/Feats)
- Reddit [r/BG3Builds](https://www.reddit.com/r/BG3Builds/)（流派命名与配点共识）

## 四、备注

- 抓取时间：2026-07-21。BG3 自 Patch 7 后机制稳定，本数据适配当前版本（战术/荣誉难度可用）。
- 个别装备"Special"列在 Wiki 中为空（纯外观/无特效道具），已在数据中如实留空。
- 流派评级（S/A/B）为社区综合共识，仅供强度参考，非绝对。
