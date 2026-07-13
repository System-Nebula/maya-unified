"""Rule-based recipe boundary detection and field parsing (zero LLM)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mia_docs.extraction.pdf import PageText

ANCHOR_RE = re.compile(
    r"^\s*(ingredients?|serves|servings?|prep\s*time|cook\s*time|total\s*time|"
    r"directions?|instructions?|method|how\s+to\s+make|steps|preparation)\s*:?\s*(.*)$",
    re.IGNORECASE,
)

# Anchor kinds grouped for confidence scoring: a real recipe block should hit
# at least 2 of these 4 families.
_ANCHOR_FAMILY = {
    "ingredient": "ingredients",
    "ingredients": "ingredients",
    "serves": "servings",
    "serving": "servings",
    "servings": "servings",
    "prep time": "time",
    "cook time": "time",
    "total time": "time",
    "direction": "steps",
    "directions": "steps",
    "instruction": "steps",
    "instructions": "steps",
    "method": "steps",
    "how to make": "steps",
    "steps": "steps",
    "preparation": "steps",
}

# Boilerplate lines that look like headings but never are recipe titles.
_TITLE_STOPLIST_RE = re.compile(
    r"table of contents|macros per serving|^\s*\d+\s*g?\s*(calories|protein|carbs|fat)\b"
    r"|^(notes?|tips?|chapter \d+)$",
    re.IGNORECASE,
)

_QTY_RE = re.compile(
    r"^([\d./½¼¾⅓⅔⅛\s-]+)\s*"
    r"(cups?|tbsps?|tablespoons?|tsps?|teaspoons?|oz|ounces?|lbs?|pounds?|"
    r"g|grams?|kg|ml|l|liters?|cloves?|cans?|pinch|dash)?\.?\s+(.+)$",
    re.IGNORECASE,
)

_BULLET_RE = re.compile(r"^\s*(?:[-*•·▢◻□☐]|\d+[.)])\s*")
_INT_RE = re.compile(r"(\d+)")

TITLE_LOOKAHEAD = 8  # lines between a heading and its 'ingredients' anchor


@dataclass
class IngredientLine:
    raw_string: str
    name: str | None = None
    quantity: str | None = None
    unit: str | None = None


@dataclass
class RecipeBlock:
    title: str
    raw_text: str
    page_start: int
    page_end: int
    ingredients: list[IngredientLine] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    servings: int | None = None
    prep_min: int | None = None
    cook_min: int | None = None
    anchor_families: set[str] = field(default_factory=set)

    @property
    def extraction_confidence(self) -> str:
        return "high" if len(self.anchor_families) >= 2 else "low"


def _anchor_family(line: str) -> str | None:
    m = ANCHOR_RE.match(line)
    if not m:
        return None
    key = re.sub(r"\s+", " ", m.group(1).lower().strip())
    return _ANCHOR_FAMILY.get(key)


def _is_title_candidate(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 80 or _anchor_family(s):
        return False
    if _BULLET_RE.match(s):
        return False
    if _TITLE_STOPLIST_RE.search(s):
        return False
    letters = sum(c.isalpha() for c in s)
    return letters >= 3


def split_recipes(pages: list[PageText]) -> list[RecipeBlock]:
    """Detect recipe boundaries: a heading followed within TITLE_LOOKAHEAD
    lines by an 'ingredients' anchor starts a new recipe."""
    lines: list[tuple[int, str]] = []
    for page in pages:
        for ln in page.text.splitlines():
            lines.append((page.page_no, ln))

    # A candidate only starts a NEW recipe if an ingredients anchor has been
    # passed since the previous accepted start — otherwise "Macros per
    # serving"-style lines between title and INGREDIENTS split one recipe
    # into several fragments.
    starts: list[int] = []
    ingredients_seen_since_start = True
    for i, (_, ln) in enumerate(lines):
        if _anchor_family(ln) == "ingredients":
            ingredients_seen_since_start = True
            continue
        if not ingredients_seen_since_start or not _is_title_candidate(ln):
            continue
        window = lines[i + 1 : i + 1 + TITLE_LOOKAHEAD]
        if any(_anchor_family(w) == "ingredients" for _, w in window):
            starts.append(i)
            ingredients_seen_since_start = False

    blocks: list[RecipeBlock] = []
    for bi, start in enumerate(starts):
        end = starts[bi + 1] if bi + 1 < len(starts) else len(lines)
        chunk = lines[start:end]
        block = _parse_block(chunk)
        if block:
            blocks.append(block)
    return blocks


def _parse_block(chunk: list[tuple[int, str]]) -> RecipeBlock | None:
    if not chunk:
        return None
    title = chunk[0][1].strip()
    raw_text = "\n".join(ln for _, ln in chunk).strip()
    block = RecipeBlock(
        title=title,
        raw_text=raw_text,
        page_start=chunk[0][0],
        page_end=chunk[-1][0],
    )

    section: str | None = None
    for _, ln in chunk[1:]:
        fam = _anchor_family(ln)
        if fam:
            block.anchor_families.add(fam)
            m = ANCHOR_RE.match(ln)
            rest = m.group(2).strip() if m else ""
            key = re.sub(r"\s+", " ", m.group(1).lower()) if m else ""
            if fam == "servings":
                block.servings = _first_int(rest or ln)
                section = None
            elif fam == "time":
                minutes = _parse_minutes(rest or ln)
                if key.startswith("prep"):
                    block.prep_min = minutes
                elif key.startswith("cook"):
                    block.cook_min = minutes
                section = None
            else:
                section = fam  # "ingredients" or "steps"
                # "Ingredients (4 servings)" carries the servings count
                sv = re.search(r"(\d+)\s*servings?", rest, re.IGNORECASE)
                if sv and block.servings is None:
                    block.servings = int(sv.group(1))
                elif rest and not sv:
                    _add_section_line(block, section, rest)
            continue
        if section:
            _add_section_line(block, section, ln)
    return block


def _add_section_line(block: RecipeBlock, section: str, ln: str) -> None:
    s = _BULLET_RE.sub("", ln).strip()
    if not s or sum(c.isalpha() for c in s) < 2:
        return
    if section == "ingredients":
        # sub-section headers ("Chicken:", "Green Sauce:") are not ingredients
        if s.endswith(":"):
            return
        block.ingredients.append(parse_ingredient(ln))
    elif section == "steps":
        block.steps.append(s)


def parse_ingredient(line: str) -> IngredientLine:
    raw = line.strip()
    s = _BULLET_RE.sub("", raw).strip()
    m = _QTY_RE.match(s)
    if not m:
        return IngredientLine(raw_string=raw, name=s or None)
    qty = m.group(1).strip() or None
    unit = m.group(2)
    return IngredientLine(
        raw_string=raw,
        quantity=qty,
        unit=unit.lower() if unit else None,
        name=m.group(3).strip(),
    )


def _first_int(text: str) -> int | None:
    m = _INT_RE.search(text)
    return int(m.group(1)) if m else None


def _parse_minutes(text: str) -> int | None:
    t = text.lower()
    hours = re.search(r"(\d+)\s*(?:hours?|hrs?|h)\b", t)
    mins = re.search(r"(\d+)\s*(?:minutes?|mins?|m)\b", t)
    if hours or mins:
        return (int(hours.group(1)) * 60 if hours else 0) + (
            int(mins.group(1)) if mins else 0
        )
    return _first_int(t)
