from .base_exceptions import ValidationError


class InvalidDateRangeError(ValidationError):
    """Signal that a report range starts after it ends."""

    def __init__(self, exc: Exception | None = None):
        """Initialize an InvalidDateRangeError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "The start of the range must come before its end."
        super().__init__(msg, exc)


class ReportRangeTooLargeError(ValidationError):
    """Signal that a report range would return an unreasonable number of buckets."""

    def __init__(self, limit: str, exc: Exception | None = None):
        """Initialize a ReportRangeTooLargeError.

        Args:
            limit: The largest range the report accepts, in words.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = f"That range is too large for this report. Ask for at most {limit}."
        super().__init__(msg, exc)
        self.limit = limit
