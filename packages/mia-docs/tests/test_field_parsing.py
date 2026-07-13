from mia_docs.extraction.recipe import parse_ingredient, split_recipes


def test_servings_and_times(sample_pages):
    pilaf, chicken = split_recipes(sample_pages)
    assert pilaf.servings == 4
    assert pilaf.prep_min == 10
    assert pilaf.cook_min == 25
    assert chicken.servings == 2
    assert chicken.prep_min == 75
    assert chicken.cook_min == 30


def test_ingredient_lines(sample_pages):
    pilaf, _ = split_recipes(sample_pages)
    assert len(pilaf.ingredients) == 6
    rice = pilaf.ingredients[0]
    assert rice.quantity == "2"
    assert rice.unit == "cups"
    assert rice.name == "basmati rice"


def test_steps_ordered(sample_pages):
    pilaf, _ = split_recipes(sample_pages)
    assert len(pilaf.steps) == 4
    assert pilaf.steps[0].startswith("Rinse")
    assert pilaf.steps[-1].startswith("Simmer")


def test_unparsed_ingredient_keeps_raw_string():
    ing = parse_ingredient("salt to taste")
    assert ing.raw_string == "salt to taste"
    assert ing.quantity is None


def test_unicode_fraction_quantity():
    ing = parse_ingredient("½ cup olive oil")
    assert ing.quantity == "½"
    assert ing.unit == "cup"
    assert ing.name == "olive oil"
