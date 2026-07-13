"""Ingredient canonicalization (rapidfuzz clustering) and technique vocab."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

# Hand-maintained technique vocabulary, matched by keyword in instructions.
TECHNIQUE_VOCAB: dict[str, list[str]] = {
    "braise": ["braise", "braising", "braised"],
    "saute": ["saute", "sauté", "sautee", "sautéed", "sauteed"],
    "roast": ["roast", "roasting", "roasted"],
    "bake": ["bake", "baking", "baked"],
    "grill": ["grill", "grilling", "grilled"],
    "fry": ["fry", "frying", "fried", "deep-fry", "pan-fry"],
    "boil": ["boil", "boiling", "boiled"],
    "simmer": ["simmer", "simmering", "simmered"],
    "steam": ["steam", "steaming", "steamed"],
    "poach": ["poach", "poaching", "poached"],
    "broil": ["broil", "broiling", "broiled"],
    "marinate": ["marinate", "marinating", "marinated", "marinade"],
    "whisk": ["whisk", "whisking", "whisked"],
    "knead": ["knead", "kneading", "kneaded"],
    "blanch": ["blanch", "blanching", "blanched"],
    "caramelize": ["caramelize", "caramelizing", "caramelized"],
    "reduce": ["reduce the", "reduction", "reduce until"],
    "sear": ["sear", "searing", "seared"],
}

_PAREN_RE = re.compile(r"\([^)]*\)")
_DESCRIPTOR_RE = re.compile(
    r"\b(fresh|freshly|large|small|medium|finely|coarsely|roughly|thinly|"
    r"chopped|minced|diced|sliced|grated|shredded|ground|melted|softened|"
    r"optional|to taste|divided|plus more|for serving|for garnish)\b",
    re.IGNORECASE,
)


def normalize_ingredient(name: str) -> str:
    s = _PAREN_RE.sub("", name.lower())
    s = _DESCRIPTOR_RE.sub("", s)
    s = re.sub(r"[^a-z\s-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" ,-")
    # naive singularization: only trailing plain 's' on the last word
    words = s.split()
    if words and len(words[-1]) > 3 and words[-1].endswith("s") and not words[-1].endswith("ss"):
        words[-1] = words[-1][:-1]
    return " ".join(words)


def build_alias_table(names: list[str], threshold: float = 90.0) -> dict[str, str]:
    """Cluster normalized ingredient names by rapidfuzz similarity.

    Returns {normalized_name: canonical_name} where the canonical is the
    shortest member of each cluster (usually the base ingredient).
    """
    canon: dict[str, str] = {}
    clusters: list[list[str]] = []
    for name in sorted({normalize_ingredient(n) for n in names if n}):
        if not name:
            continue
        placed = False
        for cluster in clusters:
            if fuzz.token_sort_ratio(name, cluster[0]) >= threshold:
                cluster.append(name)
                placed = True
                break
        if not placed:
            clusters.append([name])
    for cluster in clusters:
        canonical = min(cluster, key=len)
        for member in cluster:
            canon[member] = canonical
    return canon


def match_techniques(steps: list[str]) -> set[str]:
    text = " ".join(steps).lower()
    found: set[str] = set()
    for canonical, keywords in TECHNIQUE_VOCAB.items():
        if any(kw in text for kw in keywords):
            found.add(canonical)
    return found
