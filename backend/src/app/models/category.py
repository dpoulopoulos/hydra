import datetime
import uuid
from enum import StrEnum

from sqlalchemy import CheckConstraint, Index, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from .fields import within_cap_sql
from .mixins import CreatedAtMixin, PrimaryKeyMixin, UpdatedAtMixin

# The ordering column is a plain integer, which Postgres tops out at 2**31 - 1,
# and it is only a display hint on a list a household edits by hand. A small
# ceiling keeps an absurd value a validation error rather than a driver one.
MAX_SORT_ORDER = 10_000


class CategoryKind(StrEnum):
    EXPENSE = "expense"
    INCOME = "income"


class CategoryBase(SQLModel):
    name: str = Field(max_length=255)
    kind: CategoryKind = CategoryKind.EXPENSE
    # Display hints. Cheap to carry now, awkward to add once the frontend has
    # shipped screens that assume categories have no colour.
    icon: str | None = Field(default=None, max_length=64)
    color: str | None = Field(default=None, max_length=16)
    # Bounded on the input models rather than here. This base is also the base
    # of the table and of the response models, and a row stored before the
    # bound existed still has to be readable: validating a response against a
    # rule the stored row never had to meet turns a read into a 500.
    sort_order: int = Field(default=0)


class CategoryCreate(CategoryBase):
    sort_order: int = Field(default=0, ge=0, le=MAX_SORT_ORDER)
    parent_id: uuid.UUID | None = None


class CategoryUpdate(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    parent_id: uuid.UUID | None = Field(default=None)
    icon: str | None = Field(default=None, max_length=64)
    color: str | None = Field(default=None, max_length=16)
    sort_order: int | None = Field(default=None, ge=0, le=MAX_SORT_ORDER)
    is_archived: bool | None = Field(default=None)


class CategoryPublic(CategoryBase):
    id: uuid.UUID
    household_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    is_system: bool = False
    archived_at: datetime.datetime | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None


class CategoryTreeNode(CategoryPublic):
    children: list[CategoryPublic] = []


class CategoriesPublic(SQLModel):
    data: list[CategoryPublic]
    count: int


class CategoryTreePublic(SQLModel):
    data: list[CategoryTreeNode]
    count: int


class Category(CategoryBase, PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, table=True):
    __table_args__ = (
        CheckConstraint(within_cap_sql("sort_order", MAX_SORT_ORDER, floor=0), name="ck_category_sort_order_range"),
        # Composite foreign key target. Transactions, budgets and recurring
        # rules reference (category_id, household_id), which makes a
        # cross-household reference impossible even from a buggy service.
        UniqueConstraint("id", "household_id", name="uq_category_id_household"),
        # Two partial indexes rather than one UNIQUE(household_id, parent_id,
        # name): NULL is not equal to NULL in Postgres, so a single constraint
        # would not constrain the top level at all.
        Index(
            "uq_category_household_root_name",
            "household_id",
            "name",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
        ),
        Index(
            "uq_category_household_child_name",
            "household_id",
            "parent_id",
            "name",
            unique=True,
            postgresql_where=text("parent_id IS NOT NULL"),
        ),
        Index("ix_category_household_parent", "household_id", "parent_id"),
    )

    household_id: uuid.UUID = Field(foreign_key="household.id", ondelete="CASCADE", index=True)
    # Self reference. Depth is capped at two levels by the service: a category
    # that already has a parent cannot become one.
    parent_id: uuid.UUID | None = Field(default=None, foreign_key="category.id", ondelete="RESTRICT")
    # System categories are the guaranteed landing zone for a transaction with
    # no category, so they cannot be renamed away, archived or deleted.
    is_system: bool = Field(default=False)
    archived_at: datetime.datetime | None = Field(default=None)
