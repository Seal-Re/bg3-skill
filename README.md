# bg3-skill

Baldur's Gate 3 reference data and a damage-expectation engine, packaged as a Claude Code project skill. The goal is to answer BG3 mechanics and damage questions from a local knowledge base instead of from model memory: the agent looks up items, spells, feats and conditions in structured JSON, and computes damage with a small Python engine that follows the wiki damage rules.

All mechanics numbers come from [bg3.wiki](https://bg3.wiki) pages (the raw HTML is kept under `raw/` so it can be re-parsed). Reddit r/BG3Builds and similar community sources are used only for build naming and stat allocation, not for numeric values.

## The skill

`.claude/skills/bg3/` is a Claude Code skill:

- `SKILL.md` (55 lines) is the entry point: when to use it, how to run the engine, and the core rules (prefer the local data, cite the wiki source URL, state uncertainty).
- `reference/` holds four files loaded on demand — `knowledge-base.md` (45 lines), `engine.md` (76), `coverage.md` (98), `verification.md` (12).

Open Claude Code in this repository and ask a BG3 question; the agent picks up the skill automatically. It can also be invoked explicitly as `/bg3`.

## The damage engine

`engine/` (11 Python modules) computes a build's expected damage per round, following the wiki's damage model:

- DS / DR / DRS: a damage source triggers every attached rider once, and a rider classified as a source (DRS) triggers another full round — the basis of BG3's "riders on riders" multiplication.
- Critical hits double dice, not flat modifiers; resistances / immunities / vulnerabilities are applied per damage type at the end.
- Build inputs cover classes and levels, abilities, feats, equipment, active buffs and the round's actions; the engine resolves attacks, saves, smites, multi-projectile spells and a set of conditions.

```bash
# Expected damage for one round, broken down by damage type
python -m engine data/builds/fireball_test.json

# Full test suite
python tests/run_all.py
```

`tests/run_all.py` runs 60 tests across `test_dice.py`, `test_attack_save.py`, `test_rider_engine.py` and `test_golden_wiki.py`; all 60 pass (verified on Python 3.13). The golden-wiki tests reproduce worked examples from the wiki's damage-mechanics page end to end.

There are 15 example build files in `data/builds/`, used by the tests and as templates for new questions.

## Data (`data/`)

| File | Contents | Count |
|---|---|---|
| `equipment.json` | Non-weapon equipment (name, weight, price, special effects) | 541 |
| `weapons_named.json` | Named weapons (name, enchantment, damage) | 193 |
| `weapons_base.json` | Base weapon types (die, range, properties) | 31 |
| `legendary_effects.json` | Full effect text for legendary items | 28 |
| `legendary_list.json` | Legendary item index | 28 |
| `spells.json` | Spells (level, school, damage, save, upcast, AoE) | 217 |
| `spell_classes.json` | Spell-to-class mapping | 210 |
| `spell_urls.json` | Spell index | 217 |
| `feats.json` | Feats (name, description) | 41 |
| `conditions.json` | Damage-relevant conditions | 29 |
| `riders.json` | Hand-checked rider definitions | 84 |
| `riders.auto.json` | Auto-classified equipment riders | 38 |

`raw/` (399 files) holds the scraped wiki pages — mechanics, races, classes, conditions, surfaces, spells — that the JSON was parsed from. `tools/` holds the scrapers and parsers (`fetch_spells.py`, `parse_spells.py`, `parse_equipment.py`, `classify_riders.py`, and others).

## Documents (`docs/`)

- `01_博德之门3_流派Build大全.md` — 36 character builds grouped by main class, each with stat allocation, core mechanics, key feats, recommended equipment and role.
- `02_博德之门3_装备效果大全.md` — full equipment effects: the 28 legendary items in full text, 31 base weapon types, 193 named weapons, 541 regular items.

Both documents are in Chinese. The 36 builds exist as documented write-ups, not as 36 engine input files; the engine ships 15 sample builds in `data/builds/`.

## Data pipeline

1. `curl` the wiki pages (equipment, weapons, armour, shields, amulets, rings, cloaks, headwear, handwear, footwear, legendary, 14 weapon subtypes, 28 legendary items, classes, feats, spells, races, conditions, surfaces).
2. `tools/*.py` parse the HTML tables with regex into the JSON files above.
3. Build write-ups in `docs/` were authored by hand, checking mechanics against the wiki and stat allocation against community consensus.

Wiki snapshot date: 2026-07-21.

## Known limitations

- The engine models expected damage, not full combat: it assumes concentration is never broken, that consumable charges are sufficient, and that AoE hit counts are not simulated. Conditions and situational flags not derivable from the build must be declared explicitly.
- Riders classified automatically are tagged medium confidence; only `riders.json` is hand-verified.
- `catalog.py` fixes known field-name and weapon-string defects in the JSON in memory at load time and does not write them back; the JSON on disk still contains those defects.

## Sources

- [bg3.wiki](https://bg3.wiki) — mechanics, equipment, classes, feats, legendary items
- [r/BG3Builds](https://www.reddit.com/r/BG3Builds/) — build naming and stat allocation only

## Contributors

Seal-Re
