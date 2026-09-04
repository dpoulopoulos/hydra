from app.data import DEFAULT_CATEGORIES, SYSTEM_CATEGORY_NAME


def test_every_parent_has_a_unique_name() -> None:
    names = [category.name for category in DEFAULT_CATEGORIES]
    assert len(names) == len(set(names))


def test_every_parent_has_children() -> None:
    assert all(category.children for category in DEFAULT_CATEGORIES)


def test_sibling_names_are_unique_within_a_parent() -> None:
    for category in DEFAULT_CATEGORIES:
        assert len(category.children) == len(set(category.children))


def test_there_is_exactly_one_income_parent() -> None:
    income = [category for category in DEFAULT_CATEGORIES if category.is_income]
    assert [category.name for category in income] == ["Income"]


def test_there_is_exactly_one_system_parent() -> None:
    system = [category for category in DEFAULT_CATEGORIES if category.is_system]
    assert [category.name for category in system] == [SYSTEM_CATEGORY_NAME]


def test_the_system_parent_holds_the_fallback_category() -> None:
    system = next(category for category in DEFAULT_CATEGORIES if category.is_system)
    assert system.children == ("Uncategorized",)


def test_the_recurring_examples_have_a_home() -> None:
    """Rent and subscriptions are the two named recurring cases, so they must land somewhere."""
    pairs = {(parent.name, child) for parent in DEFAULT_CATEGORIES for child in parent.children}
    assert ("Housing", "Rent / Mortgage") in pairs
    assert ("Entertainment", "Subscriptions") in pairs
