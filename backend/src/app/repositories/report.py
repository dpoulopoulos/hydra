import datetime
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Date, cast, func, null, select
from sqlmodel import Session, col

from app.models import Category, CategoryDepth, TimeGranularity, Transaction, TransactionKind
from app.repositories.base import HouseholdScopedRepository
from app.repositories.rows import CategorySpendRow, KindTotalRow, MonthlyFlowRow, TimeBucketRow

# The kinds that represent money actually spent or earned. A transfer moves
# money between the household's own accounts, so including it would inflate
# both sides of every report.
_FLOW_KINDS = (TransactionKind.EXPENSE, TransactionKind.INCOME)


class ReportRepository(HouseholdScopedRepository[Transaction]):
    """Aggregate queries over the ledger.

    Separate from TransactionRepository because these return grouped scalars
    rather than transactions, so putting them there would make that class's
    contract untrue.

    Every query filters on a date range against occurred_on, which the
    composite indexes can serve. Grouping by EXTRACT(MONTH FROM ...) instead
    would not be able to use them.

    These use SQLAlchemy's select and execute rather than SQLModel's exec.
    The rows are grouped scalars rather than model instances, so SQLModel's
    typed select has nothing to infer and its overloads stop short of the
    column counts here.
    """

    def __init__(self, session: Session) -> None:
        """Initialize the report repository.

        Args:
            session: The database session.
        """
        super().__init__(session, Transaction)

    def spend_by_category(
        self,
        household_id: uuid.UUID,
        date_from: datetime.date,
        date_to: datetime.date,
        kind: TransactionKind,
        depth: CategoryDepth,
    ) -> Sequence[CategorySpendRow]:
        """Sum the amounts of a period per category.

        Args:
            household_id: The ID of the household.
            date_from: First day of the period, inclusive.
            date_to: Last day of the period, inclusive.
            kind: The kind of transaction to sum.
            depth: Whether to group per subcategory or roll up to the parent.

        Returns:
            One row per category, largest amount first.
        """
        parent = Category.__table__.alias("parent")  # type: ignore[attr-defined]

        if depth is CategoryDepth.PARENT:
            # COALESCE collapses a subcategory into its parent in the GROUP BY
            # itself. The tree is two levels deep, so no recursion is needed
            # and no post-processing step can disagree with the totals.
            group_id: Any = func.coalesce(col(Category.parent_id), col(Category.id))
            group_name: Any = func.coalesce(parent.c.name, col(Category.name))
            group_color: Any = func.coalesce(parent.c.color, col(Category.color))
            # A rolled up row has no parent of its own. These are constants, so
            # they are selected but deliberately kept out of the GROUP BY:
            # Postgres rejects a bare NULL there as a non-integer constant.
            parent_columns: list[Any] = [null().label("parent_id"), null().label("parent_name")]
            grouped_parent_columns: list[Any] = []
        else:
            group_id = col(Category.id)
            group_name = col(Category.name)
            group_color = col(Category.color)
            parent_columns = [parent.c.id.label("parent_id"), parent.c.name.label("parent_name")]
            grouped_parent_columns = [parent.c.id, parent.c.name]

        statement: Any = (
            select(
                group_id.label("category_id"),
                group_name.label("category_name"),
                *parent_columns,
                group_color.label("color"),
                func.sum(col(Transaction.amount_minor)).label("amount_minor"),
                func.count().label("transaction_count"),
            )
            .select_from(Transaction)
            .outerjoin(Category, col(Transaction.category_id) == col(Category.id))
            .outerjoin(parent, col(Category.parent_id) == parent.c.id)
            .where(*self._period(household_id, date_from, date_to), col(Transaction.kind) == kind)
            .group_by(group_id, group_name, *grouped_parent_columns, group_color)
            .order_by(func.sum(col(Transaction.amount_minor)).desc())
        )

        return [CategorySpendRow(*row) for row in self.session.execute(statement).all()]

    def spend_over_time(
        self,
        household_id: uuid.UUID,
        date_from: datetime.date,
        date_to: datetime.date,
        kind: TransactionKind,
        granularity: TimeGranularity,
        account_id: uuid.UUID | None = None,
        category_ids: Sequence[uuid.UUID] | None = None,
    ) -> Sequence[TimeBucketRow]:
        """Sum the amounts of a period into day or month buckets.

        Empty buckets are absent: the service fills the gaps, since that is
        far easier to test than a generate_series in SQL.

        Args:
            household_id: The ID of the household.
            date_from: First day of the period, inclusive.
            date_to: Last day of the period, inclusive.
            kind: The kind of transaction to sum.
            granularity: Whether to bucket by day or by month.
            account_id: An optional account to restrict to.
            category_ids: Optional categories to restrict to, already expanded.

        Returns:
            One row per non-empty bucket, oldest first.
        """
        bucket = cast(func.date_trunc(granularity.value, col(Transaction.occurred_on)), Date)
        conditions = [*self._period(household_id, date_from, date_to), col(Transaction.kind) == kind]

        if account_id is not None:
            conditions.append(col(Transaction.account_id) == account_id)

        if category_ids is not None:
            conditions.append(col(Transaction.category_id).in_(category_ids))

        statement: Any = (
            select(
                bucket.label("bucket"),
                func.sum(col(Transaction.amount_minor)).label("amount_minor"),
                func.count().label("transaction_count"),
            )
            .where(*conditions)
            .group_by(bucket)
            .order_by(bucket)
        )

        return [TimeBucketRow(*row) for row in self.session.execute(statement).all()]

    def monthly_flows(
        self, household_id: uuid.UUID, date_from: datetime.date, date_to: datetime.date
    ) -> Sequence[MonthlyFlowRow]:
        """Sum expenses and income of a period per month.

        Transfers are excluded, so moving money between the household's own
        accounts does not inflate both sides.

        Args:
            household_id: The ID of the household.
            date_from: First day of the period, inclusive.
            date_to: Last day of the period, inclusive.

        Returns:
            One row per month and kind, oldest first.
        """
        bucket = cast(func.date_trunc("month", col(Transaction.occurred_on)), Date)

        statement: Any = (
            select(
                bucket.label("month"),
                col(Transaction.kind).label("kind"),
                func.sum(col(Transaction.amount_minor)).label("amount_minor"),
            )
            .where(
                *self._period(household_id, date_from, date_to),
                col(Transaction.kind).in_(_FLOW_KINDS),
            )
            .group_by(bucket, col(Transaction.kind))
            .order_by(bucket)
        )

        return [MonthlyFlowRow(*row) for row in self.session.execute(statement).all()]

    def totals_by_kind(
        self, household_id: uuid.UUID, date_from: datetime.date, date_to: datetime.date
    ) -> Sequence[KindTotalRow]:
        """Sum the amounts of a period per kind.

        Args:
            household_id: The ID of the household.
            date_from: First day of the period, inclusive.
            date_to: Last day of the period, inclusive.

        Returns:
            One row per kind present in the period.
        """
        statement: Any = (
            select(
                col(Transaction.kind).label("kind"),
                func.sum(col(Transaction.amount_minor)).label("amount_minor"),
                func.count().label("transaction_count"),
            )
            .where(*self._period(household_id, date_from, date_to))
            .group_by(col(Transaction.kind))
        )

        return [KindTotalRow(*row) for row in self.session.execute(statement).all()]

    def _period(self, household_id: uuid.UUID, date_from: datetime.date, date_to: datetime.date) -> list[Any]:
        """Build the household and date conditions every report shares.

        Args:
            household_id: The ID of the household.
            date_from: First day of the period, inclusive.
            date_to: Last day of the period, inclusive.

        Returns:
            The conditions to apply to the query.
        """
        return [
            col(Transaction.household_id) == household_id,
            col(Transaction.occurred_on) >= date_from,
            col(Transaction.occurred_on) <= date_to,
        ]
