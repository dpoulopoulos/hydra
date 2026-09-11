"""The numeric ceilings in the schema, verified by making each one fire.

Every cap in the app is written twice: once on an input model, where it turns
an absurd value into a 422, and once as a ``CHECK``, which is what still holds
for a script, a data migration or a service that writes a row directly. Only
the first half is reachable from the unit suite, which mocks the session, so a
``CHECK`` there is a string in table metadata and nothing more.

These tests write straight at the table, one past the bound and then exactly
on it. The second half matters as much as the first: a ceiling that refuses the
value it should accept is off by one, and a test that only ever writes absurd
values cannot see the difference.
"""

import datetime
import uuid
from collections.abc import Callable

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.models import (
    Account,
    AccountType,
    Budget,
    Category,
    CategoryKind,
    FxRate,
    HouseholdContext,
    IncomeClient,
    IncomeSession,
    Instrument,
    RecurringRule,
    Trade,
    TradeSide,
    Transaction,
    TransactionKind,
)
from app.models.category import MAX_SORT_ORDER
from app.models.fields import MAX_AMOUNT_MINOR, MAX_FX_RATE_MICRO, MAX_PRICE_MICRO, MAX_QUANTITY_MICRO
from app.models.recurring_rule import MAX_RECURRENCE_INTERVAL
from tests.integration.conftest import make_account, make_category

MARCH = datetime.date(2024, 3, 1)

# Builds one row carrying the bounded value, with every other column well
# inside its own bounds, so the only constraint a write can trip is the one
# under test. The whole household context is passed rather than its id alone,
# because a client is owned by a user as well as by a household.
RowBuilder = Callable[[Session, HouseholdContext, int], None]


def add_transaction_amount(session: Session, household: HouseholdContext, value: int) -> None:
    """Write a transaction of the given amount.

    Args:
        session: The database session.
        household: The household that owns the row.
        value: The amount in minor units.
    """
    account = make_account(session, household_id=household.household_id)
    session.add(
        Transaction(
            household_id=household.household_id,
            account_id=account.id,
            kind=TransactionKind.EXPENSE,
            amount_minor=value,
            occurred_on=MARCH,
        )
    )
    session.flush()


def add_budget_limit(session: Session, household: HouseholdContext, value: int) -> None:
    """Write a budget with the given limit.

    Args:
        session: The database session.
        household: The household that owns the row.
        value: The limit in minor units.
    """
    category = make_category(session, household_id=household.household_id)
    session.add(
        Budget(
            household_id=household.household_id,
            category_id=category.id,
            period_month=MARCH,
            limit_minor=value,
        )
    )
    session.flush()


def add_recurring_rule_amount(session: Session, household: HouseholdContext, value: int) -> None:
    """Write a recurring rule for the given amount.

    Args:
        session: The database session.
        household: The household that owns the row.
        value: The amount in minor units.
    """
    account = make_account(session, household_id=household.household_id)
    session.add(
        RecurringRule(
            household_id=household.household_id,
            account_id=account.id,
            name="Rent",
            kind=TransactionKind.EXPENSE,
            amount_minor=value,
            start_date=MARCH,
        )
    )
    session.flush()


def add_recurring_rule_interval(session: Session, household: HouseholdContext, value: int) -> None:
    """Write a recurring rule repeating every ``value`` periods.

    Args:
        session: The database session.
        household: The household that owns the row.
        value: The number of periods between occurrences.
    """
    account = make_account(session, household_id=household.household_id)
    session.add(
        RecurringRule(
            household_id=household.household_id,
            account_id=account.id,
            name="Rent",
            kind=TransactionKind.EXPENSE,
            amount_minor=100_000,
            interval=value,
            start_date=MARCH,
        )
    )
    session.flush()


def add_account_opening_balance(session: Session, household: HouseholdContext, value: int) -> None:
    """Write an account opening at the given balance.

    Args:
        session: The database session.
        household: The household that owns the row.
        value: The opening balance in minor units.
    """
    session.add(
        Account(
            household_id=household.household_id,
            name="Current",
            type=AccountType.CURRENT,
            opening_balance_minor=value,
            opening_balance_date=MARCH,
        )
    )
    session.flush()


def add_category_sort_order(session: Session, household: HouseholdContext, value: int) -> None:
    """Write a category at the given position in the list.

    Args:
        session: The database session.
        household: The household that owns the row.
        value: The ordering hint.
    """
    session.add(
        Category(household_id=household.household_id, name="Groceries", kind=CategoryKind.EXPENSE, sort_order=value)
    )
    session.flush()


def add_fx_rate(session: Session, household: HouseholdContext, value: int) -> None:  # noqa: ARG001
    """Write an exchange rate at the given level.

    Args:
        session: The database session.
        household: Unused: a rate is a fact about two currencies rather than
            about a household, and the table is not scoped to one. It is still
            taken, so every builder has the one signature the table expects.
        value: The rate, times MICRO.
    """
    session.add(
        FxRate(base_code="USD", quote_code="EUR", rate_micro=value, as_of=datetime.datetime(2024, 3, 1, tzinfo=None))
    )
    session.flush()


def make_income_client(
    session: Session,
    household: HouseholdContext,
    default_rate_minor: int = 0,
    cadence_interval: int = 1,
) -> IncomeClient:
    """Seed a client of the household's practice.

    Args:
        session: The database session.
        household: The household whose practice the client belongs to.
        default_rate_minor: What the client usually pays for an hour.
        cadence_interval: How many periods apart the appointments are.

    Returns:
        The stored client.
    """
    account = make_account(session, household_id=household.household_id)
    client = IncomeClient(
        household_id=household.household_id,
        owner_user_id=household.user.id,
        # Never a name in the clear, so the column holds ciphertext even here.
        name_ct="Y2lwaGVydGV4dA==",
        default_account_id=account.id,
        default_rate_minor=default_rate_minor,
        cadence_interval=cadence_interval,
    )
    session.add(client)
    session.flush()
    return client


def add_income_client_rate(session: Session, household: HouseholdContext, value: int) -> None:
    """Write a client whose usual hourly rate is the given amount.

    Args:
        session: The database session.
        household: The household that owns the row.
        value: The rate in minor units.
    """
    make_income_client(session, household, default_rate_minor=value)


def add_income_client_cadence_interval(session: Session, household: HouseholdContext, value: int) -> None:
    """Write a client seen every ``value`` periods.

    Args:
        session: The database session.
        household: The household that owns the row.
        value: The number of periods between appointments.
    """
    make_income_client(session, household, cadence_interval=value)


def add_income_session_fee(session: Session, household: HouseholdContext, value: int) -> None:
    """Write a session charged at the given fee.

    Args:
        session: The database session.
        household: The household that owns the row.
        value: The fee in minor units.
    """
    client = make_income_client(session, household)
    session.add(
        IncomeSession(
            household_id=household.household_id,
            client_id=client.id,
            occurs_on=MARCH,
            fee_minor=value,
        )
    )
    session.flush()


def make_instrument(session: Session, household: HouseholdContext, last_price_micro: int | None = None) -> Instrument:
    """Seed a listing the household holds.

    Args:
        session: The database session.
        household: The household that owns the row.
        last_price_micro: The cached quote, if the row carries one.

    Returns:
        The stored instrument.
    """
    instrument = Instrument(
        household_id=household.household_id,
        symbol="VWCE.DE",
        name="Vanguard FTSE All-World",
        currency_code="EUR",
        last_price_micro=last_price_micro,
    )
    session.add(instrument)
    session.flush()
    return instrument


def add_instrument_price(session: Session, household: HouseholdContext, value: int) -> None:
    """Write a listing whose cached quote is the given price.

    Args:
        session: The database session.
        household: The household that owns the row.
        value: The price, times MICRO.
    """
    make_instrument(session, household, last_price_micro=value)


def add_trade(session: Session, household: HouseholdContext, **fields: int | uuid.UUID) -> None:
    """Write a trade, with every column but the named ones well inside its bounds.

    Args:
        session: The database session.
        household: The household that owns the row.
        **fields: The columns to override, one of which carries the value under
            test.
    """
    instrument = make_instrument(session, household)
    session.add(
        Trade(
            household_id=household.household_id,
            instrument_id=instrument.id,
            side=TradeSide.BUY,
            traded_on=MARCH,
            **{"quantity_micro": 1_000_000, "price_micro": 100_000, "fee_minor": 0, **fields},
        )
    )
    session.flush()


def add_trade_quantity(session: Session, household: HouseholdContext, value: int) -> None:
    """Write a trade of the given number of units.

    Args:
        session: The database session.
        household: The household that owns the row.
        value: The quantity, times MICRO.
    """
    add_trade(session, household, quantity_micro=value)


def add_trade_price(session: Session, household: HouseholdContext, value: int) -> None:
    """Write a trade struck at the given unit price.

    Args:
        session: The database session.
        household: The household that owns the row.
        value: The price, times MICRO.
    """
    add_trade(session, household, price_micro=value)


def add_trade_fee(session: Session, household: HouseholdContext, value: int) -> None:
    """Write a trade carrying the given commission.

    Args:
        session: The database session.
        household: The household that owns the row.
        value: The fee in minor units.
    """
    add_trade(session, household, fee_minor=value)


def add_trade_cash(session: Session, household: HouseholdContext, value: int) -> None:
    """Write a trade moving the given amount through a brokerage account.

    Args:
        session: The database session.
        household: The household that owns the row.
        value: The cash amount in minor units.
    """
    # The cash side is both or neither, so the account comes with the amount.
    account = make_account(session, household_id=household.household_id, name="Broker")
    add_trade(session, household, cash_amount_minor=value, brokerage_account_id=account.id)


# (constraint, the largest value it accepts, how to write a row carrying it).
# Every ceiling #67 added, all fifteen of them, so a cap that gains a constraint
# without a test here is visible as a missing row rather than as nothing at all.
CEILINGS = [
    pytest.param("ck_transaction_amount_within_cap", MAX_AMOUNT_MINOR, add_transaction_amount, id="transaction-amount"),
    pytest.param("ck_budget_limit_within_cap", MAX_AMOUNT_MINOR, add_budget_limit, id="budget-limit"),
    pytest.param(
        "ck_recurringrule_amount_within_cap", MAX_AMOUNT_MINOR, add_recurring_rule_amount, id="recurringrule-amount"
    ),
    pytest.param(
        "ck_recurringrule_interval_within_cap",
        MAX_RECURRENCE_INTERVAL,
        add_recurring_rule_interval,
        id="recurringrule-interval",
    ),
    pytest.param(
        "ck_account_opening_balance_within_cap",
        MAX_AMOUNT_MINOR,
        add_account_opening_balance,
        id="account-opening-balance",
    ),
    pytest.param("ck_category_sort_order_range", MAX_SORT_ORDER, add_category_sort_order, id="category-sort-order"),
    pytest.param("ck_fx_rate_within_cap", MAX_FX_RATE_MICRO, add_fx_rate, id="fx-rate"),
    pytest.param("ck_incomeclient_rate_within_cap", MAX_AMOUNT_MINOR, add_income_client_rate, id="incomeclient-rate"),
    pytest.param(
        "ck_incomeclient_cadence_interval_within_cap",
        MAX_RECURRENCE_INTERVAL,
        add_income_client_cadence_interval,
        id="incomeclient-cadence-interval",
    ),
    pytest.param("ck_incomesession_fee_within_cap", MAX_AMOUNT_MINOR, add_income_session_fee, id="incomesession-fee"),
    pytest.param("ck_instrument_price_within_cap", MAX_PRICE_MICRO, add_instrument_price, id="instrument-price"),
    pytest.param("ck_trade_quantity_within_cap", MAX_QUANTITY_MICRO, add_trade_quantity, id="trade-quantity"),
    pytest.param("ck_trade_price_within_cap", MAX_PRICE_MICRO, add_trade_price, id="trade-price"),
    pytest.param("ck_trade_fee_within_cap", MAX_AMOUNT_MINOR, add_trade_fee, id="trade-fee"),
    pytest.param("ck_trade_cash_within_cap", MAX_AMOUNT_MINOR, add_trade_cash, id="trade-cash"),
]

# The two bounded columns that also carry a floor in the same constraint: an
# opening balance may be negative, since a card starts below zero, and an
# ordering may not. Every other column here is bounded below by a constraint of
# its own, which predates #67 and is not what these tests are about.
FLOORS = [
    pytest.param(
        "ck_account_opening_balance_within_cap",
        -MAX_AMOUNT_MINOR,
        add_account_opening_balance,
        id="account-opening-balance",
    ),
    pytest.param("ck_category_sort_order_range", 0, add_category_sort_order, id="category-sort-order"),
]


class TestCeilings:
    """Each cap refuses the first value past it and accepts the last one below."""

    @pytest.mark.parametrize(("constraint", "cap", "write"), CEILINGS)
    def test_a_value_one_past_the_cap_is_refused(
        self,
        db_session: Session,
        household_a: HouseholdContext,
        constraint: str,
        cap: int,
        write: RowBuilder,
    ) -> None:
        """The database refuses it, with no input model in the way."""
        with pytest.raises(IntegrityError, match=constraint):
            write(db_session, household_a, cap + 1)

    @pytest.mark.parametrize(("constraint", "cap", "write"), CEILINGS)
    def test_a_value_at_the_cap_is_accepted(
        self,
        db_session: Session,
        household_a: HouseholdContext,
        constraint: str,
        cap: int,
        write: RowBuilder,
    ) -> None:
        """The bound is inclusive: the constraint is not off by one."""
        write(db_session, household_a, cap)


class TestFloors:
    """The same, at the other end of the two constraints that bound both ends."""

    @pytest.mark.parametrize(("constraint", "floor", "write"), FLOORS)
    def test_a_value_one_below_the_floor_is_refused(
        self,
        db_session: Session,
        household_a: HouseholdContext,
        constraint: str,
        floor: int,
        write: RowBuilder,
    ) -> None:
        """The floor is part of the same constraint and fires the same way."""
        with pytest.raises(IntegrityError, match=constraint):
            write(db_session, household_a, floor - 1)

    @pytest.mark.parametrize(("constraint", "floor", "write"), FLOORS)
    def test_a_value_at_the_floor_is_accepted(
        self,
        db_session: Session,
        household_a: HouseholdContext,
        constraint: str,
        floor: int,
        write: RowBuilder,
    ) -> None:
        """The floor is inclusive too."""
        write(db_session, household_a, floor)
