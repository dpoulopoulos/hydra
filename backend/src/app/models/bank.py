import datetime
import uuid
from enum import StrEnum
from typing import Any

from pydantic import ConfigDict
from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKeyConstraint, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from .fields import IBAN_MAX_LENGTH, MAX_AMOUNT_MINOR, within_cap_sql
from .mixins import CreatedAtMixin, PrimaryKeyMixin, UpdatedAtMixin, UtcDateTime
from .transaction import TransactionKind


class BankConnectionStatus(StrEnum):
    # Started: the browser has gone to the bank and not come back yet.
    PENDING = "pending"
    ACTIVE = "active"
    # The bank login ran out or was withdrawn at the bank. Connecting the bank
    # again brings its accounts back, mapping and history included.
    EXPIRED = "expired"
    # Disconnected in the app.
    REVOKED = "revoked"
    # The trip to the bank was abandoned or refused.
    FAILED = "failed"


class BankSyncTrigger(StrEnum):
    MANUAL = "manual"
    AUTO = "auto"


class BankSyncStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class BankDirection(StrEnum):
    # Money into the bank account.
    CREDIT = "credit"
    # Money out of it.
    DEBIT = "debit"


class BankReviewStatus(StrEnum):
    # Waiting in the inbox.
    PENDING = "pending"
    # Recorded in the ledger. The ledger row is linked.
    ACCEPTED = "accepted"
    # Looked at and left out of the ledger.
    SKIPPED = "skipped"


class BankConnection(PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, SQLModel, table=True):
    """One login at one bank, which may reach several accounts.

    A row is never deleted while its household exists. Disconnecting marks it
    revoked instead, so the accounts and inbox rows under it keep what
    recognises a transaction already seen when the bank is connected again.
    """

    __table_args__ = (
        UniqueConstraint("id", "household_id", name="uq_bankconnection_id_household"),
        CheckConstraint("length(aspsp_country) = 2", name="ck_bankconnection_country_len"),
    )

    household_id: uuid.UUID = Field(foreign_key="household.id", ondelete="CASCADE", index=True)
    created_by_user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id", ondelete="SET NULL")
    aspsp_name: str = Field(max_length=255)
    aspsp_country: str = Field(min_length=2, max_length=2)
    status: BankConnectionStatus = Field(default=BankConnectionStatus.PENDING)
    # The unguessable token the bank hands back with the code. It is what ties
    # a callback to the person who started the login, and it is cleared once
    # used so it cannot complete a second one.
    state: str | None = Field(default=None, max_length=64, unique=True)
    # Enable Banking's session, once the login is complete.
    session_id: str | None = Field(default=None, max_length=255, unique=True)
    valid_until: datetime.datetime | None = Field(default=None, sa_type=UtcDateTime)
    authorized_at: datetime.datetime | None = Field(default=None, sa_type=UtcDateTime)
    last_synced_at: datetime.datetime | None = Field(default=None, sa_type=UtcDateTime)
    last_sync_error: str | None = Field(default=None, max_length=1024)
    # When the automatic sync next picks this connection up. Null when it is
    # not active, which keeps it out of the scheduler's query altogether.
    next_auto_sync_at: datetime.datetime | None = Field(default=None, sa_type=UtcDateTime, index=True)


class BankAccount(PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, SQLModel, table=True):
    """An account at a bank, and the Hydra account its transactions go to.

    It outlives the login it was found through. A new login gives the same
    account a new uid, so it is recognised by `identity_key` instead, and the
    mapping and what has been imported carry over.
    """

    __table_args__ = (
        UniqueConstraint("id", "household_id", name="uq_bankaccount_id_household"),
        UniqueConstraint("household_id", "identity_key", name="uq_bankaccount_household_identity"),
        ForeignKeyConstraint(
            ["connection_id", "household_id"],
            ["bankconnection.id", "bankconnection.household_id"],
            name="fk_bankaccount_connection_household",
            ondelete="CASCADE",
        ),
        # Deleting the Hydra account unmaps the bank account rather than being
        # blocked by it. The column list matters: a bare SET NULL would null
        # household_id too.
        ForeignKeyConstraint(
            ["account_id", "household_id"],
            ["account.id", "account.household_id"],
            name="fk_bankaccount_account_household",
            ondelete="SET NULL (account_id)",
        ),
        # One Hydra account is fed by one bank account at most. Two would put
        # every transaction in twice.
        Index(
            "uq_bankaccount_account",
            "account_id",
            unique=True,
            postgresql_where=text("account_id IS NOT NULL"),
        ),
    )

    household_id: uuid.UUID = Field(foreign_key="household.id", ondelete="CASCADE", index=True)
    # The login this account is reached through now.
    connection_id: uuid.UUID = Field(nullable=False, index=True)
    # The account's uid within that login.
    provider_account_uid: str = Field(max_length=255)
    # The bank's identification hash when it sends one, the IBAN otherwise.
    identity_key: str = Field(max_length=255)
    iban: str | None = Field(default=None, max_length=IBAN_MAX_LENGTH)
    name: str | None = Field(default=None, max_length=255)
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    # The Hydra account this one feeds. Null until it is mapped.
    account_id: uuid.UUID | None = Field(default=None)
    # Nothing booked before this date is fetched. It is at least the Hydra
    # account's opening balance date, since anything earlier is already part
    # of the opening balance.
    import_from: datetime.date | None = Field(default=None, sa_type=Date)
    sync_enabled: bool = Field(default=True)
    # The latest booking date imported, which is where the next sync starts,
    # less an overlap.
    last_booked_on: datetime.date | None = Field(default=None, sa_type=Date)


class BankSyncRun(PrimaryKeyMixin, SQLModel, table=True):
    """One pull from one connection: the import batch a ledger row came in with."""

    __table_args__ = (
        UniqueConstraint("id", "household_id", name="uq_banksyncrun_id_household"),
        ForeignKeyConstraint(
            ["connection_id", "household_id"],
            ["bankconnection.id", "bankconnection.household_id"],
            name="fk_banksyncrun_connection_household",
            ondelete="CASCADE",
        ),
    )

    household_id: uuid.UUID = Field(foreign_key="household.id", ondelete="CASCADE", index=True)
    connection_id: uuid.UUID = Field(nullable=False, index=True)
    trigger: BankSyncTrigger
    status: BankSyncStatus = Field(default=BankSyncStatus.RUNNING)
    started_at: datetime.datetime = Field(sa_type=UtcDateTime)
    finished_at: datetime.datetime | None = Field(default=None, sa_type=UtcDateTime)
    # Booked rows the bank returned, and how many of them were new.
    fetched_count: int = Field(default=0)
    new_count: int = Field(default=0)
    error: str | None = Field(default=None, max_length=1024)


class BankTransaction(PrimaryKeyMixin, CreatedAtMixin, SQLModel, table=True):
    """A booked transaction from a bank, waiting in or settled out of the inbox."""

    __table_args__ = (
        # What makes a re-fetched row a no-op. Every sync overlaps the last.
        UniqueConstraint("bank_account_id", "dedupe_key", name="uq_banktransaction_account_dedupe"),
        CheckConstraint("amount_minor > 0", name="ck_banktransaction_amount_positive"),
        CheckConstraint(within_cap_sql("amount_minor", MAX_AMOUNT_MINOR), name="ck_banktransaction_amount_within_cap"),
        ForeignKeyConstraint(
            ["bank_account_id", "household_id"],
            ["bankaccount.id", "bankaccount.household_id"],
            name="fk_banktransaction_bankaccount_household",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["sync_run_id", "household_id"],
            ["banksyncrun.id", "banksyncrun.household_id"],
            name="fk_banktransaction_syncrun_household",
            ondelete="SET NULL (sync_run_id)",
        ),
        # The inbox: what is waiting, newest first.
        Index("ix_banktransaction_household_status_occurred", "household_id", "review_status", "occurred_on"),
        Index(
            "ix_banktransaction_ledger_transaction",
            "ledger_transaction_id",
            postgresql_where=text("ledger_transaction_id IS NOT NULL"),
        ),
    )

    household_id: uuid.UUID = Field(foreign_key="household.id", ondelete="CASCADE", index=True)
    bank_account_id: uuid.UUID = Field(nullable=False)
    sync_run_id: uuid.UUID | None = Field(default=None)
    # The bank's own reference when it gives one, a fingerprint of the row
    # otherwise. Kept for good, after `raw` is cleared.
    dedupe_key: str = Field(max_length=255)
    direction: BankDirection
    # A positive magnitude, as in the ledger. `direction` carries the meaning.
    amount_minor: int = Field(sa_type=BigInteger)
    currency_code: str = Field(min_length=3, max_length=3)
    occurred_on: datetime.date = Field(sa_type=Date)
    booking_date: datetime.date | None = Field(default=None, sa_type=Date)
    value_date: datetime.date | None = Field(default=None, sa_type=Date)
    transaction_date: datetime.date | None = Field(default=None, sa_type=Date)
    counterparty_name: str | None = Field(default=None, max_length=255)
    counterparty_iban: str | None = Field(default=None, max_length=IBAN_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=1024)
    # What the bank sent, whole. Cleared after BANK_RAW_RETENTION_DAYS.
    raw: dict[str, Any] | None = Field(default=None, sa_type=JSONB)
    review_status: BankReviewStatus = Field(default=BankReviewStatus.PENDING)
    # The ledger row an accepted transaction became. Deleting that row through
    # the app sends this one back to the inbox.
    ledger_transaction_id: uuid.UUID | None = Field(default=None, foreign_key="transaction.id", ondelete="SET NULL")
    reviewed_by_user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id", ondelete="SET NULL")
    reviewed_at: datetime.datetime | None = Field(default=None, sa_type=UtcDateTime)


class BankStatus(SQLModel):
    # Whether bank sync is configured on this server.
    enabled: bool


class AspspPublic(SQLModel):
    name: str
    country: str
    logo: str | None = None


class AspspsPublic(SQLModel):
    data: list[AspspPublic]
    count: int


class BankConnectionStart(SQLModel):
    aspsp_name: str = Field(min_length=1, max_length=255)
    aspsp_country: str = Field(min_length=2, max_length=2)


class BankAuthorizationStarted(SQLModel):
    # Where to send the browser to log in at the bank.
    url: str


class BankConnectionComplete(SQLModel):
    # What the bank put in the redirect back to the app.
    code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=1, max_length=64)


class BankAccountUpdate(SQLModel):
    # Null unlinks the bank account; leaving the field out keeps the link.
    account_id: uuid.UUID | None = Field(default=None)
    import_from: datetime.date | None = Field(default=None)
    sync_enabled: bool | None = Field(default=None)


class BankAccountPublic(SQLModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    name: str | None = None
    iban: str | None = None
    currency_code: str | None = None
    account_id: uuid.UUID | None = None
    import_from: datetime.date | None = None
    sync_enabled: bool
    last_booked_on: datetime.date | None = None


class BankConnectionPublic(SQLModel):
    id: uuid.UUID
    aspsp_name: str
    aspsp_country: str
    status: BankConnectionStatus
    valid_until: datetime.datetime | None = None
    authorized_at: datetime.datetime | None = None
    last_synced_at: datetime.datetime | None = None
    last_sync_error: str | None = None
    created_by_user_id: uuid.UUID | None = None
    accounts: list[BankAccountPublic]
    created_at: datetime.datetime


class BankConnectionsPublic(SQLModel):
    data: list[BankConnectionPublic]
    count: int


class BankSyncRunPublic(SQLModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    trigger: BankSyncTrigger
    status: BankSyncStatus
    started_at: datetime.datetime
    finished_at: datetime.datetime | None = None
    fetched_count: int
    new_count: int
    error: str | None = None


class BankInboxFilters(SQLModel):
    """Query parameters for listing the inbox."""

    # A mistyped filter must be a 422 rather than be ignored.
    model_config = ConfigDict(extra="forbid")  # type: ignore[assignment]

    status: BankReviewStatus = BankReviewStatus.PENDING
    bank_account_id: uuid.UUID | None = None
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)


class BankTransactionPublic(SQLModel):
    id: uuid.UUID
    bank_account_id: uuid.UUID
    bank_account_name: str | None = None
    # The Hydra account the bank account feeds, if it is still linked.
    account_id: uuid.UUID | None = None
    direction: BankDirection
    amount_minor: int
    currency_code: str
    occurred_on: datetime.date
    value_date: datetime.date | None = None
    transaction_date: datetime.date | None = None
    counterparty_name: str | None = None
    counterparty_iban: str | None = None
    description: str | None = None
    review_status: BankReviewStatus
    ledger_transaction_id: uuid.UUID | None = None
    reviewed_at: datetime.datetime | None = None
    created_at: datetime.datetime


class BankTransactionsPublic(SQLModel):
    data: list[BankTransactionPublic]
    count: int


class BankTransactionAccept(SQLModel):
    """How to record a bank transaction in the ledger.

    The amount, the date and the bank account's side are the bank's and are
    not chosen here.
    """

    kind: TransactionKind
    category_id: uuid.UUID | None = None
    # For a transfer: the other account. Money out of the bank account goes to
    # it; money in comes from it.
    counter_account_id: uuid.UUID | None = None
    goal_id: uuid.UUID | None = None
    # What the ledger row is called. Defaults to the counterparty.
    merchant: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=1024)
