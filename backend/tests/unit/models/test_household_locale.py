"""The locale a household writes its numbers in.

The value is handed straight to `Intl` in the browser, so a tag it cannot make
sense of would leave every amount on the screen formatted by a fallback nobody
chose. The write path checks the shape; the read path does not, so a tag stored
before this check existed still reads back.
"""

import pytest
from pydantic import ValidationError

from app.models import HouseholdPublic, HouseholdUpdate

HOUSEHOLD_ROW = {
    "id": "11111111-1111-1111-1111-111111111111",
    "name": "Test household",
    "created_at": "2026-01-01T00:00:00Z",
}


class TestHouseholdUpdateLocale:
    """What an owner may set the household locale to."""

    @pytest.mark.parametrize("locale", ["el", "en-US", "pt-BR", "sr-Latn-RS", "es-419"])
    def test_accepts_a_language_tag(self, locale: str) -> None:
        assert HouseholdUpdate(locale=locale).locale == locale

    def test_accepts_no_locale_at_all(self) -> None:
        """Null is a value here: it hands the choice back to the reader's browser."""
        assert HouseholdUpdate(locale=None).locale is None

    @pytest.mark.parametrize("locale", ["english", "en_US", "en-USA", "1234", "en-US; rm -rf", ""])
    def test_rejects_what_is_not_a_language_tag(self, locale: str) -> None:
        with pytest.raises(ValidationError):
            HouseholdUpdate(locale=locale)


class TestHouseholdPublicLocale:
    """A locale stored before the shape was checked still reads back."""

    def test_reads_back_a_locale_outside_the_shape(self) -> None:
        stored = {**HOUSEHOLD_ROW, "locale": "not a tag"}

        assert HouseholdPublic.model_validate(stored).locale == "not a tag"

    def test_reads_back_a_household_with_no_locale(self) -> None:
        assert HouseholdPublic.model_validate(HOUSEHOLD_ROW).locale is None
