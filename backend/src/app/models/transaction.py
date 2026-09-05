import datetime
import uuid
from enum import StrEnum

from pydantic import ConfigDict
from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKeyConstraint, Index, text
from sqlmodel import Field, SQLModel

from .fields import MAX_AMOUNT_MINOR
from .mixins import CreatedAtMixin, PrimaryKeyMixin, UpdatedAtMixin


class TransactionKind(StrEnum):
    EXPENSE = "expense"
    INCOME = "income"
    TRANSFER = "transfer"


class TransactionSort(StrEnum):
    DATE_DESC = "-date"
    DATE_ASC = "date"
    AMOUNT_DESC = "-amount"
    AMOUNT_ASC = "amount"


class TransactionBase(SQLModel):
    kind: TransactionKind
    # Always a positive magnitude. The meaning of the number lives in `kind`,
    # not in its sign: a sign convention cannot be enforced by a constraint, so
    # a mis-signed row would be silently wrong forever, and a transfer has no
    # natural single sign at all. Sign is applied once, in SQL.
    #
    # The ceiling lives on the input models rather than here: the response
    # models share this base, and an amount stored before the cap existed has
    # to stay readable.
    amount_minor: int = Field(gt=0)
    occurred_on: datetime.date
    merchant: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=1024)


class TransactionCreate(TransactionBase):
    amount_minor: int = Field(gt=0, le=MAX_AMOUNT_MINOR)
    account_id: uuid.UUID
    category_id: uuid.UUID | None = None
    # Set only for a transfer, where it is the destination account.
    counter_account_id: uuid.UUID | None = None


class TransactionUpdate(SQLModel):
    kind: TransactionKind | None = Field(default=None)
    amount_minor: int | None = Field(default=None, gt=0, le=MAX_AMOUNT_MINOR)
    occurred_on: datetime.date | None = Field(default=None)
    merchant: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=1024)
    account_id: uuid.UUID | None = Field(default=None)
    category_id: uuid.UUID | None = Field(default=None)
    counter_account_id: uuid.UUID | None = Field(default=None)


class TransactionPublic(TransactionBase):
    id: uuid.UUID
    household_id: uuid.UUID
    account_id: uuid.UUID
    category_id: uuid.UUID | None = None
    counter_account_id: uuid.UUID | None = None
    recurring_rule_id: uuid.UUID | None = None
    income_session_id: uuid.UUID | None = None
    is_generated: bool = False
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None


class TransactionsPublic(SQLModel):
    data: list[TransactionPublic]
    count: int


class TransactionFilters(SQLModel):
    """Query parameters for listing transactions."""

    # A mistyped filter must be a 422 rather than be ignored. A silently
    # dropped filter returns more data than the caller asked for, which is the
    # dangerous direction for a page showing someone's finances.
    model_config = ConfigDict(extra="forbid")  # type: ignore[assignment]

    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    account_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    # Whether a parent category also matches spending filed under its children.
    include_subcategories: bool = True
    kind: TransactionKind | None = None
    min_amount_minor: int | None = Field(default=None, ge=0, le=MAX_AMOUNT_MINOR)
    max_amount_minor: int | None = Field(default=None, ge=0, le=MAX_AMOUNT_MINOR)
    q: str | None = Field(default=None, max_length=255)
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)
    sort: TransactionSort = TransactionSort.DATE_DESC


class Transaction(TransactionBase, PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, table=True):
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_transaction_amount_positive"),
        # A transfer is one row: source account, destination account, no
        # category. Two mirrored rows would make every edit a two-row
        # invariant that no constraint can express. As one row, the shape is
        # enforced here, and every spending report is simply kind = 'EXPENSE',
        # so a transfer can never leak into spending.
        CheckConstraint(
            "(kind = 'TRANSFER' AND counter_account_id IS NOT NULL AND category_id IS NULL)"
            " OR (kind <> 'TRANSFER' AND counter_account_id IS NULL)",
            name="ck_transaction_transfer_shape",
        ),
        CheckConstraint(
            "counter_account_id IS NULL OR counter_account_id <> account_id",
            name="ck_transaction_distinct_accounts",
        ),
        # Composite foreign keys, so a transaction cannot reference an account
        # or category belonging to another household. This holds even if a
        # service forgets to scope a query.
        ForeignKeyConstraint(
            ["account_id", "household_id"],
            ["account.id", "account.household_id"],
            name="fk_transaction_account_household",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["counter_account_id", "household_id"],
            ["account.id", "account.household_id"],
            name="fk_transaction_counter_account_household",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["category_id", "household_id"],
            ["category.id", "category.household_id"],
            name="fk_transaction_category_household",
            ondelete="RESTRICT",
        ),
        Index("ix_transaction_household_occurred", "household_id", "occurred_on"),
        # The highest value index here: it serves income against expense, the
        # savings trend, and every report that has to exclude transfers.
        Index("ix_transaction_household_kind_occurred", "household_id", "kind", "occurred_on"),
        Index(
            "ix_transaction_household_category_occurred",
            "household_id",
            "category_id",
            "occurred_on",
            postgresql_where=text("category_id IS NOT NULL"),
        ),
        Index("ix_transaction_account_occurred", "account_id", "occurred_on"),
        # Partial, because most rows are not transfers and so leave this null.
        Index(
            "ix_transaction_counter_account_occurred",
            "counter_account_id",
            "occurred_on",
            postgresql_where=text("counter_account_id IS NOT NULL"),
        ),
        # Belt and braces for recurring rules. The cursor on the rule only ever
        # moves forward, so an occurrence is created once; this makes a second
        # attempt impossible even if two requests race.
        Index(
            "uq_transaction_rule_occurrence",
            "recurring_rule_id",
            "occurred_on",
            unique=True,
            postgresql_where=text("recurring_rule_id IS NOT NULL"),
        ),
        # At most one transaction per session, enforced where two requests
        # racing to record the same payment cannot get round it.
        Index(
            "uq_transaction_income_session",
            "income_session_id",
            unique=True,
            postgresql_where=text("income_session_id IS NOT NULL"),
        ),
    )

    household_id: uuid.UUID = Field(foreign_key="household.id", ondelete="CASCADE", index=True)
    amount_minor: int = Field(sa_type=BigInteger)
    occurred_on: datetime.date = Field(sa_type=Date)
    # Declared without a single-column foreign key: the composite constraints
    # above are what enforce these references.
    account_id: uuid.UUID = Field(nullable=False)
    counter_account_id: uuid.UUID | None = Field(default=None)
    category_id: uuid.UUID | None = Field(default=None)
    created_by_user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id", ondelete="SET NULL")
    # Set when a recurring rule created this row. SET NULL on delete, so
    # removing a rule keeps the transactions it already made: they happened.
    recurring_rule_id: uuid.UUID | None = Field(default=None, foreign_key="recurringrule.id", ondelete="SET NULL")
    # Set when a paid session created this row. SET NULL on delete is belt and
    # braces: the income service removes the transaction along with the session,
    # so an orphan should be impossible, and if one ever appeared it would read
    # as ordinary income rather than as money silently vanishing.
    income_session_id: uuid.UUID | None = Field(default=None, foreign_key="incomesession.id", ondelete="SET NULL")
    is_generated: bool = Field(default=False)
    # Unused in this version. Two nullable columns now mean adding CSV or bank
    # import later is purely additive: one partial unique index for dedupe and
    # an import batch table, with no rewrite of the ledger.
    external_id: str | None = Field(default=None, max_length=255)
    import_batch_id: uuid.UUID | None = Field(default=None)
