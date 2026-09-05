"""What the session listing filters actually narrow to.

The conditions are built without touching the database, so they can be read
back and checked directly. That matters most for `owed_only`, which is the
difference between a debtors list and a diary.
"""

import uuid
from unittest.mock import MagicMock

from app.models import IncomeSessionFilters, IncomeSessionStatus, PaymentStatus
from app.repositories.income import IncomeClientRepository, IncomeSessionRepository

HOUSEHOLD_ID = MagicMock()


def conditions(filters: IncomeSessionFilters) -> str:
    """Render the WHERE clause a set of filters produces, as text to search."""
    repository = IncomeSessionRepository(MagicMock())
    return " ".join(str(one) for one in repository._conditions(household_id=HOUSEHOLD_ID, filters=filters))


class TestOwedOnly:
    def test_a_debtors_list_leaves_the_diary_out(self) -> None:
        # An appointment next Tuesday is unpaid only in the sense that it has
        # not happened yet. Listing it beside real debts inflates the one
        # figure the page exists to make chaseable.
        clause = conditions(IncomeSessionFilters(payment_status=PaymentStatus.PENDING, owed_only=True))

        assert "status IN" in clause
        assert "fee_minor >" in clause

    def test_it_leaves_written_off_work_out_too(self) -> None:
        # A session you decided not to charge for is not a debt.
        clause = conditions(IncomeSessionFilters(owed_only=True))

        assert "payment_status !=" in clause

    def test_an_ordinary_listing_narrows_nothing(self) -> None:
        # The Sessions tab shows the diary on purpose, so the default must not
        # quietly hide the appointments still to come.
        clause = conditions(IncomeSessionFilters())

        assert "fee_minor >" not in clause

    def test_asking_for_the_diary_still_works(self) -> None:
        clause = conditions(IncomeSessionFilters(status=IncomeSessionStatus.SCHEDULED))

        assert "status =" in clause


class TestBillable:
    def test_a_waived_booking_is_not_money_in_the_diary(self) -> None:
        # It is an appointment, but one already written off. Counting it would
        # promise money the estimate knows will never arrive.
        session = MagicMock()
        session.exec.return_value.one.return_value = (0, 0)
        repository = IncomeSessionRepository(session)

        repository.booked_for_month(household_id=HOUSEHOLD_ID, month="2026-09")
        clause = str(session.exec.call_args.args[0])

        assert "payment_status !=" in clause
        assert "fee_minor >" in clause


class TestBlankNamesForOwner:
    """Tests for the statement that forgets a member's client names."""

    @staticmethod
    def rendered(household_id: uuid.UUID, owner_user_id: uuid.UUID) -> str:
        """Render the UPDATE with its values inlined, so they can be read back."""
        session = MagicMock()
        session.exec.return_value.rowcount = 0
        repository = IncomeClientRepository(session)

        repository.blank_names_for_owner(household_id=household_id, owner_user_id=owner_user_id)
        statement = session.exec.call_args.args[0]

        return str(statement.compile(compile_kwargs={"literal_binds": True}))

    def test_it_matches_the_owner_rather_than_excluding_them(self) -> None:
        # The dangerous inversion. A `!=` here would blank every *other*
        # member's names and leave the caller's intact, which is the opposite
        # of what a reset means and is not recoverable.
        household_id = uuid.uuid4()
        owner_user_id = uuid.uuid4()

        clause = self.rendered(household_id, owner_user_id)

        # Rendered without hyphens by the dialect, hence `.hex`.
        assert f"owner_user_id = '{owner_user_id.hex}'" in clause
        assert "owner_user_id !=" not in clause

    def test_it_stays_inside_the_household(self) -> None:
        household_id = uuid.uuid4()
        owner_user_id = uuid.uuid4()

        clause = self.rendered(household_id, owner_user_id)

        assert f"household_id = '{household_id.hex}'" in clause

    def test_it_clears_the_name_and_the_note(self) -> None:
        # A note about a client identifies them just as the name does, so it
        # goes with it. Anything left behind is unreadable for ever.
        clause = self.rendered(uuid.uuid4(), uuid.uuid4())

        assert "name_ct=''" in clause.replace(" = ", "=")
        assert "note_ct=NULL" in clause.replace(" = ", "=")
