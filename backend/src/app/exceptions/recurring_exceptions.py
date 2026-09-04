from .base_exceptions import NotFoundError, ValidationError


class RecurringRuleNotFoundError(NotFoundError):
    """Signal that a recurring rule does not exist in the household."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize a RecurringRuleNotFoundError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Recurring rule", message, exc)


class InvalidRecurrenceError(ValidationError):
    """Signal that a recurrence schedule does not make sense."""

    def __init__(self, message: str, exc: Exception | None = None):
        """Initialize an InvalidRecurrenceError.

        Args:
            message: What is wrong with the schedule.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__(message, exc)
