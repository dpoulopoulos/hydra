from .base_exceptions import ServiceError, ValidationError


class BankSyncNotConfiguredError(ServiceError):
    """Signal that bank sync is switched off, so no bank can be reached."""

    def __init__(self, exc: Exception | None = None):
        """Initialize a BankSyncNotConfiguredError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "Bank sync is not configured. Set ENABLE_BANKING_APP_ID and ENABLE_BANKING_PRIVATE_KEY to switch it on."
        super().__init__(msg, exc)


class BankProviderError(ServiceError):
    """Signal that Enable Banking, or the bank behind it, failed or refused the request."""

    def __init__(self, message: str, code: str | None = None, exc: Exception | None = None):
        """Initialize a BankProviderError.

        Args:
            message: What the provider said, or what went wrong reaching it.
            code: The provider's error code, such as "ASPSP_ERROR", when it gave one.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__(f"The bank could not be reached: {message}", exc)
        self.code = code


class BankSessionExpiredError(BankProviderError):
    """Signal that the bank login behind a connection has ended, so it has to be made again."""

    def __init__(self, code: str | None = None, exc: Exception | None = None):
        """Initialize a BankSessionExpiredError.

        Args:
            code: The provider's error code.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("the bank login has expired or was withdrawn. Connect the bank again.", code, exc)


class BankRateLimitedError(BankProviderError):
    """Signal that the bank refused a pull because too many were made today."""

    def __init__(self, code: str | None = None, exc: Exception | None = None):
        """Initialize a BankRateLimitedError.

        Args:
            code: The provider's error code.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "the bank allows only a few pulls a day, and today's are spent. Try again tomorrow."
        super().__init__(msg, code, exc)


class BankAuthorizationError(ValidationError):
    """Signal that the code the bank sent back could not be turned into a login."""

    def __init__(self, message: str, exc: Exception | None = None):
        """Initialize a BankAuthorizationError.

        Args:
            message: Why the authorization failed.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__(f"The bank login could not be completed: {message}", exc)
