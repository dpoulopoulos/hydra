import datetime
import uuid
from enum import StrEnum

from sqlmodel import SQLModel

from .transaction import TransactionKind


class CategoryDepth(StrEnum):
    """Whether spending is reported per subcategory or rolled up to its parent."""

    LEAF = "leaf"
    PARENT = "parent"


class TimeGranularity(StrEnum):
    DAY = "day"
    MONTH = "month"


class ReportPeriod(SQLModel):
    """The period a report covers, resolved to real dates."""

    date_from: datetime.date
    date_to: datetime.date
    currency_code: str


class CategorySpendSlice(SQLModel):
    """One category's share of the spending in a period."""

    # None is the bucket for transactions with no category at all.
    category_id: uuid.UUID | None = None
    category_name: str
    parent_id: uuid.UUID | None = None
    parent_name: str | None = None
    color: str | None = None
    amount_minor: int
    transaction_count: int
    # Fraction of the period total, 0 to 1. Computed rather than left to the
    # frontend, so every client shows the same rounding.
    share: float


class SpendByCategoryReport(SQLModel):
    period: ReportPeriod
    kind: TransactionKind
    depth: CategoryDepth
    total_minor: int
    slices: list[CategorySpendSlice]


class TimeSeriesPoint(SQLModel):
    """One bucket of a time series."""

    bucket: datetime.date
    amount_minor: int
    transaction_count: int


class SpendOverTimeReport(SQLModel):
    period: ReportPeriod
    granularity: TimeGranularity
    kind: TransactionKind
    total_minor: int
    # Averaged over buckets that had any activity, so a quiet week does not
    # drag the figure down.
    average_minor: int
    points: list[TimeSeriesPoint]


class MonthlyFlow(SQLModel):
    """Money in and out for one month."""

    month: str
    income_minor: int
    expense_minor: int
    net_minor: int
    # Running total across the requested range, which is the savings trend.
    cumulative_net_minor: int
    # None when there was no income that month, rather than a misleading zero.
    savings_rate: float | None = None


class IncomeExpenseReport(SQLModel):
    period: ReportPeriod
    months: list[MonthlyFlow]
    total_income_minor: int
    total_expense_minor: int
    total_net_minor: int
    average_savings_rate: float | None = None
