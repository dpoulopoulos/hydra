import datetime
import uuid
from collections import defaultdict
from collections.abc import Sequence

from sqlmodel import Session

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
    GoalAccountSummary,
    GoalCreate,
    GoalHistory,
    GoalMonth,
    GoalPublic,
    GoalsPublic,
    GoalUpdate,
    HouseholdContext,
    Message,
    TransactionKind,
)
from app.models.fields import month_bounds, month_key_of, month_start
from app.repositories.account import AccountRepository
from app.repositories.goal import GoalRepository

# How many recent months the on-track check averages over. Long enough that
# one skipped month does not flip a goal off track, short enough that a change
# of habit shows within a season.
PACE_WINDOW_MONTHS = 3

# The default span of a goal's history, and the most one request may ask for.
DEFAULT_HISTORY_MONTHS = 12
MAX_HISTORY_MONTHS = 120


def month_index(value: datetime.date) -> int:
    """Number a month so that consecutive months differ by one.

    Args:
        value: Any day in the month.

    Returns:
        A month count since year zero.
    """
    return value.year * 12 + value.month - 1


def months_left(target_date: datetime.date, today: datetime.date) -> int:
    """Count the months still open for saving, the current one included.

    A goal due in December, seen in October, has October, November and
    December left: three months.

    Args:
        target_date: The day the goal is due.
        today: The current day.

    Returns:
        The number of months left, or zero once the due month has passed.
    """
    return max(0, month_index(target_date) - month_index(today) + 1)


def needed_per_month(remaining_minor: int, months: int) -> int:
    """Work out what each remaining month has to add to reach a target.

    Rounded up, so saving exactly this much every month does reach the target
    rather than falling a cent short.

    Args:
        remaining_minor: What is still missing, in minor units.
        months: The months left to save in.

    Returns:
        The amount per month. All of what remains when no month is left, and
        zero once the target is reached.
    """
    if remaining_minor <= 0:
        return 0

    if months <= 0:
        return remaining_minor

    return -(-remaining_minor // months)


class GoalService:
    """Provide services for savings goals.

    A goal lives in a savings account and holds the transfers tagged with it.
    Several goals can share one account. The part of the account's balance no
    goal holds is its unassigned money, so the goals of an account and its
    unassigned share always add up to its balance.
    """

    def __init__(
        self,
        session: Session,
        goal_repository: GoalRepository,
        account_repository: AccountRepository,
    ) -> None:
        """Initialize the goal service.

        Args:
            session: The database session.
            goal_repository: The goal repository instance.
            account_repository: The account repository instance.
        """
        self.session = session
        self.goal_repository = goal_repository
        self.account_repository = account_repository

    def create_goal(self, household: HouseholdContext, goal_create: GoalCreate) -> GoalPublic:
        """Set up a goal to save towards.

        Args:
            household: The household context.
            goal_create: The goal.

        Returns:
            The created goal.

        Raises:
            AccountNotFoundError: If the account does not exist in the household.
            AccountArchivedError: If the account is archived.
            GoalAccountNotSavingsError: If the account is not a savings account.
            GoalExistsError: If the household already has a goal with that name.
        """
        account = self._require_savings_account(household=household, account_id=goal_create.account_id)
        self._check_name_free(household=household, name=goal_create.name)

        goal = Goal.model_validate(goal_create, update={"household_id": household.household_id})
        self.goal_repository.save(goal)
        self.session.commit()

        return self._to_public(goal=goal, account=account, saved_minor=0, peak_minor=0, monthly={}, first_tagged=None)

    def list_goals(self, household: HouseholdContext) -> GoalsPublic:
        """List the goals of the household, and how each account splits across them.

        Args:
            household: The household context.

        Returns:
            The goals, and one summary per savings account that holds a goal.
        """
        pairs = self.goal_repository.list_with_accounts(household_id=household.household_id)
        goals = [goal for goal, _ in pairs]
        saved = self.goal_repository.saved_by_goal(goals=goals, household_id=household.household_id)
        peaks = self.goal_repository.peak_by_goal(goals=goals, household_id=household.household_id)
        monthly = self._recent_months(household=household, goals=goals)
        first_tagged = self.goal_repository.first_tagged_on(
            goal_ids=[goal.id for goal in goals], household_id=household.household_id
        )

        data = [
            self._to_public(
                goal=goal,
                account=account,
                saved_minor=saved.get(goal.id, 0),
                peak_minor=peaks.get(goal.id, 0),
                monthly=monthly.get(goal.id, {}),
                first_tagged=first_tagged.get(goal.id),
            )
            for goal, account in pairs
        ]

        return GoalsPublic(data=data, count=len(data), accounts=self._account_summaries(household, pairs, saved))

    def get_goal(self, household: HouseholdContext, goal_id: uuid.UUID) -> GoalPublic:
        """Get one goal of the household.

        Args:
            household: The household context.
            goal_id: The ID of the goal.

        Returns:
            The goal.

        Raises:
            GoalNotFoundError: If the goal does not exist in the household.
        """
        goal = self._require_goal(household=household, goal_id=goal_id)
        return self._with_progress(household=household, goal=goal)

    def update_goal(self, household: HouseholdContext, goal_id: uuid.UUID, goal_update: GoalUpdate) -> GoalPublic:
        """Edit a goal.

        Args:
            household: The household context.
            goal_id: The ID of the goal.
            goal_update: The fields to change.

        Returns:
            The updated goal.

        Raises:
            GoalNotFoundError: If the goal does not exist in the household.
            AccountNotFoundError: If the new account does not exist in the household.
            AccountArchivedError: If the new account is archived.
            GoalAccountNotSavingsError: If the new account is not a savings account.
            GoalAccountLockedError: If the account changes while transfers are tagged with the goal.
            GoalExistsError: If another goal already has the new name.
        """
        goal = self._require_goal(household=household, goal_id=goal_id)
        fields = goal_update.model_dump(exclude_unset=True)

        if (account_id := fields.get("account_id")) is not None and account_id != goal.account_id:
            self._require_savings_account(household=household, account_id=account_id)

            if self.goal_repository.has_transfers(goal_id=goal.id, household_id=household.household_id):
                raise GoalAccountLockedError from None

        if (name := fields.get("name")) is not None and name != goal.name:
            self._check_name_free(household=household, name=name)

        # Sent as a flag rather than a time, so the server's clock decides when
        # the goal was reached and a second "done" does not move the date.
        if (is_achieved := fields.pop("is_achieved", None)) is not None:
            if not is_achieved:
                goal.achieved_at = None
            elif goal.achieved_at is None:
                goal.achieved_at = datetime.datetime.now(datetime.UTC)

        # Null is meaningful for the date alone: it clears the deadline. For
        # the other fields it would break a NOT NULL column.
        goal.sqlmodel_update({key: value for key, value in fields.items() if value is not None or key == "target_date"})
        self.goal_repository.save(goal)
        self.session.commit()

        return self._with_progress(household=household, goal=goal)

    def delete_goal(self, household: HouseholdContext, goal_id: uuid.UUID) -> Message:
        """Delete a goal.

        The transfers tagged with it stay, since they happened. Only the tag is
        cleared, by the foreign key, so their money falls back to the account's
        unassigned share and the account's balance does not change.

        Args:
            household: The household context.
            goal_id: The ID of the goal.

        Returns:
            A confirmation message.

        Raises:
            GoalNotFoundError: If the goal does not exist in the household.
        """
        goal = self._require_goal(household=household, goal_id=goal_id)
        self.goal_repository.delete(goal)
        self.session.commit()

        return Message(message="Goal deleted.")

    def history(
        self,
        household: HouseholdContext,
        goal_id: uuid.UUID,
        month_from: str | None = None,
        month_to: str | None = None,
    ) -> GoalHistory:
        """Show what a goal saved, month by month.

        Every month of the range is present, with zeros where nothing was
        tagged, so a chart has no gaps to bridge.

        Args:
            household: The household context.
            goal_id: The ID of the goal.
            month_from: The first month, "YYYY-MM". Defaults to eleven months
                before the last one.
            month_to: The last month, "YYYY-MM". Defaults to the current month.

        Returns:
            The goal's monthly history.

        Raises:
            GoalNotFoundError: If the goal does not exist in the household.
            InvalidDateRangeError: If the range starts after it ends.
            ReportRangeTooLargeError: If more than ten years are asked for.
        """
        goal = self._require_goal(household=household, goal_id=goal_id)

        month_to = month_to or month_key_of(datetime.date.today())
        if month_from is None:
            last = month_index(month_start(month_to)) - (DEFAULT_HISTORY_MONTHS - 1)
            month_from = f"{last // 12:04d}-{last % 12 + 1:02d}"

        date_from, _ = month_bounds(month_from)
        _, date_to = month_bounds(month_to)

        if date_from > date_to:
            raise InvalidDateRangeError from None

        if month_index(date_to) - month_index(date_from) + 1 > MAX_HISTORY_MONTHS:
            raise ReportRangeTooLargeError(limit="ten years of monthly figures") from None

        rows = self.goal_repository.monthly_for_goals(
            goal_ids=[goal.id], household_id=household.household_id, date_from=date_from, date_to=date_to
        )
        flows = {month: (money_in, money_out) for _, month, money_in, money_out in rows}
        cumulative = self.goal_repository.saved_before(
            goal_id=goal.id, household_id=household.household_id, before=date_from
        )

        months = []
        for index in range(month_index(date_from), month_index(date_to) + 1):
            month = datetime.date(index // 12, index % 12 + 1, 1)
            money_in, money_out = flows.get(month, (0, 0))
            cumulative += money_in - money_out
            months.append(
                GoalMonth(
                    month=month_key_of(month),
                    saved_in_minor=money_in,
                    saved_out_minor=money_out,
                    net_minor=money_in - money_out,
                    cumulative_minor=cumulative,
                )
            )

        return GoalHistory(goal_id=goal.id, month_from=month_from, month_to=month_to, months=months)

    def check_tag(
        self,
        household: HouseholdContext,
        goal_id: uuid.UUID,
        kind: TransactionKind,
        account_id: uuid.UUID,
        counter_account_id: uuid.UUID | None,
    ) -> None:
        """Check that a transaction may be tagged with a goal.

        Only a transfer into or out of the goal's own account can carry it.
        Anything else would count money the account never received, and the
        goals would no longer add up to the balance.

        Args:
            household: The household context.
            goal_id: The ID of the goal.
            kind: The kind of the transaction.
            account_id: The account the money leaves.
            counter_account_id: The account the money reaches, for a transfer.

        Raises:
            GoalNotFoundError: If the goal does not exist in the household.
            GoalTransferMismatchError: If the transaction cannot carry the goal.
        """
        goal = self._require_goal(household=household, goal_id=goal_id)

        if kind is not TransactionKind.TRANSFER:
            raise GoalTransferMismatchError("Only a transfer can be tagged with a goal.") from None

        if goal.account_id not in (account_id, counter_account_id):
            raise GoalTransferMismatchError(
                f"'{goal.name}' saves into another account. Tag a transfer into or out of that account."
            ) from None

    def _with_progress(self, household: HouseholdContext, goal: Goal) -> GoalPublic:
        """Build the public goal, with what it has saved so far.

        Args:
            household: The household context.
            goal: The goal.

        Returns:
            The public goal.

        Raises:
            AccountNotFoundError: If the goal's account is missing, which the
                composite foreign key rules out.
        """
        account = self.account_repository.get_for_household(
            entity_id=goal.account_id, household_id=household.household_id
        )
        if account is None:
            # The composite foreign key makes this impossible.
            raise AccountNotFoundError from None

        saved = self.goal_repository.saved_by_goal(goals=[goal], household_id=household.household_id)
        peaks = self.goal_repository.peak_by_goal(goals=[goal], household_id=household.household_id)
        monthly = self._recent_months(household=household, goals=[goal])
        first_tagged = self.goal_repository.first_tagged_on(goal_ids=[goal.id], household_id=household.household_id)

        return self._to_public(
            goal=goal,
            account=account,
            saved_minor=saved.get(goal.id, 0),
            peak_minor=peaks.get(goal.id, 0),
            monthly=monthly.get(goal.id, {}),
            first_tagged=first_tagged.get(goal.id),
        )

    def _recent_months(
        self, household: HouseholdContext, goals: Sequence[Goal]
    ) -> dict[uuid.UUID, dict[datetime.date, int]]:
        """Collect what each goal saved in each month of the pace window.

        Args:
            household: The household context.
            goals: The goals.

        Returns:
            A mapping of goal ID to a mapping of month to net amount saved.
        """
        today = datetime.date.today()
        first = month_index(today) - (PACE_WINDOW_MONTHS - 1)
        date_from = datetime.date(first // 12, first % 12 + 1, 1)

        result: dict[uuid.UUID, dict[datetime.date, int]] = defaultdict(dict)
        for goal_id, month, money_in, money_out in self.goal_repository.monthly_for_goals(
            goal_ids=[goal.id for goal in goals],
            household_id=household.household_id,
            date_from=date_from,
            date_to=today,
        ):
            result[goal_id][month] = money_in - money_out

        return result

    def _to_public(
        self,
        goal: Goal,
        account: Account,
        saved_minor: int,
        peak_minor: int,
        monthly: dict[datetime.date, int],
        first_tagged: datetime.date | None,
    ) -> GoalPublic:
        """Build the public representation of a goal.

        Args:
            goal: The goal.
            account: The account it lives in.
            saved_minor: What it has saved so far.
            peak_minor: The most it ever held.
            monthly: What it saved in each month of the pace window.
            first_tagged: The day of its earliest tagged transfer, if any.

        Returns:
            The public goal, with its progress and pace.
        """
        today = datetime.date.today()
        remaining = max(0, goal.target_minor - saved_minor)

        # Averaged only over the months the goal has been saving in, so a goal
        # set up this month is not judged on two months it could not have
        # saved in. Saving starts at the earlier of the goal's creation and its
        # first tagged transfer: a goal set up today can be tagged onto
        # transfers made months ago, and dividing those months of saving by
        # one month would make the pace look several times what it is.
        created = goal.created_at.date() if goal.created_at else today
        started = min(created, first_tagged) if first_tagged else created
        window = max(1, min(PACE_WINDOW_MONTHS, month_index(today) - month_index(started) + 1))
        average = sum(monthly.values()) // window

        months = needed = on_track = None
        if goal.target_date is not None:
            months = months_left(goal.target_date, today)
            needed = needed_per_month(remaining, months)

            if remaining > 0 and goal.achieved_at is None:
                on_track = months > 0 and average >= needed

        return GoalPublic(
            id=goal.id,
            household_id=goal.household_id,
            account_id=goal.account_id,
            account_name=account.name,
            currency_code=account.currency_code,
            name=goal.name,
            target_minor=goal.target_minor,
            target_date=goal.target_date,
            achieved_at=goal.achieved_at,
            saved_minor=saved_minor,
            peak_saved_minor=peak_minor,
            remaining_minor=remaining,
            progress=saved_minor / goal.target_minor,
            months_left=months,
            needed_per_month_minor=needed,
            average_monthly_minor=average,
            on_track=on_track,
            created_at=goal.created_at,
            updated_at=goal.updated_at,
        )

    def _account_summaries(
        self,
        household: HouseholdContext,
        pairs: Sequence[tuple[Goal, Account]],
        saved: dict[uuid.UUID, int],
    ) -> list[GoalAccountSummary]:
        """Split each goal account's balance into what goals hold and the rest.

        Args:
            household: The household context.
            pairs: The goals with their accounts.
            saved: What each goal has saved.

        Returns:
            One summary per account, ordered by account name.
        """
        accounts = {account.id: account for _, account in pairs}
        assigned: dict[uuid.UUID, int] = defaultdict(int)
        for goal, _ in pairs:
            assigned[goal.account_id] += saved.get(goal.id, 0)

        balances = self.account_repository.balances_of(account_ids=list(accounts), household_id=household.household_id)

        return [
            GoalAccountSummary(
                account_id=account.id,
                account_name=account.name,
                currency_code=account.currency_code,
                balance_minor=balances.get(account.id, 0),
                assigned_minor=assigned[account.id],
                unassigned_minor=balances.get(account.id, 0) - assigned[account.id],
            )
            for account in sorted(accounts.values(), key=lambda account: account.name)
        ]

    def _require_savings_account(self, household: HouseholdContext, account_id: uuid.UUID) -> Account:
        """Load an open savings account of the household.

        Args:
            household: The household context.
            account_id: The ID of the account.

        Returns:
            The account.

        Raises:
            AccountNotFoundError: If the account does not exist in the household.
            AccountArchivedError: If the account is archived.
            GoalAccountNotSavingsError: If the account is not a savings account.
        """
        account = self.account_repository.get_for_household(entity_id=account_id, household_id=household.household_id)

        if not account:
            raise AccountNotFoundError from None

        if account.archived_at is not None:
            raise AccountArchivedError(name=account.name) from None

        if account.type is not AccountType.SAVINGS:
            raise GoalAccountNotSavingsError(name=account.name) from None

        return account

    def _check_name_free(self, household: HouseholdContext, name: str) -> None:
        """Check that no goal of the household already has a name.

        Args:
            household: The household context.
            name: The name to check.

        Raises:
            GoalExistsError: If the name is taken.
        """
        if self.goal_repository.get_by_name(household_id=household.household_id, name=name):
            raise GoalExistsError(identifier=name) from None

    def _require_goal(self, household: HouseholdContext, goal_id: uuid.UUID) -> Goal:
        """Load a goal of the household.

        Args:
            household: The household context.
            goal_id: The ID of the goal.

        Returns:
            The goal.

        Raises:
            GoalNotFoundError: If the goal does not exist in the household.
        """
        goal = self.goal_repository.get_for_household(entity_id=goal_id, household_id=household.household_id)

        if not goal:
            raise GoalNotFoundError from None

        return goal
