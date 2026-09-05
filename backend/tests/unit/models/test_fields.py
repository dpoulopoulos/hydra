from datetime import date

import pytest
from pydantic import TypeAdapter, ValidationError

from app.models import UserCreate
from app.models.fields import (
    BCRYPT_MAX_PASSWORD_BYTES,
    Iban,
    MonthKey,
    month_bounds,
    month_key_of,
    month_start,
    next_month_start,
)


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


class TestMonthKey:
    """Tests for the MonthKey type and its date helpers."""

    @pytest.mark.parametrize("value", ["2026-01", "2026-09", "2026-12", "1999-06"])
    def test_accepts_a_valid_month(self, value: str) -> None:
        assert TypeAdapter(MonthKey).validate_python(value) == value

    @pytest.mark.parametrize(
        "value",
        ["2026-00", "2026-13", "2026-1", "26-01", "2026/01", "2026-01-01", "", "not-a-month"],
    )
    def test_rejects_an_invalid_month(self, value: str) -> None:
        with pytest.raises(ValidationError):
            TypeAdapter(MonthKey).validate_python(value)

    def test_month_start_pins_to_the_first(self) -> None:
        assert month_start("2026-09") == date(2026, 9, 1)

    def test_next_month_start_rolls_over_the_year(self) -> None:
        assert next_month_start("2026-09") == date(2026, 10, 1)
        assert next_month_start("2026-12") == date(2027, 1, 1)

    def test_month_bounds_covers_the_whole_month(self) -> None:
        assert month_bounds("2026-09") == (date(2026, 9, 1), date(2026, 9, 30))
        assert month_bounds("2026-01") == (date(2026, 1, 1), date(2026, 1, 31))

    def test_month_bounds_ends_a_february_correctly(self) -> None:
        assert month_bounds("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
        assert month_bounds("2028-02") == (date(2028, 2, 1), date(2028, 2, 29))

    def test_month_bounds_ends_a_december_correctly(self) -> None:
        assert month_bounds("2026-12") == (date(2026, 12, 1), date(2026, 12, 31))

    def test_month_key_of_formats_a_date(self) -> None:
        assert month_key_of(date(2026, 9, 17)) == "2026-09"
        assert month_key_of(date(2026, 1, 1)) == "2026-01"

    def test_round_trips(self) -> None:
        assert month_key_of(month_start("2026-07")) == "2026-07"


class TestIban:
    """Test the Iban field type."""

    adapter = TypeAdapter(Iban)

    def test_spacing_and_case_are_normalized(self):
        """Test that an IBAN written in groups of four is stored compact."""
        # Arrange: Set up an IBAN the way a bank statement prints it
        written = "gr16 0110 1250 0000 0001 2300 695"

        # Act: Validate it
        iban = self.adapter.validate_python(written)

        # Assert: Verify the spaces are gone and the letters are upper case
        assert iban == "GR1601101250000000012300695"

    def test_valid_iban_is_accepted(self):
        """Test that a well formed IBAN passes the check digits."""
        # Arrange: Set up a valid IBAN
        written = "DE89370400440532013000"

        # Act: Validate it
        iban = self.adapter.validate_python(written)

        # Assert: Verify it is returned unchanged
        assert iban == written

    def test_mistyped_iban_is_rejected(self):
        """Test that a single wrong digit fails the check digits."""
        # Arrange: Set up a valid IBAN with one digit changed
        written = "DE89370400440532013001"

        # Act & Assert: Verify the check digits catch it
        with pytest.raises(ValidationError) as exc_info:
            self.adapter.validate_python(written)

        assert "check digits" in str(exc_info.value)

    def test_malformed_iban_is_rejected(self):
        """Test that something that is not shaped like an IBAN is rejected."""
        # Arrange: Set up a value that is too short and starts with digits
        written = "1234"

        # Act & Assert: Verify the shape is refused before the check digits
        with pytest.raises(ValidationError) as exc_info:
            self.adapter.validate_python(written)

        assert "country code" in str(exc_info.value)
