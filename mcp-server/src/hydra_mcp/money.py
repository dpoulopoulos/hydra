from decimal import Decimal, InvalidOperation

from mcp.server.mcpserver.exceptions import ToolError

# Hydra stores money as an integer count of minor units. Almost every currency
# it can hold has two of them; the exceptions are listed rather than guessed,
# because rounding a yen to two decimals is not a rounding error, it is a
# hundredfold one.
MINOR_UNIT_EXPONENTS = {
    "JPY": 0,
    "KRW": 0,
    "ISK": 0,
    "CLP": 0,
    "VND": 0,
    "BHD": 3,
    "JOD": 3,
    "KWD": 3,
    "OMR": 3,
    "TND": 3,
}
DEFAULT_MINOR_UNIT_EXPONENT = 2

SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "JPY": "¥", "CHF": "CHF "}


def exponent_of(currency_code: str) -> int:
    """How many decimal places a currency has.

    Args:
        currency_code: The ISO 4217 code.

    Returns:
        The number of decimal places.
    """
    return MINOR_UNIT_EXPONENTS.get(currency_code.upper(), DEFAULT_MINOR_UNIT_EXPONENT)


def to_major(amount_minor: int, currency_code: str) -> str:
    """Render a stored amount as the number a person would write.

    Args:
        amount_minor: The amount, as hydra stores it.
        currency_code: The currency it is in.

    Returns:
        The amount in major units, with the currency's own number of decimals.
    """
    exponent = exponent_of(currency_code)
    return f"{Decimal(amount_minor).scaleb(-exponent):.{exponent}f}"


def to_minor(amount: str | float | Decimal, currency_code: str) -> int:
    """Read an amount a caller wrote and turn it into what hydra stores.

    More precision than the currency has is refused rather than rounded away.
    A caller that wrote 10.005 has made a mistake, and saying so puts it where
    it can be corrected, where a silent round would hide it until somebody
    reconciled a statement.

    Args:
        amount: The amount in major units.
        currency_code: The currency it is in.

    Returns:
        The amount as an integer count of minor units.

    Raises:
        ToolError: If the amount is not a number, is negative, or carries more
            decimal places than the currency has.
    """
    try:
        value = Decimal(str(amount))
    except InvalidOperation:
        raise ToolError(f"'{amount}' is not an amount. Write it in major units, for example 42.50.") from None

    if not value.is_finite():
        raise ToolError(f"'{amount}' is not an amount. Write it in major units, for example 42.50.")

    if value < 0:
        raise ToolError(
            f"An amount is always positive: {amount} is not one. "
            "The direction is carried by the kind of transaction, never by a minus sign."
        )

    exponent = exponent_of(currency_code)
    scaled = value.scaleb(exponent)
    if scaled != scaled.to_integral_value():
        places = "whole numbers" if exponent == 0 else f"{exponent} decimal places"
        raise ToolError(f"{currency_code} amounts go to {places}, so {amount} cannot be recorded exactly.")

    return int(scaled)


def display(amount_minor: int, currency_code: str, *, negative: bool = False) -> str:
    """Render an amount for somebody to read.

    This is the one place a sign is applied, from what the caller says the
    amount means, so a model reading the result cannot invent one.

    Args:
        amount_minor: The amount, as hydra stores it.
        currency_code: The currency it is in.
        negative: Whether the amount is money going out.

    Returns:
        The amount with its currency and, if it is going out, a minus sign.
    """
    symbol = SYMBOLS.get(currency_code.upper(), f"{currency_code.upper()} ")
    sign = "-" if negative and amount_minor != 0 else ""
    return f"{sign}{symbol}{to_major(abs(amount_minor), currency_code)}"


def signed_display(amount_minor: int, currency_code: str) -> str:
    """Render an already signed total, such as a net figure.

    Unlike a single transaction, a total is genuinely negative when more went
    out than came in, so its own sign is kept rather than supplied.

    Args:
        amount_minor: The total, as hydra stores it.
        currency_code: The currency it is in.

    Returns:
        The total with its currency and its own sign.
    """
    return display(amount_minor, currency_code, negative=amount_minor < 0)


def money(amount_minor: int, currency_code: str, *, negative: bool = False) -> dict[str, object]:
    """Describe an amount every way a caller might need it.

    The string is what a reader should quote, the integer is what arithmetic
    should use, and the currency is always stated rather than assumed.

    Args:
        amount_minor: The amount, as hydra stores it.
        currency_code: The currency it is in.
        negative: Whether the amount is money going out.

    Returns:
        The amount, its display form, its exact minor units and its currency.
    """
    return {
        "amount": to_major(abs(amount_minor), currency_code),
        "display": display(amount_minor, currency_code, negative=negative),
        "amount_minor": amount_minor,
        "currency": currency_code.upper(),
    }
