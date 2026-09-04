import datetime
import uuid
from collections.abc import Sequence

from sqlmodel import Session, col, func, select

from app.models import Budget, Category
from app.repositories.base import HouseholdScopedRepository


class BudgetRepository(HouseholdScopedRepository[Budget]):
    """Repository for Budget database operations."""

    def __init__(self, session: Session) -> None:
        """Initialize the budget repository.

        Args:
            session: The database session.
        """
        super().__init__(session, Budget)

    def list_for_month(self, household_id: uuid.UUID, period_month: datetime.date) -> Sequence[Budget]:
        """List the budgets of a household for one month.

        Args:
            household_id: The ID of the household.
            period_month: The first day of the month.

        Returns:
            The budgets set for that month.
        """
        statement = select(Budget).where(Budget.household_id == household_id, Budget.period_month == period_month)
        return self.session.exec(statement).all()

    def list_with_categories(
        self, household_id: uuid.UUID, period_month: datetime.date
    ) -> Sequence[tuple[Budget, Category]]:
        """List the budgets of a month together with their categories.

        Joined so a budget report does not need one category lookup per row.

        Args:
            household_id: The ID of the household.
            period_month: The first day of the month.

        Returns:
            Pairs of budget and category, ordered by category name.
        """
        statement = (
            select(Budget, Category)
            .join(Category, col(Budget.category_id) == col(Category.id))
            .where(Budget.household_id == household_id, Budget.period_month == period_month)
            .order_by(col(Category.sort_order), col(Category.name))
        )
        return self.session.exec(statement).all()

    def get_for_category_month(
        self, household_id: uuid.UUID, category_id: uuid.UUID, period_month: datetime.date
    ) -> Budget | None:
        """Get the budget of one category in one month.

        Args:
            household_id: The ID of the household.
            category_id: The ID of the category.
            period_month: The first day of the month.

        Returns:
            The budget if one is set, None otherwise.
        """
        statement = select(Budget).where(
            Budget.household_id == household_id,
            Budget.category_id == category_id,
            Budget.period_month == period_month,
        )
        return self.session.exec(statement).first()

    def get_for_categories_month(
        self,
        household_id: uuid.UUID,
        category_ids: Sequence[uuid.UUID],
        period_month: datetime.date,
    ) -> Sequence[Budget]:
        """Get the budgets of several categories in one month.

        Args:
            household_id: The ID of the household.
            category_ids: The IDs of the categories.
            period_month: The first day of the month.

        Returns:
            The budgets that exist among those categories.
        """
        if not category_ids:
            return []

        statement = select(Budget).where(
            Budget.household_id == household_id,
            Budget.period_month == period_month,
            col(Budget.category_id).in_(category_ids),
        )
        return self.session.exec(statement).all()

    def count_for_category(self, category_id: uuid.UUID, household_id: uuid.UUID) -> int:
        """Count the budgets set for a category.

        Args:
            category_id: The ID of the category.
            household_id: The ID of the household.

        Returns:
            The number of budgets referencing the category.
        """
        statement = (
            select(func.count())
            .select_from(Budget)
            .where(Budget.household_id == household_id, Budget.category_id == category_id)
        )
        return self.session.exec(statement).one()
