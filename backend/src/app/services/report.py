import datetime
import uuid
from collections.abc import Sequence

from sqlmodel import Session

from app.exceptions import CategoryNotFoundError, InvalidDateRangeError, ReportRangeTooLargeError
from app.models import (
    CategoryDepth,
    CategorySpendSlice,
    HouseholdContext,
    IncomeExpenseReport,
    MonthlyFlow,
    ReportPeriod,
    SpendByCategoryReport,
    SpendOverTimeReport,
    TimeGranularity,
    TimeSeriesPoint,
    TransactionKind,
)
from app.models.fields import month_key_of, month_start, next_month_start
from app.repositories.category import CategoryRepository
from app.repositories.household import HouseholdRepository
from app.repositories.report import ReportRepository
from app.repositories.rows import MonthlyFlowRow, TimeBucketRow

# Guards on how much a single request can ask for. Daily buckets over decades
# would be a very large response for a chart nobody can read.
MAX_DAILY_RANGE_DAYS = 731
MAX_FLOW_RANGE_MONTHS = 120

# The label used for spending that has no category at all.
UNCATEGORIZED_LABEL = "Uncategorized"


class ReportService:
    """Provide the aggregated figures the charts are drawn from."""

    def __init__(
        self,
        session: Session,
        report_repository: ReportRepository,
        household_repository: HouseholdRepository,
        category_repository: CategoryRepository,
    ) -> None:
        """Initialize the report service.

        Args:
            session: The database session.
            report_repository: The report repository instance.
            household_repository: The household repository instance, used for the currency.
            category_repository: The category repository instance.
        """
        self.session = session
        self.report_repository = report_repository
        self.household_repository = household_repository
        self.category_repository = category_repository

    def spend_by_category(
        self,
        household: HouseholdContext,
        month: str,
        kind: TransactionKind = TransactionKind.EXPENSE,
        depth: CategoryDepth = CategoryDepth.PARENT,
    ) -> SpendByCategoryReport:
        """Break a month's spending down by category.

        Args:
            household: The household context.
            month: The month, in "YYYY-MM" form.
            kind: Whether to break down expenses or income.
            depth: Whether to report per subcategory or rolled up to the parent.

        Returns:
            One slice per category, largest first, with each share of the total.
        """
        date_from = month_start(month)
        date_to = next_month_start(month) - datetime.timedelta(days=1)

        rows = self.report_repository.spend_by_category(
            household_id=household.household_id,
            date_from=date_from,
            date_to=date_to,
            kind=kind,
            depth=depth,
        )
        total = sum(row.amount_minor for row in rows)

        slices = [
            CategorySpendSlice(
                category_id=row.category_id,
                category_name=row.category_name or UNCATEGORIZED_LABEL,
                parent_id=row.parent_id,
                parent_name=row.parent_name,
                color=row.color,
                amount_minor=row.amount_minor,
                transaction_count=row.transaction_count,
                # Guarded rather than divided blindly: a month with no spending
                # has a total of zero.
                share=round(row.amount_minor / total, 4) if total else 0.0,
            )
            for row in rows
        ]

        return SpendByCategoryReport(
            period=self._period(household=household, date_from=date_from, date_to=date_to),
            kind=kind,
            depth=depth,
            total_minor=total,
            slices=slices,
        )

    def spend_over_time(
        self,
        household: HouseholdContext,
        date_from: datetime.date,
        date_to: datetime.date,
        granularity: TimeGranularity = TimeGranularity.DAY,
        kind: TransactionKind = TransactionKind.EXPENSE,
        account_id: uuid.UUID | None = None,
        category_id: uuid.UUID | None = None,
    ) -> SpendOverTimeReport:
        """Chart spending over a period.

        Args:
            household: The household context.
            date_from: First day of the period, inclusive.
            date_to: Last day of the period, inclusive.
            granularity: Whether to bucket by day or by month.
            kind: Whether to chart expenses or income.
            account_id: An optional account to restrict to.
            category_id: An optional category to restrict to. A parent category
                includes the spending filed under its subcategories.

        Returns:
            One point per bucket, with empty buckets filled in.

        Raises:
            InvalidDateRangeError: If the range starts after it ends.
            ReportRangeTooLargeError: If daily buckets are asked for over more than two years.
            CategoryNotFoundError: If the category does not exist in the household.
        """
        self._check_range(date_from=date_from, date_to=date_to)

        if granularity is TimeGranularity.DAY and (date_to - date_from).days > MAX_DAILY_RANGE_DAYS:
            raise ReportRangeTooLargeError(limit="two years of daily figures") from None

        category_ids = None

        if category_id is not None:
            category_ids = self._expand_category(household=household, category_id=category_id)

        rows = self.report_repository.spend_over_time(
            household_id=household.household_id,
            date_from=date_from,
            date_to=date_to,
            kind=kind,
            granularity=granularity,
            account_id=account_id,
            category_ids=category_ids,
        )
        points = self._fill_gaps(rows=rows, date_from=date_from, date_to=date_to, granularity=granularity)
        total = sum(point.amount_minor for point in points)
        active = [point for point in points if point.transaction_count]

        return SpendOverTimeReport(
            period=self._period(household=household, date_from=date_from, date_to=date_to),
            granularity=granularity,
            kind=kind,
            total_minor=total,
            average_minor=round(total / len(active)) if active else 0,
            points=points,
        )

    def income_expense(self, household: HouseholdContext, month_from: str, month_to: str) -> IncomeExpenseReport:
        """Compare money in against money out, month by month.

        Transfers never appear, because a transfer is one row of kind transfer
        rather than a pair of rows that would show up on both sides.

        Args:
            household: The household context.
            month_from: First month of the range, in "YYYY-MM" form.
            month_to: Last month of the range, in "YYYY-MM" form.

        Returns:
            One entry per month, with the running net that is the savings trend.

        Raises:
            InvalidDateRangeError: If the range starts after it ends.
            ReportRangeTooLargeError: If more than ten years are asked for.
        """
        date_from = month_start(month_from)
        date_to = next_month_start(month_to) - datetime.timedelta(days=1)

        self._check_range(date_from=date_from, date_to=date_to)

        buckets = self._month_buckets(date_from=date_from, date_to=date_to)

        if len(buckets) > MAX_FLOW_RANGE_MONTHS:
            raise ReportRangeTooLargeError(limit="ten years of monthly figures") from None

        rows = self.report_repository.monthly_flows(
            household_id=household.household_id, date_from=date_from, date_to=date_to
        )
        months = self._pivot_flows(rows=rows, buckets=buckets)
        total_income = sum(month.income_minor for month in months)
        total_expense = sum(month.expense_minor for month in months)
        rates = [month.savings_rate for month in months if month.savings_rate is not None]

        return IncomeExpenseReport(
            period=self._period(household=household, date_from=date_from, date_to=date_to),
            months=months,
            total_income_minor=total_income,
            total_expense_minor=total_expense,
            total_net_minor=total_income - total_expense,
            average_savings_rate=round(sum(rates) / len(rates), 4) if rates else None,
        )

    def _pivot_flows(self, rows: Sequence[MonthlyFlowRow], buckets: Sequence[datetime.date]) -> list[MonthlyFlow]:
        """Turn one row per month and kind into one entry per month.

        Args:
            rows: The grouped rows from the repository.
            buckets: Every month of the range, including those with no activity.

        Returns:
            One entry per month, oldest first, with a running net.
        """
        income: dict[datetime.date, int] = {}
        expense: dict[datetime.date, int] = {}

        for row in rows:
            target = income if row.kind is TransactionKind.INCOME else expense
            target[row.month] = target.get(row.month, 0) + row.amount_minor

        months: list[MonthlyFlow] = []
        running = 0

        for bucket in buckets:
            money_in = income.get(bucket, 0)
            money_out = expense.get(bucket, 0)
            net = money_in - money_out
            running += net

            months.append(
                MonthlyFlow(
                    month=month_key_of(bucket),
                    income_minor=money_in,
                    expense_minor=money_out,
                    net_minor=net,
                    cumulative_net_minor=running,
                    # None rather than zero when nothing came in: a savings
                    # rate of "0%" would suggest income that was all spent.
                    savings_rate=round(net / money_in, 4) if money_in else None,
                )
            )

        return months

    def _fill_gaps(
        self,
        rows: Sequence[TimeBucketRow],
        date_from: datetime.date,
        date_to: datetime.date,
        granularity: TimeGranularity,
    ) -> list[TimeSeriesPoint]:
        """Add a zero point for every bucket with no activity.

        Done here rather than with a generate_series in SQL: a chart with
        missing days misleads, and filling in Python is straightforward to
        test, which the SQL version is not.

        Args:
            rows: The non-empty buckets from the repository.
            date_from: First day of the period, inclusive.
            date_to: Last day of the period, inclusive.
            granularity: Whether the buckets are days or months.

        Returns:
            One point per bucket in the range, oldest first.
        """
        found = {row.bucket: row for row in rows}
        buckets = (
            self._day_buckets(date_from=date_from, date_to=date_to)
            if granularity is TimeGranularity.DAY
            else self._month_buckets(date_from=date_from, date_to=date_to)
        )

        return [
            TimeSeriesPoint(
                bucket=bucket,
                amount_minor=found[bucket].amount_minor if bucket in found else 0,
                transaction_count=found[bucket].transaction_count if bucket in found else 0,
            )
            for bucket in buckets
        ]

    def _day_buckets(self, date_from: datetime.date, date_to: datetime.date) -> list[datetime.date]:
        """List every day of a range.

        Args:
            date_from: First day, inclusive.
            date_to: Last day, inclusive.

        Returns:
            The days, oldest first.
        """
        return [date_from + datetime.timedelta(days=offset) for offset in range((date_to - date_from).days + 1)]

    def _month_buckets(self, date_from: datetime.date, date_to: datetime.date) -> list[datetime.date]:
        """List the first day of every month a range touches.

        Args:
            date_from: First day, inclusive.
            date_to: Last day, inclusive.

        Returns:
            The months, oldest first.
        """
        buckets: list[datetime.date] = []
        bucket = date_from.replace(day=1)
        last = date_to.replace(day=1)

        while bucket <= last:
            buckets.append(bucket)
            bucket = next_month_start(month_key_of(bucket))

        return buckets

    def _expand_category(self, household: HouseholdContext, category_id: uuid.UUID) -> list[uuid.UUID]:
        """Resolve a category filter to itself and its subcategories.

        Args:
            household: The household context.
            category_id: The ID of the category.

        Returns:
            The category's own ID followed by the IDs of its subcategories.

        Raises:
            CategoryNotFoundError: If the category does not exist in the household.
        """
        category = self.category_repository.get_for_household(
            entity_id=category_id, household_id=household.household_id
        )

        if not category:
            raise CategoryNotFoundError from None

        children = self.category_repository.list_for_household(
            household_id=household.household_id, include_archived=True, parent_id=category_id
        )

        return [category_id, *(child.id for child in children)]

    def _check_range(self, date_from: datetime.date, date_to: datetime.date) -> None:
        """Check that a range is the right way round.

        Args:
            date_from: First day, inclusive.
            date_to: Last day, inclusive.

        Raises:
            InvalidDateRangeError: If the range starts after it ends.
        """
        if date_from > date_to:
            raise InvalidDateRangeError from None

    def _period(self, household: HouseholdContext, date_from: datetime.date, date_to: datetime.date) -> ReportPeriod:
        """Describe the period a report covers.

        Args:
            household: The household context.
            date_from: First day, inclusive.
            date_to: Last day, inclusive.

        Returns:
            The period, with the household currency so the client can format amounts.
        """
        entity = self.household_repository.get_by_id(household.household_id)

        return ReportPeriod(
            date_from=date_from,
            date_to=date_to,
            currency_code=entity.currency_code if entity else "EUR",
        )
