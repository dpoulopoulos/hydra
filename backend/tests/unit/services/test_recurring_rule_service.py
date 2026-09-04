import uuid
from datetime import date
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

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
) -> RecurringRule:
    """Build a recurring rule row for the tests."""
    return RecurringRule(
        household_id=HOUSEHOLD_ID,
        name="Rent",
        frequency=frequency,
        interval=interval,
        day_of_month=day_of_month,
        start_date=start_date,
        end_date=end_date,
        kind=TransactionKind.EXPENSE,
        amount_minor=amount_minor,
        account_id=uuid.uuid4(),
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
        mock_recurring_rule_service.session.exec.return_value.first.return_value = make_account(
            archived=True
        )

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

        result = mock_recurring_rule_service.materialize_due(
            household=household_context, until=date(2026, 3, 15)
        )

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

        mock_recurring_rule_service.materialize_due(
            household=household_context, until=date(2026, 1, 15)
        )

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

        mock_recurring_rule_service.materialize_due(
            household=household_context, until=date(2026, 3, 15)
        )

        assert rule.last_generated_on == date(2026, 3, 1)
        assert rule.next_occurrence_on == date(2026, 4, 1)

    def test_a_second_pass_creates_nothing(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        rule = make_rule(next_occurrence_on=date(2026, 4, 1))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]

        result = mock_recurring_rule_service.materialize_due(
            household=household_context, until=date(2026, 3, 15)
        )

        assert result.created_count == 0

    def test_exhausts_a_rule_that_has_ended(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        rule = make_rule(next_occurrence_on=date(2026, 4, 1), end_date=date(2026, 3, 31))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]

        result = mock_recurring_rule_service.materialize_due(
            household=household_context, until=date(2026, 6, 1)
        )

        assert result.created_count == 0
        assert rule.next_occurrence_on is None

    def test_stops_at_the_end_date(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        rule = make_rule(next_occurrence_on=date(2026, 1, 1), end_date=date(2026, 2, 15))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]

        result = mock_recurring_rule_service.materialize_due(
            household=household_context, until=date(2026, 6, 1)
        )

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

        result = mock_recurring_rule_service.materialize_due(
            household=household_context, until=date(2026, 1, 1)
        )

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

        mock_recurring_rule_service.materialize_due(
            household=household_context, until=date(2026, 3, 15)
        )

        mock_recurring_rule_service.session.commit.assert_called_once()

    def test_locks_the_rules_it_reads(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """Two members opening the app at once must not create the same occurrence twice."""
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = []

        mock_recurring_rule_service.materialize_due(
            household=household_context, until=date(2026, 3, 15)
        )

        # Compiled against the Postgres dialect, since SKIP LOCKED is not
        # rendered by the generic one.
        statement = str(
            mock_recurring_rule_service.session.exec.call_args.args[0].compile(
                dialect=postgresql.dialect()
            )
        )
        assert "FOR UPDATE" in statement
        assert "SKIP LOCKED" in statement


class TestListUpcoming:
    """Tests for list_upcoming."""

    def test_projects_without_creating_anything(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        rule = make_rule(next_occurrence_on=date(2026, 4, 1))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]

        result = mock_recurring_rule_service.list_upcoming(
            household=household_context, until=date(2026, 6, 15)
        )

        assert [occurrence.occurs_on for occurrence in result.data] == [
            date(2026, 4, 1),
            date(2026, 5, 1),
            date(2026, 6, 1),
        ]
        assert result.total_minor == 360_000
        mock_recurring_rule_service.session.add.assert_not_called()
        mock_recurring_rule_service.session.commit.assert_not_called()

    def test_skips_an_exhausted_rule(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [
            make_rule(next_occurrence_on=None)
        ]

        result = mock_recurring_rule_service.list_upcoming(
            household=household_context, until=date(2026, 6, 15)
        )

        assert result.count == 0


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

        result = mock_recurring_rule_service.list_upcoming(
            household=household_context, until=date(9999, 12, 31)
        )

        assert result.count > 0
        assert all(occurrence.occurs_on <= date(9999, 12, 31) for occurrence in result.data)

    def test_a_rule_stored_with_an_interval_above_the_cap_still_reads(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """Nothing clamps a rule saved before the cap, so a read must survive one."""
        rule = make_rule(
            frequency=RecurrenceFrequency.YEARLY, interval=100_000, next_occurrence_on=date(2026, 4, 1)
        )
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.all.return_value = [rule]

        result = mock_recurring_rule_service.list_upcoming(
            household=household_context, until=date(2026, 6, 15)
        )

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
        mock_recurring_rule_service.session.exec.return_value.first.return_value = rule

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
        mock_recurring_rule_service.session.exec.return_value.first.return_value = rule

        result = mock_recurring_rule_service.update_rule(
            household=household_context, rule_id=rule.id, rule_update=RecurringRuleUpdate(is_active=False)
        )

        assert result.is_active is False

    def test_changing_the_schedule_does_not_move_the_cursor_backwards(
        self, mock_recurring_rule_service: RecurringRuleService, household_context: HouseholdContext
    ) -> None:
        """Otherwise the next pass would create a transaction that already exists."""
        rule = make_rule(next_occurrence_on=date(2026, 4, 1), last_generated_on=date(2026, 3, 1))
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.return_value = rule

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
            start_date=date(2026, 1, 1), next_occurrence_on=date(2026, 1, 1), last_generated_on=None
        )
        mock_recurring_rule_service.session.exec = MagicMock()
        mock_recurring_rule_service.session.exec.return_value.first.return_value = rule

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
        mock_recurring_rule_service.session.exec.return_value.first.return_value = rule

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
