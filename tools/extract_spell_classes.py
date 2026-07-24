"""Extract class/subclass attribution from each spell's HTML info box.

Parses the "Classes:" field (e.g.
  "Class level 1: Cleric and Life Domain (Domain Spell) Class level 2: Paladin
   Class level 6: College of Lore (via Magical Secrets ) Class level 10: Bard (via Magical Secrets )")
into a mapping {spell_name: [{class, level, ...}, ...]}.

Normalization:
  - Core classes: Cleric, Wizard, Sorcerer, Warlock, Bard, Druid, Paladin,
    Ranger, Fighter, Rogue, Monk.
  - Subclasses are kept verbatim (e.g. "Circle of the Spores", "Hunter",
    "Eldritch Knight", "Arcane Trickster", "Oathbreaker", "The Hexblade",
    "Necromancer", "Draconic Bloodline", "Life Domain", "Death Domain").
  - "(via Magical Secrets )" / "(via Magical Secrets)" -> Bard Magical Secrets
    (level 6 for College of Lore, level 10 for plain Bard). Both annotated
    with via="Magical Secrets".
  - "(Domain Spell)" / "(Circle Spell)" / "(Oath Spell)" -> the preceding
    subclass name is how that subclass gets the spell (subclass-specific list).
  - "(via Necromancy School )" -> subclass "Necromancer" via school feature.
  - "(via Pact of the Tome ...)" -> Warlock Pact of the Tome feature.
  - Multi-name entries ("Eldritch Knight and Arcane Trickster") split.
"""
from __future__ import annotations
import json
import os
import re
import sys
from html import unescape

RAW_DIR = r"E:\Seal\bg3\raw_spells"
OUT = r"E:\Seal\bg3\data\spell_classes.json"

# Section terminators that end the "Classes" field entirely.
# Ordered roughly by how early they appear. "Used by creatures:" must terminate
# before NPC names leak in as fake class entries.
SECTION_TERMINATORS = (
    "Granted by features:",
    "Granted by items:",
    "Other ways to learn:",
    "Used by creatures:",
    "Races:",
    "Notes",
    "Bugs",
    "External links",
    "Sources",
    "See also",
    "Spotted an issue",
    "Retrieved from",
    "Categories :",
    "Categories:",
    "Navigation menu",
)

# Core class names (used to identify a bare class entry among mixed text).
CORE_CLASSES = {
    "Cleric", "Wizard", "Sorcerer", "Warlock", "Bard",
    "Druid", "Paladin", "Ranger", "Fighter", "Rogue", "Monk",
}


def strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text


def extract_classes_section(text: str) -> str | None:
    """Return the raw text of the Classes field, or None if absent."""
    idx = text.find("Classes:")
    if idx == -1:
        # try "Classes :" or "Classes" followed by colon variants
        m = re.search(r"\bClasses\b\s*:", text)
        if not m:
            return None
        idx = m.start()
    # start after "Classes" + colon
    rest = text[idx:]
    # strip leading "Classes:"
    rest = re.sub(r"^Classes\s*:\s*", "", rest)
    # find earliest terminator
    end = len(rest)
    for term in SECTION_TERMINATORS:
        # match as a token boundary
        for m in re.finditer(re.escape(term), rest):
            # ensure preceded by space or start
            pos = m.start()
            if pos == 0 or rest[pos - 1] == " ":
                if pos < end:
                    end = pos
                break
    return rest[:end].strip()


def split_level_chunks(section: str) -> list[tuple[int, str]]:
    """Split the Classes section into (level, content) pairs.

    Pattern: 'Class level N: <content>' where content runs until the next
    'Class level' or end.
    """
    # find all 'Class level <n>:' markers
    markers = list(re.finditer(r"Class level (\d+)\s*:", section))
    if not markers:
        return []
    chunks = []
    for i, m in enumerate(markers):
        lvl = int(m.group(1))
        start = m.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(section)
        content = section[start:end].strip()
        chunks.append((lvl, content))
    return chunks


def split_entries(content: str) -> list[str]:
    """Split a level's content into individual entry strings.

    Entries are comma- or 'and'-separated, but parentheses protect commas
    inside annotations. We split on commas/and only at paren-depth 0.
    """
    entries = []
    depth = 0
    buf = []
    i = 0
    while i < len(content):
        c = content[i]
        if c == "(":
            depth += 1
            buf.append(c)
        elif c == ")":
            depth = max(0, depth - 1)
            buf.append(c)
        elif depth == 0 and c == ",":
            entries.append("".join(buf).strip())
            buf = []
        elif depth == 0 and content[i:i + 5].lower() == " and ":
            entries.append("".join(buf).strip())
            buf = []
            i += 4  # skip "and " (loop adds 1)
        else:
            buf.append(c)
        i += 1
    last = "".join(buf).strip()
    if last:
        entries.append(last)
    return [e for e in entries if e]


def parse_entry(entry: str, level: int) -> list[dict]:
    """Parse one comma/and entry into one or more class dicts.

    An entry may be:
      - bare core class: "Cleric"
      - bare subclass: "Circle of the Spores"
      - class + subclass: "Cleric and Life Domain (Domain Spell)"
        -> actually split into two entries by split_entries; but
        "Eldritch Knight and Arcane Trickster" also splits.
      - class with annotation: "Warlock (via Pact of the Tome once per long rest)"
      - subclass with annotation: "College of Lore (via Magical Secrets )"
      - "Necromancer (via Necromancy School )"
    """
    results = []
    # capture annotation in trailing parentheses
    paren_match = re.search(r"\s*\(([^)]*)\)\s*$", entry)
    annotation = paren_match.group(1).strip() if paren_match else ""
    name = entry[: paren_match.start()].strip() if paren_match else entry.strip()

    # The name could itself contain " and " if split_entries didn't catch it
    # (it should have, but guard anyway). Also handle "X and Y" joined by
    # the same annotation rare cases.
    # We rely on split_entries for the main and-splitting; here name is a
    # single token phrase.

    via = None
    if annotation:
        low = annotation.lower()
        if "magical secrets" in low:
            via = "Magical Secrets"
        elif "necromancy school" in low:
            via = "Necromancy School"
        elif "pact of the tome" in low:
            via = "Pact of the Tome"
        elif "domain spell" in low:
            via = "Domain Spell"
        elif "circle spell" in low:
            via = "Circle Spell"
        elif "oath spell" in low:
            via = "Oath Spell"
        elif "nature spell" in low:
            via = "Nature Spell"
        # else: unknown annotation, leave via=None

    entry_obj = {"class": name, "level": level}
    if via:
        entry_obj["via"] = via
    results.append(entry_obj)
    return results


def resolve_class(raw_name: str, via: str | None) -> str:
    """Normalize the class field. Subclasses map to their parent class for
    the 'class' key, but we also record subclass separately.

    Per task spec the output is {class, level} (plus via). The user asked to
    keep subclass names. We'll store the raw class/subclass name in 'class'
    and add a 'subclass' field only when it is a known subclass pattern, and
    a 'core_class' field for the parent. This keeps the spec shape
    ({class, level}) while preserving subclass info.
    """
    return raw_name  # keep verbatim; subclass detection done separately


def is_subclass(name: str) -> tuple[bool, str]:
    """If name is a subclass, return (True, parent_core_class)."""
    n = name.strip()
    # Known subclass prefixes / names -> parent class
    subclass_map = [
        # Cleric domains
        (re.compile(r"^(Life Domain|Death Domain|Tempest Domain|Light Domain|Nature Domain|Knowledge Domain|Trickery Domain|War Domain|Arcana Domain|Forge Domain|Grave Domain|Twilight Domain|Order Domain|Peace Domain|Silence Domain)$"), "Cleric"),
        # Druid circles
        (re.compile(r"^Circle of (the Spores|the Land|the Moon|the Shepherd|the Stars|Dreams|Spores|Land|Moon)$"), "Druid"),
        # Bard colleges
        (re.compile(r"^College of (Lore|Valor|Swords|Whispers|Glamour|Eloquence|Spirits|Creation|Tragedy|Dance|Lore)$"), "Bard"),
        # Paladin oaths
        (re.compile(r"^(Oath of (Devotion|Vengeance|the Ancients|Breaker|Conquest|Redemption|the Crown|the Watchers|Glory|Heroism|Ancients)|Oathbreaker)$"), "Paladin"),
        # Ranger archetypes
        (re.compile(r"^(Hunter|Gloom Stalker|Beast Master|Fey Wanderer|Horizon Walker|Swarmkeeper|Monster Slayer)$"), "Ranger"),
        # Fighter archetypes
        (re.compile(r"^(Eldritch Knight|Battle Master|Champion|Arcane Archer|Cavalier|Samurai|Purple Dragon Knight|Rune Knight|Psi Warrior|Echo Knight)$"), "Fighter"),
        # Rogue archetypes
        (re.compile(r"^(Arcane Trickster|Thief|Assassin|Swashbuckler|Scout|Inquisitive|Mastermind|Phantom|Soulknife)$"), "Rogue"),
        # Monk archetypes (wiki uses "Way of Shadow" without "the")
        (re.compile(r"^Way of (the )?(Open Hand|Shadow|Four Elements|Sun Soul|Drunken Master|Kensei|Mercy|Astral Self|Ascendant Dragon)$"), "Monk"),
        # Wizard schools (incl. "X School" feature annotation variants)
        (re.compile(r"^(Necromancer|Abjurer|Conjurer|Diviner|Enchanter|Evoker|Illusionist|Transmuter|War Magic|Bladesinger|Chronurgy|Graviturgy|Scribes|Order of Scribes)$"), "Wizard"),
        (re.compile(r"^(Abjuration|Conjuration|Divination|Enchantment|Evocation|Illusion|Transmutation|Necromancy) School$"), "Wizard"),
        # Sorcerer origins
        (re.compile(r"^(Draconic Bloodline|Wild Magic|Storm Sorcery|Divine Soul|Shadow Magic|Aberrant Mind|Clockwork Soul)$"), "Sorcerer"),
        # Warlock patrons (The Archfey / The Fiend / The Great Old One / The Hexblade etc.)
        (re.compile(r"^(The Hexblade|The Fiend|The Great Old One|The Archfey|Archfey|Genie|Undead|Undying|Celestial|Fathomless|Hexblade)$"), "Warlock"),
        # Barbarian subclasses (Giant / Wildheart) — Barbarian not in core spellcaster
        # list but captured for completeness.
        (re.compile(r"^(Giant|Wildheart|Berserker|Wild Magic|Zealot|Storm Herald|Beast|Ancestral Guardian)$"), "Barbarian"),
    ]
    for pat, parent in subclass_map:
        if pat.match(n):
            return True, parent
    return False, ""


def parse_spell_file(path: str) -> tuple[str | None, list[dict]]:
    """Return (spell_name, list_of_class_entries) for one HTML file."""
    with open(path, encoding="utf-8") as f:
        html = f.read()
    text = strip_tags(html)

    # Spell name: try <title> or first H1
    title_match = re.search(r"<title>([^<]+)</title>", html)
    spell_name = None
    if title_match:
        t = unescape(title_match.group(1)).strip()
        # bg3.wiki titles look like "Spell name - bg3.wiki"
        t = re.sub(r"\s*-\s*bg3\.wiki\s*$", "", t, flags=re.IGNORECASE)
        # strip disambiguation suffixes like "(spell)" / "(Cantrip)"
        t = re.sub(r"\s*\((spell|cantrip)\)\s*$", "", t, flags=re.IGNORECASE)
        spell_name = t.strip()
    if not spell_name:
        h1 = re.search(r"<h1[^>]*>([^<]+)</h1>", html)
        if h1:
            spell_name = unescape(h1.group(1)).strip()

    section = extract_classes_section(text)
    if not section:
        return spell_name, []

    chunks = split_level_chunks(section)
    entries: list[dict] = []
    for level, content in chunks:
        for raw_entry in split_entries(content):
            if not raw_entry:
                continue
            for e in parse_entry(raw_entry, level):
                # enrich with subclass info
                name = e["class"]
                is_sub, parent = is_subclass(name)
                if is_sub:
                    e["subclass"] = name
                    e["core_class"] = parent
                elif name in CORE_CLASSES:
                    e["core_class"] = name
                entries.append(e)
    return spell_name, entries


def main():
    files = sorted(
        f for f in os.listdir(RAW_DIR)
        if f.lower().endswith(".html")
    )
    print(f"Found {len(files)} HTML files", file=sys.stderr)

    mapping: dict[str, list[dict]] = {}
    no_classes: list[str] = []
    errors: list[str] = []

    for fn in files:
        path = os.path.join(RAW_DIR, fn)
        try:
            name, entries = parse_spell_file(path)
        except Exception as ex:  # noqa: BLE001
            errors.append(f"{fn}: {ex}")
            continue
        if name is None:
            name = os.path.splitext(fn)[0]
        if not entries:
            no_classes.append(name)
            continue
        mapping[name] = entries

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2, sort_keys=True)

    # Report
    print(f"\n=== REPORT ===")
    print(f"Total HTML files processed: {len(files)}")
    print(f"Spells WITH Classes field (in mapping): {len(mapping)}")
    print(f"Spells WITHOUT Classes field: {len(no_classes)}")
    if errors:
        print(f"Errors: {len(errors)}")
        for e in errors:
            print(f"  {e}")

    # Class distribution: count unique (class) per spell where core_class set
    from collections import Counter
    dist = Counter()
    subclass_dist = Counter()
    via_dist = Counter()
    for spell, entries in mapping.items():
        seen_core = set()
        for e in entries:
            core = e.get("core_class")
            if core:
                seen_core.add(core)
            if "subclass" in e:
                subclass_dist[e["subclass"]] += 1
            if "via" in e:
                via_dist[e["via"]] += 1
        for c in seen_core:
            dist[c] += 1

    print("\n=== CORE CLASS DISTRIBUTION (spells per core class) ===")
    for cls, n in sorted(dist.items(), key=lambda x: -x[1]):
        print(f"  {cls}: {n}")

    print("\n=== SUBCLASS DISTRIBUTION (entries per subclass) ===")
    for cls, n in sorted(subclass_dist.items(), key=lambda x: -x[1]):
        print(f"  {cls}: {n}")

    print("\n=== VIA MECHANISM DISTRIBUTION (entries) ===")
    for v, n in sorted(via_dist.items(), key=lambda x: -x[1]):
        print(f"  {v}: {n}")

    print("\n=== SPELLS WITHOUT CLASSES FIELD ===")
    for s in no_classes:
        print(f"  {s}")

    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
