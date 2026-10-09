from .base_exceptions import NotFoundError, ServiceError, ValidationError


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


class AspspNotFoundError(ValidationError):
    """Signal that the bank asked for is not one Enable Banking can reach."""

    def __init__(self, name: str, country: str, exc: Exception | None = None):
        """Initialize an AspspNotFoundError.

        Args:
            name: The bank's name, as given.
            country: The bank's country, as given.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__(f"No bank called '{name}' can be connected in {country}.", exc)


class BankConnectionNotFoundError(NotFoundError):
    """Signal that a bank connection does not exist in the household."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize a BankConnectionNotFoundError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Bank connection", message, exc)


class BankAccountNotFoundError(NotFoundError):
    """Signal that a bank account does not exist in the household."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize a BankAccountNotFoundError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Bank account", message, exc)


class BankConnectionNotPermittedError(ServiceError):
    """Signal that only whoever connected a bank, or an owner, may disconnect it."""

    def __init__(self, exc: Exception | None = None):
        """Initialize a BankConnectionNotPermittedError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Only whoever connected this bank, or a household owner, can disconnect it.", exc)


class BankConnectionInactiveError(ValidationError):
    """Signal that a connection cannot be used because its login is not active."""

    def __init__(self, exc: Exception | None = None):
        """Initialize a BankConnectionInactiveError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("This bank connection is not active. Connect the bank again.", exc)


class BankAccountMappingError(ValidationError):
    """Signal that a bank account cannot feed the Hydra account, or from that date."""

    def __init__(self, message: str, exc: Exception | None = None):
        """Initialize a BankAccountMappingError.

        Args:
            message: Why the mapping was refused.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__(message, exc)


class BankAccountAlreadyMappedError(ServiceError):
    """Signal that the Hydra account is already fed by another bank account."""

    def __init__(self, exc: Exception | None = None):
        """Initialize a BankAccountAlreadyMappedError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Another bank account already feeds this account. Unlink that one first.", exc)
