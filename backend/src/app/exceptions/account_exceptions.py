from .base_exceptions import ConflictError, NotFoundError, ServiceError, ValidationError


class AccountNotFoundError(NotFoundError):
    """Signal that an account does not exist in the household."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize an AccountNotFoundError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Account", message, exc)


class AccountExistsError(ConflictError):
    """Signal that the household already has an account with that name."""

    def __init__(self, name: str, message: str | None = None, exc: Exception | None = None):
        """Initialize an AccountExistsError.

        Args:
            name: The conflicting account name.
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Account", name, message, exc)


class AccountInUseError(ServiceError):
    """Signal that an account cannot be deleted because it still has history.

    A conflict, but not the "already exists" kind ConflictError describes, so
    the message is written out rather than composed from that template.
    """

    def __init__(self, name: str, exc: Exception | None = None):
        """Initialize an AccountInUseError.

        Args:
            name: The name of the account in use.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = f"Account '{name}' still has transactions. Archive it instead, so its history and past balances are kept."
        super().__init__(msg, exc)
        self.name = name


class AccountArchivedError(ValidationError):
    """Signal that an archived account cannot take new transactions."""

    def __init__(self, name: str, exc: Exception | None = None):
        """Initialize an AccountArchivedError.

        Args:
            name: The name of the archived account.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = f"Account '{name}' is archived. Restore it before adding transactions to it."
        super().__init__(msg, exc)
