"""Goals add up to their account, checked against a real ledger.

A goal holds the transfers tagged with it, and the rest of its account's
balance is unassigned. The point of the split is that the two always add up to
the balance the Accounts page shows, so every test here writes through the
services and then reconciles the goal figures against the account's balance
rather than against what the goal service reports about itself.
"""

import datetime
import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.exceptions import GoalNotFoundError, GoalTransferMismatchError
from app.models import (
    Account,
    AccountType,
    GoalCreate,
    HouseholdContext,
    Transaction,
    TransactionCreate,
    TransactionKind,
    TransactionUpdate,
)
from app.repositories import AccountRepository
from app.services import GoalService, TransactionService
from tests.integration.conftest import make_account

OPENING_MINOR = 100_000
CAR_IN_MINOR = 800_000
CAR_OUT_MINOR = 50_000
HOLIDAY_IN_MINOR = 300_000


def transfer(
    source: Account,
    destination: Account,
    amount_minor: int,
    goal_id: uuid.UUID | None = None,
    on: datetime.date = datetime.date(2024, 3, 1),
) -> TransactionCreate:
    """Build a transfer for the tests."""
    return TransactionCreate(
        kind=TransactionKind.TRANSFER,
        amount_minor=amount_minor,
        occurred_on=on,
        account_id=source.id,
        counter_account_id=destination.id,
        goal_id=goal_id,
    )


@pytest.fixture
def accounts(db_session: Session, household_a: HouseholdContext) -> tuple[Account, Account]:
    """Seed a current account and a savings account with an untagged opening balance."""
    current = make_account(db_session, household_a.household_id, name="Current")
    savings = make_account(
        db_session,
        household_a.household_id,
        name="Savings",
        opening_balance_minor=OPENING_MINOR,
        account_type=AccountType.SAVINGS,
    )
    return current, savings


def test_goals_and_unassigned_add_up_to_the_balance(
    household_a: HouseholdContext,
    accounts: tuple[Account, Account],
    goal_service: GoalService,
    transaction_service: TransactionService,
    account_repository: AccountRepository,
) -> None:
    current, savings = accounts
    car = goal_service.create_goal(household_a, GoalCreate(name="Car", account_id=savings.id, target_minor=2_000_000))
    holiday = goal_service.create_goal(
        household_a, GoalCreate(name="Holiday", account_id=savings.id, target_minor=400_000)
    )

    transaction_service.create_transaction(household_a, transfer(current, savings, CAR_IN_MINOR, car.id))
    transaction_service.create_transaction(household_a, transfer(savings, current, CAR_OUT_MINOR, car.id))
    transaction_service.create_transaction(household_a, transfer(current, savings, HOLIDAY_IN_MINOR, holiday.id))
    # Untagged, so it lands in unassigned.
    transaction_service.create_transaction(household_a, transfer(current, savings, 7_000))

    listing = goal_service.list_goals(household_a)
    saved = {goal.name: goal.saved_minor for goal in listing.data}
    [summary] = listing.accounts
    balance = account_repository.balance_of(account_id=savings.id, household_id=household_a.household_id)

    assert saved == {"Car": CAR_IN_MINOR - CAR_OUT_MINOR, "Holiday": HOLIDAY_IN_MINOR}
    assert summary.balance_minor == balance
    assert summary.unassigned_minor == OPENING_MINOR + 7_000
    assert summary.assigned_minor + summary.unassigned_minor == balance


def test_deleting_a_goal_returns_its_money_to_unassigned(
    db_session: Session,
    household_a: HouseholdContext,
    accounts: tuple[Account, Account],
    goal_service: GoalService,
    transaction_service: TransactionService,
) -> None:
    current, savings = accounts
    car = goal_service.create_goal(household_a, GoalCreate(name="Car", account_id=savings.id, target_minor=1))
    keep = goal_service.create_goal(household_a, GoalCreate(name="Keep", account_id=savings.id, target_minor=1))
    tagged = transaction_service.create_transaction(household_a, transfer(current, savings, CAR_IN_MINOR, car.id))

    goal_service.delete_goal(household_a, car.id)

    row = db_session.get(Transaction, tagged.id)
    assert row is not None
    db_session.refresh(row)
    assert row.goal_id is None
    assert row.household_id == household_a.household_id
    [summary] = goal_service.list_goals(household_a).accounts
    assert summary.unassigned_minor == OPENING_MINOR + CAR_IN_MINOR
    assert goal_service.get_goal(household_a, keep.id).saved_minor == 0


def test_history_reports_each_month_and_the_running_total(
    household_a: HouseholdContext,
    accounts: tuple[Account, Account],
    goal_service: GoalService,
    transaction_service: TransactionService,
) -> None:
    current, savings = accounts
    car = goal_service.create_goal(household_a, GoalCreate(name="Car", account_id=savings.id, target_minor=1))
    for on, amount in [(datetime.date(2024, 1, 15), 10_000), (datetime.date(2024, 3, 2), 20_000)]:
        transaction_service.create_transaction(household_a, transfer(current, savings, amount, car.id, on=on))
    transaction_service.create_transaction(
        household_a, transfer(savings, current, 5_000, car.id, on=datetime.date(2024, 3, 20))
    )

    history = goal_service.history(household_a, car.id, month_from="2024-02", month_to="2024-03")

    assert [(m.month, m.saved_in_minor, m.saved_out_minor) for m in history.months] == [
        ("2024-02", 0, 0),
        ("2024-03", 20_000, 5_000),
    ]
    assert [m.cumulative_minor for m in history.months] == [10_000, 25_000]


def test_the_peak_survives_spending_the_goal(
    household_a: HouseholdContext,
    accounts: tuple[Account, Account],
    goal_service: GoalService,
    transaction_service: TransactionService,
) -> None:
    current, savings = accounts
    laptop = goal_service.create_goal(household_a, GoalCreate(name="Laptop", account_id=savings.id, target_minor=1))
    for on, amount in [(datetime.date(2024, 1, 5), 70_000), (datetime.date(2024, 2, 5), 50_000)]:
        transaction_service.create_transaction(household_a, transfer(current, savings, amount, laptop.id, on=on))
    # Spent in two goes, the second on the same day as a smaller top up.
    transaction_service.create_transaction(
        household_a, transfer(savings, current, 100_000, laptop.id, on=datetime.date(2024, 3, 1))
    )
    transaction_service.create_transaction(
        household_a, transfer(current, savings, 5_000, laptop.id, on=datetime.date(2024, 3, 2))
    )
    transaction_service.create_transaction(
        household_a, transfer(savings, current, 25_000, laptop.id, on=datetime.date(2024, 3, 2))
    )

    result = goal_service.get_goal(household_a, laptop.id)

    assert result.saved_minor == 0
    assert result.peak_saved_minor == 120_000


def test_a_tag_must_touch_the_goal_account(
    db_session: Session,
    household_a: HouseholdContext,
    accounts: tuple[Account, Account],
    goal_service: GoalService,
    transaction_service: TransactionService,
) -> None:
    current, savings = accounts
    elsewhere = make_account(db_session, household_a.household_id, name="Elsewhere")
    car = goal_service.create_goal(household_a, GoalCreate(name="Car", account_id=savings.id, target_minor=1))

    with pytest.raises(GoalTransferMismatchError):
        transaction_service.create_transaction(household_a, transfer(current, elsewhere, 1_000, car.id))

    tagged = transaction_service.create_transaction(household_a, transfer(current, savings, 1_000, car.id))
    with pytest.raises(GoalTransferMismatchError):
        transaction_service.update_transaction(
            household_a, tagged.id, TransactionUpdate(counter_account_id=elsewhere.id)
        )


def test_another_households_goal_cannot_be_tagged(
    db_session: Session,
    household_a: HouseholdContext,
    household_b: HouseholdContext,
    accounts: tuple[Account, Account],
    goal_service: GoalService,
    transaction_service: TransactionService,
) -> None:
    current, savings = accounts
    their_savings = make_account(db_session, household_b.household_id, name="Savings", account_type=AccountType.SAVINGS)
    theirs = goal_service.create_goal(
        household_b, GoalCreate(name="Theirs", account_id=their_savings.id, target_minor=1)
    )

    with pytest.raises(GoalNotFoundError):
        transaction_service.create_transaction(household_a, transfer(current, savings, 1, theirs.id))


def test_the_database_refuses_a_tag_on_an_expense(
    db_session: Session, household_a: HouseholdContext, accounts: tuple[Account, Account], goal_service: GoalService
) -> None:
    _, savings = accounts
    car = goal_service.create_goal(household_a, GoalCreate(name="Car", account_id=savings.id, target_minor=1))
    db_session.add(
        Transaction(
            household_id=household_a.household_id,
            kind=TransactionKind.EXPENSE,
            amount_minor=1,
            occurred_on=datetime.date(2024, 3, 1),
            account_id=savings.id,
            goal_id=car.id,
        )
    )

    with pytest.raises(IntegrityError, match="ck_transaction_goal_transfer_only"):
        db_session.flush()
