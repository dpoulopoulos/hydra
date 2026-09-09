import datetime
import uuid
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, Date, UniqueConstraint
from sqlmodel import Field, SQLModel

from .fields import IBAN_MAX_LENGTH, MAX_AMOUNT_MINOR, Iban, within_cap_sql
from .mixins import CreatedAtMixin, PrimaryKeyMixin, UpdatedAtMixin


class AccountType(StrEnum):
    CASH = "cash"
    # The everyday bank account. Called a current account in Europe, a
    # checking account in the United States.
    CURRENT = "current"
    SAVINGS = "savings"
    CREDIT_CARD = "credit_card"
    # An account held with a broker. Its balance is the cash sitting there:
    # what has been transferred in and not yet spent, plus what sales have
    # returned and not yet been withdrawn. Buying takes cash out of it and
    # turns it into a holding, so this and the holdings never describe the same
    # money, and net worth adds both.
    BROKERAGE = "brokerage"


class AccountBase(SQLModel):
    name: str = Field(max_length=255)
    type: AccountType
    institution: str | None = Field(default=None, max_length=255)
    # Stored compact and upper case, whatever spacing the user typed. It is
    # here so the account can be handed to someone who has to pay into it; the
    # app never uses it to move money itself.
    iban: Iban | None = Field(default=None, max_length=IBAN_MAX_LENGTH)


class AccountCreate(AccountBase):
    # The balance the account already held when the user started tracking it.
    # Fixed at creation: changing it would silently rewrite every historical
    # balance, so a correction belongs in an adjustment transaction instead.
    opening_balance_minor: int = Field(default=0, ge=-MAX_AMOUNT_MINOR, le=MAX_AMOUNT_MINOR)
    opening_balance_date: datetime.date


class AccountUpdate(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    type: AccountType | None = Field(default=None)
    institution: str | None = Field(default=None, max_length=255)
    iban: Iban | None = Field(default=None, max_length=IBAN_MAX_LENGTH)
    is_archived: bool | None = Field(default=None)


class AccountPublic(AccountBase):
    id: uuid.UUID
    household_id: uuid.UUID
    currency_code: str
    opening_balance_minor: int
    opening_balance_date: datetime.date
    # Derived from the ledger on every read, never stored. See AccountRepository.
    current_balance_minor: int = 0
    archived_at: datetime.datetime | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None


class AccountsPublic(SQLModel):
    data: list[AccountPublic]
    count: int
    # Across the accounts returned, so the net worth tile is the same request.
    total_balance_minor: int = 0


class Account(AccountBase, PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, table=True):
    __table_args__ = (
        UniqueConstraint("household_id", "name", name="uq_account_household_name"),
        # Composite foreign key target, so a transaction cannot reference an
        # account belonging to a different household.
        UniqueConstraint("id", "household_id", name="uq_account_id_household"),
        CheckConstraint("length(currency_code) = 3", name="ck_account_currency_code_len"),
        # An opening balance is the only money column that may be negative: an
        # overdraft or a card balance starts below zero. So it is bounded on
        # both sides rather than capped alone.
        CheckConstraint(
            within_cap_sql("opening_balance_minor", MAX_AMOUNT_MINOR, floor=-MAX_AMOUNT_MINOR),
            name="ck_account_opening_balance_within_cap",
        ),
    )

    household_id: uuid.UUID = Field(foreign_key="household.id", ondelete="CASCADE", index=True)
    # Denormalized from the household on purpose. It is the lever multi-currency
    # would need later; until then the service keeps it equal to the household's.
    currency_code: str = Field(default="EUR", min_length=3, max_length=3)
    opening_balance_minor: int = Field(default=0, sa_type=BigInteger)
    opening_balance_date: datetime.date = Field(sa_type=Date)
    archived_at: datetime.datetime | None = Field(default=None)
