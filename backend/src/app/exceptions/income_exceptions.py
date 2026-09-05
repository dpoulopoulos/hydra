from .base_exceptions import ConflictError, NotFoundError, ServiceError, ValidationError


class IncomeClientNotFoundError(NotFoundError):
    """Signal that a client does not exist in the household."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize an IncomeClientNotFoundError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Client", message, exc)


class IncomeSessionNotFoundError(NotFoundError):
    """Signal that a session does not exist in the household."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize an IncomeSessionNotFoundError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Session", message, exc)


class IncomeVaultNotFoundError(NotFoundError):
    """Signal that the household has not set up a PIN for client names yet."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize an IncomeVaultNotFoundError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Client name key", message, exc)


class IncomeVaultExistsError(ConflictError):
    """Signal that the household already has a key, so setting one up would replace it."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize an IncomeVaultExistsError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Client name key", "household", message, exc)


class IncomeClientInUseError(ServiceError):
    """Signal that a client cannot be deleted because sessions still reference them.

    A conflict, but not the "already exists" kind ConflictError describes, so
    the message is written out rather than composed from that template.
    """

    def __init__(self, exc: Exception | None = None):
        """Initialize an IncomeClientInUseError.

        The client's name is deliberately absent from the message. It is stored
        encrypted and unreadable here, and an error string is the last place it
        should ever surface.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "This client still has sessions. Archive them instead, so the record of the work is kept."
        super().__init__(msg, exc)


class SessionPaymentDateError(ValidationError):
    """Signal that the payment date and the payment status disagree.

    A paid session has a date the money arrived; an unpaid one cannot have one.
    The database enforces this as well, but reaching it would be a 500 where a
    422 belongs.
    """

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize a SessionPaymentDateError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = message or "A paid session needs the date the money arrived, and an unpaid one cannot have one."
        super().__init__(msg, exc)


class IncomeClientNotOwnedError(ServiceError):
    """Signal that a client belongs to another member of the household.

    Not a 404: the row is visible to everyone in the household, because the
    sessions and the money are shared. It is the name that is private, and only
    the person whose key it is under can change it.
    """

    def __init__(self, exc: Exception | None = None):
        """Initialize an IncomeClientNotOwnedError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "This client belongs to another member of the household. Only they can change or remove them."
        super().__init__(msg, exc)


class ClientCadenceError(ValidationError):
    """Signal that a client's schedule is only half described.

    "Every week" says nothing without a date to pin it to, and a date pins
    nothing without a frequency. The database enforces the same rule, so this
    exists to turn it into a clear message rather than an integrity error.
    """

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize a ClientCadenceError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = message or "A repeating client needs both how often you see them and the day it started."
        super().__init__(msg, exc)
