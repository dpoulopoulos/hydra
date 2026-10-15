"""Accounts in more than one currency, against a real ledger.

What makes several currencies safe lives in SQL: the arriving leg of a transfer
adds what arrived rather than what left, totals are grouped by currency, and a
report only counts the accounts holding the currency it is in. Against a mocked
session each of those is asserted only against what the mock was told to say.

The household keeps its books in euros. "Dollars" is a current account in USD,
and "Dollar savings" a savings account in USD.
"""

import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.exceptions import AccountCurrencyLockedError, TransferShapeError
from app.models import (
    Account,
    AccountType,
    AccountUpdate,
    GoalCreate,
    HouseholdContext,
    Transaction,
    TransactionCreate,
    TransactionKind,
)
from app.services import AccountService, GoalService, ReportService, TransactionService
from tests.integration.conftest import make_account

MONTH = "2024-03"
DAY = datetime.date(2024, 3, 10)

EURO_OPENING_MINOR = 100_000
SENT_MINOR = 10_000
ARRIVED_MINOR = 10_850
EURO_SPENT_MINOR = 2_000
DOLLAR_SPENT_MINOR = 3_000


@pytest.fixture
def euros(db_session: Session, household_a: HouseholdContext) -> Account:
    return make_account(
        db_session, household_id=household_a.household_id, name="Current", opening_balance_minor=EURO_OPENING_MINOR
    )


@pytest.fixture
def dollars(db_session: Session, household_a: HouseholdContext) -> Account:
    return make_account(db_session, household_id=household_a.household_id, name="Dollars", currency_code="USD")


def exchange(
    transaction_service: TransactionService, household: HouseholdContext, source: Account, destination: Account
) -> None:
    """Move a hundred euros into dollars, which arrive as 108.50."""
    transaction_service.create_transaction(
        household,
        TransactionCreate(
            kind=TransactionKind.TRANSFER,
            amount_minor=SENT_MINOR,
            counter_amount_minor=ARRIVED_MINOR,
            occurred_on=DAY,
            account_id=source.id,
            counter_account_id=destination.id,
        ),
    )


def spend(transaction_service: TransactionService, household: HouseholdContext, account: Account, minor: int) -> None:
    transaction_service.create_transaction(
        household,
        TransactionCreate(kind=TransactionKind.EXPENSE, amount_minor=minor, occurred_on=DAY, account_id=account.id),
    )


class TestTransferBetweenCurrencies:
    def test_each_side_moves_by_its_own_figure(
        self,
        account_service: AccountService,
        transaction_service: TransactionService,
        household_a: HouseholdContext,
        euros: Account,
        dollars: Account,
    ) -> None:
        exchange(transaction_service, household_a, euros, dollars)

        assert account_service.get_account(household_a, euros.id).current_balance_minor == (
            EURO_OPENING_MINOR - SENT_MINOR
        )
        assert account_service.get_account(household_a, dollars.id).current_balance_minor == ARRIVED_MINOR

    def test_one_without_what_arrived_is_refused(
        self, transaction_service: TransactionService, household_a: HouseholdContext, euros: Account, dollars: Account
    ) -> None:
        with pytest.raises(TransferShapeError, match="Say how much arrived in USD"):
            transaction_service.create_transaction(
                household_a,
                TransactionCreate(
                    kind=TransactionKind.TRANSFER,
                    amount_minor=SENT_MINOR,
                    occurred_on=DAY,
                    account_id=euros.id,
                    counter_account_id=dollars.id,
                ),
            )

    def test_the_database_refuses_an_amount_received_on_an_expense(
        self, db_session: Session, household_a: HouseholdContext, euros: Account
    ) -> None:
        """Only a transfer has a second side for money to arrive on."""
        db_session.add(
            Transaction(
                household_id=household_a.household_id,
                account_id=euros.id,
                kind=TransactionKind.EXPENSE,
                amount_minor=SENT_MINOR,
                counter_amount_minor=ARRIVED_MINOR,
                occurred_on=DAY,
            )
        )

        with pytest.raises(IntegrityError, match="ck_transaction_counter_amount_transfer_only"):
            db_session.flush()

    def test_a_goal_in_dollars_fills_by_what_arrived(
        self,
        db_session: Session,
        goal_service: GoalService,
        transaction_service: TransactionService,
        household_a: HouseholdContext,
        euros: Account,
    ) -> None:
        savings = make_account(
            db_session,
            household_id=household_a.household_id,
            name="Dollar savings",
            account_type=AccountType.SAVINGS,
            currency_code="USD",
        )
        trip = goal_service.create_goal(household_a, GoalCreate(name="Trip", account_id=savings.id, target_minor=1))
        transaction_service.create_transaction(
            household_a,
            TransactionCreate(
                kind=TransactionKind.TRANSFER,
                amount_minor=SENT_MINOR,
                counter_amount_minor=ARRIVED_MINOR,
                occurred_on=DAY,
                account_id=euros.id,
                counter_account_id=savings.id,
                goal_id=trip.id,
            ),
        )

        goal = goal_service.get_goal(household_a, trip.id)

        assert (goal.saved_minor, goal.currency_code) == (ARRIVED_MINOR, "USD")


class TestTotals:
    def test_the_account_list_totals_each_currency_apart(
        self,
        account_service: AccountService,
        transaction_service: TransactionService,
        household_a: HouseholdContext,
        euros: Account,
        dollars: Account,
    ) -> None:
        exchange(transaction_service, household_a, euros, dollars)

        totals = account_service.list_accounts(household_a).totals

        assert [(total.currency_code, total.amount_minor) for total in totals] == [
            ("EUR", EURO_OPENING_MINOR - SENT_MINOR),
            ("USD", ARRIVED_MINOR),
        ]

    def test_net_worth_is_the_household_currency_and_the_rest_is_said_apart(
        self,
        report_service: ReportService,
        transaction_service: TransactionService,
        household_a: HouseholdContext,
        euros: Account,
        dollars: Account,
    ) -> None:
        exchange(transaction_service, household_a, euros, dollars)

        summary = report_service.month_summary(household_a, MONTH)

        assert summary.net_worth_minor == EURO_OPENING_MINOR - SENT_MINOR
        assert [(total.currency_code, total.amount_minor) for total in summary.other_currencies] == [
            ("USD", ARRIVED_MINOR)
        ]


class TestReports:
    @pytest.fixture(autouse=True)
    def spending(
        self, transaction_service: TransactionService, household_a: HouseholdContext, euros: Account, dollars: Account
    ) -> None:
        spend(transaction_service, household_a, euros, EURO_SPENT_MINOR)
        spend(transaction_service, household_a, dollars, DOLLAR_SPENT_MINOR)

    def test_the_breakdown_counts_only_the_household_currency(
        self, report_service: ReportService, household_a: HouseholdContext
    ) -> None:
        report = report_service.spend_by_category(household_a, MONTH)

        assert (report.period.currency_code, report.total_minor) == ("EUR", EURO_SPENT_MINOR)

    def test_the_month_counts_only_the_household_currency(
        self, report_service: ReportService, household_a: HouseholdContext
    ) -> None:
        assert report_service.month_summary(household_a, MONTH).expense_minor == EURO_SPENT_MINOR

    def test_one_account_is_charted_in_its_own_currency(
        self, report_service: ReportService, household_a: HouseholdContext, dollars: Account
    ) -> None:
        report = report_service.spend_over_time(
            household_a, date_from=datetime.date(2024, 3, 1), date_to=datetime.date(2024, 3, 31), account_id=dollars.id
        )

        assert (report.period.currency_code, report.total_minor) == ("USD", DOLLAR_SPENT_MINOR)


class TestChangingCurrency:
    def test_an_empty_account_changes_currency(
        self, account_service: AccountService, household_a: HouseholdContext, dollars: Account
    ) -> None:
        account = account_service.update_account(household_a, dollars.id, AccountUpdate(currency_code="GBP"))

        assert account.currency_code == "GBP"

    def test_an_account_with_transactions_keeps_its_currency(
        self,
        account_service: AccountService,
        transaction_service: TransactionService,
        household_a: HouseholdContext,
        dollars: Account,
    ) -> None:
        spend(transaction_service, household_a, dollars, DOLLAR_SPENT_MINOR)

        with pytest.raises(AccountCurrencyLockedError, match="still has transactions"):
            account_service.update_account(household_a, dollars.id, AccountUpdate(currency_code="GBP"))

    def test_the_destination_of_a_transfer_keeps_its_currency(
        self,
        account_service: AccountService,
        transaction_service: TransactionService,
        household_a: HouseholdContext,
        euros: Account,
        dollars: Account,
    ) -> None:
        """A transaction holds an account from either side."""
        exchange(transaction_service, household_a, euros, dollars)

        with pytest.raises(AccountCurrencyLockedError):
            account_service.update_account(household_a, dollars.id, AccountUpdate(currency_code="GBP"))
