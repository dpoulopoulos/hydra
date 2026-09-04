import datetime
import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentHousehold, ReportServiceDep
from app.exceptions import InvalidDateRangeError, ReportRangeTooLargeError, ServiceError
from app.models import (
    BudgetProgressReport,
    CategoryDepth,
    IncomeExpenseReport,
    MonthSummaryReport,
    SpendByCategoryReport,
    SpendOverTimeReport,
    TimeGranularity,
    TransactionKind,
)
from app.models.fields import MONTH_KEY_PATTERN

router = APIRouter(prefix="/reports", tags=["reports"])


def report_exception_mappings() -> dict[type[ServiceError], int]:
    """Map service exceptions to appropriate HTTP status codes.

    Returns:
        A dictionary mapping exception types to HTTP status codes.
    """
    # CategoryNotFoundError is raised by these endpoints too, but it is
    # registered by the categories router. Handlers are registered globally by
    # exception type, so listing a type in two mappings would let the last one
    # registered silently win.
    return {
        InvalidDateRangeError: status.HTTP_400_BAD_REQUEST,
        ReportRangeTooLargeError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    }


@router.get("/spend-by-category", response_model=SpendByCategoryReport)
def spend_by_category(
    *,
    report_service: ReportServiceDep,
    household: CurrentHousehold,
    month: str = Query(pattern=MONTH_KEY_PATTERN),
    kind: TransactionKind = Query(default=TransactionKind.EXPENSE),
    depth: CategoryDepth = Query(default=CategoryDepth.PARENT),
) -> SpendByCategoryReport:
    """Break a month's spending down by category.

    Transfers can never appear here: they are their own kind, so moving money
    between your own accounts is not spending.

    Args:
        report_service: The report service dependency.
        household: The current household context.
        month: The month, in "YYYY-MM" form.
        kind: Whether to break down expenses or income.
        depth: Whether to report per subcategory, or rolled up to the parent.

    Returns:
        One slice per category, largest first, with each share of the total.

    Raises:
        HTTPException: If the month is not in "YYYY-MM" form (422).
    """
    return report_service.spend_by_category(household=household, month=month, kind=kind, depth=depth)


@router.get("/spend-over-time", response_model=SpendOverTimeReport)
def spend_over_time(
    *,
    report_service: ReportServiceDep,
    household: CurrentHousehold,
    date_from: datetime.date = Query(),
    date_to: datetime.date = Query(),
    granularity: TimeGranularity = Query(default=TimeGranularity.DAY),
    kind: TransactionKind = Query(default=TransactionKind.EXPENSE),
    account_id: uuid.UUID | None = Query(default=None),
    category_id: uuid.UUID | None = Query(default=None),
) -> SpendOverTimeReport:
    """Chart spending over a period.

    Buckets with no activity are returned as zero rather than left out, so the
    chart cannot imply a gap in time that is not there.

    Args:
        report_service: The report service dependency.
        household: The current household context.
        date_from: First day of the period, inclusive.
        date_to: Last day of the period, inclusive.
        granularity: Whether to bucket by day or by month.
        kind: Whether to chart expenses or income.
        account_id: An optional account to restrict to.
        category_id: An optional category to restrict to. A parent category
            includes the spending filed under its subcategories.

    Returns:
        One point per bucket, oldest first.

    Raises:
        HTTPException: If the range starts after it ends (400), the range asks
            for too many buckets (422), or the category does not exist in the
            household (404).
    """
    return report_service.spend_over_time(
        household=household,
        date_from=date_from,
        date_to=date_to,
        granularity=granularity,
        kind=kind,
        account_id=account_id,
        category_id=category_id,
    )


@router.get("/income-expense", response_model=IncomeExpenseReport)
def income_expense(
    *,
    report_service: ReportServiceDep,
    household: CurrentHousehold,
    month_from: str = Query(pattern=MONTH_KEY_PATTERN),
    month_to: str = Query(pattern=MONTH_KEY_PATTERN),
) -> IncomeExpenseReport:
    """Compare money in against money out, month by month.

    Each month also carries the running net, which is the savings trend.
    Transfers appear on neither side.

    Args:
        report_service: The report service dependency.
        household: The current household context.
        month_from: First month of the range, in "YYYY-MM" form.
        month_to: Last month of the range, in "YYYY-MM" form.

    Returns:
        One entry per month, oldest first, plus the totals for the range.

    Raises:
        HTTPException: If the range starts after it ends (400), or covers more
            than ten years (422).
    """
    return report_service.income_expense(household=household, month_from=month_from, month_to=month_to)


@router.get("/budget-progress", response_model=BudgetProgressReport)
def budget_progress(
    *,
    report_service: ReportServiceDep,
    household: CurrentHousehold,
    month: str = Query(pattern=MONTH_KEY_PATTERN),
) -> BudgetProgressReport:
    """Compare a month's spending against the limits set for it.

    A limit on a parent category counts the spending filed under its
    subcategories, so budgeting "Food & Drink" tracks what was spent on
    groceries and restaurants together.

    Args:
        report_service: The report service dependency.
        household: The current household context.
        month: The month, in "YYYY-MM" form.

    Returns:
        One row per budget, sorted by how much of each limit is used, plus the
        spending that had no limit at all.

    Raises:
        HTTPException: If the month is not in "YYYY-MM" form (422).
    """
    return report_service.budget_progress(household=household, month=month)


@router.get("/summary", response_model=MonthSummaryReport)
def month_summary(
    *,
    report_service: ReportServiceDep,
    household: CurrentHousehold,
    month: str = Query(pattern=MONTH_KEY_PATTERN),
) -> MonthSummaryReport:
    """Gather the dashboard figures for one month.

    One request rather than several, so opening the app is a single round trip.

    Args:
        report_service: The report service dependency.
        household: The current household context.
        month: The month, in "YYYY-MM" form.

    Returns:
        The month's income, spending and net, the current net worth, how much
        was budgeted, how many categories went over, and the biggest categories.

    Raises:
        HTTPException: If the month is not in "YYYY-MM" form (422).
    """
    return report_service.month_summary(household=household, month=month)
