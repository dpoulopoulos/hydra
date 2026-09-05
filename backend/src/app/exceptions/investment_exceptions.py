from .base_exceptions import ConflictError, NotFoundError, ServiceError, ValidationError


class InstrumentNotFoundError(NotFoundError):
    """Signal that an instrument does not exist in the household."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize an InstrumentNotFoundError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Instrument", message, exc)


class InstrumentExistsError(ConflictError):
    """Signal that the household already tracks that symbol."""

    def __init__(self, symbol: str, message: str | None = None, exc: Exception | None = None):
        """Initialize an InstrumentExistsError.

        Args:
            symbol: The conflicting ticker symbol.
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Instrument", symbol, message, exc)


class InstrumentInUseError(ServiceError):
    """Signal that an instrument cannot be deleted because it still has trades.

    A conflict, but not the "already exists" kind ConflictError describes, so
    the message is written out rather than composed from that template.
    """

    def __init__(self, symbol: str, exc: Exception | None = None):
        """Initialize an InstrumentInUseError.

        Args:
            symbol: The ticker symbol of the instrument in use.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = f"Instrument '{symbol}' still has trades. Delete them first, or keep it for the record it holds."
        super().__init__(msg, exc)
        self.symbol = symbol


class TradeNotFoundError(NotFoundError):
    """Signal that a trade does not exist in the household."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize a TradeNotFoundError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Trade", message, exc)


class InsufficientUnitsError(ValidationError):
    """Signal that a sale would leave the position holding fewer than zero units.

    Checked over the whole history rather than at the moment of the sale, since
    a trade can be back-dated or edited after later ones already exist.
    """

    def __init__(self, symbol: str, exc: Exception | None = None):
        """Initialize an InsufficientUnitsError.

        Args:
            symbol: The ticker symbol being sold.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = f"That would sell more units of '{symbol}' than the household holds on that date."
        super().__init__(msg, exc)
        self.symbol = symbol


class PriceProviderNotConfiguredError(ServiceError):
    """Signal that no price provider is set up, so prices cannot be fetched."""

    def __init__(self, exc: Exception | None = None):
        """Initialize a PriceProviderNotConfiguredError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        # Names the setting rather than the vendor. A message that names a
        # vendor goes stale the moment the vendor is swapped, and this one
        # already had: it pointed at a provider the app no longer uses.
        msg = (
            "No market data provider is configured, so prices cannot be fetched. "
            "Set EODHD_API_KEY to switch it on, or MARKET_DATA_PROVIDER if prices come from elsewhere."
        )
        super().__init__(msg, exc)


class PriceProviderError(ServiceError):
    """Signal that the market data provider failed or refused the request."""

    def __init__(self, message: str, exc: Exception | None = None):
        """Initialize a PriceProviderError.

        Args:
            message: What the provider said, or what went wrong reaching it.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__(f"The market data provider could not be reached: {message}", exc)


class InstrumentNotPriceableError(ValidationError):
    """Signal that a symbol could not be priced and no currency was given for it.

    Creating an instrument normally asks the provider what the listing quotes
    in, because that is the only place the answer is certain. When the provider
    does not recognise the symbol there are two possibilities, a typo and a
    listing it simply does not carry, and they need different answers: the
    first should be corrected, the second tracked by hand. Saying so is better
    than guessing a currency and quietly valuing the position in the wrong one.
    """

    def __init__(self, symbol: str, exc: Exception | None = None):
        """Initialize an InstrumentNotPriceableError.

        Args:
            symbol: The ticker symbol that could not be priced.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = (
            f"No price could be found for '{symbol}'. Check the symbol, including its exchange suffix, "
            "or set the currency yourself to track it by hand."
        )
        super().__init__(msg, exc)
        self.symbol = symbol


class TradeNotConvertibleError(ServiceError):
    """Signal that a trade's cash side cannot be worked out without a rate."""

    def __init__(self, currency_code: str, base_currency: str, exc: Exception | None = None):
        """Initialize a TradeNotConvertibleError.

        Args:
            currency_code: The currency the listing quotes in.
            base_currency: The currency the household keeps its accounts in.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = (
            f"This trade is in {currency_code} but the account is in {base_currency}, and no "
            f"{currency_code} rate has been fetched yet. Refresh prices, or enter what actually "
            "left the account."
        )
        super().__init__(msg, exc)


class NotABrokerageAccountError(ServiceError):
    """Signal that the far side of a trade's cash movement is not a brokerage account."""

    def __init__(self, name: str, exc: Exception | None = None):
        """Initialize a NotABrokerageAccountError.

        Args:
            name: The name of the account that was offered.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__(f"'{name}' is not a brokerage account, so a trade cannot settle into it.", exc)
