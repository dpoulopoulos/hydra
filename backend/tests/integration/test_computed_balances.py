"""Balances, which are computed from the ledger rather than stored.

The balance query applies the sign, picks the second leg of a transfer up over
counter_account_id and adds the result to the opening balance, all in one
UNION ALL. None of that runs against a mocked session.

The cases here are the ones a stored balance could not survive: an edit that
moves a transaction into the past, and a transfer re-pointed at another
account. A running total would have to be rewritten for both; a computed one
simply comes out right.
"""

import datetime

import pytest
from sqlmodel import Session

from app.models import Account, HouseholdContext, Transaction, TransactionKind, TransactionUpdate
from app.repositories import AccountRepository
from app.services import AccountService, TransactionService
from tests.integration.conftest import make_account

OPENING_MINOR = 100_000
SAVINGS_OPENING_MINOR = 20_000
SALARY_MINOR = 250_000
RENT_MINOR = 90_000
TRANSFER_MINOR = 30_000


class TestLedgerSign:
    """Which way each kind moves an account."""

    @pytest.fixture
    def accounts(self, db_session: Session, household_a: HouseholdContext) -> tuple[Account, Account]:
        """Seed a current account and a savings account.

        Args:
            db_session: The database session.
            household_a: The household to seed.

        Returns:
            The current account and the savings account.
        """
        current = make_account(
            db_session, household_id=household_a.household_id, name="Current", opening_balance_minor=OPENING_MINOR
        )
        savings = make_account(
            db_session,
            household_id=household_a.household_id,
            name="Savings",
            opening_balance_minor=SAVINGS_OPENING_MINOR,
        )
        return current, savings

    def test_an_untouched_account_is_worth_its_opening_balance(
        self, account_service: AccountService, household_a: HouseholdContext, accounts: tuple[Account, Account]
    ) -> None:
        """With no ledger, the balance is the figure the account started from."""
        current, _ = accounts

        assert account_service.get_account(household=household_a, account_id=current.id).current_balance_minor == (
            OPENING_MINOR
        )

    def test_income_adds_and_an_expense_subtracts(
        self,
        db_session: Session,
        account_service: AccountService,
        household_a: HouseholdContext,
        accounts: tuple[Account, Account],
    ) -> None:
        """The sign is applied in SQL, since the stored amount is a magnitude."""
        current, _ = accounts
        db_session.add_all(
            [
                Transaction(
                    household_id=household_a.household_id,
                    account_id=current.id,
                    kind=TransactionKind.INCOME,
                    amount_minor=SALARY_MINOR,
                    occurred_on=datetime.date(2024, 3, 25),
                ),
                Transaction(
                    household_id=household_a.household_id,
                    account_id=current.id,
                    kind=TransactionKind.EXPENSE,
                    amount_minor=RENT_MINOR,
                    occurred_on=datetime.date(2024, 3, 1),
                ),
            ]
        )
        db_session.flush()

        account = account_service.get_account(household=household_a, account_id=current.id)

        assert account.current_balance_minor == OPENING_MINOR + SALARY_MINOR - RENT_MINOR

    def test_a_transfer_moves_money_without_creating_any(
        self,
        db_session: Session,
        account_service: AccountService,
        household_a: HouseholdContext,
        accounts: tuple[Account, Account],
    ) -> None:
        """One row, two legs: the second is picked up over counter_account_id."""
        current, savings = accounts
        db_session.add(
            Transaction(
                household_id=household_a.household_id,
                account_id=current.id,
                counter_account_id=savings.id,
                kind=TransactionKind.TRANSFER,
                amount_minor=TRANSFER_MINOR,
                occurred_on=datetime.date(2024, 3, 15),
            )
        )
        db_session.flush()

        source = account_service.get_account(household=household_a, account_id=current.id)
        destination = account_service.get_account(household=household_a, account_id=savings.id)

        assert source.current_balance_minor == OPENING_MINOR - TRANSFER_MINOR
        assert destination.current_balance_minor == SAVINGS_OPENING_MINOR + TRANSFER_MINOR
        assert source.current_balance_minor + destination.current_balance_minor == (
            OPENING_MINOR + SAVINGS_OPENING_MINOR
        )


class TestEditsAStoredBalanceCouldNotSurvive:
    """The two cases the balance is computed rather than stored for."""

    def test_a_back_dated_edit_leaves_the_balance_correct(
        self,
        db_session: Session,
        account_service: AccountService,
        transaction_service: TransactionService,
        household_a: HouseholdContext,
    ) -> None:
        """The balance sums the whole ledger, so moving a row in time cannot change it."""
        account = make_account(db_session, household_id=household_a.household_id, opening_balance_minor=OPENING_MINOR)
        transaction = Transaction(
            household_id=household_a.household_id,
            account_id=account.id,
            kind=TransactionKind.EXPENSE,
            amount_minor=RENT_MINOR,
            occurred_on=datetime.date(2024, 3, 1),
        )
        db_session.add(transaction)
        db_session.flush()

        transaction_service.update_transaction(
            household=household_a,
            transaction_id=transaction.id,
            transaction_update=TransactionUpdate(occurred_on=datetime.date(2023, 6, 1)),
        )

        assert account_service.get_account(household=household_a, account_id=account.id).current_balance_minor == (
            OPENING_MINOR - RENT_MINOR
        )

    def test_a_corrected_amount_is_reflected_immediately(
        self,
        db_session: Session,
        account_service: AccountService,
        transaction_service: TransactionService,
        household_a: HouseholdContext,
    ) -> None:
        """There is no stored total to correct, so nothing can drift from the ledger."""
        account = make_account(db_session, household_id=household_a.household_id, opening_balance_minor=OPENING_MINOR)
        transaction = Transaction(
            household_id=household_a.household_id,
            account_id=account.id,
            kind=TransactionKind.EXPENSE,
            amount_minor=RENT_MINOR,
            occurred_on=datetime.date(2024, 3, 1),
        )
        db_session.add(transaction)
        db_session.flush()

        transaction_service.update_transaction(
            household=household_a,
            transaction_id=transaction.id,
            transaction_update=TransactionUpdate(amount_minor=1_000),
        )

        assert account_service.get_account(household=household_a, account_id=account.id).current_balance_minor == (
            OPENING_MINOR - 1_000
        )

    def test_a_re_pointed_transfer_moves_the_money_with_it(
        self,
        db_session: Session,
        account_service: AccountService,
        transaction_service: TransactionService,
        household_a: HouseholdContext,
    ) -> None:
        """Both legs follow the edit, so the account it used to reach is whole again."""
        current = make_account(
            db_session, household_id=household_a.household_id, name="Current", opening_balance_minor=OPENING_MINOR
        )
        savings = make_account(
            db_session,
            household_id=household_a.household_id,
            name="Savings",
            opening_balance_minor=SAVINGS_OPENING_MINOR,
        )
        holiday = make_account(db_session, household_id=household_a.household_id, name="Holiday")
        transfer = Transaction(
            household_id=household_a.household_id,
            account_id=current.id,
            counter_account_id=savings.id,
            kind=TransactionKind.TRANSFER,
            amount_minor=TRANSFER_MINOR,
            occurred_on=datetime.date(2024, 3, 15),
        )
        db_session.add(transfer)
        db_session.flush()

        transaction_service.update_transaction(
            household=household_a,
            transaction_id=transfer.id,
            transaction_update=TransactionUpdate(counter_account_id=holiday.id),
        )

        assert (
            account_service.get_account(household=household_a, account_id=savings.id).current_balance_minor
            == SAVINGS_OPENING_MINOR
        )
        assert account_service.get_account(household=household_a, account_id=holiday.id).current_balance_minor == (
            TRANSFER_MINOR
        )
        assert account_service.get_account(household=household_a, account_id=current.id).current_balance_minor == (
            OPENING_MINOR - TRANSFER_MINOR
        )

    def test_a_deleted_transaction_leaves_no_trace_in_the_balance(
        self,
        db_session: Session,
        account_service: AccountService,
        transaction_service: TransactionService,
        household_a: HouseholdContext,
    ) -> None:
        """Removing the row is the whole correction: there is no total to adjust."""
        account = make_account(db_session, household_id=household_a.household_id, opening_balance_minor=OPENING_MINOR)
        transaction = Transaction(
            household_id=household_a.household_id,
            account_id=account.id,
            kind=TransactionKind.EXPENSE,
            amount_minor=RENT_MINOR,
            occurred_on=datetime.date(2024, 3, 1),
        )
        db_session.add(transaction)
        db_session.flush()

        transaction_service.delete_transaction(household=household_a, transaction_id=transaction.id)

        assert (
            account_service.get_account(household=household_a, account_id=account.id).current_balance_minor
            == OPENING_MINOR
        )


class TestBalanceScoping:
    """The balance query is scoped like every other read."""

    def test_a_foreign_account_has_no_balance(
        self,
        db_session: Session,
        account_repository: AccountRepository,
        household_a: HouseholdContext,
        household_b: HouseholdContext,
    ) -> None:
        """Asking for another household's account returns zero, not its money."""
        foreign = make_account(db_session, household_id=household_b.household_id, opening_balance_minor=OPENING_MINOR)

        balance = account_repository.balance_of(account_id=foreign.id, household_id=household_a.household_id)

        assert balance == 0

    def test_balances_are_returned_for_several_accounts_at_once(
        self, db_session: Session, account_repository: AccountRepository, household_a: HouseholdContext
    ) -> None:
        """Listing accounts costs one query, so the batched form has to agree with the single one."""
        current = make_account(
            db_session, household_id=household_a.household_id, name="Current", opening_balance_minor=OPENING_MINOR
        )
        savings = make_account(
            db_session,
            household_id=household_a.household_id,
            name="Savings",
            opening_balance_minor=SAVINGS_OPENING_MINOR,
        )
        db_session.add(
            Transaction(
                household_id=household_a.household_id,
                account_id=current.id,
                counter_account_id=savings.id,
                kind=TransactionKind.TRANSFER,
                amount_minor=TRANSFER_MINOR,
                occurred_on=datetime.date(2024, 3, 15),
            )
        )
        db_session.flush()

        balances = account_repository.balances_of(
            account_ids=[current.id, savings.id], household_id=household_a.household_id
        )

        assert balances == {
            current.id: OPENING_MINOR - TRANSFER_MINOR,
            savings.id: SAVINGS_OPENING_MINOR + TRANSFER_MINOR,
        }
