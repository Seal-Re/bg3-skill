# 引擎覆盖度：已建模 / 未建模

> 本文件记录引擎对照 bg3.wiki 核对的覆盖情况。回答时若涉及未建模项需说明。

## 已建模（对照 bg3.wiki 核对通过）

### 核心机制
- **荣耀模式开关**：build 顶层 `honour_mode: true` 时，所有 DRS 降级为普通 DR（wiki Honour Mode exception）。golden 测试验证 36.0→24.0。
- **多 source 法术**：Magic Missile/Scorching Ray/Eldritch Blast 每弹/每束为独立 DS，各自再触发 spell 侧 rider（DamageBonus 语义）。多段法术（Ice Knife 穿刺+冰）每段独立 source。补丁表在 `catalog.MULTISOURCE_SPELL_PATCHES`。
- **暴击域**：`target.crit_immune`（Adamantine，nat20 当普通命中）、`auto_crit`（Paralysed/Sleeping/Unconscious，近战必暴击，由 conditions 自动推导）、`on_crit` rider（暴击触发型，骰随暴击翻倍、flat 不翻；Craterflesh/Sword of Life Stealing）。
- **无视抗性/免疫**：rider damage 标 `bypass_resistance: true`（Hellfire Greataxe）跳过 res/imm，易伤仍生效。
- **conditions 引擎消费**：conditions.json 的 `resistances`/`vulnerabilities`/`immunities`（Wet 易冰电、Frozen 易钝雷力、Petrified/Blade Ward 抗、Chilled/Brittle 易伤）、`auto_crit_vs_melee`、`advantage_vs` 由 round.py `_apply_target_condition_effects` 自动应用到 target。
- **圣击**：从 riders.json 读基础定义（kind 已正名为 DRS），`round._build_smite_drs` 按 slot 缩放骰数。
- **种族机制**（v3 新增，对照 `raw/races/` 核对）：
  - build 顶层 `species` 字段（`"Tiefling"`/`"Dragonborn:Black"`/`"Halfling:Strongheart"` 等）。`target.species` 同理（表示我方承受伤害）。
  - **种族抗性**：`catalog.SPECIES_RESISTANCES`（Tiefling→Fire；Dwarf/Duergar/Strongheart-Halfling→Poison；Dragonborn 10 子种族按祖先）自动并入 target.resistances。
  - **Half-Orc Savage Attacks**：近战武器暴击 +1 武器骰（不是整组）。`DamageComponent.savage_attacks` 标志，`has_savage_attacks()` 检测 species。
  - **Halfling Luck**：nat1 重掷一次。`attack.p_hit(halfling_luck=...)`，`has_halfling_luck()` 检测。
  - **Dragonborn 吐息**：round_action 类型 `racial_breath`，2d6→3d6(6级)→4d6(11级)，DC=8+CON+prof，half on save，DEX/CON 豁免按子种族（`catalog.DRAGONBORN_BREATH`）。
  - **Duergar Enlarge / Zariel Searing Smite**：riders.json 条目，作 active_buff 声明（+1d4 武器 DR / +1d6 火 DRS）。
  - **种族豁免优势**：Gnome Cunning（INT/WIS/CHA）等通过 `catalog.SPECIES_SAVE_ADVANTAGE` 注入 target.save_bonus（属性级）。
- **专长机制**（v4 新增，对照 `raw/mechanics/Feats.html` 核对）：引擎已接入 12 个影响伤害的专长——
  - `Tavern Brawler`：STR mod 第二次加到**伤害+攻击骰**（unarmed/thrown）。
  - `Great Weapon Master`/`Sharpshooter`：attack_modifier(-5攻击/+10伤害,All In);GWM 还有 `bonus_attack` action(暴击触发附赠攻击,按 p_crit 加权)。
  - `Savage Attacker`：近战武器骰重掷取高（仅 melee;rider 骰重掷为已知简化）。
  - `Elemental Adept: <type>`：feat 名带类型;该类型 bypass 抗性/免疫 + 骰 min=2（`elemental_adept_types()`）。
  - `Polearm Master`：`bonus_attack` action,butt 1d4 + max(STR,DEX)。
  - `Spell Sniper`：法术攻击暴击阈值 -1（`crit_threshold(attack_kind='spell')`）。
  - `Charger`/`Martial Adept`：riders.json active_buff(+5 flat / +1d8 DR)。
  - build `feats:[...]` 声明;部分经 active_buff 触发。
- **装备 rider 覆盖**（v5 新增 + v6 数据集驱动复核对漏）：riders.json 现 65 条。v5 补 13 件高优先级漏检装备——
  - 传奇武器:Bloodthirst(crit-1+穿刺易伤,修键名bug)、Balduran's Giantslayer(prof DR + STR翻倍 DR)、Duellist's Prerogative(19暴击+Withering Cut)、The Clover(19暴击+穿刺易伤)、Shar's Spear of Evening(遮蔽+1d6)。
  - 常规:Gloves of Archery(远程+2)、Gloves of the Balanced Hands(副手+ability_mod)、Shadow-Cloaked Ring(遮蔽+1d4)、Legacy of the Masters(+2攻击+2伤害)、Circlet of Hunting(标记+1d4攻击骰)、Sarevok's Horned Helmet(暴击-1无条件)、Bonespike Gloves(物理 bypass S/P/B)、Poisoner's Ring(毒易伤)。
  - **v6 复核补漏**(数据集驱动:扫 541 常规装备+193 武器+28 传奇的 Special 字段,挑影响攻击伤害输出却没入库的):Spellmight Gloves(法术-5/+1d8)、Daredevil Gloves/Gloves of the Duellist/Marksmanship Hat/Swordmaster Gloves/Winkling/Blackguard's Gauntlets/Gauntlets of the Warmaster/Unwanted Masterwork Gauntlets/Bhaalist Gloves(各 +N 攻击)、Dark Justiciar Gauntlets(武器+1d4死灵)、Gloves of Uninhibited Kushigo(投掷+1d4)、Scabby Pugilist Circlet(被围+2)、Necklace of Elemental Augmentation(戏法+spell_mod)、Ring of Arcane Synergy(武器+spell_mod)、Risky Ring(攻击优势)。发现 v5 文档曾声称 Shadow-Cloaked/Necklace 已覆盖但实际未入库——数据集驱动法捕到。
  - 引擎扩展:`attack_modifier` rider 现扫描 equipped items(此前只扫 feats/buffs);`dr_bypass` kind;attack 路径 apply_resistances 传 bypass_types。**v6 修 spell 侧 rider condition 漏检**:`_spell_action` 现对 spell_riders 过 `_condition_met`(此前不过 condition,条件型 spell rider 会误触发)。
  - **v6 修正**:Viconia's Walking Fortress 的 2d4 Force 实为受击反击(防御侧),不应作攻击 rider——已标注,不接入进攻侧。
- **具名武器 damage 解析**（v5 新增）：weapons_named.json 的 damage 字段有 21 件异常（`2d61d4`/`1d10 + 21d4` 等连写）。`_normalize_named` 用限定骰面正则（d4/d6/d8/d10/d12/d20/d100）提取主骰，避免 `2d61`（61面骰）荒谬值；**全部 21 件**的额外骰经 `NAMED_WEAPON_EXTRA_DICE` 表作 rider 补回（附骰类型逐件抓 wiki 核对：火/光耀/死灵/心灵/力场/闪电/毒/冷等）。
- **法术伤害侧 rider**（v5）：Necklace of Elemental Augmentation（戏法+spell_mod）、Hat of the Sharp Caster（法术骰重掷1-2取高,`dice.upgrade_reroll_low2`）、Psychic Spark（Magic Missile+1弹）。`_rider_type` 识别 `SameAsSpell`。
- **防御向装备/承受侧**（v6 新增）：`catalog.DEFENSIVE_ITEMS`（Adamantine 暴击免疫 + Superior Padding/Plate/Material 单类型减伤 + Magical Plate 全减伤）。target.equipped 声明穿戴,target.crit_immune/flat_reduction 自动推导;`apply_resistances` 减 flat(min 0)。
- **条件 flag 自动推断**（v6 新增）：`attacker_has_advantage`（从 action.advantage 推断,Crimson Mischief 等）、`off_hand_attack`（从 weapon_slot=off_hand 推断,Gloves of the Balanced Hands）由 `_set_auto_flag`/`_clear_auto_flags` 按攻击作用域自动设/清,build 无需手动声明。其余 flag（target_obscured/target_marked/target_le_half_hp 等）仍需 build 显式声明（依赖战局状态）。
- **状态触发型装备**（v6 新增,rider kind `inflicts_condition`）：攻击命中给 target 叠 condition,回合末由 `_end_of_turn_damage` 结算。Spineshudder Amulet/Gloves of Belligerent Skies（远程法术/雷电流→Reverberation 2层/命中）、Thunderskin Cloak（+1层）、Winter's Clutches（冰伤→Encrusted 2层）、Snowburst Ring（冰伤→Prone）、Luminous Gloves/Coruscation Ring（光耀/法术→Radiating Orb）。`_apply_inflicted_conditions` 按期望命中数(p_normal+p_crit)×count / spell n_hits 叠层;Reverberation 5层触发 1d4雷DRS、Encrusted 7层触发 1d4冰DRS+Frozen易伤。spell action 现返回 p_normal/p_crit/n_hits 供叠层计数。
- **Arcane Acuity 系列**（v6 新增）：Hat of Fire Acuity/Storm Scion/Helmet of Arcane Acuity 造成对应伤害获 Arcane Acuity(+1法术攻击&DC)。Acuity 作 active_buff 声明,`spell_attack_bonus`/`spell_save_dc` 检测后 +1。`grants_condition` rider 记录触发条件(火/雷/武器伤)。
- **进攻侧暴击降阈值装备**（v6 补）：Shade-Slayer Cloak(隐藏时-1)、Covert Cowl(遮蔽时-1)——此前误归防御侧,实为进攻 crit_threshold rider。
- **职业等级进度**（v7 新增，对照 `raw/classes/` 12 职业页核对）：此前只有零散硬编码（rage_damage/sneak_attack_dice/monk die）。现已数据驱动——
  - `proficiency_bonus` 自动从总等级推导（1-4=2/5-8=3/9-12=4/13-16=5/17-20=6）;build 显式声明则尊重。
  - `Extra Attack`（Fighter/Barbarian/Paladin/Ranger/Monk 5级,Fighter 11级再+1,Bard Valour 6级）:attack action 标 `extra_attack:true` 自动加攻击数。
  - `max_spell_slot()`（全施法者 lvl1/3/5/7/9/11→1-6环;半施法 Paladin/Ranger 2/5/9级→1-3环;Warlock Pact 1/3/5/7/9→1-5环）。
  - `Improved Divine Smite`（Paladin 11,近战每击+1d8光耀 DR,自动注入）。
  - `Champion` 子类（Fighter subclass:Champion,crit_threshold-1）;classes 支持 `subclass` 字段。
  - `Brutal Critical`（Barbarian 9,暴击+1武器骰,走 savage_attacks 路径）。
  - 已有:Sneak Attack（Rogue 每两级+1d6）、Rage damage（Barbarian 2/3）、Monk Martial Arts die、Dragonborn 吐息骰。
  - **仍需 build 显式声明的进度特征**:Action Surge（战士2,额外动作,build 加额外 attack action）、Wild Shape（兽形数据）、Fighting Style（Archery/Dueling 等,引擎未建模）、子类法术。
- **法术职业限制 + 环阶校验**（v8 新增）：`data/spell_classes.json`（210 法术/976 条归属,从 raw/spells Classes 字段提取,含 core_class 归一化/子类/Magical Secrets/Domain Spell/Oath Spell 等机制）。`Character.can_cast(spell)` 校验 build 职业能否学;`_spell_action` 职业不符则 note 警告（不归零,物品/种族施法仍可用）,upcast 超 `max_spell_slot()` 则夹紧+note。
- **狂暴 Rage 完善**（v8）：此前只有 rage_damage 伤害 DR。补:(1) 物理抗性（狂暴时 self_resistances 含 B/P/S,承受侧）;(2) Reckless Attack（野蛮人2级,action 标 `reckless:true` → 近战优势,原文"敌人也获优势"仅进攻侧简化）。
- **超魔 Metamagic**（v8 新增,对照 `raw/classes/Sorcerer.html`）：build active_buffs 声明 `Metamagic: <Type>`（需 Sorcerer 3+）。Twinned（单体法术 n_targets×2）、Heightened（目标首次豁免劣势→p_fail 升高,save 法术增伤）、Empowered（伤害骰重掷取高,EV 抬高 via upgrade_savage）。Quickened（Action→Bonus Action,不影响伤害值,不建模）。
- **职业子类/特征补全**（v9 新增,数据集驱动核对 12 职业后补漏）：riders.json 补 Agonizing Blast（Warlock 祈唤,EB 每束+CHA Force）、Draconic Bloodline（Sorcerer 元素亲和+CHA,active_buff 声明）、Empowered Evocation（Wizard Evocation 子类10,+INT 塑能,subclass:Evocation 自动注入）。引擎补:Monk Ki-Empowered Strikes（L6 徒手 bypass 物理抗性）、Fighting Style（build `fighting_style` 字段:Archery +2远程命中/Dueling +2近战伤害无副手）、Warlock Thirsting Blade（祈唤 Extra Attack,active_buff 声明）。
- **职业机制覆盖**（v9 核对）：12 职业 43 项核心机制,已建模 38 项(Barbarian Rage/Reckless/Brutal/ExtraAttack、Bard ExtraAttack、Fighter ExtraAttack×2/Champion、Monk MartialArts/Ki-Empowered/ExtraAttack、Paladin Smite/ImprovedDivineSmite/ExtraAttack、Ranger ExtraAttack/ColossusSlayer、Rogue SneakAttack、Sorcerer Metamagic/Draconic、Warlock PactMagic/Agonizing/Thirsting、Wizard Evocation、通用 prof/slot/can_cast)。v10+v11 补全后仅剩 Bardic Inspiration(资源骰,非稳态)、Channel Divinity(除 Tempest Destructive Wrath 外的情境)、Action Surge(build 加额外 attack action 表达)、Stunning Strike(施加状态)未建模。
- **10 子系统全建模**（v11 新增,对照 `raw/classes/`+`raw/spells/` 核对）：此前标注"超出核心"的 10 个子系统现已全部接入——
  - **Wild Shape 兽形**:`catalog.BEAST_FORMS`(8 形态:Owlbear/Sabertooth/Bear/Deep Rothe Moon 专属 + Wolf/Panther/Spider/Badger),`wild_shape` action,兽形攻击骰+STR mod+Multiattack,Moon 专属校验。
  - **Shadow Blade 法术武器**:`_spell_sources` 按环阶缩放(2d8@2环→5d8@7环,每2环+1d8),+STR/DEX mod 到伤害。
  - **四象 ki 法术**:`KI_SPELLS`(7 个:Fist of Unbroken Air/Fist of Four Thunders/Water Whip/Sweeping Cinder Strike/Gong of the Summit/Embrace of the Inferno/Flames of the Phoenix),`ki_spell` action,save DC=8+prof+WIS,attack 型走命中。
  - **死灵/召唤法术**:`SUMMON_ATTACKS`(13 召唤物:Skeleton/Zombie/Ghoul/Mummy + 4 元素 + Mephit/Dryad/Danse Macabre Ghoul/Cambion/Deva),`summon` action,含 extra 伤害(Skeleton +1d10 死灵、Mummy +6d6 死灵)。
  - **预言骰 Portent**:Div Wiz2+,active_buff "Portent",强制一次攻击命中(p_miss 伤害补回)。
  - **Wild Magic surge**:Sorc Wild Magic,active_buff "Wild Magic Surge",每法术 +1.4 EV(5%×伤害类 surge 均值)。
  - **Assassin Assassinate**:对 Surprised 目标优势+必暴击(target.flags `surprised`)。
  - **Tempest Destructive Wrath**:雷电/雷鸣取最大值(max_roll)。
- **防御侧全量**（v11 新增）：target 减伤修饰——Adamantine 暴击免疫 + Superior Padding/Magical Plate flat 减伤(`DEFENSIVE_ITEMS`) + Evasion(target.evasion,DEX save half→none)+ Uncanny Dodge(target.uncanny_dodge,单次命中 half)+ Heavy Armour Master(flat_reduction)+ 种族/Rage/conditions 抗性。AC 构成作文档说明(target.ac 输入)。
- **热门 build 基准 + bug 修复**（v10）：用 6 个社区热门 build 端到端跑伤害,发现并修 2 个 bug:
  - **GWM 双重计算**:`_attack_modifiers` 对 feat+active_buff 重复声明同一 rider(GWM feat + 'Great Weapon Master (active)' buff)各加一次,导致 -10/+20(应 -5/+10)。已按 source 去重。战斗大师战士(Fighter12 GWM+Giantslayer)修正后 87.73/回合(3击×优势命中×GWM,合理)。
  - **Tempest Domain / Destructive Wrath**（补建）:Cleric Tempest 子类 2 级 Channel Divinity,雷电/雷鸣伤害取最大值。build 声明 `subclass:"Tempest Domain"` + active_buff `Destructive Wrath`,该 source 的 Lightning/Thunder 骰转 max_roll(flat)。风暴核弹牧(Call Lightning 3d10)13.61→24.75(max 30,half save),与手算 0.65×30+0.35×15=24.75 一致。
  - 注:社区 build 大全(01_*.md)只有配点思路无数值,故无"实际数据"对比基准;正确性锚点是 wiki Damage_mechanics 算例(36.0 端到端一致)。
  - **全部 36 热门 build 端到端跑通**(v10):30/30 复杂多职 build(含多子类/圣击/超魔/投掷/双挥/法术混合)零崩溃。补 Hand Crossbow/Dwarven Thrower 到 NAMED_WEAPON_PATCHES。补 **Assassin 子类 Assassinate**(对 Surprised 目标优势+必暴击,build target.flags 加 `surprised`,临时设 target.auto_crit 攻击后恢复)。修 GWM 双重计算 + 补 Tempest Destructive Wrath 后,6 标杆 build 数值经手算核对合理(投掷蛮 91.8/战斗大师 87.7/风暴牧 24.75 等)。
- **元素反应**（v3 新增，对照 `raw/conditions/`+`raw/surfaces/` 核对）：
  - **Wet 易冰/电**（上轮 bug 修复后生效）、Chilled 易冰+抗火、Frozen 易钝/雷/力+抗火、Brittle 易钝/雷——均经 condition vulnerabilities 自动应用。
  - **回合末持续伤害**：`_end_of_turn_damage` 结算 Burning(1d4火)/Brittle(2d6冰)/Electrocuted(1d4电)，BURNING stack-id 互斥取最强（Melting 10d6 等）。
  - **Reverberation 5层**：触发 1d4 雷 DRS（+Prone 豁免未建模为伤害）。
  - **冻结链顺序敏感**（Chilled→Wet 才冻结）：数据记录在 conditions.json，引擎未做状态机转换（需 build 显式声明 Frozen）。
- **spells.json 修正**（v3）：Hellish Rebuke(DEX半伤+升环1d10)、Searing Smite(命中即1d6火,CON结束持续)、Burning Hands/Branding Smite(升环1d6)、Faerie Fire(不造伤害,DEX避免减益)。

## 仍未建模（有意简化，回答时需说明）
- **专注法术**（Hex/Hunter's Mark）假设整回合持续，不模拟被打断
- **消耗型 rider**（Lightning Charges 等）假设充能充足
- **条件触发型 rider**（优势/光照/半血）由 build JSON 显式设 flag，不自动推断（`attacker_has_advantage`/`target_le_full_hp`/`target_illuminated`/`self_healed_recently` 等）
- **AoE 法术**按 `n_targets` 参数计伤害，不模拟几何命中数
- **攻击骰加值来源**：Bless(+1d4)、Archery fighting style(+2)、高地(±2)、Coatings 等**未建模**——`attack_bonus` 只算 prof+属性+附魔+attack_modifier(GWM/Sharpshooter)
- **AC 构成**：target.ac 是一个数字，不模拟中甲 DEX 上限(+2)/重甲无 DEX/Mage Armour(13+DEX)/Unarmoured Defence 等构成
- **武器动作 DC / 混合 DC / 固定 DC**：只有 `spell_save_dc`(8+prof+施法属性)；武器动作 DC(8+prof+max(STR,DEX)+2)、混合 DC、陷阱固定 DC 未建模
- **死亡豁免**：不涉及（引擎聚焦进攻伤害）
- **Savage Attacker**（专长）：暴击时 savage 加值的翻倍近似忽略;**只重掷武器基础骰不含 rider 骰**(原文"your damage dice"含 rider,已知简化);走 `has_savage_attacker()` 特殊路径,非普通 rider
- **未接入的专长**:Crossbow Expert(近距弩无劣势,引擎未建模近距劣势来源)、Dual Wielder(副手武器骰升级,引擎未模拟副手武器选择)、Sentinel/Lucky(反应/资源受限难稳态)、防御向(Heavy Armour Master -3物理/Shield Master/Resilient/Mage Slayer/Defensive Duellist/War Caster/Medium Armour Master,需"承受伤害"侧扩展)。B 类专长(Actor/Alert/Mobile/Tough/各护甲熟练/Magic Initiate/Ability Improvement 等)纯属性/熟练/生存,经 build abilities 体现,无需 rider。
- **种族法术精确数值**：种族页只给环阶，精确骰需 raw/spells/ 法术页（已抓）；种族版"按2环施放"由 build 在 upcast_level 显式声明
- **Savage Attacks 对 Smite/Sneak 二次骰**：仅实现武器骰+1；对 Smite/Sneak 暴击的二次加骰（荣耀模式取消）未建模
- **种族豁免优势的类别级**（Fey Ancestry 魅惑/Dwarven 毒等需法术标签）：仅实现属性级（Gnome Cunning INT/WIS/CHA）
- **地表转换链状态机**（水+电→电水、水+冰→冰面→Prone、冰+火→水、火+油→火面、水+火→Steam）：数据在 raw/surfaces/，引擎未做动态转换（Prone 状态本身已建模）
- **Encrusted with Frost 7层→Frozen 触发**：数据有，引擎未做层数触发状态机
- **"可多次施加/每 source 多次结算"**（Colossus Slayer 对同一 source 多次）：当前每 source 结算一次
- **多 source 法术的 DRS 互相触发链**：引擎只展一层 DRS（无 DRS-spawn-DRS 链）

