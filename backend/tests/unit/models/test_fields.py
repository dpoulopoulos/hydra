import pytest
from pydantic import ValidationError

from app.models import UserCreate
from app.models.fields import BCRYPT_MAX_PASSWORD_BYTES


class TestPassword:
    """Test the Password field type."""

    def test_password_at_byte_limit_is_accepted(self):
        """Test that a password of exactly the maximum length is accepted."""
        # Arrange: Set up a password of exactly the maximum number of bytes
        password = "a" * BCRYPT_MAX_PASSWORD_BYTES

        # Act: Build a user with that password
        user = UserCreate(email="user@example.com", password=password)

        # Assert: Verify the password was accepted unchanged
        assert user.password == password

    def test_password_over_character_limit_is_rejected(self):
        """Test that a password with too many characters is rejected."""
        # Arrange: Set up a password one character over the limit
        password = "a" * (BCRYPT_MAX_PASSWORD_BYTES + 1)

        # Act & Assert: Verify the password is rejected by the length constraint
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(email="user@example.com", password=password)

        assert "at most" in str(exc_info.value)

    def test_password_within_character_limit_but_over_byte_limit_is_rejected(self):
        """Test that multi-byte characters are measured as encoded bytes, not characters."""
        # Arrange: Set up a password that fits the character limit but not the byte
        # limit, since each of these characters encodes to two bytes
        password = "é" * (BCRYPT_MAX_PASSWORD_BYTES // 2 + 1)
        assert len(password) <= BCRYPT_MAX_PASSWORD_BYTES
        assert len(password.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES

        # Act & Assert: Verify the password is rejected for its encoded size
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(email="user@example.com", password=password)

        assert "bytes once UTF-8 encoded" in str(exc_info.value)
