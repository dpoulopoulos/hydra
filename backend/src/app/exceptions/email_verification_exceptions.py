from app.exceptions.base_exceptions import NotFoundError, ValidationError

from .base_exceptions import ServiceError


class EmailVerificationNotFoundError(NotFoundError):
    """Signal that an email verification was not found."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize an EmailVerificationNotFoundError.

        Args:
            message: An optional custom message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Email verification", message, exc)


class EmailVerificationTokenNotValidError(ValidationError):
    """Signal that the email verification token is not valid."""

    def __init__(self, exc: Exception | None = None):
        """Initialize an EmailVerificationTokenNotValidError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "The email verification token is not valid."
        super().__init__(msg, exc)


class EmailVerificationExpiredError(ServiceError):
    """Signal that the email verification has expired."""

    def __init__(self, exc: Exception | None = None):
        """Initialize an EmailVerificationExpiredError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "The email verification has expired."
        super().__init__(msg, exc)


class EmailVerificationUsedError(ServiceError):
    """Signal that the email verification has already been used."""

    def __init__(self, exc: Exception | None = None):
        """Initialize an EmailVerificationUsedError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "The email verification has already been used."
        super().__init__(msg, exc)
