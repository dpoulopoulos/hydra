from app.models.user import User

from .base_exceptions import ConflictError, NotFoundError, ServiceError


class UserExistsError(ConflictError):
    """Signal that a user already exists in the database."""

    def __init__(self, user: User, message: str | None = None, exc: Exception | None = None):
        """Initialize a UserExistsError.

        Args:
            user: The user information.
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("User", user.email, message, exc)


class UserNotFoundError(NotFoundError):
    """Signal that a user does not exist in the database."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize a UserNotFoundError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("User", message, exc)


class UserNotAuthorizedError(ServiceError):
    """Signal that a user is not authorized to perform an action."""

    def __init__(self, user: User, exc: Exception | None = None):
        """Initialize a UserNotAuthorizedError.

        Args:
            user: The user that is not authorized.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = f"User with email '{user.email}' doesn't have enough privileges to perform this action."
        super().__init__(msg, exc)


class UserNotActiveError(ServiceError):
    """Signal that a user is not active."""

    def __init__(self, user: User, exc: Exception | None = None, is_verified: bool = True):
        """Initialize a UserNotActiveError.

        Args:
            user: The user that is not active.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
            is_verified: If False, indicates the account is inactive because email is not verified.
        """
        if not is_verified:
            msg = (
                "Please verify your email address to activate your account. Check your inbox for the verification link."
            )
        else:
            msg = f"User with email {user.email} is not active."
        super().__init__(msg, exc)
        self.is_verified = is_verified


class DeleteSuperUserError(ServiceError):
    """Signal that a super user tried to delete themselves."""

    def __init__(self, exc: Exception | None = None):
        """Initialize a delete super user error.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "Superuser accounts cannot be deleted."
        super().__init__(msg, exc)
