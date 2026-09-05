import datetime
import uuid
from collections.abc import Sequence
from typing import Any

from sqlmodel import Session, col, func, select

from app.models import RecurringRule
from app.repositories.base import HouseholdScopedRepository


class RecurringRuleRepository(HouseholdScopedRepository[RecurringRule]):
    """Repository for RecurringRule database operations."""

    def __init__(self, session: Session) -> None:
        """Initialize the recurring rule repository.

        Args:
            session: The database session.
        """
        super().__init__(session, RecurringRule)

    def list_for_household(
        self,
        household_id: uuid.UUID,
        is_active: bool | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[RecurringRule], int]:
        """List the recurring rules of a household.

        Args:
            household_id: The ID of the household.
            is_active: An optional active state to filter on.
            skip: Number of records to skip.
            limit: Maximum number of records to return.

        Returns:
            Tuple of (rules, total_count), soonest due first.
        """
        conditions: list[Any] = [RecurringRule.household_id == household_id]

        if is_active is not None:
            conditions.append(RecurringRule.is_active == is_active)

        count = self.session.exec(select(func.count()).select_from(RecurringRule).where(*conditions)).one()
        page = self.session.exec(
            select(RecurringRule)
            .where(*conditions)
            .order_by(col(RecurringRule.next_occurrence_on))
            .offset(skip)
            .limit(limit)
        ).all()

        return page, count

    def list_active(self, household_id: uuid.UUID) -> Sequence[RecurringRule]:
        """List the active rules of a household.

        Args:
            household_id: The ID of the household.

        Returns:
            The active rules, soonest due first.
        """
        statement = (
            select(RecurringRule)
            .where(RecurringRule.household_id == household_id, RecurringRule.is_active == True)  # noqa: E712
            .order_by(col(RecurringRule.next_occurrence_on))
        )
        return self.session.exec(statement).all()

    def lock_due(self, household_id: uuid.UUID, until: datetime.date) -> Sequence[RecurringRule]:
        """Load and lock the active rules that have fallen due.

        Locked FOR UPDATE, and rules locked by another request are skipped.
        Two household members opening the app at the same moment is the
        realistic way the same occurrence would be created twice.

        Args:
            household_id: The ID of the household.
            until: The last day to consider due, inclusive.

        Returns:
            The rules that are due and were not already locked elsewhere.
        """
        statement = (
            select(RecurringRule)
            .where(
                RecurringRule.household_id == household_id,
                RecurringRule.is_active == True,  # noqa: E712
                col(RecurringRule.next_occurrence_on).is_not(None),
                col(RecurringRule.next_occurrence_on) <= until,
            )
            .order_by(col(RecurringRule.next_occurrence_on))
            .with_for_update(skip_locked=True)
        )
        return self.session.exec(statement).all()

    def count_for_account(self, account_id: uuid.UUID, household_id: uuid.UUID) -> int:
        """Count the recurring rules paid from an account.

        Args:
            account_id: The ID of the account.
            household_id: The ID of the household.

        Returns:
            The number of rules whose money moves out of the account.
        """
        statement = (
            select(func.count())
            .select_from(RecurringRule)
            .where(RecurringRule.household_id == household_id, RecurringRule.account_id == account_id)
        )
        return self.session.exec(statement).one()

    def count_for_counter_account(self, account_id: uuid.UUID, household_id: uuid.UUID) -> int:
        """Count the recurring transfer rules that move money into an account.

        Only transfer rules carry a counter account, so this is the reference
        the source account count does not see.

        Args:
            account_id: The ID of the account.
            household_id: The ID of the household.

        Returns:
            The number of rules that name the account as their destination.
        """
        statement = (
            select(func.count())
            .select_from(RecurringRule)
            .where(RecurringRule.household_id == household_id, RecurringRule.counter_account_id == account_id)
        )
        return self.session.exec(statement).one()

    def count_for_category(self, category_id: uuid.UUID, household_id: uuid.UUID) -> int:
        """Count the recurring rules filed under a category.

        Args:
            category_id: The ID of the category.
            household_id: The ID of the household.

        Returns:
            The number of rules referencing the category.
        """
        statement = (
            select(func.count())
            .select_from(RecurringRule)
            .where(RecurringRule.household_id == household_id, RecurringRule.category_id == category_id)
        )
        return self.session.exec(statement).one()
