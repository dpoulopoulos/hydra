"""Freelance income: clients, the sessions they attend, and what they pay.

A salary lands on the same day for the same amount. A freelance practice does
not: a client comes or is ill, pays on the day or three weeks later, and a new
client makes the month better than the last one. This module is the record of
that, and the forecast built on top of it.

Two facts are kept apart on every session, and keeping them apart is the point
of the whole module:

* what happened  - the hour was worked, missed, called off, or is still ahead
* whether it was paid - the money is here, still owed, or was never charged

Only a paid session is money, so only a paid session reaches the ledger. An
attended session nobody has paid for yet is a debt, and calling it income would
be a lie the account balance would eventually contradict.

Client names never reach this database in the clear. They arrive already
encrypted by the browser and are stored, returned and never read here. That is
why the columns are named `*_ct`, why there is no uniqueness constraint on a
name, and why nothing in this module can search by one.

The key is one person's, not the household's. A practice belongs to whoever runs
it: everyone in the household sees the sessions and the money, because that is
household income and it lands in the shared ledger, but only the person who
added a client can read that client's name. Everybody else sees the row with the
name blanked out. That is why the vault is keyed on the user and why a client
records who owns it.
"""

import datetime
import uuid
from enum import StrEnum

from pydantic import ConfigDict
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field, SQLModel

from .fields import MAX_AMOUNT_MINOR, MonthKey, within_cap_sql
from .mixins import CreatedAtMixin, PrimaryKeyMixin, UpdatedAtMixin, UtcDateTime
from .recurring_rule import MAX_RECURRENCE_INTERVAL, RecurrenceFrequency

# Ciphertext is base64 of a 12 byte nonce, the AES-GCM ciphertext and its 16
# byte tag, so it is always longer than the text it hides. These bounds leave
# room for a long name or a paragraph of notes and still refuse anything that
# is plainly not a name at all.
MAX_NAME_CIPHERTEXT_LENGTH = 512
MAX_NOTE_CIPHERTEXT_LENGTH = 2048

# Monday is 0, matching datetime.date.weekday(), so the two never need
# translating between each other.
MONDAY = 0
SUNDAY = 6


class IncomeSessionStatus(StrEnum):
    """What happened to the hour."""

    SCHEDULED = "scheduled"
    ATTENDED = "attended"
    # A no-show. Counts against the client's attendance rate.
    MISSED = "missed"
    # Called off in advance. Deliberately not counted against the client: it is
    # the difference between someone who forgets and someone who telephones.
    CANCELLED = "cancelled"


class PaymentStatus(StrEnum):
    """Whether the money arrived."""

    # Earned and not yet in the bank. This is a debt, not income.
    PENDING = "pending"
    # The money is here. This, and only this, puts a row in the ledger.
    PAID = "paid"
    # Deliberately not charged: a free intake, a make-up session, goodwill.
    # Neither owed nor earned, so it leaves the debtors list without pretending
    # anybody paid.
    WAIVED = "waived"


class ForecastBasis(StrEnum):
    """How much the forecast is actually worth believing."""

    HISTORY = "history"
    SINGLE_MONTH = "single_month"
    INSUFFICIENT_HISTORY = "insufficient_history"


class IncomeSessionSort(StrEnum):
    DATE_DESC = "-date"
    DATE_ASC = "date"


# --------------------------------------------------------------------------- #
# The vault: what the browser needs to rebuild the key, and nothing else.
# --------------------------------------------------------------------------- #


class IncomeVaultBase(SQLModel):
    """One person's key material for the encryption of their client names.

    Every field here is opaque to the server. It stores them, hands them back,
    and cannot read a single name with them: the PIN that unlocks the wrapped
    key never leaves the browser. Storing the parameters rather than hardcoding
    them is what allows the cost of the key derivation to be raised later
    without stranding a vault created under the old ones.

    One row per user rather than per household. Two people sharing a household
    share their money, not their client lists, and a shared PIN would make one
    person's practice readable by the other.
    """

    kdf: str = Field(default="argon2id", max_length=32)
    kdf_salt: str = Field(max_length=64)
    kdf_memory_kib: int = Field(ge=1)
    kdf_iterations: int = Field(ge=1)
    kdf_parallelism: int = Field(ge=1)
    # base64 of nonce || AES-GCM(data key). A wrong PIN fails to unwrap this,
    # which is the only PIN check there is or should be: a separate verifier
    # would hand an offline guesser a free oracle.
    wrapped_dek: str = Field(max_length=256)


class IncomeVaultUpsert(IncomeVaultBase):
    """Set up the vault, or re-wrap the same key under a new PIN.

    Changing a PIN re-wraps the data key and touches no client row, because the
    names were never encrypted with the PIN itself.
    """


class IncomeVaultPublic(IncomeVaultBase):
    user_id: uuid.UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None


class IncomeVault(IncomeVaultBase, CreatedAtMixin, UpdatedAtMixin, table=True):
    user_id: uuid.UUID = Field(
        foreign_key="user.id",
        ondelete="CASCADE",
        primary_key=True,
    )


# --------------------------------------------------------------------------- #
# Clients
# --------------------------------------------------------------------------- #


class IncomeClientBase(SQLModel):
    # Encrypted by the browser before it is sent. Never a name in the clear.
    name_ct: str = Field(max_length=MAX_NAME_CIPHERTEXT_LENGTH)
    # How often this person is seen: weekly, fortnightly, monthly, or nothing
    # settled at all. Most of a practice is standing appointments, and the
    # pattern is a fact about the client rather than about any one hour.
    #
    # The same vocabulary as recurring rules, because it is the same question
    # and the date arithmetic behind it is already written and tested.
    cadence_frequency: RecurrenceFrequency | None = Field(default=None)
    # Every `interval` periods. Two with a weekly frequency is a fortnight.
    cadence_interval: int = Field(default=1, ge=1)
    # The date the pattern is pinned to. A monthly cadence keeps its day of the
    # month; a weekly one keeps its weekday, unless `cadence_weekdays` names
    # days outright, and then this only decides which weeks count.
    cadence_anchor_on: datetime.date | None = Field(default=None)
    # The days of the week a weekly cadence falls on, Monday as 0. This is what
    # lets a practice say "Monday, Tuesday, Thursday and Friday" rather than
    # being forced into one appointment a week. Empty means the pattern simply
    # keeps the weekday it was pinned to, which is the common case and needs no
    # thought from anybody.
    cadence_weekdays: list[int] = Field(default_factory=list, sa_column=Column(ARRAY(SmallInteger)))
    # Encrypted too. A note about a client identifies them as surely as a name.
    note_ct: str | None = Field(default=None, max_length=MAX_NOTE_CIPHERTEXT_LENGTH)
    # What this client usually pays for an hour. A starting point for a session,
    # never the last word on it: the fee lives on the session, because it is the
    # session that varies.
    default_rate_minor: int = Field(default=0, ge=0)


class IncomeClientCreate(IncomeClientBase):
    cadence_interval: int = Field(default=1, ge=1, le=MAX_RECURRENCE_INTERVAL)
    # The ceiling lives here rather than on the base, which the table and the
    # response models share. A rate stored before the cap existed still has to
    # be readable: refusing it on the way out is the 500 this bound prevents,
    # moved to the read path.
    default_rate_minor: int = Field(default=0, ge=0, le=MAX_AMOUNT_MINOR)
    # Required, not optional. Every paid session has to land somewhere, and
    # asking once at creation removes a failure that would otherwise turn up
    # months later, halfway through recording a payment.
    default_account_id: uuid.UUID
    default_category_id: uuid.UUID | None = None


class IncomeClientUpdate(SQLModel):
    name_ct: str | None = Field(default=None, max_length=MAX_NAME_CIPHERTEXT_LENGTH)
    # Sent as null to go back to seeing somebody as and when.
    cadence_frequency: RecurrenceFrequency | None = Field(default=None)
    cadence_interval: int | None = Field(default=None, ge=1, le=MAX_RECURRENCE_INTERVAL)
    cadence_anchor_on: datetime.date | None = Field(default=None)
    cadence_weekdays: list[int] | None = Field(default=None)
    note_ct: str | None = Field(default=None, max_length=MAX_NOTE_CIPHERTEXT_LENGTH)
    default_rate_minor: int | None = Field(default=None, ge=0, le=MAX_AMOUNT_MINOR)
    default_account_id: uuid.UUID | None = Field(default=None)
    default_category_id: uuid.UUID | None = Field(default=None)
    is_archived: bool | None = Field(default=None)


class IncomeClientPublic(IncomeClientBase):
    id: uuid.UUID
    household_id: uuid.UUID
    # Who added this client, and so whose key the name is under. The page reads
    # it to know whether to try decrypting at all, and whether to offer an edit.
    owner_user_id: uuid.UUID
    # Redeclared without the base's default, so the generated client is told
    # what is true: a stored client always has a rate, even if it is zero.
    default_rate_minor: int
    cadence_interval: int
    cadence_weekdays: list[int]
    default_account_id: uuid.UUID
    default_category_id: uuid.UUID | None = None
    archived_at: datetime.datetime | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None


class IncomeClientsPublic(SQLModel):
    data: list[IncomeClientPublic]
    count: int


class IncomeClientFilters(SQLModel):
    """Query parameters for listing clients.

    There is deliberately no text search. The server cannot read a name, so a
    `q` parameter here could only ever match nothing, and offering one would
    imply a capability that the encryption exists to remove.
    """

    model_config = ConfigDict(extra="forbid")  # type: ignore[assignment]

    is_archived: bool | None = None
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=200)


class IncomeClient(IncomeClientBase, PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, table=True):
    __table_args__ = (
        CheckConstraint("default_rate_minor >= 0", name="ck_incomeclient_rate_non_negative"),
        CheckConstraint(
            within_cap_sql("default_rate_minor", MAX_AMOUNT_MINOR),
            name="ck_incomeclient_rate_within_cap",
        ),
        CheckConstraint("cadence_interval >= 1", name="ck_incomeclient_cadence_interval_positive"),
        CheckConstraint(
            within_cap_sql("cadence_interval", MAX_RECURRENCE_INTERVAL),
            name="ck_incomeclient_cadence_interval_within_cap",
        ),
        # A pattern with nothing to pin it to is not a pattern: "every week"
        # cannot say which day without an anchor. Either both are set or
        # neither is, and the row can never be half a schedule.
        CheckConstraint(
            "(cadence_frequency IS NULL AND cadence_anchor_on IS NULL)"
            " OR (cadence_frequency IS NOT NULL AND cadence_anchor_on IS NOT NULL)",
            name="ck_incomeclient_cadence_shape",
        ),
        # Monday to Sunday and nothing else. An out-of-range day would silently
        # never match, which is worse than being refused.
        CheckConstraint(
            f"cadence_weekdays IS NULL OR ("
            f"array_length(cadence_weekdays, 1) IS NULL OR ("
            f"{MONDAY} <= ALL(cadence_weekdays) AND {SUNDAY} >= ALL(cadence_weekdays)))",
            name="ck_incomeclient_cadence_weekdays_range",
        ),
        # Composite foreign key target, so a session cannot reference a client
        # belonging to a different household.
        UniqueConstraint("id", "household_id", name="uq_incomeclient_id_household"),
        # There is no unique constraint on the name, and there cannot be one:
        # the same name encrypts to different ciphertext every time. Two clients
        # with one name are allowed here and warned about in the page, which is
        # the only place a name can actually be read.
        ForeignKeyConstraint(
            ["default_account_id", "household_id"],
            ["account.id", "account.household_id"],
            name="fk_incomeclient_account_household",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["default_category_id", "household_id"],
            ["category.id", "category.household_id"],
            name="fk_incomeclient_category_household",
            ondelete="RESTRICT",
        ),
    )

    household_id: uuid.UUID = Field(foreign_key="household.id", ondelete="CASCADE", index=True)
    # Whose practice this client belongs to, and whose key their name is
    # encrypted under. Never null: a name with no owner is a name nobody can
    # ever read. RESTRICT rather than CASCADE, because removing a user must not
    # silently delete the sessions and income behind their clients.
    owner_user_id: uuid.UUID = Field(foreign_key="user.id", ondelete="RESTRICT", index=True)
    default_rate_minor: int = Field(default=0, sa_type=BigInteger)
    cadence_anchor_on: datetime.date | None = Field(default=None, sa_type=Date)
    # Declared without single-column foreign keys: the composite constraints
    # above are what enforce these references.
    default_account_id: uuid.UUID = Field(nullable=False)
    default_category_id: uuid.UUID | None = Field(default=None)
    # Archived rather than deleted, and stamped rather than flagged: a client
    # you stop seeing is like an account you close, and the date is worth
    # keeping.
    archived_at: datetime.datetime | None = Field(default=None, sa_type=UtcDateTime)


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #


class IncomeSessionBase(SQLModel):
    # When the hour was. Not when the money moved: that is `paid_on`.
    occurs_on: datetime.date
    # Zero is legal. A free intake session or a make-up hour is a real session
    # and belongs in the attendance record even though it earns nothing.
    fee_minor: int = Field(default=0, ge=0)
    status: IncomeSessionStatus = IncomeSessionStatus.SCHEDULED
    payment_status: PaymentStatus = PaymentStatus.PENDING
    # When the money actually arrived, which is the date the ledger uses. An
    # hour worked on 28 September and paid on 3 October is October's income,
    # because that is the month a bank statement would show it in.
    paid_on: datetime.date | None = Field(default=None)
    note_ct: str | None = Field(default=None, max_length=MAX_NOTE_CIPHERTEXT_LENGTH)


class IncomeSessionCreate(IncomeSessionBase):
    fee_minor: int = Field(default=0, ge=0, le=MAX_AMOUNT_MINOR)
    client_id: uuid.UUID


class IncomeSessionUpdate(SQLModel):
    client_id: uuid.UUID | None = Field(default=None)
    occurs_on: datetime.date | None = Field(default=None)
    fee_minor: int | None = Field(default=None, ge=0, le=MAX_AMOUNT_MINOR)
    status: IncomeSessionStatus | None = Field(default=None)
    payment_status: PaymentStatus | None = Field(default=None)
    paid_on: datetime.date | None = Field(default=None)
    note_ct: str | None = Field(default=None, max_length=MAX_NOTE_CIPHERTEXT_LENGTH)


class IncomeSessionPublic(IncomeSessionBase):
    id: uuid.UUID
    household_id: uuid.UUID
    client_id: uuid.UUID
    # Redeclared without the base's defaults. A stored session always has all
    # four, and a default here would make them optional in the generated client
    # for no reason other than how the table was declared.
    occurs_on: datetime.date
    fee_minor: int
    status: IncomeSessionStatus
    payment_status: PaymentStatus
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None


class IncomeSessionsPublic(SQLModel):
    data: list[IncomeSessionPublic]
    count: int
    # Across the sessions the filter matched, so the table footer is the same
    # request rather than a second one.
    earned_total_minor: int = 0
    outstanding_total_minor: int = 0


class IncomeSessionFilters(SQLModel):
    """Query parameters for listing sessions.

    A mistyped filter must be a 422 rather than be ignored. A silently dropped
    filter returns more data than the caller asked for, which is the dangerous
    direction for a page listing who owes money.
    """

    model_config = ConfigDict(extra="forbid")  # type: ignore[assignment]

    client_id: uuid.UUID | None = None
    # Shorthand for the two dates below, which is what the page uses.
    month: MonthKey | None = None
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    status: IncomeSessionStatus | None = None
    # "Who has not paid me" is one query string away, which is the question
    # this whole module exists to answer.
    payment_status: PaymentStatus | None = None
    # Narrow to work somebody actually owes for: the hour was worked, the fee
    # was not written off, and it is not zero. Without it a debtors list also
    # shows next week's appointments, which are unpaid only in the sense that
    # they have not happened yet.
    owed_only: bool = False
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)
    sort: IncomeSessionSort = IncomeSessionSort.DATE_DESC


class IncomeSession(IncomeSessionBase, PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, table=True):
    __table_args__ = (
        CheckConstraint("fee_minor >= 0", name="ck_incomesession_fee_non_negative"),
        CheckConstraint(within_cap_sql("fee_minor", MAX_AMOUNT_MINOR), name="ck_incomesession_fee_within_cap"),
        # `paid_on` is the date of a payment, so it exists exactly when there
        # was one. Without this, a row could claim to be paid on no date, or
        # carry a payment date while sitting in the debtors list.
        #
        # The enum is compared against its member name, not its value, which is
        # how SQLModel stores it and how every other check in this app is
        # written.
        CheckConstraint(
            "(payment_status = 'PAID' AND paid_on IS NOT NULL) OR (payment_status <> 'PAID' AND paid_on IS NULL)",
            name="ck_incomesession_paid_on_shape",
        ),
        ForeignKeyConstraint(
            ["client_id", "household_id"],
            ["incomeclient.id", "incomeclient.household_id"],
            name="fk_incomesession_client_household",
            ondelete="RESTRICT",
        ),
        Index("ix_incomesession_household_occurs", "household_id", "occurs_on"),
        # The per-client walk behind the attendance rate and the client table.
        Index("ix_incomesession_client_occurs", "client_id", "occurs_on"),
        # The month and status aggregation the forecast is built from.
        Index("ix_incomesession_household_status_occurs", "household_id", "status", "occurs_on"),
        # "What am I owed", which is a tile on the page and so runs on every
        # single load.
        Index("ix_incomesession_household_payment_occurs", "household_id", "payment_status", "occurs_on"),
    )

    household_id: uuid.UUID = Field(foreign_key="household.id", ondelete="CASCADE", index=True)
    # Declared without a single-column foreign key: the composite constraint
    # above is what enforces this reference.
    client_id: uuid.UUID = Field(nullable=False)
    occurs_on: datetime.date = Field(sa_type=Date)
    fee_minor: int = Field(default=0, sa_type=BigInteger)
    paid_on: datetime.date | None = Field(default=None, sa_type=Date)
    created_by_user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id", ondelete="SET NULL")


# --------------------------------------------------------------------------- #
# Reporting: the summary tiles and the forecast
# --------------------------------------------------------------------------- #


class IncomeMonth(SQLModel):
    """One month of the practice, as the forecast sees it."""

    month: str
    # What the month was worth: every worked, chargeable session in it. This is
    # what the forecast is built on, because it describes the practice rather
    # than the clients' banking habits.
    earned_minor: int
    # What actually arrived. The only one of the three that matches /reports.
    received_minor: int
    # earned - received. What people still owe for that month's work.
    outstanding_minor: int
    attended_count: int
    missed_count: int
    cancelled_count: int
    unpaid_count: int
    client_count: int
    # What was still owed when the month closed: everything worked by then that
    # had not been paid for by then. A running balance, so it falls when people
    # settle up, unlike `outstanding_minor`, which only ever describes the one
    # month's own work.
    owed_balance_minor: int = 0


class ClientForecastRow(SQLModel):
    """One client's contribution, and what they still owe."""

    client_id: uuid.UUID
    # Still ciphertext. The page decrypts it; the server never could.
    name_ct: str
    attended_count: int
    missed_count: int
    # attended / (attended + missed). None rather than 0.0 when there is
    # nothing to divide, so an untested client is not shown as unreliable.
    attendance_rate: float | None = None
    outstanding_minor: int
    # How long the oldest debt has been sitting there, which is the number that
    # decides whether it is worth a telephone call.
    oldest_unpaid_on: datetime.date | None = None
    average_monthly_minor: int
    booked_minor: int
    last_session_on: datetime.date | None = None
    is_archived: bool


class IncomeForecast(SQLModel):
    """What the coming month is likely to bring."""

    month: str
    currency_code: str
    likely_minor: int
    low_minor: int
    high_minor: int
    basis: ForecastBasis
    months_used: int
    # Oldest first, and complete months only: the current month is a fraction of
    # itself and would drag the average down in exactly the week the estimate is
    # worth reading.
    history: list[IncomeMonth]
    # Sessions already in the diary for the forecast month.
    booked_minor: int
    booked_session_count: int
    # What the month has already earned: work done and chargeable. The one
    # figure here that is a fact, and the only one the estimate treats as a
    # floor. Zero for a month still to come, most of the answer by the end of
    # one in progress.
    earned_so_far_minor: int
    # What the sessions still in the diary are expected to bring, discounted by
    # how much of a diary has historically turned into work. Always at or below
    # `booked_minor`, because some appointments are missed or called off.
    expected_from_diary_minor: int
    # The discount that was applied, 0 to 1, for the page to explain itself
    # with. None when there is no record to work it out from, in which case the
    # diary was taken at face value.
    diary_realisation_rate: float | None = None
    # How many appointments the month holds: booked, plus the standing ones a
    # client's schedule says are still to come. The number of coin flips behind
    # the estimate, and what makes it move when the roster does.
    trial_count: int = 0
    # How many of those the estimate expects to actually happen, including the
    # strangers. None when the figure came from monthly totals instead, which
    # do not know how many hours went into them.
    expected_session_count: float | None = None
    # Sessions a month from clients the practice had never seen before. The one
    # part of the estimate no schedule could have predicted.
    new_client_session_rate: float | None = None
    # How often the month should land inside the band, as a percentage.
    confidence_percent: int = 95
    # The share of a caseload that stops coming in a month. Somebody leaving is
    # not a cancellation: it takes every future appointment with it, which is
    # why an appointment late in the month is worth slightly less than an
    # identical one early in it.
    monthly_churn_rate: float | None = None
    # How long a client typically stays, in months. The mean of a
    # geometric distribution: one client in twenty leaving each month means
    # the average client stays twenty. None until somebody has actually
    # left, because a short record is not evidence that nobody leaves.
    expected_client_months: float | None = None
    # What one client is worth over that whole time. The figure that says
    # whether taking somebody new on is worth the effort, which no monthly
    # total ever does.
    client_lifetime_value_minor: int | None = None
    average_sessions_per_month: float | None = None
    # How many clients the practice still sees, and how many of them the
    # estimate was able to price. They agree for every practice small enough to
    # be read in one go. When they do not, the estimate covers `priced` of
    # `active` clients and is low by whatever the rest would have brought, so
    # the page has to be able to say that rather than show a bare figure.
    active_client_count: int = 0
    priced_client_count: int = 0
    clients: list[ClientForecastRow]


class IncomeSummary(SQLModel):
    """The tiles for one month, in a single request."""

    month: str
    currency_code: str
    earned_minor: int
    received_minor: int
    outstanding_minor: int
    # Owed across every month, not only this one. A debt from March is still a
    # debt in September, and a tile scoped to the current month would hide the
    # ones worth chasing.
    total_outstanding_minor: int
    oldest_unpaid_on: datetime.date | None = None
    attended_count: int
    unpaid_count: int
    scheduled_minor: int
    scheduled_count: int
    missed_count: int
    cancelled_count: int
    active_client_count: int
    # The calendar year the month falls in, and what has been earned across the
    # whole of it. A freelancer's year is the unit the tax office asks about,
    # and it is the only figure here that a single quiet month cannot move.
    year: int = 0
    year_earned_minor: int = 0
    year_session_count: int = 0
