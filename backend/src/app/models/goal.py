import datetime
import uuid

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKeyConstraint, UniqueConstraint
from sqlmodel import Field, SQLModel

from .fields import MAX_AMOUNT_MINOR, MonthKey, within_cap_sql
from .mixins import CreatedAtMixin, PrimaryKeyMixin, UpdatedAtMixin, UtcDateTime

GOAL_NAME_MAX_LENGTH = 100


class GoalCreate(SQLModel):
    name: str = Field(min_length=1, max_length=GOAL_NAME_MAX_LENGTH)
    # The savings account the money for this goal sits in. Several goals can
    # share one account: each holds the transfers tagged with it, and whatever
    # nothing is tagged with is the account's unassigned money.
    account_id: uuid.UUID
    target_minor: int = Field(gt=0, le=MAX_AMOUNT_MINOR)
    target_date: datetime.date | None = None


class GoalUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=GOAL_NAME_MAX_LENGTH)
    account_id: uuid.UUID | None = Field(default=None)
    target_minor: int | None = Field(default=None, gt=0, le=MAX_AMOUNT_MINOR)
    target_date: datetime.date | None = Field(default=None)
    is_achieved: bool | None = Field(default=None)


class GoalPublic(SQLModel):
    id: uuid.UUID
    household_id: uuid.UUID
    account_id: uuid.UUID
    account_name: str
    currency_code: str
    name: str
    target_minor: int
    target_date: datetime.date | None = None
    achieved_at: datetime.datetime | None = None
    # Tagged transfers into the account, less tagged transfers out of it.
    saved_minor: int
    # The most the goal ever held. Equal to saved_minor until money is tagged
    # back out, which is what happens once a reached goal is spent: the goal
    # then holds nothing, but it did reach this much.
    peak_saved_minor: int
    remaining_minor: int
    # Saved over target, so 1.0 is reached. Not capped, so an overshoot shows.
    progress: float
    # Months left to save in, the current one included. None without a date,
    # and zero once the date has passed.
    months_left: int | None = None
    # What each remaining month has to add to reach the target in time. None
    # without a date.
    needed_per_month_minor: int | None = None
    # The average of the last few months set against what is needed. None
    # without a date, or once the target is reached.
    average_monthly_minor: int
    on_track: bool | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None


class GoalAccountSummary(SQLModel):
    """How one savings account's balance splits across its goals."""

    account_id: uuid.UUID
    account_name: str
    currency_code: str
    balance_minor: int
    assigned_minor: int
    # The balance no goal claims: the opening balance, interest, and any
    # transfer left untagged. It can go negative when more is tagged out of a
    # goal than was ever tagged in, which is worth showing rather than hiding.
    unassigned_minor: int


class GoalsPublic(SQLModel):
    data: list[GoalPublic]
    count: int
    accounts: list[GoalAccountSummary]


class GoalMonth(SQLModel):
    month: MonthKey
    saved_in_minor: int
    saved_out_minor: int
    net_minor: int
    # Everything saved up to the end of this month, from the very first
    # tagged transfer, not only from the start of the range.
    cumulative_minor: int


class GoalHistory(SQLModel):
    goal_id: uuid.UUID
    month_from: MonthKey
    month_to: MonthKey
    months: list[GoalMonth]


class Goal(PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("household_id", "name", name="uq_goal_household_name"),
        # Composite foreign key target, so a transaction cannot be tagged with
        # a goal belonging to a different household.
        UniqueConstraint("id", "household_id", name="uq_goal_id_household"),
        CheckConstraint("target_minor > 0", name="ck_goal_target_positive"),
        CheckConstraint(within_cap_sql("target_minor", MAX_AMOUNT_MINOR), name="ck_goal_target_within_cap"),
        # Composite, so a goal cannot point at another household's account even
        # if a service forgets to scope a query.
        ForeignKeyConstraint(
            ["account_id", "household_id"],
            ["account.id", "account.household_id"],
            name="fk_goal_account_household",
            ondelete="RESTRICT",
        ),
    )

    household_id: uuid.UUID = Field(foreign_key="household.id", ondelete="CASCADE", index=True)
    account_id: uuid.UUID = Field(nullable=False, index=True)
    name: str = Field(max_length=GOAL_NAME_MAX_LENGTH)
    target_minor: int = Field(sa_type=BigInteger)
    target_date: datetime.date | None = Field(default=None, sa_type=Date)
    achieved_at: datetime.datetime | None = Field(default=None, sa_type=UtcDateTime)
