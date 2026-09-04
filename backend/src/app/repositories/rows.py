import datetime
import uuid
from typing import NamedTuple

from app.models import TransactionKind


class CategorySpendRow(NamedTuple):
    """One grouped row of the spend-by-category aggregation."""

    category_id: uuid.UUID | None
    category_name: str | None
    parent_id: uuid.UUID | None
    parent_name: str | None
    color: str | None
    amount_minor: int
    transaction_count: int


class TimeBucketRow(NamedTuple):
    """One grouped row of the spend-over-time aggregation."""

    bucket: datetime.date
    amount_minor: int
    transaction_count: int


class MonthlyFlowRow(NamedTuple):
    """One grouped row of the income-against-expense aggregation."""

    month: datetime.date
    kind: TransactionKind
    amount_minor: int


class KindTotalRow(NamedTuple):
    """One grouped row of a period total per kind."""

    kind: TransactionKind
    amount_minor: int
    transaction_count: int
