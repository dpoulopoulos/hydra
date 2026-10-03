import uuid
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest

from app.exceptions import (
    AccountArchivedError,
    AccountNotFoundError,
    GoalAccountLockedError,
    GoalAccountNotSavingsError,
    GoalExistsError,
    GoalNotFoundError,
    GoalTransferMismatchError,
    InvalidDateRangeError,
    ReportRangeTooLargeError,
)
from app.models import (
    Account,
    AccountType,
    Goal,
    GoalCreate,
    GoalUpdate,
    HouseholdContext,
    Message,
    TransactionKind,
)
from app.services import GoalService
from app.services.goal import months_left, needed_per_month

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def make_account(name: str = "Savings", account_type: AccountType = AccountType.SAVINGS) -> Account:
    """Build an account row for the tests."""
    return Account(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        name=name,
        type=account_type,
        opening_balance_date=date(2026, 1, 1),
    )


def make_goal(
    account: Account,
    name: str = "New car",
    target_minor: int = 2_000_000,
    target_date: date | None = None,
) -> Goal:
    """Build a goal row for the tests."""
    return Goal(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        account_id=account.id,
        name=name,
        target_minor=target_minor,
        target_date=target_date,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
def service(mock_goal_service: GoalService) -> GoalService:
    """Replace the repositories' reads with mocks the tests program."""
    mock_goal_service.goal_repository = MagicMock()
    mock_goal_service.account_repository = MagicMock()
    mock_goal_service.goal_repository.saved_by_goal.return_value = {}
    mock_goal_service.goal_repository.monthly_for_goals.return_value = []
    mock_goal_service.goal_repository.get_by_name.return_value = None
    mock_goal_service.goal_repository.first_tagged_on.return_value = {}
    mock_goal_service.goal_repository.peak_by_goal.return_value = {}
    return mock_goal_service


class TestMonthsLeft:
    """Tests for months_left."""

    def test_counts_the_current_month(self) -> None:
        assert months_left(date(2026, 12, 31), today=date(2026, 10, 3)) == 3

    def test_is_one_in_the_due_month(self) -> None:
        assert months_left(date(2026, 10, 31), today=date(2026, 10, 3)) == 1

    def test_crosses_years(self) -> None:
        assert months_left(date(2027, 12, 1), today=date(2026, 10, 3)) == 15

    def test_is_zero_once_the_month_has_passed(self) -> None:
        assert months_left(date(2026, 9, 30), today=date(2026, 10, 3)) == 0


class TestNeededPerMonth:
    """Tests for needed_per_month."""

    def test_splits_evenly(self) -> None:
        assert needed_per_month(30_000, 3) == 10_000

    def test_rounds_up_so_the_target_is_reached(self) -> None:
        assert needed_per_month(10_000, 3) == 3_334

    def test_is_zero_once_reached(self) -> None:
        assert needed_per_month(0, 3) == 0

    def test_is_everything_left_when_no_month_is(self) -> None:
        assert needed_per_month(5_000, 0) == 5_000


class TestCreateGoal:
    """Tests for create_goal."""

    def test_creates_a_goal(self, service: GoalService, household_context: HouseholdContext) -> None:
        account = make_account()
        service.account_repository.get_for_household.return_value = account

        result = service.create_goal(
            household=household_context,
            goal_create=GoalCreate(name="New car", account_id=account.id, target_minor=2_000_000),
        )

        assert result.name == "New car"
        assert result.saved_minor == 0
        assert result.remaining_minor == 2_000_000
        assert result.account_name == "Savings"
        service.goal_repository.save.assert_called_once()
        service.session.commit.assert_called_once()

    def test_rejects_an_account_that_is_not_savings(
        self, service: GoalService, household_context: HouseholdContext
    ) -> None:
        account = make_account(name="Everyday", account_type=AccountType.CURRENT)
        service.account_repository.get_for_household.return_value = account

        with pytest.raises(GoalAccountNotSavingsError):
            service.create_goal(
                household=household_context,
                goal_create=GoalCreate(name="Car", account_id=account.id, target_minor=1),
            )

    def test_rejects_an_archived_account(self, service: GoalService, household_context: HouseholdContext) -> None:
        account = make_account()
        account.archived_at = datetime.now(UTC)
        service.account_repository.get_for_household.return_value = account

        with pytest.raises(AccountArchivedError):
            service.create_goal(
                household=household_context,
                goal_create=GoalCreate(name="Car", account_id=account.id, target_minor=1),
            )

    def test_rejects_an_unknown_account(self, service: GoalService, household_context: HouseholdContext) -> None:
        service.account_repository.get_for_household.return_value = None

        with pytest.raises(AccountNotFoundError):
            service.create_goal(
                household=household_context,
                goal_create=GoalCreate(name="Car", account_id=uuid.uuid4(), target_minor=1),
            )

    def test_rejects_a_taken_name(self, service: GoalService, household_context: HouseholdContext) -> None:
        account = make_account()
        service.account_repository.get_for_household.return_value = account
        service.goal_repository.get_by_name.return_value = make_goal(account)

        with pytest.raises(GoalExistsError):
            service.create_goal(
                household=household_context,
                goal_create=GoalCreate(name="New car", account_id=account.id, target_minor=1),
            )

    def test_rejects_a_target_of_zero(self) -> None:
        with pytest.raises(ValueError):
            GoalCreate(name="Car", account_id=uuid.uuid4(), target_minor=0)


class TestListGoals:
    """Tests for list_goals."""

    def test_splits_the_balance_into_goals_and_unassigned(
        self, service: GoalService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        car = make_goal(account, name="Car")
        holiday = make_goal(account, name="Holiday", target_minor=400_000)
        service.goal_repository.list_with_accounts.return_value = [(car, account), (holiday, account)]
        service.goal_repository.saved_by_goal.return_value = {car.id: 800_000, holiday.id: 300_000}
        service.account_repository.balances_of.return_value = {account.id: 1_200_000}

        result = service.list_goals(household=household_context)

        assert result.count == 2
        assert [goal.saved_minor for goal in result.data] == [800_000, 300_000]
        [summary] = result.accounts
        assert summary.balance_minor == 1_200_000
        assert summary.assigned_minor == 1_100_000
        assert summary.unassigned_minor == 100_000

    def test_reports_progress(self, service: GoalService, household_context: HouseholdContext) -> None:
        account = make_account()
        goal = make_goal(account, target_minor=1_000_000)
        service.goal_repository.list_with_accounts.return_value = [(goal, account)]
        service.goal_repository.saved_by_goal.return_value = {goal.id: 250_000}
        service.account_repository.balances_of.return_value = {account.id: 250_000}

        [result] = service.list_goals(household=household_context).data

        assert result.progress == 0.25
        assert result.remaining_minor == 750_000

    def test_reports_the_most_a_goal_ever_held(self, service: GoalService, household_context: HouseholdContext) -> None:
        # Saved up, then spent: it holds nothing now, but it did reach its target.
        account = make_account()
        goal = make_goal(account, target_minor=120_000)
        service.goal_repository.list_with_accounts.return_value = [(goal, account)]
        service.goal_repository.saved_by_goal.return_value = {goal.id: 0}
        service.goal_repository.peak_by_goal.return_value = {goal.id: 120_000}
        service.account_repository.balances_of.return_value = {account.id: 0}

        [result] = service.list_goals(household=household_context).data

        assert result.saved_minor == 0
        assert result.peak_saved_minor == 120_000

    def test_works_out_the_pace_for_a_dated_goal(
        self, service: GoalService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        today = date.today()
        goal = make_goal(account, target_minor=1_000_000, target_date=today)
        service.goal_repository.list_with_accounts.return_value = [(goal, account)]
        service.goal_repository.saved_by_goal.return_value = {goal.id: 400_000}
        service.account_repository.balances_of.return_value = {account.id: 400_000}

        [result] = service.list_goals(household=household_context).data

        assert result.months_left == 1
        assert result.needed_per_month_minor == 600_000
        assert result.on_track is False

    def test_is_on_track_when_recent_saving_keeps_pace(
        self, service: GoalService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        today = date.today()
        goal = make_goal(account, target_minor=1_000_000, target_date=today)
        service.goal_repository.list_with_accounts.return_value = [(goal, account)]
        service.goal_repository.saved_by_goal.return_value = {goal.id: 400_000}
        # 1,800,000 over the three month window averages 600,000: exactly the pace needed.
        service.goal_repository.monthly_for_goals.return_value = [
            (goal.id, date(today.year, today.month, 1), 1_800_000, 0)
        ]
        service.account_repository.balances_of.return_value = {account.id: 400_000}

        [result] = service.list_goals(household=household_context).data

        assert result.average_monthly_minor == 600_000
        assert result.on_track is True

    def test_counts_back_dated_saving_over_the_months_it_covers(
        self, service: GoalService, household_context: HouseholdContext
    ) -> None:
        # Set up today, but tagged onto three months of transfers made before:
        # the pace is one month's worth, not three months' worth.
        account = make_account()
        today = date.today()
        goal = make_goal(account, target_minor=1_000_000, target_date=today)
        goal.created_at = datetime.now(UTC)
        first = date(today.year - 1, 1, 1)
        service.goal_repository.list_with_accounts.return_value = [(goal, account)]
        service.goal_repository.saved_by_goal.return_value = {goal.id: 300_000}
        service.goal_repository.monthly_for_goals.return_value = [
            (goal.id, date(today.year, today.month, 1), 300_000, 0)
        ]
        service.goal_repository.first_tagged_on.return_value = {goal.id: first}
        service.account_repository.balances_of.return_value = {account.id: 300_000}

        [result] = service.list_goals(household=household_context).data

        assert result.average_monthly_minor == 100_000

    def test_judges_a_new_goal_on_its_own_month(
        self, service: GoalService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        today = date.today()
        goal = make_goal(account, target_minor=1_000_000, target_date=today)
        goal.created_at = datetime.now(UTC)
        service.goal_repository.list_with_accounts.return_value = [(goal, account)]
        service.goal_repository.monthly_for_goals.return_value = [
            (goal.id, date(today.year, today.month, 1), 300_000, 0)
        ]
        service.goal_repository.first_tagged_on.return_value = {goal.id: today}
        service.account_repository.balances_of.return_value = {account.id: 300_000}

        [result] = service.list_goals(household=household_context).data

        assert result.average_monthly_minor == 300_000

    def test_has_no_pace_without_a_date(self, service: GoalService, household_context: HouseholdContext) -> None:
        account = make_account()
        goal = make_goal(account)
        service.goal_repository.list_with_accounts.return_value = [(goal, account)]
        service.account_repository.balances_of.return_value = {account.id: 0}

        [result] = service.list_goals(household=household_context).data

        assert result.months_left is None
        assert result.needed_per_month_minor is None
        assert result.on_track is None


class TestUpdateGoal:
    """Tests for update_goal."""

    def test_renames_a_goal(self, service: GoalService, household_context: HouseholdContext) -> None:
        account = make_account()
        goal = make_goal(account)
        service.goal_repository.get_for_household.return_value = goal
        service.account_repository.get_for_household.return_value = account

        result = service.update_goal(household=household_context, goal_id=goal.id, goal_update=GoalUpdate(name="Van"))

        assert result.name == "Van"
        service.session.commit.assert_called_once()

    def test_clears_the_date(self, service: GoalService, household_context: HouseholdContext) -> None:
        account = make_account()
        goal = make_goal(account, target_date=date(2027, 1, 1))
        service.goal_repository.get_for_household.return_value = goal
        service.account_repository.get_for_household.return_value = account

        result = service.update_goal(
            household=household_context, goal_id=goal.id, goal_update=GoalUpdate(target_date=None)
        )

        assert result.target_date is None

    def test_marks_a_goal_reached_once(self, service: GoalService, household_context: HouseholdContext) -> None:
        account = make_account()
        goal = make_goal(account)
        reached = datetime(2026, 5, 1, tzinfo=UTC)
        goal.achieved_at = reached
        service.goal_repository.get_for_household.return_value = goal
        service.account_repository.get_for_household.return_value = account

        result = service.update_goal(
            household=household_context, goal_id=goal.id, goal_update=GoalUpdate(is_achieved=True)
        )

        assert result.achieved_at == reached

    def test_reopens_a_goal(self, service: GoalService, household_context: HouseholdContext) -> None:
        account = make_account()
        goal = make_goal(account)
        goal.achieved_at = datetime(2026, 5, 1, tzinfo=UTC)
        service.goal_repository.get_for_household.return_value = goal
        service.account_repository.get_for_household.return_value = account

        result = service.update_goal(
            household=household_context, goal_id=goal.id, goal_update=GoalUpdate(is_achieved=False)
        )

        assert result.achieved_at is None

    def test_will_not_move_a_goal_that_holds_money(
        self, service: GoalService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        other = make_account(name="Other savings")
        goal = make_goal(account)
        service.goal_repository.get_for_household.return_value = goal
        service.account_repository.get_for_household.return_value = other
        service.goal_repository.has_transfers.return_value = True

        with pytest.raises(GoalAccountLockedError):
            service.update_goal(
                household=household_context, goal_id=goal.id, goal_update=GoalUpdate(account_id=other.id)
            )

    def test_rejects_an_unknown_goal(self, service: GoalService, household_context: HouseholdContext) -> None:
        service.goal_repository.get_for_household.return_value = None

        with pytest.raises(GoalNotFoundError):
            service.update_goal(household=household_context, goal_id=uuid.uuid4(), goal_update=GoalUpdate(name="X"))


class TestDeleteGoal:
    """Tests for delete_goal."""

    def test_deletes_a_goal(self, service: GoalService, household_context: HouseholdContext) -> None:
        goal = make_goal(make_account())
        service.goal_repository.get_for_household.return_value = goal

        result = service.delete_goal(household=household_context, goal_id=goal.id)

        assert isinstance(result, Message)
        service.goal_repository.delete.assert_called_once_with(goal)
        service.session.commit.assert_called_once()


class TestHistory:
    """Tests for history."""

    def test_fills_every_month_and_keeps_a_running_total(
        self, service: GoalService, household_context: HouseholdContext
    ) -> None:
        goal = make_goal(make_account())
        service.goal_repository.get_for_household.return_value = goal
        service.goal_repository.saved_before.return_value = 100_000
        service.goal_repository.monthly_for_goals.return_value = [
            (goal.id, date(2026, 1, 1), 50_000, 0),
            (goal.id, date(2026, 3, 1), 30_000, 10_000),
        ]

        result = service.history(household=household_context, goal_id=goal.id, month_from="2026-01", month_to="2026-03")

        assert [month.month for month in result.months] == ["2026-01", "2026-02", "2026-03"]
        assert [month.net_minor for month in result.months] == [50_000, 0, 20_000]
        assert [month.cumulative_minor for month in result.months] == [150_000, 150_000, 170_000]

    def test_defaults_to_twelve_months(self, service: GoalService, household_context: HouseholdContext) -> None:
        goal = make_goal(make_account())
        service.goal_repository.get_for_household.return_value = goal
        service.goal_repository.saved_before.return_value = 0

        result = service.history(household=household_context, goal_id=goal.id, month_to="2026-03")

        assert result.month_from == "2025-04"
        assert len(result.months) == 12

    def test_rejects_a_backwards_range(self, service: GoalService, household_context: HouseholdContext) -> None:
        service.goal_repository.get_for_household.return_value = make_goal(make_account())

        with pytest.raises(InvalidDateRangeError):
            service.history(household=household_context, goal_id=uuid.uuid4(), month_from="2026-03", month_to="2026-01")

    def test_rejects_a_range_over_ten_years(self, service: GoalService, household_context: HouseholdContext) -> None:
        service.goal_repository.get_for_household.return_value = make_goal(make_account())

        with pytest.raises(ReportRangeTooLargeError):
            service.history(household=household_context, goal_id=uuid.uuid4(), month_from="2010-01", month_to="2026-01")


class TestCheckTag:
    """Tests for check_tag."""

    def test_accepts_a_transfer_into_the_goal_account(
        self, service: GoalService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        goal = make_goal(account)
        service.goal_repository.get_for_household.return_value = goal

        service.check_tag(
            household=household_context,
            goal_id=goal.id,
            kind=TransactionKind.TRANSFER,
            account_id=uuid.uuid4(),
            counter_account_id=account.id,
        )

    def test_accepts_a_transfer_out_of_the_goal_account(
        self, service: GoalService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        goal = make_goal(account)
        service.goal_repository.get_for_household.return_value = goal

        service.check_tag(
            household=household_context,
            goal_id=goal.id,
            kind=TransactionKind.TRANSFER,
            account_id=account.id,
            counter_account_id=uuid.uuid4(),
        )

    def test_rejects_an_expense(self, service: GoalService, household_context: HouseholdContext) -> None:
        account = make_account()
        goal = make_goal(account)
        service.goal_repository.get_for_household.return_value = goal

        with pytest.raises(GoalTransferMismatchError):
            service.check_tag(
                household=household_context,
                goal_id=goal.id,
                kind=TransactionKind.EXPENSE,
                account_id=account.id,
                counter_account_id=None,
            )

    def test_rejects_a_transfer_between_other_accounts(
        self, service: GoalService, household_context: HouseholdContext
    ) -> None:
        goal = make_goal(make_account())
        service.goal_repository.get_for_household.return_value = goal

        with pytest.raises(GoalTransferMismatchError):
            service.check_tag(
                household=household_context,
                goal_id=goal.id,
                kind=TransactionKind.TRANSFER,
                account_id=uuid.uuid4(),
                counter_account_id=uuid.uuid4(),
            )

    def test_rejects_an_unknown_goal(self, service: GoalService, household_context: HouseholdContext) -> None:
        service.goal_repository.get_for_household.return_value = None

        with pytest.raises(GoalNotFoundError):
            service.check_tag(
                household=household_context,
                goal_id=uuid.uuid4(),
                kind=TransactionKind.TRANSFER,
                account_id=uuid.uuid4(),
                counter_account_id=uuid.uuid4(),
            )
