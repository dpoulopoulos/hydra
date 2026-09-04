"""The bounds on the input models must not be applied to what is read back.

Every model in the app is built as a base the input models, the response models
and the table all share, so a bound added to the base is also a bound on the way
out. A row stored before a bound existed would then fail response validation,
which turns a listing into a 500: the failure the bounds are there to prevent,
moved from the write path to the read path.
"""

import uuid
from datetime import UTC, date, datetime

from app.models import (
    RecurrenceFrequency,
    RecurringRulePublic,
    TransactionKind,
    TransactionPublic,
)
from app.models.fields import MAX_AMOUNT_MINOR

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


class TestTransactionPublic:
    """An amount stored before the money fields were capped."""

    def test_reads_back_an_amount_above_the_cap(self) -> None:
        stored = {
            "id": uuid.uuid4(),
            "household_id": HOUSEHOLD_ID,
            "account_id": uuid.uuid4(),
            "kind": TransactionKind.EXPENSE,
            "amount_minor": MAX_AMOUNT_MINOR + 1,
            "occurred_on": date(2026, 1, 1),
            "created_at": datetime.now(UTC),
        }

        assert TransactionPublic.model_validate(stored).amount_minor == MAX_AMOUNT_MINOR + 1


class TestRecurringRulePublic:
    """A rule amount stored before the money fields were capped."""

    def test_reads_back_an_amount_above_the_cap(self) -> None:
        assert _rule(amount_minor=MAX_AMOUNT_MINOR + 1).amount_minor == MAX_AMOUNT_MINOR + 1



def _rule(amount_minor: int = 120_000) -> RecurringRulePublic:
    """Validate a stored recurring rule as it is read back."""
    return RecurringRulePublic.model_validate(
        {
            "id": uuid.uuid4(),
            "household_id": HOUSEHOLD_ID,
            "account_id": uuid.uuid4(),
            "name": "Rent",
            "frequency": RecurrenceFrequency.MONTHLY,
            "interval": 1,
            "start_date": date(2026, 1, 1),
            "kind": TransactionKind.EXPENSE,
            "amount_minor": amount_minor,
            "created_at": datetime.now(UTC),
        }
    )
