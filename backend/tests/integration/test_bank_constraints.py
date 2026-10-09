"""The constraints the bank sync tables carry, verified by making them fire."""

import datetime
import uuid
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import (
    BankAccount,
    BankConnection,
    BankConnectionStatus,
    BankDirection,
    BankSyncRun,
    BankSyncTrigger,
    BankTransaction,
    Household,
    HouseholdContext,
    Transaction,
    TransactionKind,
)
from tests.integration.conftest import make_account


def make_connection(session: Session, household_id: uuid.UUID) -> BankConnection:
    connection = BankConnection(
        household_id=household_id, aspsp_name="Mock ASPSP", aspsp_country="GR", status=BankConnectionStatus.ACTIVE
    )
    session.add(connection)
    session.flush()
    return connection


def make_bank_account(
    session: Session, household_id: uuid.UUID, connection_id: uuid.UUID, identity_key: str, **fields: Any
) -> BankAccount:
    bank_account = BankAccount(
        household_id=household_id,
        connection_id=connection_id,
        provider_account_uid=str(uuid.uuid4()),
        identity_key=identity_key,
        **fields,
    )
    session.add(bank_account)
    session.flush()
    return bank_account


def make_bank_transaction(
    session: Session, household_id: uuid.UUID, bank_account_id: uuid.UUID, dedupe_key: str, **fields: Any
) -> BankTransaction:
    row = BankTransaction(
        household_id=household_id,
        bank_account_id=bank_account_id,
        dedupe_key=dedupe_key,
        direction=fields.pop("direction", BankDirection.DEBIT),
        amount_minor=fields.pop("amount_minor", 1250),
        currency_code="EUR",
        occurred_on=datetime.date(2026, 10, 1),
        **fields,
    )
    session.add(row)
    session.flush()
    return row


def test_a_refetched_row_cannot_be_stored_twice(db_session: Session, household_a: HouseholdContext) -> None:
    """Test that the same dedupe key on the same bank account is refused."""
    connection = make_connection(db_session, household_a.household_id)
    bank_account = make_bank_account(db_session, household_a.household_id, connection.id, "hash-1")
    make_bank_transaction(db_session, household_a.household_id, bank_account.id, "ref-1")

    with pytest.raises(IntegrityError, match="uq_banktransaction_account_dedupe"):
        make_bank_transaction(db_session, household_a.household_id, bank_account.id, "ref-1")


def test_one_hydra_account_is_fed_by_one_bank_account(db_session: Session, household_a: HouseholdContext) -> None:
    """Test that mapping two bank accounts onto one Hydra account is refused."""
    account = make_account(db_session, household_a.household_id)
    connection = make_connection(db_session, household_a.household_id)
    make_bank_account(db_session, household_a.household_id, connection.id, "hash-1", account_id=account.id)

    with pytest.raises(IntegrityError, match="uq_bankaccount_account"):
        make_bank_account(db_session, household_a.household_id, connection.id, "hash-2", account_id=account.id)


def test_a_bank_account_cannot_feed_another_households_account(
    db_session: Session, household_a: HouseholdContext, household_b: HouseholdContext
) -> None:
    """Test that the composite foreign key keeps a mapping inside its household."""
    foreign_account = make_account(db_session, household_b.household_id)
    connection = make_connection(db_session, household_a.household_id)

    with pytest.raises(IntegrityError, match="fk_bankaccount_account_household"):
        make_bank_account(db_session, household_a.household_id, connection.id, "hash-1", account_id=foreign_account.id)


def test_deleting_the_hydra_account_unmaps_the_bank_account(db_session: Session, household_a: HouseholdContext) -> None:
    """Test that a mapping never blocks deleting an account, and keeps its household."""
    account = make_account(db_session, household_a.household_id)
    connection = make_connection(db_session, household_a.household_id)
    bank_account = make_bank_account(db_session, household_a.household_id, connection.id, "h", account_id=account.id)

    db_session.delete(account)
    db_session.flush()
    db_session.refresh(bank_account)

    assert bank_account.account_id is None
    assert bank_account.household_id == household_a.household_id


def test_an_accepted_row_is_recorded_once_per_account(db_session: Session, household_a: HouseholdContext) -> None:
    """Test that two ledger rows with the same external id on one account are refused."""
    account = make_account(db_session, household_a.household_id)

    def add(external_id: str) -> None:
        db_session.add(
            Transaction(
                household_id=household_a.household_id,
                account_id=account.id,
                kind=TransactionKind.EXPENSE,
                amount_minor=100,
                occurred_on=datetime.date(2026, 10, 1),
                external_id=external_id,
            )
        )
        db_session.flush()

    add("eb:1")
    with pytest.raises(IntegrityError, match="uq_transaction_account_external_id"):
        add("eb:1")


def test_deleting_a_ledger_row_clears_the_inbox_link(db_session: Session, household_a: HouseholdContext) -> None:
    """Test that the database itself never leaves an inbox row pointing at a deleted transaction."""
    account = make_account(db_session, household_a.household_id)
    connection = make_connection(db_session, household_a.household_id)
    bank_account = make_bank_account(db_session, household_a.household_id, connection.id, "h", account_id=account.id)
    ledger = Transaction(
        household_id=household_a.household_id,
        account_id=account.id,
        kind=TransactionKind.EXPENSE,
        amount_minor=1250,
        occurred_on=datetime.date(2026, 10, 1),
    )
    db_session.add(ledger)
    db_session.flush()
    row = make_bank_transaction(
        db_session, household_a.household_id, bank_account.id, "ref-1", ledger_transaction_id=ledger.id
    )

    db_session.delete(ledger)
    db_session.flush()
    db_session.refresh(row)

    assert row.ledger_transaction_id is None


def test_deleting_the_household_removes_every_bank_row(db_session: Session, household_a: HouseholdContext) -> None:
    """Test that the cascade from the household reaches every bank table without a constraint in the way."""
    account = make_account(db_session, household_a.household_id)
    connection = make_connection(db_session, household_a.household_id)
    bank_account = make_bank_account(db_session, household_a.household_id, connection.id, "h", account_id=account.id)
    run = BankSyncRun(
        household_id=household_a.household_id,
        connection_id=connection.id,
        trigger=BankSyncTrigger.MANUAL,
        started_at=datetime.datetime.now(datetime.UTC),
    )
    db_session.add(run)
    db_session.flush()
    ledger = Transaction(
        household_id=household_a.household_id,
        account_id=account.id,
        kind=TransactionKind.EXPENSE,
        amount_minor=1250,
        occurred_on=datetime.date(2026, 10, 1),
        external_id="eb:x",
        import_batch_id=run.id,
    )
    db_session.add(ledger)
    db_session.flush()
    make_bank_transaction(
        db_session,
        household_a.household_id,
        bank_account.id,
        "ref-1",
        sync_run_id=run.id,
        ledger_transaction_id=ledger.id,
        raw={"entry_reference": "ref-1"},
    )

    household = db_session.get(Household, household_a.household_id)
    assert household is not None
    db_session.delete(household)
    db_session.flush()
    db_session.expunge_all()

    for model in (BankTransaction, BankAccount, BankSyncRun, BankConnection):
        assert db_session.exec(select(model)).all() == []
