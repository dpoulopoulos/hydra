import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Final

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import settings

pwd_context = PasswordHash((BcryptHasher(),))


ALGORITHM = "HS256"


class TokenType(StrEnum):
    """Types of JWT tokens issued by the application."""

    SESSION = "session"
    PASSWORD_RESET = "password_reset"
    EMAIL_VERIFICATION = "email_verification"


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


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password.

    Args:
        plain_password: The plain text password to verify.
        hashed_password: The hashed password to verify against.

    Returns:
        True if the passwords match, False otherwise.
    """
    return pwd_context.verify(plain_password, hashed_password)
