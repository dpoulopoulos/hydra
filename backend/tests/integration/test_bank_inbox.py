"""Adding to the inbox and accepting from it into the ledger, against a real database."""

import datetime
import uuid

import pytest
from sqlmodel import Session

from app.exceptions import (
    AccountArchivedError,
    AccountNotFoundError,
    BankTransactionNotFoundError,
    BankTransactionReviewedError,
    TransactionCategoryKindError,
)
from app.models import (
    Account,
    BankAccount,
    BankConnection,
    BankConnectionStatus,
    BankDirection,
    BankInboxAdd,
    BankInboxEntry,
    BankInboxFilters,
    BankReviewStatus,
    BankSyncRun,
    BankSyncTrigger,
    BankTransaction,
    BankTransactionAccept,
    CategoryKind,
    HouseholdContext,
    Transaction,
    TransactionKind,
)
from app.repositories import AccountRepository, BankAccountRepository, BankTransactionRepository
from app.services import BankInboxService, TransactionService
from tests.integration.conftest import make_account, make_category


@pytest.fixture
def inbox_service(db_session: Session, transaction_service: TransactionService) -> BankInboxService:
    return BankInboxService(
        session=db_session,
        bank_transaction_repository=BankTransactionRepository(db_session),
        bank_account_repository=BankAccountRepository(db_session),
        transaction_service=transaction_service,
    )


def seed_row(
    db_session: Session, household: HouseholdContext, account: Account, direction: BankDirection = BankDirection.DEBIT
) -> BankTransaction:
    connection = BankConnection(
        household_id=household.household_id,
        aspsp_name="Mock ASPSP",
        aspsp_country="GR",
        status=BankConnectionStatus.ACTIVE,
    )
    db_session.add(connection)
    db_session.flush()
    bank_account = BankAccount(
        household_id=household.household_id,
        connection_id=connection.id,
        provider_account_uid="uid",
        identity_key=str(uuid.uuid4()),
        name="Main",
        account_id=account.id,
    )
    run = BankSyncRun(
        household_id=household.household_id,
        connection_id=connection.id,
        trigger=BankSyncTrigger.MANUAL,
        started_at=datetime.datetime.now(datetime.UTC),
    )
    db_session.add(bank_account)
    db_session.add(run)
    db_session.flush()
    row = BankTransaction(
        household_id=household.household_id,
        bank_account_id=bank_account.id,
        sync_run_id=run.id,
        dedupe_key="ref:1",
        direction=direction,
        amount_minor=1250,
        currency_code="EUR",
        occurred_on=datetime.date(2026, 10, 1),
        counterparty_name="Coffee Island",
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_accepting_records_the_ledger_row_and_links_it(
    db_session: Session, household_a: HouseholdContext, inbox_service: BankInboxService
) -> None:
    """Test that the ledger row and the inbox status are written together, and the balance moves."""
    account = make_account(db_session, household_a.household_id)
    category = make_category(db_session, household_a.household_id)
    row = seed_row(db_session, household_a, account)

    result = inbox_service.accept(
        household_a, row.id, BankTransactionAccept(kind=TransactionKind.EXPENSE, category_id=category.id)
    )

    assert result.review_status == BankReviewStatus.ACCEPTED
    ledger = db_session.get(Transaction, result.ledger_transaction_id)
    assert ledger is not None
    assert ledger.external_id == f"eb:{row.id}"
    assert ledger.import_batch_id == row.sync_run_id
    assert ledger.merchant == "Coffee Island"
    assert AccountRepository(db_session).balance_of(account.id, household_a.household_id) == -1250


def test_accepting_twice_is_refused(
    db_session: Session, household_a: HouseholdContext, inbox_service: BankInboxService
) -> None:
    """Test that a row already accepted cannot put a second row in the ledger."""
    account = make_account(db_session, household_a.household_id)
    row = seed_row(db_session, household_a, account)
    inbox_service.accept(household_a, row.id, BankTransactionAccept(kind=TransactionKind.EXPENSE))

    with pytest.raises(BankTransactionReviewedError):
        inbox_service.accept(household_a, row.id, BankTransactionAccept(kind=TransactionKind.EXPENSE))


def test_a_money_in_transfer_lands_on_the_bank_account(
    db_session: Session, household_a: HouseholdContext, inbox_service: BankInboxService
) -> None:
    """Test that money arriving as a transfer leaves the other account and reaches the linked one."""
    account = make_account(db_session, household_a.household_id, name="Main")
    savings = make_account(db_session, household_a.household_id, name="Savings")
    row = seed_row(db_session, household_a, account, BankDirection.CREDIT)

    inbox_service.accept(
        household_a, row.id, BankTransactionAccept(kind=TransactionKind.TRANSFER, counter_account_id=savings.id)
    )

    balances = AccountRepository(db_session).balances_of([account.id, savings.id], household_a.household_id)
    assert balances[account.id] == 1250
    assert balances[savings.id] == -1250


def test_the_ledgers_own_rules_still_apply(
    db_session: Session, household_a: HouseholdContext, inbox_service: BankInboxService
) -> None:
    """Test that accepting goes through the same checks as recording by hand, and leaves the row waiting."""
    account = make_account(db_session, household_a.household_id)
    income = make_category(db_session, household_a.household_id, name="Salary", kind=CategoryKind.INCOME)
    row = seed_row(db_session, household_a, account)

    with pytest.raises(TransactionCategoryKindError):
        inbox_service.accept(
            household_a, row.id, BankTransactionAccept(kind=TransactionKind.EXPENSE, category_id=income.id)
        )

    db_session.refresh(row)
    assert row.review_status == BankReviewStatus.PENDING


def test_an_archived_account_cannot_take_the_row(
    db_session: Session, household_a: HouseholdContext, inbox_service: BankInboxService
) -> None:
    """Test that the archived check of the ledger refuses the accept."""
    account = make_account(db_session, household_a.household_id)
    row = seed_row(db_session, household_a, account)
    account.archived_at = datetime.datetime.now(datetime.UTC)
    db_session.add(account)
    db_session.flush()

    with pytest.raises(AccountArchivedError):
        inbox_service.accept(household_a, row.id, BankTransactionAccept(kind=TransactionKind.EXPENSE))


def test_deleting_the_ledger_row_sends_the_bank_row_back(
    db_session: Session,
    household_a: HouseholdContext,
    inbox_service: BankInboxService,
    transaction_service: TransactionService,
) -> None:
    """Test that deleting an accepted transaction puts its bank row back in the inbox, ready to accept again."""
    account = make_account(db_session, household_a.household_id)
    row = seed_row(db_session, household_a, account)
    accepted = inbox_service.accept(household_a, row.id, BankTransactionAccept(kind=TransactionKind.EXPENSE))
    assert accepted.ledger_transaction_id is not None

    transaction_service.delete_transaction(household_a, accepted.ledger_transaction_id)

    pending = inbox_service.list_inbox(household_a, BankInboxFilters())
    assert [r.id for r in pending.data] == [row.id]
    assert pending.data[0].ledger_transaction_id is None
    again = inbox_service.accept(household_a, row.id, BankTransactionAccept(kind=TransactionKind.EXPENSE))
    assert again.review_status == BankReviewStatus.ACCEPTED


def test_skip_and_reopen_move_the_row_between_lists(
    db_session: Session, household_a: HouseholdContext, inbox_service: BankInboxService
) -> None:
    """Test that the inbox lists rows by their review status."""
    account = make_account(db_session, household_a.household_id)
    row = seed_row(db_session, household_a, account)

    inbox_service.skip(household_a, row.id)
    assert inbox_service.list_inbox(household_a, BankInboxFilters()).count == 0
    assert inbox_service.list_inbox(household_a, BankInboxFilters(status=BankReviewStatus.SKIPPED)).count == 1

    inbox_service.reopen(household_a, row.id)
    assert inbox_service.list_inbox(household_a, BankInboxFilters()).count == 1


def test_another_household_cannot_see_or_accept_the_row(
    db_session: Session,
    household_a: HouseholdContext,
    household_b: HouseholdContext,
    inbox_service: BankInboxService,
) -> None:
    """Test that the inbox is scoped to the household."""
    account = make_account(db_session, household_a.household_id)
    row = seed_row(db_session, household_a, account)

    assert inbox_service.list_inbox(household_b, BankInboxFilters()).count == 0
    with pytest.raises(BankTransactionNotFoundError):
        inbox_service.accept(household_b, row.id, BankTransactionAccept(kind=TransactionKind.EXPENSE))


def coffee(reference: str | None = None, direction: BankDirection = BankDirection.DEBIT) -> BankInboxEntry:
    return BankInboxEntry(
        direction=direction,
        amount_minor=350,
        occurred_on=datetime.date(2026, 10, 2),
        counterparty_name="Coffee Island",
        reference=reference,
    )


def test_adding_puts_rows_in_the_inbox_on_the_account(
    db_session: Session, household_a: HouseholdContext, inbox_service: BankInboxService
) -> None:
    """Test that added rows wait in the inbox, on the account they were added to, in its currency."""
    account = make_account(db_session, household_a.household_id)

    added = inbox_service.add(household_a, BankInboxAdd(account_id=account.id, entries=[coffee(), coffee()]))

    assert (added.received, added.added) == (2, 2)
    pending = inbox_service.list_inbox(household_a, BankInboxFilters())
    assert pending.count == 2
    assert {(r.account_id, r.bank_account_id, r.bank_account_name) for r in pending.data} == {(account.id, None, None)}
    assert {r.currency_code for r in pending.data} == {account.currency_code}


def test_adding_the_same_entries_again_adds_nothing(
    db_session: Session, household_a: HouseholdContext, inbox_service: BankInboxService
) -> None:
    """Test that rows are recognised by reference, or by what they say and their place among identical ones."""
    account = make_account(db_session, household_a.household_id)
    entries = [coffee(), coffee(), coffee(reference="TR-1")]
    inbox_service.add(household_a, BankInboxAdd(account_id=account.id, entries=entries))

    again = inbox_service.add(household_a, BankInboxAdd(account_id=account.id, entries=[*entries, coffee()]))

    # The third identical coffee is new; the rest were there.
    assert (again.received, again.added) == (4, 1)
    assert inbox_service.list_inbox(household_a, BankInboxFilters()).count == 4


def test_an_added_row_is_accepted_onto_its_account(
    db_session: Session,
    household_a: HouseholdContext,
    inbox_service: BankInboxService,
    transaction_service: TransactionService,
) -> None:
    """Test that accepting an added row records it on its account, and deleting it sends it back."""
    account = make_account(db_session, household_a.household_id)
    inbox_service.add(household_a, BankInboxAdd(account_id=account.id, entries=[coffee()]))
    row = inbox_service.list_inbox(household_a, BankInboxFilters()).data[0]

    accepted = inbox_service.accept(household_a, row.id, BankTransactionAccept(kind=TransactionKind.EXPENSE))

    ledger = db_session.get(Transaction, accepted.ledger_transaction_id)
    assert ledger is not None
    assert ledger.account_id == account.id
    assert ledger.external_id == f"inbox:{row.id}"
    assert ledger.import_batch_id is None
    assert ledger.merchant == "Coffee Island"
    assert AccountRepository(db_session).balance_of(account.id, household_a.household_id) == -350

    assert accepted.ledger_transaction_id is not None
    transaction_service.delete_transaction(household_a, accepted.ledger_transaction_id)
    assert [r.id for r in inbox_service.list_inbox(household_a, BankInboxFilters()).data] == [row.id]


def test_a_money_in_transfer_from_an_added_row_lands_on_its_account(
    db_session: Session, household_a: HouseholdContext, inbox_service: BankInboxService
) -> None:
    """Test that money in on an added row is a transfer from the other account into this one."""
    account = make_account(db_session, household_a.household_id)
    other = make_account(db_session, household_a.household_id, name="Savings")
    inbox_service.add(
        household_a, BankInboxAdd(account_id=account.id, entries=[coffee(direction=BankDirection.CREDIT)])
    )
    row = inbox_service.list_inbox(household_a, BankInboxFilters()).data[0]

    accepted = inbox_service.accept(
        household_a, row.id, BankTransactionAccept(kind=TransactionKind.TRANSFER, counter_account_id=other.id)
    )

    ledger = db_session.get(Transaction, accepted.ledger_transaction_id)
    assert ledger is not None
    assert (ledger.account_id, ledger.counter_account_id) == (other.id, account.id)


def test_adding_needs_an_open_account_of_the_household(
    db_session: Session,
    household_a: HouseholdContext,
    household_b: HouseholdContext,
    inbox_service: BankInboxService,
) -> None:
    """Test that rows cannot be added to another household's account, or to an archived one."""
    account = make_account(db_session, household_a.household_id)

    with pytest.raises(AccountNotFoundError):
        inbox_service.add(household_b, BankInboxAdd(account_id=account.id, entries=[coffee()]))

    account.archived_at = datetime.datetime.now(datetime.UTC)
    db_session.add(account)
    db_session.flush()
    with pytest.raises(AccountArchivedError):
        inbox_service.add(household_a, BankInboxAdd(account_id=account.id, entries=[coffee()]))
