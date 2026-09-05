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


class BudgetProgressRow(SQLModel):
    """One category's spending against its limit for a month."""

    budget_id: uuid.UUID
    category_id: uuid.UUID
    category_name: str
    parent_id: uuid.UUID | None = None
    # True when the limit is set on a parent, so the figure includes the
    # spending filed under its subcategories.
    covers_subcategories: bool = False
    limit_minor: int
    spent_minor: int
    # Negative once the limit is passed, which is the useful number to show.
    remaining_minor: int
    # Not capped at 1, so overspending is visible rather than flattened.
    progress: float
    is_over_budget: bool


class BudgetProgressReport(SQLModel):
    period: ReportPeriod
    total_limit_minor: int
    total_spent_minor: int
    total_remaining_minor: int
    rows: list[BudgetProgressRow]
    # Spending in categories with no limit this month, so the report accounts
    # for the whole month rather than only the budgeted part of it.
    unbudgeted_spend_minor: int


class MonthSummaryReport(SQLModel):
    """The dashboard figures for one month, in a single request."""

    period: ReportPeriod
    income_minor: int
    expense_minor: int
    net_minor: int

    # Net worth, split into where it is held. Reported apart as well as
    # together because the three behave differently, and someone reading a
    # single total cannot tell which part moved.
    #
    # Money in banks, wallets, savings and on credit cards.
    bank_minor: int = 0
    # Cash sitting with a broker: transferred in and not yet spent, plus what
    # sales have returned and not yet been withdrawn.
    brokerage_minor: int = 0
    # What the holdings are worth at their last known price. The only one of
    # the three that moves without anybody recording anything.
    assets_minor: int = 0
    # All three added together, and nothing is counted twice. Buying takes cash
    # out of a brokerage account and turns it into a holding, so a euro is
    # either still cash or already a holding, never both.
    net_worth_minor: int
    # Open holdings with no price or no exchange rate. They contribute nothing
    # to `assets_minor`, so a total with any of these is understated, and the
    # page must be able to say so rather than quietly rounding them to zero.
    unpriced_asset_count: int = 0
    budgeted_minor: int
    over_budget_category_count: int
    transaction_count: int
    top_categories: list[CategorySpendSlice]
