import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import cache
from typing import Any, Final

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import settings

pwd_context = PasswordHash((BcryptHasher(),))


ALGORITHM = "HS256"


# An API token is "hyd_<token_id>_<secret>". The prefix is what tells one apart
# from a session JWT at the door, so nothing needs a second header to say which
# kind of credential arrived: a JWT is base64url of a JSON header and cannot
# begin with it.
API_TOKEN_PREFIX = "hyd_"
API_TOKEN_SEPARATOR = "_"
# The lookup half, stored in the clear and indexed. Hexadecimal rather than
# url-safe base64, because that alphabet includes the separator: an id able to
# contain "_" would make the split between the two halves ambiguous.
API_TOKEN_ID_BYTES = 8
# The secret half: 256 bits, which is what makes the hashing note below true.
# It may contain the separator, which is why the split is taken from the left.
API_TOKEN_SECRET_BYTES = 32


class TokenType(StrEnum):
    """Types of JWT tokens issued by the application."""

    SESSION = "session"
    PASSWORD_RESET = "password_reset"
    EMAIL_VERIFICATION = "email_verification"
    HOUSEHOLD_INVITE = "household_invite"


class JWT:
    """JWT configuration constants.

    Groups all JWT-related constants for token creation and validation.
    Values derived from settings.PROJECT_ID for consistency across the application.
    """

    ALGORITHM: Final = "HS256"
    ISSUER: Final = settings.PROJECT_ID
    AUDIENCE: Final = f"{settings.PROJECT_ID}-api"

    class Claims:
        """JWT claim names used in token payloads.

        Standard claims follow RFC 7519. The TOKEN_TYPE claim is a private claim
        using a collision-resistant namespace per RFC 7519 Section 4.3.
        """

        # Standard claims (RFC 7519).
        ISS: Final = "iss"
        AUD: Final = "aud"
        SUB: Final = "sub"
        EXP: Final = "exp"
        NBF: Final = "nbf"
        IAT: Final = "iat"
        # Private claim with collision-resistant namespace (RFC 7519 Section 4.3).
        TOKEN_TYPE: Final = f"{settings.PROJECT_ID}/token_type"


def create_typed_token(subject: Any, token_type: TokenType, expires_hours: int) -> str:
    """Create a typed JWT token (password_reset, email_verification, etc.).

    Args:
        subject: The subject of the token (typically email).
        token_type: The type of token (e.g., "password_reset", "email_verification").
        expires_hours: Number of hours until token expires.

    Returns:
        The encoded JWT token.
    """
    delta = timedelta(hours=expires_hours)
    now = datetime.now(UTC)
    expires = now + delta
    payload = {
        JWT.Claims.ISS: JWT.ISSUER,
        JWT.Claims.AUD: JWT.AUDIENCE,
        JWT.Claims.SUB: str(subject),
        JWT.Claims.EXP: expires.timestamp(),
        JWT.Claims.NBF: now,
        JWT.Claims.IAT: now,
        JWT.Claims.TOKEN_TYPE: token_type.value,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT.ALGORITHM)


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """Decode and validate a JWT token.

    Validates issuer, audience, expiration, and token type per RFC 7519.

    Args:
        token: The encoded JWT token string.
        expected_type: The expected TokenType for this token.

    Returns:
        The decoded payload as a dictionary.

    Raises:
        InvalidTokenError: If token is invalid, expired, or wrong type.
    """
    payload: dict[str, Any] = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[JWT.ALGORITHM],
        issuer=JWT.ISSUER,
        audience=JWT.AUDIENCE,
        options={
            "require": [JWT.Claims.ISS, JWT.Claims.AUD, JWT.Claims.SUB, JWT.Claims.EXP, JWT.Claims.NBF, JWT.Claims.IAT],
        },
    )

    if payload.get(JWT.Claims.TOKEN_TYPE) != expected_type.value:
        raise InvalidTokenError("Token type mismatch")

    return payload


def verify_typed_token(
    token: str,
    expected_type: TokenType,
    invalid_token_exception: type[Exception],
) -> dict[str, Any]:
    """Verify a typed token and map JWT errors to domain exceptions.

    Args:
        token: The JWT token to verify.
        expected_type: The expected TokenType.
        invalid_token_exception: Exception class to raise on JWT validation errors.

    Returns:
        The decoded token payload.

    Raises:
        invalid_token_exception: If the token is invalid, expired, or wrong type.
    """
    try:
        return decode_token(token, expected_type=expected_type)
    except InvalidTokenError as exc:
        raise invalid_token_exception from exc


def create_password_reset_token(subject: str) -> str:
    """Create a JWT password reset token.

    Args:
        subject: The subject of the token (email address).

    Returns:
        The encoded JWT password reset token.
    """
    return create_typed_token(
        subject=subject,
        token_type=TokenType.PASSWORD_RESET,
        expires_hours=settings.EMAIL_PASSWORD_RESET_TOKEN_EXPIRE_HOURS,
    )


def create_email_verification_token(subject: str) -> str:
    """Create a JWT email verification token.

    Args:
        subject: The subject of the token (email address).

    Returns:
        The encoded JWT email verification token.
    """
    return create_typed_token(
        subject=subject,
        token_type=TokenType.EMAIL_VERIFICATION,
        expires_hours=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS,
    )


def create_access_token(subject: uuid.UUID) -> str:
    """Create a JWT access token.

    Args:
        subject: The subject of the token.

    Returns:
        The encoded JWT access token.
    """
    return create_typed_token(
        subject=subject,
        token_type=TokenType.SESSION,
        expires_hours=settings.SESSION_TOKEN_EXPIRE_HOURS,
    )


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt.

    Args:
        password: The plain text password to hash.

    Returns:
        Bcrypt hashed password string.
    """
    return pwd_context.hash(password)


@cache
def dummy_password_hash() -> str:
    """Return a hash to verify against when there is no stored hash to use.

    Hashing is deliberately slow, so a caller who skips it answers measurably sooner. Verifying against
    this hash instead keeps a login attempt for an address with no account as expensive as one for an
    address that has it. It is built from a password nobody holds, once per process, at the same cost
    factor as every stored hash.

    Returns:
        A bcrypt hash that no password matches.
    """
    return get_password_hash(secrets.token_urlsafe(32))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password.

    Args:
        plain_password: The plain text password to verify.
        hashed_password: The hashed password to verify against.

    Returns:
        True if the passwords match, False otherwise.
    """
    return pwd_context.verify(plain_password, hashed_password)


def hash_api_token_secret(secret: str) -> str:
    """Hash the secret half of an API token.

    SHA-256 rather than bcrypt, deliberately, for three reasons:

    A password hash is slow on purpose, to make a low entropy, human chosen
    input expensive to guess. This secret is 256 bits from a CSPRNG, so there
    is no dictionary that reaches it and a work factor buys nothing.

    The cost would be paid on every request, and a machine client makes many.
    At the cost factor the passwords use that is around a tenth of a second
    each, which is a denial of service this application would be doing to
    itself.

    bcrypt also hashes only the first 72 bytes, and it salts, so the stored
    value cannot be searched for. The salt is what would force a scan over
    every row; the random token id already does the lookup, so the salt has no
    remaining job.

    Args:
        secret: The secret half of the credential.

    Returns:
        The hash, as hexadecimal.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def generate_api_token() -> tuple[str, str, str]:
    """Mint an API token.

    Returns:
        The full credential the holder keeps, its lookup id, and the hash of
        its secret half, in that order. The secret half leaves this function
        only inside the full credential, and cannot be recovered from the hash.
    """
    token_id = secrets.token_hex(API_TOKEN_ID_BYTES)
    secret = secrets.token_urlsafe(API_TOKEN_SECRET_BYTES)
    credential = f"{API_TOKEN_PREFIX}{token_id}{API_TOKEN_SEPARATOR}{secret}"
    return credential, token_id, hash_api_token_secret(secret)


def split_api_token(credential: str) -> tuple[str, str] | None:
    """Split a presented credential into its lookup id and its secret half.

    Returning None is also how a caller tells an API token apart from a session
    JWT, which cannot carry the prefix.

    The split is taken at the first separator. That is unambiguous because the
    lookup id is hexadecimal, so only the secret half can contain a "_".

    Args:
        credential: The string presented as a bearer token.

    Returns:
        The lookup id and the secret half, or None if the string is not shaped
        like an API token at all.
    """
    if not credential.startswith(API_TOKEN_PREFIX):
        return None

    token_id, separator, secret = credential.removeprefix(API_TOKEN_PREFIX).partition(API_TOKEN_SEPARATOR)
    if not separator or not token_id or not secret:
        return None

    return token_id, secret


def verify_api_token_secret(secret: str, secret_hash: str) -> bool:
    """Check the secret half of a credential against a stored hash.

    Args:
        secret: The secret half presented by the caller.
        secret_hash: The hash held in the database.

    Returns:
        True if they match.
    """
    return hmac.compare_digest(hash_api_token_secret(secret), secret_hash)
