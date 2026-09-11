import datetime
import uuid
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKeyConstraint, Index
from sqlmodel import Field, SQLModel

from .fields import MAX_AMOUNT_MINOR, within_cap_sql
from .mixins import CreatedAtMixin, PrimaryKeyMixin, UpdatedAtMixin
from .transaction import TransactionKind

# A hundred years of monthly occurrences. The date arithmetic behind a rule
# builds real dates, and datetime.date stops at year 9999, so an unbounded
# interval pushes the next occurrence past the last date there is: an error
# raised on every read that materialises a rule. No real schedule repeats less
# often than this.
MAX_RECURRENCE_INTERVAL = 1200


class RecurrenceFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class RecurringRuleBase(SQLModel):
    name: str = Field(max_length=255)
    frequency: RecurrenceFrequency = RecurrenceFrequency.MONTHLY
    # Every `interval` periods. Two with a weekly frequency is a fortnight.
    interval: int = Field(default=1, ge=1)
    start_date: datetime.date
    end_date: datetime.date | None = Field(default=None)
    # For a monthly or yearly rule, the day it falls on. A day beyond the end
    # of a short month is pulled back to the last day of it.
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    # --- the transaction this rule creates ---
    kind: TransactionKind = TransactionKind.EXPENSE
    amount_minor: int = Field(gt=0)
    merchant: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=1024)
    is_active: bool = True


class RecurringRuleCreate(RecurringRuleBase):
    # The caps live here rather than on the base, which the table and the
    # response models share. A rule stored before either cap existed still has
    # to be readable: refusing it on the way out is the 500 this bound is meant
    # to prevent, moved to the read path.
    interval: int = Field(default=1, ge=1, le=MAX_RECURRENCE_INTERVAL)
    amount_minor: int = Field(gt=0, le=MAX_AMOUNT_MINOR)
    account_id: uuid.UUID
    category_id: uuid.UUID | None = None
    counter_account_id: uuid.UUID | None = None


class RecurringRuleUpdate(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    frequency: RecurrenceFrequency | None = Field(default=None)
    interval: int | None = Field(default=None, ge=1, le=MAX_RECURRENCE_INTERVAL)
    end_date: datetime.date | None = Field(default=None)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    amount_minor: int | None = Field(default=None, gt=0, le=MAX_AMOUNT_MINOR)
    merchant: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=1024)
    category_id: uuid.UUID | None = Field(default=None)
    is_active: bool | None = Field(default=None)


class RecurringRulePublic(RecurringRuleBase):
    id: uuid.UUID
    household_id: uuid.UUID
    account_id: uuid.UUID
    category_id: uuid.UUID | None = None
    counter_account_id: uuid.UUID | None = None
    next_occurrence_on: datetime.date | None = None
    last_generated_on: datetime.date | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None


class RecurringRulesPublic(SQLModel):
    data: list[RecurringRulePublic]
    count: int


class UpcomingOccurrence(SQLModel):
    """A date a rule will fall due on, not yet recorded."""

    rule_id: uuid.UUID
    name: str
    kind: TransactionKind
    amount_minor: int
    occurs_on: datetime.date
    account_id: uuid.UUID
    category_id: uuid.UUID | None = None
    # Whether the rule is unable to record this occurrence, because an account
    # it names has been archived. It is still projected, so the list can say
    # what a restored account would pick up, but it is money that will not
    # move while the account is away.
    is_blocked: bool = False


class UpcomingOccurrencesPublic(SQLModel):
    data: list[UpcomingOccurrence]
    count: int
    # Signed by kind and with transfers left out, the way every other total in
    # the API is derived. An amount is a positive magnitude, so summing the
    # occurrences as they stand would count income as an outgoing and count a
    # move between the household's own accounts at all. A blocked occurrence
    # is left out too: nothing is going to be recorded for it.
    net_minor: int = 0


class RecurringRunResult(SQLModel):
    """What one materialization pass did."""

    created_count: int
    # Occurrences that fell due but were not written: the rule's account is
    # archived or gone, or the transaction was already there.
    skipped_count: int
    rules_advanced: int


class RecurringRule(RecurringRuleBase, PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, table=True):
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_recurringrule_amount_positive"),
        CheckConstraint(within_cap_sql("amount_minor", MAX_AMOUNT_MINOR), name="ck_recurringrule_amount_within_cap"),
        CheckConstraint("interval >= 1", name="ck_recurringrule_interval_positive"),
        CheckConstraint(
            within_cap_sql("interval", MAX_RECURRENCE_INTERVAL),
            name="ck_recurringrule_interval_within_cap",
        ),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_recurringrule_date_order"),
        CheckConstraint(
            "day_of_month IS NULL OR (day_of_month >= 1 AND day_of_month <= 31)",
            name="ck_recurringrule_day_of_month_range",
        ),
        # The same shape rule the ledger enforces, so a rule cannot generate a
        # transaction the transaction table would refuse.
        CheckConstraint(
            "(kind = 'TRANSFER' AND counter_account_id IS NOT NULL AND category_id IS NULL)"
            " OR (kind <> 'TRANSFER' AND counter_account_id IS NULL)",
            name="ck_recurringrule_transfer_shape",
        ),
        CheckConstraint(
            "counter_account_id IS NULL OR counter_account_id <> account_id",
            name="ck_recurringrule_distinct_accounts",
        ),
        ForeignKeyConstraint(
            ["account_id", "household_id"],
            ["account.id", "account.household_id"],
            name="fk_recurringrule_account_household",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["counter_account_id", "household_id"],
            ["account.id", "account.household_id"],
            name="fk_recurringrule_counter_account_household",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["category_id", "household_id"],
            ["category.id", "category.household_id"],
            name="fk_recurringrule_category_household",
            ondelete="RESTRICT",
        ),
        # Drives the materialization query: which rules are due?
        Index("ix_recurringrule_due", "household_id", "next_occurrence_on"),
    )

    household_id: uuid.UUID = Field(foreign_key="household.id", ondelete="CASCADE", index=True)
    amount_minor: int = Field(sa_type=BigInteger)
    start_date: datetime.date = Field(sa_type=Date)
    end_date: datetime.date | None = Field(default=None, sa_type=Date)
    account_id: uuid.UUID = Field(nullable=False)
    counter_account_id: uuid.UUID | None = Field(default=None)
    category_id: uuid.UUID | None = Field(default=None)
    # The materialization cursor: the next date not yet created. NULL means the
    # rule is exhausted, which is what moving it forward only ever does.
    next_occurrence_on: datetime.date | None = Field(default=None, sa_type=Date)
    last_generated_on: datetime.date | None = Field(default=None, sa_type=Date)
