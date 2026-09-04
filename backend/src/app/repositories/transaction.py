import uuid
from collections.abc import Sequence
from typing import Any

from sqlmodel import Session, col, func, or_, select

from app.models import Category, Transaction, TransactionFilters, TransactionSort
from app.repositories.base import HouseholdScopedRepository


class TransactionRepository(HouseholdScopedRepository[Transaction]):
    """Repository for Transaction database operations."""

    def __init__(self, session: Session) -> None:
        """Initialize the transaction repository.

        Args:
            session: The database session.
        """
        super().__init__(session, Transaction)

    def list_for_household(
        self,
        household_id: uuid.UUID,
        filters: TransactionFilters,
        category_ids: Sequence[uuid.UUID] | None = None,
    ) -> tuple[Sequence[Transaction], int]:
        """List the transactions of a household matching a set of filters.

        Args:
            household_id: The ID of the household.
            filters: The filters to apply.
            category_ids: The categories the filter resolves to. Passed in
                already expanded, so a parent category can match the spending
                filed under its subcategories.

        Returns:
            Tuple of (transactions, total_count).
        """
        conditions = self._conditions(household_id=household_id, filters=filters, category_ids=category_ids)

        count_statement = select(func.count()).select_from(Transaction).where(*conditions)
        count = self.session.exec(count_statement).one()

        statement = (
            select(Transaction)
            .where(*conditions)
            .order_by(*self._ordering(filters.sort))
            .offset(filters.skip)
            .limit(filters.limit)
        )

        return self.session.exec(statement).all(), count

    def count_for_account(self, account_id: uuid.UUID, household_id: uuid.UUID) -> int:
        """Count the transactions that reference an account, on either side.

        Args:
            account_id: The ID of the account.
            household_id: The ID of the household.

        Returns:
            The number of transactions referencing the account.
        """
        statement = (
            select(func.count())
            .select_from(Transaction)
            .where(
                Transaction.household_id == household_id,
                or_(
                    Transaction.account_id == account_id,
                    Transaction.counter_account_id == account_id,
                ),
            )
        )
        return self.session.exec(statement).one()

    def count_for_category(self, category_id: uuid.UUID, household_id: uuid.UUID) -> int:
        """Count the transactions filed under a category.

        Args:
            category_id: The ID of the category.
            household_id: The ID of the household.

        Returns:
            The number of transactions in the category.
        """
        statement = (
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.household_id == household_id, Transaction.category_id == category_id)
        )
        return self.session.exec(statement).one()

    def descendant_category_ids(self, category_id: uuid.UUID, household_id: uuid.UUID) -> list[uuid.UUID]:
        """Get a category together with its subcategories.

        The tree is two levels deep, so this is one query rather than a
        recursive walk.

        Args:
            category_id: The ID of the category.
            household_id: The ID of the household.

        Returns:
            The category's own ID followed by the IDs of its subcategories.
        """
        statement = select(Category.id).where(Category.household_id == household_id, Category.parent_id == category_id)
        return [category_id, *self.session.exec(statement).all()]

    def _conditions(
        self,
        household_id: uuid.UUID,
        filters: TransactionFilters,
        category_ids: Sequence[uuid.UUID] | None,
    ) -> list[Any]:
        """Build the WHERE clauses for a filtered listing.

        Args:
            household_id: The ID of the household.
            filters: The filters to apply.
            category_ids: The categories the filter resolves to.

        Returns:
            The conditions to apply to the query.
        """
        conditions: list[Any] = [Transaction.household_id == household_id]

        # Half-open on the upper bound is avoided here on purpose: occurred_on
        # is a date, so an inclusive range is what a caller means by "up to and
        # including this day", and both bounds stay usable by the index.
        if filters.date_from is not None:
            conditions.append(Transaction.occurred_on >= filters.date_from)

        if filters.date_to is not None:
            conditions.append(Transaction.occurred_on <= filters.date_to)

        if filters.account_id is not None:
            conditions.append(
                or_(
                    Transaction.account_id == filters.account_id,
                    Transaction.counter_account_id == filters.account_id,
                )
            )

        if category_ids is not None:
            conditions.append(col(Transaction.category_id).in_(category_ids))

        if filters.kind is not None:
            conditions.append(Transaction.kind == filters.kind)

        if filters.min_amount_minor is not None:
            conditions.append(Transaction.amount_minor >= filters.min_amount_minor)

        if filters.max_amount_minor is not None:
            conditions.append(Transaction.amount_minor <= filters.max_amount_minor)

        if filters.q:
            pattern = f"%{filters.q}%"
            conditions.append(or_(col(Transaction.merchant).ilike(pattern), col(Transaction.note).ilike(pattern)))

        return conditions

    def _ordering(self, sort: TransactionSort) -> list[Any]:
        """Build the ORDER BY clauses for a listing.

        The primary key is appended as a tiebreaker, so paging through
        transactions that share a date is stable rather than arbitrary.

        Args:
            sort: The requested order.

        Returns:
            The ordering to apply to the query.
        """
        orderings: dict[TransactionSort, list[Any]] = {
            TransactionSort.DATE_DESC: [col(Transaction.occurred_on).desc()],
            TransactionSort.DATE_ASC: [col(Transaction.occurred_on).asc()],
            TransactionSort.AMOUNT_DESC: [col(Transaction.amount_minor).desc()],
            TransactionSort.AMOUNT_ASC: [col(Transaction.amount_minor).asc()],
        }

        return [*orderings[sort], col(Transaction.id).asc()]
