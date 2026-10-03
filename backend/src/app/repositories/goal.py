import datetime
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import case
from sqlmodel import Session, col, func, select

from app.models import Account, Goal, Transaction
from app.repositories.base import HouseholdScopedRepository


class GoalRepository(HouseholdScopedRepository[Goal]):
    """Repository for Goal database operations.

    What a goal has saved is derived from the transfers tagged with it on every
    read, never stored, for the same reason account balances are not: a stored
    total would drift the first time a tagged transfer is edited or deleted.
    """

    def __init__(self, session: Session) -> None:
        """Initialize the goal repository.

        Args:
            session: The database session.
        """
        super().__init__(session, Goal)

    def list_with_accounts(self, household_id: uuid.UUID) -> Sequence[tuple[Goal, Account]]:
        """List the goals of a household together with their accounts.

        Joined so listing goals does not need one account lookup per goal.

        Args:
            household_id: The ID of the household.

        Returns:
            Pairs of goal and account. Open goals come first, then by name.
        """
        statement = (
            select(Goal, Account)
            .join(Account, col(Goal.account_id) == col(Account.id))
            .where(Goal.household_id == household_id)
            .order_by(col(Goal.achieved_at).is_not(None), col(Goal.name))
        )
        return self.session.exec(statement).all()

    def get_by_name(self, household_id: uuid.UUID, name: str) -> Goal | None:
        """Get a goal by name within a household.

        Args:
            household_id: The ID of the household.
            name: The goal name.

        Returns:
            The goal if one exists with that name, None otherwise.
        """
        statement = select(Goal).where(Goal.household_id == household_id, Goal.name == name)
        return self.session.exec(statement).first()

    def has_transfers(self, goal_id: uuid.UUID, household_id: uuid.UUID) -> bool:
        """Check whether any transaction is tagged with a goal.

        Args:
            goal_id: The ID of the goal.
            household_id: The ID of the household that owns it.

        Returns:
            True if at least one transaction carries the goal.
        """
        statement = select(Transaction.id).where(
            Transaction.household_id == household_id, Transaction.goal_id == goal_id
        )
        return self.session.exec(statement).first() is not None

    def saved_by_goal(self, goals: Sequence[Goal], household_id: uuid.UUID) -> dict[uuid.UUID, int]:
        """Sum what each goal has saved, in minor units.

        Args:
            goals: The goals.
            household_id: The ID of the household that owns them.

        Returns:
            A mapping of goal ID to its saved amount. Goals with no tagged
            transfer are absent.
        """
        if not goals:
            return {}

        signed = self._signed_amount()
        statement = (
            select(col(Goal.id), func.sum(signed))
            .join(Goal, col(Transaction.goal_id) == col(Goal.id))
            .where(
                Transaction.household_id == household_id,
                col(Transaction.goal_id).in_([goal.id for goal in goals]),
            )
            .group_by(col(Goal.id))
        )
        return {goal_id: int(total) for goal_id, total in self.session.exec(statement).all()}

    def peak_by_goal(self, goals: Sequence[Goal], household_id: uuid.UUID) -> dict[uuid.UUID, int]:
        """Find the most each goal ever held, in minor units.

        The running total of a goal's tagged transfers, taken at its highest.
        Within a day, money in is counted before money out, since the order
        of two entries on one day is not something the ledger records.

        Args:
            goals: The goals.
            household_id: The ID of the household that owns them.

        Returns:
            A mapping of goal ID to its peak. Goals with no tagged transfer
            are absent.
        """
        if not goals:
            return {}

        into = col(Transaction.counter_account_id) == col(Goal.account_id)
        running = (
            select(
                col(Goal.id).label("goal_id"),
                func.sum(self._signed_amount())
                .over(
                    partition_by=col(Goal.id),
                    order_by=(col(Transaction.occurred_on), case((into, 0), else_=1), col(Transaction.id)),
                )
                .label("running"),
            )
            .join(Goal, col(Transaction.goal_id) == col(Goal.id))
            .where(
                Transaction.household_id == household_id,
                col(Transaction.goal_id).in_([goal.id for goal in goals]),
            )
            .subquery()
        )
        statement = select(running.c.goal_id, func.max(running.c.running)).group_by(running.c.goal_id)
        return {goal_id: int(peak) for goal_id, peak in self.session.exec(statement).all()}

    def monthly_for_goals(
        self,
        goal_ids: Sequence[uuid.UUID],
        household_id: uuid.UUID,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> list[tuple[uuid.UUID, datetime.date, int, int]]:
        """Sum the money tagged into and out of goals, month by month.

        Args:
            goal_ids: The IDs of the goals.
            household_id: The ID of the household that owns them.
            date_from: The first day to include.
            date_to: The last day to include.

        Returns:
            (goal ID, first day of month, money in, money out) rows, both
            amounts as positive magnitudes. Months with nothing tagged are
            absent.
        """
        if not goal_ids:
            return []

        month: Any = func.date_trunc("month", col(Transaction.occurred_on))
        into = col(Transaction.counter_account_id) == col(Goal.account_id)
        statement = (
            select(
                col(Goal.id),
                month,
                func.sum(case((into, col(Transaction.amount_minor)), else_=0)),
                func.sum(case((into, 0), else_=col(Transaction.amount_minor))),
            )
            .join(Goal, col(Transaction.goal_id) == col(Goal.id))
            .where(
                Transaction.household_id == household_id,
                col(Transaction.goal_id).in_(goal_ids),
                Transaction.occurred_on >= date_from,
                Transaction.occurred_on <= date_to,
            )
            .group_by(col(Goal.id), month)
            .order_by(month)
        )
        return [
            (goal_id, _as_date(month_start), int(money_in), int(money_out))
            for goal_id, month_start, money_in, money_out in self.session.exec(statement).all()
        ]

    def first_tagged_on(self, goal_ids: Sequence[uuid.UUID], household_id: uuid.UUID) -> dict[uuid.UUID, datetime.date]:
        """Find the day of each goal's earliest tagged transfer.

        Args:
            goal_ids: The IDs of the goals.
            household_id: The ID of the household that owns them.

        Returns:
            A mapping of goal ID to that day. Goals with nothing tagged are absent.
        """
        if not goal_ids:
            return {}

        statement = (
            select(col(Goal.id), func.min(col(Transaction.occurred_on)))
            .join(Goal, col(Transaction.goal_id) == col(Goal.id))
            .where(Transaction.household_id == household_id, col(Goal.id).in_(goal_ids))
            .group_by(col(Goal.id))
        )
        return dict(self.session.exec(statement).all())

    def saved_before(self, goal_id: uuid.UUID, household_id: uuid.UUID, before: datetime.date) -> int:
        """Sum what a goal had saved before a day, in minor units.

        Lets a history that starts part way through still report a running
        total that matches the goal's real balance.

        Args:
            goal_id: The ID of the goal.
            household_id: The ID of the household that owns it.
            before: The first day not to include.

        Returns:
            The saved amount, or zero when nothing was tagged before then.
        """
        statement = (
            select(func.coalesce(func.sum(self._signed_amount()), 0))
            .join(Goal, col(Transaction.goal_id) == col(Goal.id))
            .where(
                Transaction.household_id == household_id,
                Transaction.goal_id == goal_id,
                Transaction.occurred_on < before,
            )
        )
        return int(self.session.exec(statement).one())

    def _signed_amount(self) -> Any:
        """Build the expression for a tagged transfer's effect on its goal.

        A transfer into the goal's account adds to the goal and one out of it
        takes away. Needs Goal joined on the transaction's goal_id.

        Returns:
            The signed amount, in minor units.
        """
        return case(
            (col(Transaction.counter_account_id) == col(Goal.account_id), col(Transaction.amount_minor)),
            else_=-col(Transaction.amount_minor),
        )


def _as_date(value: datetime.date | datetime.datetime) -> datetime.date:
    """Drop the time part date_trunc adds to a month.

    Args:
        value: The truncated month, as the driver returns it.

    Returns:
        The first day of the month.
    """
    return value.date() if isinstance(value, datetime.datetime) else value
