from app.exceptions import CategoryInUseError


def test_says_the_category_is_in_use() -> None:
    error = CategoryInUseError(name="Coffee")

    assert "Coffee" in str(error)
    assert "Archive it instead" in str(error)


def test_names_what_is_blocking_the_delete() -> None:
    error = CategoryInUseError(name="Coffee", reason="has transactions filed under it")

    assert "Coffee' still has transactions filed under it." in str(error)
    assert "Archive it instead" in str(error)
