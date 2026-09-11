from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import TypeAdapter, ValidationError

from app.models import InstrumentPriceUpdate, UserCreate
from app.models.fields import (
    BCRYPT_MAX_PASSWORD_BYTES,
    Iban,
    MonthKey,
    UtcMoment,
    month_bounds,
    month_key_of,
    month_start,
    next_month_start,
)


class TestPassword:
    """Test the Password field type."""

    def test_password_at_byte_limit_is_accepted(self) -> None:
        """Test that a password of exactly the maximum length is accepted."""
        # Arrange: Set up a password of exactly the maximum number of bytes
        password = "a" * BCRYPT_MAX_PASSWORD_BYTES

        # Act: Build a user with that password
        user = UserCreate(email="user@example.com", password=password)

        # Assert: Verify the password was accepted unchanged
        assert user.password == password

    def test_password_over_character_limit_is_rejected(self) -> None:
        """Test that a password with too many characters is rejected."""
        # Arrange: Set up a password one character over the limit
        password = "a" * (BCRYPT_MAX_PASSWORD_BYTES + 1)

        # Act & Assert: Verify the password is rejected by the length constraint
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(email="user@example.com", password=password)

        assert "at most" in str(exc_info.value)

    def test_password_within_character_limit_but_over_byte_limit_is_rejected(self) -> None:
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

    def test_spacing_and_case_are_normalized(self) -> None:
        """Test that an IBAN written in groups of four is stored compact."""
        # Arrange: Set up an IBAN the way a bank statement prints it
        written = "gr16 0110 1250 0000 0001 2300 695"

        # Act: Validate it
        iban = self.adapter.validate_python(written)

        # Assert: Verify the spaces are gone and the letters are upper case
        assert iban == "GR1601101250000000012300695"

    def test_valid_iban_is_accepted(self) -> None:
        """Test that a well formed IBAN passes the check digits."""
        # Arrange: Set up a valid IBAN
        written = "DE89370400440532013000"

        # Act: Validate it
        iban = self.adapter.validate_python(written)

        # Assert: Verify it is returned unchanged
        assert iban == written

    def test_mistyped_iban_is_rejected(self) -> None:
        """Test that a single wrong digit fails the check digits."""
        # Arrange: Set up a valid IBAN with one digit changed
        written = "DE89370400440532013001"

        # Act & Assert: Verify the check digits catch it
        with pytest.raises(ValidationError) as exc_info:
            self.adapter.validate_python(written)

        assert "check digits" in str(exc_info.value)

    def test_malformed_iban_is_rejected(self) -> None:
        """Test that something that is not shaped like an IBAN is rejected."""
        # Arrange: Set up a value that is too short and starts with digits
        written = "1234"

        # Act & Assert: Verify the shape is refused before the check digits
        with pytest.raises(ValidationError) as exc_info:
            self.adapter.validate_python(written)

        assert "country code" in str(exc_info.value)


class TestUtcMoment:
    """Test the UtcMoment field type.

    A moment typed in by a caller reaches a ``timestamptz`` column, which reads
    a value that names no zone in whatever zone the database session carries.
    That makes what gets stored depend on the server's configuration rather
    than on what was sent, so a naive input is read as the UTC the rest of the
    app is written in before it gets anywhere near the column.
    """

    adapter = TypeAdapter(UtcMoment)

    def test_a_moment_with_no_zone_is_read_as_utc(self) -> None:
        """Test that a naive input is not left for the session zone to decide."""
        # Arrange: Set up a timestamp with no offset, as a caller may send one
        written = "2026-09-08T15:30:00"

        # Act: Validate it
        moment = self.adapter.validate_python(written)

        # Assert: Verify it names UTC and keeps the wall time it was sent with
        assert moment == datetime(2026, 9, 8, 15, 30, tzinfo=UTC)

    def test_a_moment_in_another_zone_is_converted(self) -> None:
        """Test that an offset the caller did send is honoured, not ignored."""
        # Arrange: Set up the same instant, written in a zone two hours ahead
        written = "2026-09-08T17:30:00+02:00"

        # Act: Validate it
        moment = self.adapter.validate_python(written)

        # Assert: Verify it is the instant the offset names, in UTC
        assert moment == datetime(2026, 9, 8, 15, 30, tzinfo=UTC)
        assert moment.utcoffset() == timedelta(0)

    def test_a_typed_price_is_dated_in_utc(self) -> None:
        """Test that the one input model carrying a moment applies the rule."""
        # Arrange & Act: Type in a price dated with no zone
        price_update = InstrumentPriceUpdate(price_micro=12_845_670_000, as_of="2026-09-08T15:30:00")

        # Assert: Verify the moment it will be stored as names UTC
        assert price_update.as_of == datetime(2026, 9, 8, 15, 30, tzinfo=UTC)
