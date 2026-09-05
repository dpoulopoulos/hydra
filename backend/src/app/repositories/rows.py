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


class SessionMonthRow(NamedTuple):
    """One grouped row of the sessions-by-month aggregation.

    `earned` and `received` are separate on purpose. The first is what the
    month's work was worth and is what the forecast reads; the second is what
    actually arrived and is the only one the ledger agrees with.
    """

    month: datetime.date
    earned_minor: int
    received_minor: int
    attended_count: int
    missed_count: int
    cancelled_count: int
    unpaid_count: int
    client_count: int


class ClientTallyRow(NamedTuple):
    """One grouped row of the per-client aggregation.

    The counts and `earned_minor` cover the requested window; the outstanding
    figures cover all of time, because a debt does not expire with the window
    somebody happened to ask about.
    """

    client_id: uuid.UUID
    attended_count: int
    missed_count: int
    # Called off in advance. Kept apart from a no-show because only one of the
    # two says the hour was never going to happen, and the forecast prices an
    # appointment by how often that client's appointments survive.
    cancelled_count: int
    earned_minor: int
    outstanding_minor: int
    oldest_unpaid_on: datetime.date | None
    last_session_on: datetime.date | None


class NewClientMonthRow(NamedTuple):
    """What clients the practice had never seen before brought, in one month.

    A client counts as new in the month of their very first session ever, and
    every session they had that month counts with them. It is the arrival rate
    the forecast needs: not how many strangers rang up, but how much work they
    turned into.
    """

    month: datetime.date
    session_count: int
    earned_minor: int
