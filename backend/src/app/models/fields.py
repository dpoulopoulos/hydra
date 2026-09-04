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
