import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from jwt.exceptions import InvalidTokenError

from app.core.config import settings
from app.core.security import (
    ALGORITHM,
    JWT,
    TokenType,
    create_access_token,
    create_email_verification_token,
    create_password_reset_token,
    dummy_password_hash,
    get_password_hash,
    verify_password,
    verify_typed_token,
)
from app.models.fields import BCRYPT_MAX_PASSWORD_BYTES


class TestCreateAccessToken:
    """Test suite for create_access_token function."""

    def test_create_session_token(self) -> None:
        """Test creating an access token with a UUID subject."""
        # Arrange: Set up test data
        subject = uuid.uuid4()

        # Act: Create access token
        before_creation = datetime.now(UTC)
        token = create_access_token(subject)
        after_creation = datetime.now(UTC)

        # Assert: Verify token is valid and contains correct data
        decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM], audience=JWT.AUDIENCE)

        assert isinstance(token, str)
        assert len(token) > 0
        assert decoded[JWT.Claims.SUB] == str(subject)

        # Verify expiration is set correctly (8 days by default)
        exp_timestamp = decoded["exp"]
        expected_exp = before_creation + timedelta(hours=settings.SESSION_TOKEN_EXPIRE_HOURS)
        actual_exp = datetime.fromtimestamp(exp_timestamp, tz=UTC)

        # Allow for a few seconds of drift
        assert (
            expected_exp - timedelta(seconds=5)
            <= actual_exp
            <= after_creation + timedelta(hours=settings.SESSION_TOKEN_EXPIRE_HOURS) + timedelta(seconds=5)
        )

    def test_create_session_token_uses_correct_algorithm(self) -> None:
        """Test that the token uses the HS256 algorithm."""
        # Arrange: Set up test data
        subject = uuid.uuid4()

        # Act: Create access token
        token = create_access_token(subject)

        # Assert: Verify token uses HS256 algorithm
        unverified_header = jwt.get_unverified_header(token)
        assert unverified_header["alg"] == "HS256"

        # Assert: Verify token can be decoded with the expected algorithm
        decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM], audience=JWT.AUDIENCE)
        assert decoded is not None


class TestGetPasswordHash:
    """Test suite for get_password_hash function."""

    def test_get_password_hash_returns_string(self) -> None:
        """Test that get_password_hash returns a string."""
        # Arrange: Set up test password
        password = "testpassword123"

        # Act: Hash the password
        hashed = get_password_hash(password)

        # Assert: Verify hash is a non-empty string
        assert isinstance(hashed, str)
        assert len(hashed) > 0

    def test_get_password_hash_returns_different_hash_each_time(self) -> None:
        """Test that hashing the same password twice produces different hashes (due to salt)."""
        # Arrange: Set up test password
        password = "testpassword123"

        # Act: Hash the same password twice
        hash1 = get_password_hash(password)
        hash2 = get_password_hash(password)

        # Assert: Verify hashes are different due to random salt
        assert hash1 != hash2

    def test_get_password_hash_produces_bcrypt_format(self) -> None:
        """Test that the hash is in bcrypt format."""
        # Arrange: Set up test password
        password = "testpassword123"

        # Act: Hash the password
        hashed = get_password_hash(password)

        # Assert: Verify hash is in bcrypt format (starts with $2b$)
        assert hashed.startswith("$2b$")

    def test_get_password_hash_with_empty_string(self) -> None:
        """Test hashing an empty string."""
        # Arrange: Set up empty password
        password = ""

        # Act: Hash the empty password
        hashed = get_password_hash(password)

        # Assert: Verify hash is a non-empty string
        assert isinstance(hashed, str)
        assert len(hashed) > 0

    def test_get_password_hash_at_bcrypt_limit(self) -> None:
        """Test hashing a password of exactly the maximum length bcrypt accepts."""
        # Arrange: Set up a password of exactly 72 bytes
        password = "a" * BCRYPT_MAX_PASSWORD_BYTES

        # Act: Hash the password
        hashed = get_password_hash(password)

        # Assert: Verify hash is a non-empty string
        assert isinstance(hashed, str)
        assert len(hashed) > 0

    def test_get_password_hash_rejects_password_over_bcrypt_limit(self) -> None:
        """Test that a password longer than bcrypt accepts is rejected, not truncated."""
        # Arrange: Set up a password one byte over the limit
        password = "a" * (BCRYPT_MAX_PASSWORD_BYTES + 1)

        # Act & Assert: Verify hashing raises rather than silently truncating,
        # which would make this password equivalent to its 72 byte prefix
        with pytest.raises(ValueError):
            get_password_hash(password)

    def test_get_password_hash_with_special_characters(self) -> None:
        """Test hashing a password with special characters."""
        # Arrange: Set up password with special characters
        password = "p@ssw0rd!#$%^&*()_+-=[]{}|;:',.<>?/~`"

        # Act: Hash the password
        hashed = get_password_hash(password)

        # Assert: Verify hash is a non-empty string
        assert isinstance(hashed, str)
        assert len(hashed) > 0


class TestDummyPasswordHash:
    """Test suite for dummy_password_hash function."""

    def test_dummy_password_hash_produces_bcrypt_format(self) -> None:
        """Test that the dummy hash looks like any other stored hash."""
        # Act: Ask for the dummy hash
        hashed = dummy_password_hash()

        # Assert: Verify it is bcrypt at the same cost as a stored hash, so verifying costs the same
        assert hashed.startswith("$2b$")
        assert hashed.split("$")[2] == get_password_hash("testpassword123").split("$")[2]

    def test_dummy_password_hash_is_computed_once(self) -> None:
        """Test that repeated calls return the same hash rather than hashing again."""
        # Act: Ask for the dummy hash twice
        first = dummy_password_hash()
        second = dummy_password_hash()

        # Assert: Verify the same hash comes back, so no request pays to build it
        assert first == second

    def test_dummy_password_hash_matches_no_password(self) -> None:
        """Test that verifying against the dummy hash fails."""
        # Act: Verify a password against the dummy hash
        result = verify_password("testpassword123", dummy_password_hash())

        # Assert: Verify the result is False, since nobody holds the hashed password
        assert result is False


class TestVerifyPassword:
    """Test suite for verify_password function."""

    def test_verify_password_returns_true_for_correct_password(self) -> None:
        """Test that verify_password returns True for the correct password."""
        # Arrange: Set up password and hash
        plain_password = "testpassword123"
        hashed_password = get_password_hash(plain_password)

        # Act: Verify the correct password
        result = verify_password(plain_password, hashed_password)

        # Assert: Verify result is True
        assert result is True

    def test_verify_password_returns_false_for_incorrect_password(self) -> None:
        """Test that verify_password returns False for an incorrect password."""
        # Arrange: Set up correct password hash and wrong password
        plain_password = "testpassword123"
        wrong_password = "wrongpassword456"
        hashed_password = get_password_hash(plain_password)

        # Act: Verify the wrong password
        result = verify_password(wrong_password, hashed_password)

        # Assert: Verify result is False
        assert result is False

    def test_verify_password_with_empty_string(self) -> None:
        """Test verifying an empty password."""
        # Arrange: Set up empty password and its hash
        plain_password = ""
        hashed_password = get_password_hash(plain_password)

        # Act & Assert: Verify correct empty password returns True
        assert verify_password(plain_password, hashed_password) is True

        # Act & Assert: Verify wrong password (non-empty) against empty hash returns False
        assert verify_password("nonempty", hashed_password) is False

    def test_verify_password_case_sensitive(self) -> None:
        """Test that password verification is case-sensitive."""
        # Arrange: Set up password with mixed case and its hash
        plain_password = "TestPassword123"
        hashed_password = get_password_hash(plain_password)

        # Act & Assert: Verify correct password returns True
        assert verify_password(plain_password, hashed_password) is True

        # Act & Assert: Verify lowercase version returns False
        assert verify_password("testpassword123", hashed_password) is False

        # Act & Assert: Verify uppercase version returns False
        assert verify_password("TESTPASSWORD123", hashed_password) is False

    def test_verify_password_with_special_characters(self) -> None:
        """Test verifying passwords with special characters."""
        # Arrange: Set up password with special characters and its hash
        plain_password = "p@ssw0rd!#$%"
        hashed_password = get_password_hash(plain_password)

        # Act & Assert: Verify correct password returns True
        assert verify_password(plain_password, hashed_password) is True

        # Act & Assert: Verify slightly different password returns False
        assert verify_password("p@ssw0rd!#$", hashed_password) is False

    def test_verify_password_with_unicode_characters(self) -> None:
        """Test verifying passwords with unicode characters."""
        # Arrange: Set up password with unicode characters and its hash
        plain_password = "пароль密码🔐"
        hashed_password = get_password_hash(plain_password)

        # Act & Assert: Verify correct password returns True
        assert verify_password(plain_password, hashed_password) is True

        # Act & Assert: Verify incomplete password returns False
        assert verify_password("пароль密码", hashed_password) is False

    def test_verify_password_with_whitespace(self) -> None:
        """Test that whitespace in passwords is significant."""
        # Arrange: Set up password with whitespace and its hash
        plain_password = "password with spaces"
        hashed_password = get_password_hash(plain_password)

        # Act & Assert: Verify correct password returns True
        assert verify_password(plain_password, hashed_password) is True

        # Act & Assert: Verify password without spaces returns False
        assert verify_password("passwordwithspaces", hashed_password) is False

        # Act & Assert: Verify password with leading space returns False
        assert verify_password(" password with spaces", hashed_password) is False

        # Act & Assert: Verify password with trailing space returns False
        assert verify_password("password with spaces ", hashed_password) is False


class TestCreatePasswordResetToken:
    """Test suite for create_password_reset_token function."""

    def test_create_password_reset_token(self) -> None:
        """Test creating a password reset token."""
        # Arrange: Set up test data
        email = "user@example.com"

        # Act: Create password reset token
        before_creation = datetime.now(UTC)
        token = create_password_reset_token(email)
        after_creation = datetime.now(UTC)

        # Assert: Verify token is valid and contains correct data
        decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM], audience=JWT.AUDIENCE)

        assert isinstance(token, str)
        assert len(token) > 0
        assert decoded[JWT.Claims.SUB] == email
        assert decoded[JWT.Claims.TOKEN_TYPE] == "password_reset"

        # Verify expiration is set correctly (8 hours by default)
        exp_timestamp = decoded["exp"]
        expected_exp = before_creation + timedelta(hours=settings.EMAIL_PASSWORD_RESET_TOKEN_EXPIRE_HOURS)
        actual_exp = datetime.fromtimestamp(exp_timestamp, tz=UTC)

        # Allow for a few seconds of drift
        assert (
            expected_exp - timedelta(seconds=5)
            <= actual_exp
            <= after_creation + timedelta(hours=settings.EMAIL_PASSWORD_RESET_TOKEN_EXPIRE_HOURS) + timedelta(seconds=5)
        )

        # Verify nbf (not before) is set
        assert "nbf" in decoded

    def test_create_password_reset_token_uses_correct_algorithm(self) -> None:
        """Test that password reset tokens use the HS256 algorithm."""
        # Arrange: Set up test data
        email = "user@example.com"

        # Act: Create password reset token
        token = create_password_reset_token(email)

        # Assert: Verify token uses HS256 algorithm
        unverified_header = jwt.get_unverified_header(token)
        assert unverified_header["alg"] == "HS256"

        # Assert: Verify token can be decoded with the expected algorithm
        decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM], audience=JWT.AUDIENCE)
        assert decoded is not None


class TestCreateEmailVerificationToken:
    """Test suite for create_email_verification_token function."""

    def test_create_email_verification_token(self) -> None:
        """Test creating an email verification token."""
        # Arrange: Set up test data
        email = "user@example.com"

        # Act: Create email verification token
        before_creation = datetime.now(UTC)
        token = create_email_verification_token(email)
        after_creation = datetime.now(UTC)

        # Assert: Verify token is valid and contains correct data
        decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM], audience=JWT.AUDIENCE)

        assert isinstance(token, str)
        assert len(token) > 0
        assert decoded[JWT.Claims.SUB] == email
        assert decoded[JWT.Claims.TOKEN_TYPE] == "email_verification"

        # Verify expiration is set correctly (8 hours by default)
        exp_timestamp = decoded["exp"]
        expected_exp = before_creation + timedelta(hours=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS)
        actual_exp = datetime.fromtimestamp(exp_timestamp, tz=UTC)

        # Allow for a few seconds of drift
        assert (
            expected_exp - timedelta(seconds=5)
            <= actual_exp
            <= after_creation + timedelta(hours=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS) + timedelta(seconds=5)
        )

        # Verify nbf (not before) is set
        assert "nbf" in decoded

    def test_create_email_verification_token_uses_correct_algorithm(self) -> None:
        """Test that email verification tokens use the HS256 algorithm."""
        # Arrange: Set up test data
        email = "user@example.com"

        # Act: Create email verification token
        token = create_email_verification_token(email)

        # Assert: Verify token uses HS256 algorithm
        unverified_header = jwt.get_unverified_header(token)
        assert unverified_header["alg"] == "HS256"

        # Assert: Verify token can be decoded with the expected algorithm
        decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM], audience=JWT.AUDIENCE)
        assert decoded is not None


class TestVerifyTypedToken:
    """Test suite for verify_typed_token function."""

    def test_verify_typed_token_success_returns_decoded_payload(self) -> None:
        """Test that verify_typed_token returns decoded payload on success."""
        # Arrange: Create a valid token
        email = "user@example.com"
        token = create_password_reset_token(email)

        class CustomTokenError(Exception):
            pass

        # Act: Verify the token
        decoded = verify_typed_token(token, TokenType.PASSWORD_RESET, CustomTokenError)

        # Assert: Verify decoded payload is correct
        assert decoded[JWT.Claims.SUB] == email
        assert decoded[JWT.Claims.TOKEN_TYPE] == "password_reset"
        assert JWT.Claims.ISS in decoded
        assert JWT.Claims.AUD in decoded
        assert JWT.Claims.EXP in decoded

    def test_verify_typed_token_maps_invalid_token_to_custom_exception(self) -> None:
        """Test that InvalidTokenError is mapped to custom exception."""

        # Arrange: Create a custom exception class
        class CustomTokenError(Exception):
            pass

        # Act & Assert: Verify that invalid token raises custom exception
        with pytest.raises(CustomTokenError):
            verify_typed_token("invalid.token.here", TokenType.PASSWORD_RESET, CustomTokenError)

    def test_verify_typed_token_preserves_exception_chain(self) -> None:
        """Test that exception chain is preserved (from exc)."""

        # Arrange: Create a custom exception class
        class CustomTokenError(Exception):
            pass

        # Act & Assert: Verify that exception chain is preserved
        with pytest.raises(CustomTokenError) as exc_info:
            verify_typed_token("invalid.token.here", TokenType.PASSWORD_RESET, CustomTokenError)

        # Assert: Verify the original InvalidTokenError is in the chain
        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, InvalidTokenError)

    def test_verify_typed_token_wrong_token_type_raises_exception(self) -> None:
        """Test that wrong token type raises custom exception."""
        # Arrange: Create an email verification token but expect password reset
        email = "user@example.com"
        token = create_email_verification_token(email)

        class CustomTokenError(Exception):
            pass

        # Act & Assert: Verify that wrong token type raises exception
        with pytest.raises(CustomTokenError):
            verify_typed_token(token, TokenType.PASSWORD_RESET, CustomTokenError)

    def test_verify_typed_token_expired_token_raises_exception(self) -> None:
        """Test that expired token raises custom exception."""
        # Arrange: Create an expired token
        email = "user@example.com"
        expired_time = datetime.now(UTC) - timedelta(hours=1)
        payload = {
            JWT.Claims.ISS: JWT.ISSUER,
            JWT.Claims.AUD: JWT.AUDIENCE,
            JWT.Claims.SUB: email,
            JWT.Claims.EXP: expired_time.timestamp(),
            JWT.Claims.NBF: expired_time - timedelta(hours=1),
            JWT.Claims.IAT: expired_time - timedelta(hours=1),
            JWT.Claims.TOKEN_TYPE: TokenType.PASSWORD_RESET.value,
        }
        expired_token = jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT.ALGORITHM)

        class CustomTokenError(Exception):
            pass

        # Act & Assert: Verify that expired token raises exception
        with pytest.raises(CustomTokenError):
            verify_typed_token(expired_token, TokenType.PASSWORD_RESET, CustomTokenError)

    def test_verify_typed_token_works_for_all_token_types(self) -> None:
        """Test that verify_typed_token works for all TokenType variants."""
        # Arrange: Create tokens for each type
        email = "user@example.com"
        user_id = uuid.uuid4()

        test_cases = [
            (create_password_reset_token(email), TokenType.PASSWORD_RESET, email),
            (create_email_verification_token(email), TokenType.EMAIL_VERIFICATION, email),
            (create_access_token(user_id), TokenType.SESSION, str(user_id)),
        ]

        class CustomTokenError(Exception):
            pass

        # Act & Assert: Verify each token type works
        for token, token_type, expected_subject in test_cases:
            decoded = verify_typed_token(token, token_type, CustomTokenError)
            assert decoded[JWT.Claims.SUB] == expected_subject
            assert decoded[JWT.Claims.TOKEN_TYPE] == token_type.value
