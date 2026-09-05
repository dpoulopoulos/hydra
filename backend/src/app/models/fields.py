from datetime import date
from typing import Annotated

from pydantic import AfterValidator, StringConstraints

# bcrypt hashes at most 72 bytes of input and rejects anything longer. Bounding
# passwords here turns an over-long password into a validation error instead of
# letting it be silently truncated, which would make every password sharing the
# first 72 bytes equivalent.
BCRYPT_MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 8


def _within_bcrypt_limit(value: str) -> str:
    """Reject a password that exceeds what bcrypt is able to hash.

    Args:
        value: The plain text password.

    Returns:
        The password, unchanged.

    Raises:
        ValueError: If the password exceeds 72 bytes once UTF-8 encoded. A
            password may be within the character limit and still exceed it,
            since non-ASCII characters encode to more than one byte.
    """
    if len(value.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes once UTF-8 encoded.")
    return value


Password = Annotated[str, AfterValidator(_within_bcrypt_limit)]


# Money is stored in minor units in a BigInteger column, which tops out at
# 2**63 - 1. Python's int is unbounded and Pydantic is happy to carry any of it,
# so without a cap an absurd amount is only refused by the driver: a 500 where
# a 422 belongs. The cap sits an order of magnitude below the column, so a total
# of capped amounts still fits, and no real amount comes close to it.
MAX_AMOUNT_MINOR = 2**62


# A calendar month, as used by budgets and by the report endpoints. Budgets are
# stored as a `date` pinned to the first of the month; "YYYY-MM" is the wire
# format, so a caller cannot pass a day that the storage would silently drop.
MONTH_KEY_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"

MonthKey = Annotated[str, StringConstraints(pattern=MONTH_KEY_PATTERN)]


def month_start(month: str) -> date:
    """Convert a month key to the first day of that month.

    Args:
        month: A month in "YYYY-MM" form.

    Returns:
        The first day of the month.
    """
    year, month_number = month.split("-")
    return date(int(year), int(month_number), 1)


def next_month_start(month: str) -> date:
    """Get the first day of the month after the given one.

    Report and budget queries filter on a half-open range, so they need the
    start of the following month rather than the end of this one.

    Args:
        month: A month in "YYYY-MM" form.

    Returns:
        The first day of the following month.
    """
    start = month_start(month)
    return date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)


def month_key_of(value: date) -> str:
    """Format a date as the month key of the month that contains it.

    Args:
        value: Any date.

    Returns:
        The month in "YYYY-MM" form.
    """
    return f"{value.year:04d}-{value.month:02d}"


# Quantities, prices and exchange rates need more precision than money does.
# A holding can be a fraction of a unit, an ETF quotes to four decimal places
# or more, and a rate to six. Rounding any of them to whole minor units would
# lose value on every multiplication, so all three are stored as integers
# scaled by MICRO, the same way money is stored scaled by the currency's minor
# unit. Integers keep the arithmetic exact and keep floats out of the wire
# format, which is why the rest of the app has no Decimal in it either.
MICRO = 1_000_000

# A quantity of units held, times MICRO. 1_500_000 is one and a half units.
# The cap is a thousand million units, which fits a BigInteger column with room
# to spare and is far beyond any household holding.
MAX_QUANTITY_MICRO = 10**15

# The price of one unit, in minor units of the instrument's own currency, times
# MICRO. A share at 128.4567 EUR is 12_845_670_000: 12845.67 cents times MICRO.
# The cap pairs with the quantity cap so their product, in minor units, stays
# below MAX_AMOUNT_MINOR and can never overflow the column it is summed into.
MAX_PRICE_MICRO = 10**15

# An exchange rate, times MICRO. A cap of a million to one covers every real
# pair, including the weakest currencies against the strongest.
MAX_FX_RATE_MICRO = 10**12


def market_value_minor(quantity_micro: int, price_micro: int) -> int:
    """Multiply a quantity by a unit price, in minor units.

    Both inputs are scaled by MICRO, so the product carries MICRO squared and
    has to be divided by it once. Rounding is half up on the absolute value, so
    the result does not drift towards zero on a negative quantity.

    Args:
        quantity_micro: The number of units held, times MICRO.
        price_micro: The price of one unit in minor units, times MICRO.

    Returns:
        The value of the holding, in minor units.
    """
    return _round_scaled(quantity_micro * price_micro, MICRO * MICRO)


def convert_minor(amount_minor: int, rate_micro: int) -> int:
    """Convert an amount of money at an exchange rate.

    Args:
        amount_minor: The amount, in minor units of the source currency.
        rate_micro: How many units of the target currency one unit of the
            source currency buys, times MICRO.

    Returns:
        The amount, in minor units of the target currency.
    """
    return _round_scaled(amount_minor * rate_micro, MICRO)


def apportion_minor(amount_minor: int, part: int, whole: int) -> int:
    """Take the share of an amount that belongs to part of a whole.

    Used to work out how much of a position's cost basis leaves with the units
    being sold. The share is rounded rather than truncated, so selling a
    position in pieces takes the whole cost basis out across those pieces
    instead of leaving a residue behind on the last one.

    Args:
        amount_minor: The amount to divide, in minor units.
        part: The size of the share.
        whole: The size of the whole. Zero yields zero, since there is nothing
            to take a share of.

    Returns:
        The share, in minor units.
    """
    if whole <= 0:
        return 0

    return _round_scaled(amount_minor * part, whole)


def _round_scaled(numerator: int, scale: int) -> int:
    """Divide by a scale, rounding half away from zero.

    Python's ``round`` on integers rounds half to even, and floor division
    rounds towards negative infinity. Neither is what a ledger wants: the same
    magnitude has to round the same way whichever sign it carries.

    Args:
        numerator: The scaled value.
        scale: The scale to remove.

    Returns:
        The rounded result.
    """
    sign = -1 if numerator < 0 else 1
    return sign * ((abs(numerator) * 2 + scale) // (scale * 2))


# How many minor units make one major unit, for the currencies that are not the
# usual hundred. ISO 4217 gives most currencies two decimal places; these are
# the exceptions a price parser has to know about, because a quote arrives as a
# decimal string in major units and has to land in minor ones. The map is small
# on purpose: it lists only what differs, and everything absent is two.
_CURRENCY_MINOR_DIGITS = {
    "BIF": 0,
    "CLP": 0,
    "DJF": 0,
    "GNF": 0,
    "ISK": 0,
    "JPY": 0,
    "KMF": 0,
    "KRW": 0,
    "PYG": 0,
    "RWF": 0,
    "UGX": 0,
    "UYI": 0,
    "VND": 0,
    "VUV": 0,
    "XAF": 0,
    "XOF": 0,
    "XPF": 0,
    "BHD": 3,
    "IQD": 3,
    "JOD": 3,
    "KWD": 3,
    "LYD": 3,
    "OMR": 3,
    "TND": 3,
}


def minor_digits(currency_code: str) -> int:
    """Get how many decimal places a currency uses.

    Args:
        currency_code: A three letter ISO 4217 code.

    Returns:
        The number of minor unit digits, two for anything not listed.
    """
    return _CURRENCY_MINOR_DIGITS.get(currency_code.upper(), 2)
