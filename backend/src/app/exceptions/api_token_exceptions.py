from .base_exceptions import NotFoundError, ServiceError, ValidationError


class ApiTokenNotFoundError(NotFoundError):
    """Signal that an API token does not exist, or does not belong to this user."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize an ApiTokenNotFoundError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("API token", message, exc)


class InvalidApiTokenError(ValidationError):
    """Signal that a presented API token does not check out.

    Deliberately says nothing about why. Unknown, revoked, expired, a wrong
    secret and an inactive owner all answer the same way, so the response
    cannot be used to learn which tokens exist or what state one is in.
    """

    def __init__(self, exc: Exception | None = None):
        """Initialize an InvalidApiTokenError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("The API token is not valid.", exc)


class ApiTokenReadOnlyError(ServiceError):
    """Signal that a read scoped token attempted a request that changes data."""

    def __init__(self, exc: Exception | None = None):
        """Initialize an ApiTokenReadOnlyError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "This API token is read only and cannot change anything."
        super().__init__(msg, exc)


class ApiTokenNotPermittedError(ServiceError):
    """Signal that an operation is reachable with a session but not with an API token.

    Minting a credential, revoking one, and changing the password or the
    address behind them are the operations that would let a leaked token
    entrench itself. Those stay with the browser session.
    """

    def __init__(self, exc: Exception | None = None):
        """Initialize an ApiTokenNotPermittedError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "This action requires signing in, and cannot be done with an API token."
        super().__init__(msg, exc)


class ApiTokenLimitError(ServiceError):
    """Signal that the user already holds as many active tokens as they may."""

    def __init__(self, limit: int, exc: Exception | None = None):
        """Initialize an ApiTokenLimitError.

        Args:
            limit: The number of active tokens allowed.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = f"You already have {limit} active API tokens. Revoke one before creating another."
        super().__init__(msg, exc)
        self.limit = limit
