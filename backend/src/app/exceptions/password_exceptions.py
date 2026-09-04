from app.exceptions.base_exceptions import NotFoundError, ValidationError

from .base_exceptions import ServiceError


class PasswordUnmodifiedError(ServiceError):
    """Signal that an unmodified password was provided during a password update."""

    def __init__(self, exc: Exception | None = None):
        """Initialize an unmodified password error.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "New password cannot be the same as the current one."
        super().__init__(msg, exc)


class PasswordIsWrongError(ValidationError):
    """Signal that a wrong password was provided."""

    def __init__(self, exc: Exception | None = None):
        """Initialize an PasswordIsWrongError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "The provided password is wrong."
        super().__init__(msg, exc)


class InvalidEmailOrPasswordError(ValidationError):
    """Signal that a login attempt carried an email or a password that does not check out.

    Deliberately does not say which of the two was wrong: telling an unknown address apart from a wrong
    password turns the login endpoint into a way of asking whether an address has an account here.
    """

    def __init__(self, exc: Exception | None = None):
        """Initialize an InvalidEmailOrPasswordError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "Incorrect email or password."
        super().__init__(msg, exc)


class InvalidCredentialsError(ValidationError):
    """Signal that invalid credentials were provided."""

    def __init__(self, exc: Exception | None = None):
        """Initialize an InvalidCredentialsError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "Could not validate credentials."
        super().__init__(msg, exc)


class PasswordResetNotFoundError(NotFoundError):
    """Signal that a password reset was not found."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize a PasswordResetNotFoundError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Password reset request", message, exc)


class PasswordResetTokenNotValidError(ValidationError):
    """Signal that the password reset token is not valid."""

    def __init__(self, exc: Exception | None = None):
        """Initialize a PasswordResetTokenNotValidError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "The password reset token is not valid."
        super().__init__(msg, exc)


class PasswordResetExpiredError(ServiceError):
    """Signal that the password reset has expired."""

    def __init__(self, exc: Exception | None = None):
        """Initialize a PasswordResetExpiredError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "The password reset has expired."
        super().__init__(msg, exc)


class PasswordResetUsedError(ServiceError):
    """Signal that the password reset has already been used."""

    def __init__(self, exc: Exception | None = None):
        """Initialize a PasswordResetUsedError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "The password reset has already been used."
        super().__init__(msg, exc)
