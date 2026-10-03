from .base_exceptions import ConflictError, NotFoundError, ServiceError, ValidationError


class GoalNotFoundError(NotFoundError):
    """Signal that a goal does not exist in the household."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize a GoalNotFoundError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Goal", message, exc)


class GoalExistsError(ConflictError):
    """Signal that the household already has a goal with that name."""

    def __init__(self, identifier: str, message: str | None = None, exc: Exception | None = None):
        """Initialize a GoalExistsError.

        Args:
            identifier: The name that is already taken.
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Goal", identifier, message, exc)


class GoalAccountNotSavingsError(ValidationError):
    """Signal that a goal can only live in a savings account."""

    def __init__(self, name: str, exc: Exception | None = None):
        """Initialize a GoalAccountNotSavingsError.

        Args:
            name: The name of the account.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = f"'{name}' is not a savings account. A goal needs a savings account to hold its money."
        super().__init__(msg, exc)


class GoalAccountLockedError(ServiceError):
    """Signal that a goal cannot move to another account once money is tagged to it.

    The tagged transfers name the old account. Moving the goal would leave them
    pointing at an account the goal no longer lives in, and the money would
    silently stop counting.
    """

    def __init__(self, exc: Exception | None = None):
        """Initialize a GoalAccountLockedError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "Transfers are already tagged with this goal, so it cannot move to another account."
        super().__init__(msg, exc)


class GoalTransferMismatchError(ValidationError):
    """Signal that a transaction cannot be tagged with that goal."""

    def __init__(self, message: str, exc: Exception | None = None):
        """Initialize a GoalTransferMismatchError.

        Args:
            message: Why the tag does not fit.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__(message, exc)
