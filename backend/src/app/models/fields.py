from typing import Annotated

from pydantic import AfterValidator

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
