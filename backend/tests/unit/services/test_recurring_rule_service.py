import itertools
import uuid
from collections.abc import Callable
from datetime import date
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.exceptions import (
    AccountArchivedError,
    AccountNotFoundError,
    CategoryNotFoundError,
    InvalidRecurrenceError,
    RecurringRuleNotFoundError,
    SameAccountTransferError,
    TransactionCategoryKindError,
    TransferShapeError,
)
from app.models import (
    Account,
    AccountType,
    Category,
    CategoryKind,
    HouseholdContext,
    Message,
    RecurrenceFrequency,
    RecurringRule,
    RecurringRuleCreate,
    RecurringRuleUpdate,
    Transaction,
    TransactionKind,
)
from app.services import RecurringRuleService

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def make_account(name: str = "Current", archived: bool = False) -> Account:
    """Build an account row for the tests."""
    from datetime import UTC, datetime

    return Account(
        household_id=HOUSEHOLD_ID,
        name=name,
        type=AccountType.CURRENT,
        currency_code="EUR",
        opening_balance_minor=0,
        opening_balance_date=date(2026, 1, 1),
        archived_at=datetime.now(UTC) if archived else None,
    )


def created_transactions(service: RecurringRuleService) -> list[Transaction]:
    """Collect the transactions a materialization pass added to the session."""
    return [call.args[0] for call in service.session.add.call_args_list if isinstance(call.args[0], Transaction)]


def unique_violation(constraint: str = "uq_transaction_rule_occurrence") -> IntegrityError:
    """Build the error Postgres raises when an insert hits a unique index."""
    return IntegrityError(
        "INSERT INTO transaction ...",
        {},
        Exception(f'duplicate key value violates unique constraint "{constraint}"'),
    )


def flush_failing_on(nth: int, error: Exception) -> Callable[[], None]:
    """Build a flush stub that raises on its nth call and passes otherwise."""
    calls = itertools.count(1)

    def flush() -> None:
        if next(calls) == nth:
            raise error

    return flush


def make_category(name: str = "Rent / Mortgage", kind: CategoryKind = CategoryKind.EXPENSE) -> Category:
    """Build a category row for the tests."""
    return Category(household_id=HOUSEHOLD_ID, name=name, kind=kind)


def make_rule(
    frequency: RecurrenceFrequency = RecurrenceFrequency.MONTHLY,
    interval: int = 1,
    day_of_month: int | None = 1,
    start_date: date = date(2026, 1, 1),
    end_date: date | None = None,
    next_occurrence_on: date | None = date(2026, 1, 1),
    last_generated_on: date | None = None,
    amount_minor: int = 120_000,
    kind: TransactionKind = TransactionKind.EXPENSE,
    account_id: uuid.UUID | None = None,
    counter_account_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    name: str = "Rent",
) -> RecurringRule:
    """Build a recurring rule row for the tests."""
    return RecurringRule(
        household_id=HOUSEHOLD_ID,
        name=name,
        frequency=frequency,
        interval=interval,
        day_of_month=day_of_month,
        start_date=start_date,
        end_date=end_date,
        kind=kind,
        amount_minor=amount_minor,
        account_id=account_id or uuid.uuid4(),
        counter_account_id=counter_account_id or (uuid.uuid4() if kind is TransactionKind.TRANSFER else None),
        category_id=category_id,
        next_occurrence_on=next_occurrence_on,
        last_generated_on=last_generated_on,
    )


class TestCreateRule:
    """Tests for create_rule."""

    def test_creates_a_monthly_rule(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        category = make_category()
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.side_effect = [account, category]

        result = mock_recurring_rule_service.create_rule(
            household=household_context,
            rule_create=RecurringRuleCreate(
                name="Rent",
                frequency=RecurrenceFrequency.MONTHLY,
                day_of_month=1,
                start_date=date(2026, 1, 1),
                amount_minor=120_000,
                account_id=account.id,
                category_id=category.id,
            ),
        )

        assert result.next_occurrence_on == date(2026, 1, 1)
        mock_recurring_rule_service.session.commit.assert_called_once()

    def test_the_cursor_waits_for_the_billing_day(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """A rule set up on the 20th that bills on the 15th first falls due next month."""
        account = make_account()
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.return_value = account

        result = mock_recurring_rule_service.create_rule(
            household=household_context,
            rule_create=RecurringRuleCreate(
                name="Netflix",
                day_of_month=15,
                start_date=date(2026, 3, 20),
                amount_minor=1_299,
                account_id=account.id,
            ),
        )

        assert result.next_occurrence_on == date(2026, 4, 15)

    def test_rejects_a_rule_that_ends_before_it_starts(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.return_value = account

        with pytest.raises(InvalidRecurrenceError):
            mock_recurring_rule_service.create_rule(
                household=household_context,
                rule_create=RecurringRuleCreate(
                    name="Gym",
                    start_date=date(2026, 6, 1),
                    end_date=date(2026, 1, 1),
                    amount_minor=3_000,
                    account_id=account.id,
                ),
            )

    def test_rejects_a_rule_that_would_never_come_due(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """The billing day falls after the rule has already ended."""
        account = make_account()
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.return_value = account

        with pytest.raises(InvalidRecurrenceError):
            mock_recurring_rule_service.create_rule(
                household=household_context,
                rule_create=RecurringRuleCreate(
                    name="Gym",
                    day_of_month=28,
                    start_date=date(2026, 3, 1),
                    end_date=date(2026, 3, 10),
                    amount_minor=3_000,
                    account_id=account.id,
                ),
            )

    def test_rejects_a_start_date_with_no_room_left_on_the_calendar(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """The first occurrence would fall past the last date there is: a 400, not a 500."""
        account = make_account()
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.return_value = account

        with pytest.raises(InvalidRecurrenceError):
            mock_recurring_rule_service.create_rule(
                household=household_context,
                rule_create=RecurringRuleCreate(
                    name="Gym",
                    day_of_month=1,
                    start_date=date(9999, 12, 31),
                    amount_minor=3_000,
                    account_id=account.id,
                ),
            )

    def test_rejects_a_zero_interval(self) -> None:
        with pytest.raises(ValueError):
            RecurringRuleCreate(
                name="Gym",
                interval=0,
                start_date=date(2026, 1, 1),
                amount_minor=1,
                account_id=uuid.uuid4(),
            )

    def test_rejects_a_day_beyond_the_calendar(self) -> None:
        with pytest.raises(ValueError):
            RecurringRuleCreate(
                name="Gym",
                day_of_month=32,
                start_date=date(2026, 1, 1),
                amount_minor=1,
                account_id=uuid.uuid4(),
            )

    def test_rejects_an_archived_account(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account(archived=True)

        with pytest.raises(AccountArchivedError):
            mock_recurring_rule_service.create_rule(
                household=household_context,
                rule_create=RecurringRuleCreate(
                    name="Rent",
                    start_date=date(2026, 1, 1),
                    amount_minor=1,
                    account_id=uuid.uuid4(),
                ),
            )

    def test_rejects_an_account_from_another_household(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.return_value = None

        with pytest.raises(AccountNotFoundError):
            mock_recurring_rule_service.create_rule(
                household=household_context,
                rule_create=RecurringRuleCreate(
                    name="Rent",
                    start_date=date(2026, 1, 1),
                    amount_minor=1,
                    account_id=uuid.uuid4(),
                ),
            )

    def test_rejects_a_category_from_another_household(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.side_effect = [account, None]

        with pytest.raises(CategoryNotFoundError):
            mock_recurring_rule_service.create_rule(
                household=household_context,
                rule_create=RecurringRuleCreate(
                    name="Rent",
                    start_date=date(2026, 1, 1),
                    amount_minor=1,
                    account_id=account.id,
                    category_id=uuid.uuid4(),
                ),
            )

    def test_rejects_an_income_category_on_an_expense_rule(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        category = make_category(name="Salary", kind=CategoryKind.INCOME)
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.side_effect = [account, category]

        with pytest.raises(TransactionCategoryKindError):
            mock_recurring_rule_service.create_rule(
                household=household_context,
                rule_create=RecurringRuleCreate(
                    name="Rent",
                    start_date=date(2026, 1, 1),
                    amount_minor=1,
                    account_id=account.id,
                    category_id=category.id,
                ),
            )

    def test_rejects_a_transfer_rule_with_no_destination(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        with pytest.raises(TransferShapeError):
            mock_recurring_rule_service.create_rule(
                household=household_context,
                rule_create=RecurringRuleCreate(
                    name="To savings",
                    kind=TransactionKind.TRANSFER,
                    start_date=date(2026, 1, 1),
                    amount_minor=20_000,
                    account_id=uuid.uuid4(),
                ),
            )

    def test_rejects_a_transfer_rule_to_the_same_account(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.return_value = account

        with pytest.raises(SameAccountTransferError):
            mock_recurring_rule_service.create_rule(
                household=household_context,
                rule_create=RecurringRuleCreate(
                    name="To savings",
                    kind=TransactionKind.TRANSFER,
                    start_date=date(2026, 1, 1),
                    amount_minor=20_000,
                    account_id=account.id,
                    counter_account_id=account.id,
                ),
            )


class TestMaterializeDue:
    """Tests for materialize_due."""

    def test_creates_every_occurrence_that_has_fallen_due(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        rule = make_rule(next_occurrence_on=date(2026, 1, 1))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account()

        result = mock_recurring_rule_service.materialize_due(household=household_context, until=date(2026, 3, 15))

        assert result.created_count == 3
        assert result.rules_advanced == 1
        dates = [
            call.args[0].occurred_on
            for call in mock_recurring_rule_service.session.add.call_args_list
            if hasattr(call.args[0], "occurred_on")
        ]
        assert dates == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]

    def test_marks_the_transactions_as_generated(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        rule = make_rule(next_occurrence_on=date(2026, 1, 1))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account()

        mock_recurring_rule_service.materialize_due(household=household_context, until=date(2026, 1, 15))

        created = [
            call.args[0]
            for call in mock_recurring_rule_service.session.add.call_args_list
            if hasattr(call.args[0], "occurred_on")
        ]
        assert created[0].is_generated is True
        assert created[0].recurring_rule_id == rule.id

    def test_moves_the_cursor_past_what_it_created(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """The cursor only ever moves forward, which is what makes a second pass a no-op."""
        rule = make_rule(next_occurrence_on=date(2026, 1, 1))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account()

        mock_recurring_rule_service.materialize_due(household=household_context, until=date(2026, 3, 15))

        assert rule.last_generated_on == date(2026, 3, 1)
        assert rule.next_occurrence_on == date(2026, 4, 1)

    def test_a_second_pass_creates_nothing(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        rule = make_rule(next_occurrence_on=date(2026, 4, 1))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account()

        result = mock_recurring_rule_service.materialize_due(household=household_context, until=date(2026, 3, 15))

        assert result.created_count == 0

    def test_exhausts_a_rule_that_has_ended(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        rule = make_rule(next_occurrence_on=date(2026, 4, 1), end_date=date(2026, 3, 31))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account()

        result = mock_recurring_rule_service.materialize_due(household=household_context, until=date(2026, 6, 1))

        assert result.created_count == 0
        assert rule.next_occurrence_on is None

    def test_stops_at_the_end_date(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        rule = make_rule(next_occurrence_on=date(2026, 1, 1), end_date=date(2026, 2, 15))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account()

        result = mock_recurring_rule_service.materialize_due(household=household_context, until=date(2026, 6, 1))

        assert result.created_count == 2
        assert rule.next_occurrence_on is None

    def test_caps_a_runaway_rule(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """A rule dated decades ago must not insert thousands of rows at once."""
        rule = make_rule(
            frequency=RecurrenceFrequency.WEEKLY,
            day_of_month=None,
            start_date=date(1990, 1, 1),
            next_occurrence_on=date(1990, 1, 1),
        )
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account()

        result = mock_recurring_rule_service.materialize_due(household=household_context, until=date(2026, 1, 1))

        assert result.created_count == 500

    def test_commits_once_for_everything(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """So a failure part way cannot leave the cursors ahead of the ledger."""
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [
            make_rule(next_occurrence_on=date(2026, 1, 1)),
            make_rule(next_occurrence_on=date(2026, 2, 1)),
        ]
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account()

        mock_recurring_rule_service.materialize_due(household=household_context, until=date(2026, 3, 15))

        mock_recurring_rule_service.session.commit.assert_called_once()

    def test_locks_the_rules_it_reads(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """Two members opening the app at once must not create the same occurrence twice."""
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = []
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account()

        mock_recurring_rule_service.materialize_due(household=household_context, until=date(2026, 3, 15))

        # Compiled against the Postgres dialect, since SKIP LOCKED is not
        # rendered by the generic one.
        # SQLAlchemy leaves dialect() unannotated, so the call is untyped here.
        dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
        statement = str(mock_recurring_rule_service.session.exec.call_args.args[0].compile(dialect=dialect))
        assert "FOR UPDATE" in statement
        assert "SKIP LOCKED" in statement

    def test_does_not_generate_into_an_archived_account(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """The manual path refuses an archived account, so a rule must not write one either."""
        rule = make_rule(next_occurrence_on=date(2026, 1, 1))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account(archived=True)

        result = mock_recurring_rule_service.materialize_due(household=household_context, until=date(2026, 3, 15))

        assert created_transactions(mock_recurring_rule_service) == []
        assert result.created_count == 0
        assert result.skipped_count == 3

    def test_leaves_the_cursor_alone_when_the_account_is_archived(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """So unarchiving the account picks the rule up where it left off."""
        rule = make_rule(next_occurrence_on=date(2026, 1, 1))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account(archived=True)

        result = mock_recurring_rule_service.materialize_due(household=household_context, until=date(2026, 3, 15))

        assert rule.next_occurrence_on == date(2026, 1, 1)
        assert rule.last_generated_on is None
        assert result.rules_advanced == 0

    def test_skips_a_rule_whose_account_has_gone(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """A page load must not turn into a 404 because one rule lost its account."""
        rule = make_rule(next_occurrence_on=date(2026, 1, 1))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]
        mock_recurring_rule_service.session.exec.return_value.first.return_value = None

        result = mock_recurring_rule_service.materialize_due(household=household_context, until=date(2026, 3, 15))

        assert created_transactions(mock_recurring_rule_service) == []
        assert result.created_count == 0
        assert result.skipped_count == 3

    def test_checks_the_destination_account_of_a_transfer(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """Both sides of a transfer have to be able to take the money."""
        rule = make_rule(
            next_occurrence_on=date(2026, 1, 1),
            kind=TransactionKind.TRANSFER,
            counter_account_id=uuid.uuid4(),
        )
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]
        mock_recurring_rule_service.session.exec.return_value.first.side_effect = [
            make_account(),
            make_account(name="Savings", archived=True),
        ]

        result = mock_recurring_rule_service.materialize_due(household=household_context, until=date(2026, 3, 15))

        assert created_transactions(mock_recurring_rule_service) == []
        assert result.created_count == 0

    def test_one_unusable_rule_does_not_hold_up_the_rest(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [
            make_rule(next_occurrence_on=date(2026, 1, 1)),
            make_rule(next_occurrence_on=date(2026, 1, 1)),
        ]
        mock_recurring_rule_service.session.exec.return_value.first.side_effect = [
            make_account(archived=True),
            make_account(),
        ]

        result = mock_recurring_rule_service.materialize_due(household=household_context, until=date(2026, 3, 15))

        assert result.created_count == 3
        assert result.skipped_count == 3
        assert result.rules_advanced == 1

    def test_an_occurrence_another_request_already_wrote_is_skipped(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """The unique index must cost the racing request an occurrence, not the page it ran under."""
        rule = make_rule(next_occurrence_on=date(2026, 1, 1))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account()
        mock_recurring_rule_service.session.flush.side_effect = flush_failing_on(2, unique_violation())

        result = mock_recurring_rule_service.materialize_due(household=household_context, until=date(2026, 3, 15))

        assert result.created_count == 2
        assert result.skipped_count == 1

    def test_a_duplicate_is_rolled_back_to_the_savepoint(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """Without the savepoint the whole pass would be an aborted transaction."""
        rule = make_rule(next_occurrence_on=date(2026, 1, 1))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account()
        mock_recurring_rule_service.session.flush.side_effect = flush_failing_on(1, unique_violation())

        mock_recurring_rule_service.materialize_due(household=household_context, until=date(2026, 1, 15))

        mock_recurring_rule_service.session.begin_nested.return_value.rollback.assert_called_once()
        mock_recurring_rule_service.session.commit.assert_called_once()

    def test_the_cursor_still_moves_past_a_duplicate(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """The occurrence exists, written by the request that won the race."""
        rule = make_rule(next_occurrence_on=date(2026, 1, 1))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account()
        mock_recurring_rule_service.session.flush.side_effect = flush_failing_on(1, unique_violation())

        mock_recurring_rule_service.materialize_due(household=household_context, until=date(2026, 1, 15))

        assert rule.next_occurrence_on == date(2026, 2, 1)

    def test_an_unrelated_integrity_error_is_not_swallowed(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """A broken reference is a bug to be seen, not an occurrence to skip."""
        rule = make_rule(next_occurrence_on=date(2026, 1, 1))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account()
        mock_recurring_rule_service.session.flush.side_effect = flush_failing_on(
            1, unique_violation("fk_transaction_account_household")
        )

        with pytest.raises(IntegrityError):
            mock_recurring_rule_service.materialize_due(household=household_context, until=date(2026, 1, 15))


class TestListUpcoming:
    """Tests for list_upcoming."""

    def test_projects_without_creating_anything(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        rule = make_rule(next_occurrence_on=date(2026, 4, 1))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account()

        result = mock_recurring_rule_service.list_upcoming(household=household_context, until=date(2026, 6, 15))

        assert [occurrence.occurs_on for occurrence in result.data] == [
            date(2026, 4, 1),
            date(2026, 5, 1),
            date(2026, 6, 1),
        ]
        assert result.net_minor == -360_000
        mock_recurring_rule_service.session.add.assert_not_called()
        mock_recurring_rule_service.session.commit.assert_not_called()

    def test_the_net_signs_income_and_expenses_and_leaves_transfers_out(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """An amount is a magnitude, so the headline has to read the kind to mean anything."""
        rules = [
            make_rule(name="Rent", amount_minor=120_000, next_occurrence_on=date(2026, 4, 1)),
            make_rule(
                name="Salary",
                kind=TransactionKind.INCOME,
                amount_minor=300_000,
                next_occurrence_on=date(2026, 4, 25),
            ),
            make_rule(
                name="To savings",
                kind=TransactionKind.TRANSFER,
                amount_minor=50_000,
                next_occurrence_on=date(2026, 4, 28),
            ),
        ]
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = rules
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account()

        result = mock_recurring_rule_service.list_upcoming(household=household_context, until=date(2026, 4, 30))

        assert result.count == 3
        assert result.net_minor == 180_000

    def test_a_window_of_only_transfers_nets_to_nothing(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """A transfer moves money between the household's own accounts."""
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [
            make_rule(
                name="To savings",
                kind=TransactionKind.TRANSFER,
                amount_minor=50_000,
                next_occurrence_on=date(2026, 4, 1),
            )
        ]
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account()

        result = mock_recurring_rule_service.list_upcoming(household=household_context, until=date(2026, 4, 30))

        assert result.count == 1
        assert result.net_minor == 0

    def test_skips_an_exhausted_rule(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [make_rule(next_occurrence_on=None)]

        result = mock_recurring_rule_service.list_upcoming(household=household_context, until=date(2026, 6, 15))

        assert result.count == 0

    def test_marks_the_occurrences_of_a_rule_whose_account_is_archived(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """The pass steps over this rule, so the list must not promise the payment as if it will happen."""
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [
            make_rule(next_occurrence_on=date(2026, 4, 1))
        ]
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account(archived=True)

        result = mock_recurring_rule_service.list_upcoming(household=household_context, until=date(2026, 6, 15))

        assert result.count == 3
        assert all(occurrence.is_blocked for occurrence in result.data)

    def test_a_blocked_rule_is_left_out_of_the_net(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """Counting it would put money in the total that is not going to move."""
        archived = make_account(name="Old Current", archived=True)
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [
            make_rule(name="Rent", amount_minor=120_000, account_id=archived.id, next_occurrence_on=date(2026, 4, 1)),
            make_rule(
                name="Salary",
                kind=TransactionKind.INCOME,
                amount_minor=300_000,
                next_occurrence_on=date(2026, 4, 25),
            ),
        ]
        mock_recurring_rule_service.session.exec.return_value.first.side_effect = [archived, make_account()]

        result = mock_recurring_rule_service.list_upcoming(household=household_context, until=date(2026, 4, 30))

        assert result.count == 2
        assert result.net_minor == 300_000

    def test_marks_the_occurrences_of_a_rule_whose_account_has_gone(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """A projection must not turn into a 404 because one rule lost its account."""
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [
            make_rule(next_occurrence_on=date(2026, 4, 1))
        ]
        mock_recurring_rule_service.session.exec.return_value.first.return_value = None

        result = mock_recurring_rule_service.list_upcoming(household=household_context, until=date(2026, 6, 15))

        assert all(occurrence.is_blocked for occurrence in result.data)
        assert result.net_minor == 0

    def test_marks_a_transfer_whose_destination_is_archived(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """Both sides have to be able to take the money, as the pass itself checks."""
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [
            make_rule(
                name="To savings",
                kind=TransactionKind.TRANSFER,
                next_occurrence_on=date(2026, 4, 1),
            )
        ]
        mock_recurring_rule_service.session.exec.return_value.first.side_effect = [
            make_account(),
            make_account(name="Savings", archived=True),
        ]

        result = mock_recurring_rule_service.list_upcoming(household=household_context, until=date(2026, 4, 30))

        assert all(occurrence.is_blocked for occurrence in result.data)

    def test_asks_about_each_account_once_for_the_whole_listing(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """Otherwise a page of rules on one account is a lookup per rule."""
        account = make_account()
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [
            make_rule(name="Rent", account_id=account.id, next_occurrence_on=date(2026, 4, 1)),
            make_rule(name="Gym", account_id=account.id, next_occurrence_on=date(2026, 4, 2)),
        ]
        mock_recurring_rule_service.session.exec.return_value.first.side_effect = [account]

        result = mock_recurring_rule_service.list_upcoming(household=household_context, until=date(2026, 4, 30))

        assert result.count == 2
        assert not any(occurrence.is_blocked for occurrence in result.data)


class TestSchedulesPastTheCalendar:
    """A schedule that runs out of calendar ends, rather than raising a 500."""

    @pytest.mark.parametrize(
        ("frequency", "interval"),
        [
            (RecurrenceFrequency.YEARLY, 1200),
            (RecurrenceFrequency.WEEKLY, 1),
        ],
    )
    def test_looking_ahead_to_the_last_date_there_is(
        self,
        mock_recurring_rule_service: RecurringRuleService,
        household_context: HouseholdContext,
        frequency: RecurrenceFrequency,
        interval: int,
    ) -> None:
        rule = make_rule(frequency=frequency, interval=interval, next_occurrence_on=date(9990, 1, 1))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]

        result = mock_recurring_rule_service.list_upcoming(household=household_context, until=date(9999, 12, 31))

        assert result.count > 0
        assert all(occurrence.occurs_on <= date(9999, 12, 31) for occurrence in result.data)

    def test_a_rule_stored_with_an_interval_above_the_cap_still_reads(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """Nothing clamps a rule saved before the cap, so a read must survive one."""
        rule = make_rule(frequency=RecurrenceFrequency.YEARLY, interval=100_000, next_occurrence_on=date(2026, 4, 1))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]

        result = mock_recurring_rule_service.list_upcoming(household=household_context, until=date(2026, 6, 15))

        assert [occurrence.occurs_on for occurrence in result.data] == [date(2026, 4, 1)]

    def test_a_rule_that_runs_out_of_calendar_is_exhausted(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        rule = make_rule(
            frequency=RecurrenceFrequency.YEARLY,
            interval=1200,
            day_of_month=None,
            next_occurrence_on=date(9990, 1, 1),
        )
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account()

        mock_recurring_rule_service.materialize_due(household=household_context, until=date(9999, 12, 31))

        assert rule.last_generated_on == date(9990, 1, 1)
        assert rule.next_occurrence_on is None


class TestUpdateRule:
    """Tests for update_rule."""

    def test_changes_the_amount(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        rule = make_rule()
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.side_effect = [rule]

        result = mock_recurring_rule_service.update_rule(
            household=household_context,
            rule_id=rule.id,
            rule_update=RecurringRuleUpdate(amount_minor=130_000),
        )

        assert result.amount_minor == 130_000

    def test_pauses_a_rule(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        rule = make_rule()
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.side_effect = [rule]

        result = mock_recurring_rule_service.update_rule(
            household=household_context, rule_id=rule.id, rule_update=RecurringRuleUpdate(is_active=False)
        )

        assert result.is_active is False

    def test_pauses_a_rule_whose_account_has_been_archived(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """Otherwise there would be no way to pause or fix such a rule short of deleting it."""
        account = make_account(archived=True)
        rule = make_rule(account_id=account.id)
        mock_recurring_rule_service.session.exec = MagicMock()
        # The account is offered, so an edit that looked it up would be refused.
        mock_recurring_rule_service.session.exec.return_value.first.side_effect = [rule, account]

        result = mock_recurring_rule_service.update_rule(
            household=household_context, rule_id=rule.id, rule_update=RecurringRuleUpdate(is_active=False)
        )

        assert result.is_active is False

    def test_rejects_a_category_on_a_transfer_rule(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """The stored rule already says what kind it is, so the category cannot be judged on its own."""
        rule = make_rule(kind=TransactionKind.TRANSFER, counter_account_id=uuid.uuid4())
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.return_value = rule

        with pytest.raises(TransferShapeError):
            mock_recurring_rule_service.update_rule(
                household=household_context,
                rule_id=rule.id,
                rule_update=RecurringRuleUpdate(category_id=uuid.uuid4()),
            )

        mock_recurring_rule_service.session.commit.assert_not_called()

    def test_changing_the_schedule_does_not_move_the_cursor_backwards(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """Otherwise the next pass would create a transaction that already exists."""
        rule = make_rule(next_occurrence_on=date(2026, 4, 1), last_generated_on=date(2026, 3, 1))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.side_effect = [rule]

        result = mock_recurring_rule_service.update_rule(
            household=household_context,
            rule_id=rule.id,
            rule_update=RecurringRuleUpdate(interval=2),
        )

        assert result.next_occurrence_on == date(2026, 5, 1)

    def test_changing_the_schedule_before_anything_ran_uses_the_start_date(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        rule = make_rule(
            start_date=date(2026, 1, 1),
            next_occurrence_on=date(2026, 1, 1),
            last_generated_on=None,
        )
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.side_effect = [rule]

        result = mock_recurring_rule_service.update_rule(
            household=household_context,
            rule_id=rule.id,
            rule_update=RecurringRuleUpdate(day_of_month=15),
        )

        assert result.next_occurrence_on == date(2026, 1, 15)

    def test_rejects_an_end_date_before_the_start(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        rule = make_rule(start_date=date(2026, 3, 1))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.side_effect = [rule]

        with pytest.raises(InvalidRecurrenceError):
            mock_recurring_rule_service.update_rule(
                household=household_context,
                rule_id=rule.id,
                rule_update=RecurringRuleUpdate(end_date=date(2026, 1, 1)),
            )

    def test_a_rule_from_another_household_is_not_found(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.return_value = None

        with pytest.raises(RecurringRuleNotFoundError):
            mock_recurring_rule_service.update_rule(
                household=household_context,
                rule_id=uuid.uuid4(),
                rule_update=RecurringRuleUpdate(amount_minor=1),
            )

    def test_rejects_giving_a_transfer_rule_a_category(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """A transfer carries no category, so the edit is refused instead of failing the flush."""
        rule = make_rule(kind=TransactionKind.TRANSFER, counter_account_id=uuid.uuid4())
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.side_effect = [rule]

        with pytest.raises(TransferShapeError):
            mock_recurring_rule_service.update_rule(
                household=household_context,
                rule_id=rule.id,
                rule_update=RecurringRuleUpdate(category_id=uuid.uuid4()),
            )

    def test_rejects_a_category_from_another_household(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        rule = make_rule()
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.side_effect = [rule, None]

        with pytest.raises(CategoryNotFoundError):
            mock_recurring_rule_service.update_rule(
                household=household_context,
                rule_id=rule.id,
                rule_update=RecurringRuleUpdate(category_id=uuid.uuid4()),
            )

    def test_rejects_an_income_category_on_an_expense_rule(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        category = make_category(name="Salary", kind=CategoryKind.INCOME)
        rule = make_rule()
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.side_effect = [rule, category]

        with pytest.raises(TransactionCategoryKindError):
            mock_recurring_rule_service.update_rule(
                household=household_context,
                rule_id=rule.id,
                rule_update=RecurringRuleUpdate(category_id=category.id),
            )


class TestDeleteRule:
    """Tests for delete_rule."""

    def test_deletes_the_rule_but_keeps_its_transactions(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        rule = make_rule()
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.return_value = rule

        result = mock_recurring_rule_service.delete_rule(household=household_context, rule_id=rule.id)

        assert isinstance(result, Message)
        assert "kept" in result.message
        mock_recurring_rule_service.session.delete.assert_called_once_with(rule)
