from app.exceptions import AccountInUseError


def test_says_the_account_is_in_use() -> None:
    error = AccountInUseError(name="Current")

    assert "Current" in str(error)
    assert "Archive it instead" in str(error)


def test_names_what_is_blocking_the_delete() -> None:
    error = AccountInUseError(name="Savings", reason="is the destination of a recurring transfer")

    assert "Savings' is the destination of a recurring transfer." in str(error)
    assert "Archive it instead" in str(error)
