import datetime
import uuid

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKeyConstraint, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from .fields import MonthKey
from .mixins import CreatedAtMixin, PrimaryKeyMixin, UpdatedAtMixin


class BudgetCreate(SQLModel):
    category_id: uuid.UUID
    # "YYYY-MM" on the wire. Storage pins the month to a date on its first day,
    # so accepting a full date would let a caller pass a day that is then
    # silently dropped.
    month: MonthKey
    limit_minor: int = Field(ge=0)


class BudgetUpdate(SQLModel):
    limit_minor: int | None = Field(default=None, ge=0)


class BudgetEntry(SQLModel):
    """One category limit within a bulk update."""

    category_id: uuid.UUID
    limit_minor: int = Field(ge=0)


class BudgetBulkUpsert(SQLModel):
    """The complete set of limits for one month."""

    month: MonthKey
    entries: list[BudgetEntry]


class BudgetCopyRequest(SQLModel):
    """Copy a month of limits onto another month."""

    from_month: MonthKey
    to_month: MonthKey
    overwrite: bool = False


class BudgetPublic(SQLModel):
    id: uuid.UUID
    household_id: uuid.UUID
    category_id: uuid.UUID
    month: MonthKey
    limit_minor: int
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None


class BudgetsPublic(SQLModel):
    data: list[BudgetPublic]
    count: int
    total_limit_minor: int = 0


class Budget(PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("household_id", "category_id", "period_month", name="uq_budget_household_category_month"),
        # Guarantees the unique constraint means "one limit per category per
        # month" rather than one per category per arbitrary day.
        CheckConstraint("EXTRACT(DAY FROM period_month) = 1", name="ck_budget_period_month_first"),
        CheckConstraint("limit_minor >= 0", name="ck_budget_limit_non_negative"),
        ForeignKeyConstraint(
            ["category_id", "household_id"],
            ["category.id", "category.household_id"],
            name="fk_budget_category_household",
            ondelete="RESTRICT",
        ),
        Index("ix_budget_household_period", "household_id", "period_month"),
    )

    household_id: uuid.UUID = Field(foreign_key="household.id", ondelete="CASCADE", index=True)
    category_id: uuid.UUID = Field(nullable=False)
    # Always the first of the month. A date rather than separate year and month
    # columns, so a range over several months is a BETWEEN on one indexed
    # column instead of arithmetic on two.
    period_month: datetime.date = Field(sa_type=Date)
    limit_minor: int = Field(sa_type=BigInteger)
