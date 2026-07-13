from mia_docs.extraction.recipe import split_recipes


def test_detects_two_recipes(sample_pages):
    blocks = split_recipes(sample_pages)
    titles = [b.title for b in blocks]
    assert titles == ["Saffron Rice Pilaf", "Lemon Garlic Chicken"]


def test_page_ranges(sample_pages):
    blocks = split_recipes(sample_pages)
    assert blocks[0].page_start == 1
    assert blocks[1].page_start == 2


def test_prose_page_not_a_recipe(sample_pages):
    blocks = split_recipes(sample_pages)
    assert all("Author" not in b.title for b in blocks)


def test_confidence_high_with_multiple_anchors(sample_pages):
    blocks = split_recipes(sample_pages)
    assert all(b.extraction_confidence == "high" for b in blocks)


def test_low_confidence_block():
    from mia_docs.extraction.pdf import PageText

    pages = [
        PageText(
            page_no=1,
            text="Mystery Dish\n\nIngredients:\nsome flour\nsome water\n",
        )
    ]
    blocks = split_recipes(pages)
    assert len(blocks) == 1
    assert blocks[0].extraction_confidence == "low"
