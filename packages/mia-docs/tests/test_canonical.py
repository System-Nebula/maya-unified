from mia_docs.extraction.canonical import (
    build_alias_table,
    match_techniques,
    normalize_ingredient,
)


def test_normalize_strips_descriptors():
    assert normalize_ingredient("1 large onion, finely chopped") == "onion"
    assert normalize_ingredient("fresh parsley for garnish") == "parsley"


def test_normalize_singularizes():
    assert normalize_ingredient("chicken thighs") == "chicken thigh"


def test_alias_table_clusters_variants():
    table = build_alias_table(
        ["basmati rice", "basmati rices", "olive oil", "extra olive oil"]
    )
    assert table["basmati rice"] == "basmati rice"
    # plural variant normalizes then clusters to the same canonical
    assert table[normalize_ingredient("basmati rices")] == "basmati rice"


def test_match_techniques():
    steps = [
        "Saute the onion in butter until golden.",
        "Simmer covered for 18 minutes.",
    ]
    assert match_techniques(steps) == {"saute", "simmer"}
