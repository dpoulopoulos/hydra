"""Syncing a bank into the inbox against a real database, with the bank itself faked."""

import datetime
import uuid
from typing import Any
from unittest.mock import MagicMock

from sqlmodel import Session, select

from app.models import (
    BankAccount,
    BankConnection,
    BankConnectionStatus,
    BankReviewStatus,
    BankSyncTrigger,
    BankTransaction,
    HouseholdContext,
)
from app.services.bank_sync import BankSyncService
from tests.integration.conftest import make_account

TODAY = datetime.date.today()


def booked(reference: str | None, days_ago: int, amount: str = "4.20", **fields: Any) -> dict[str, Any]:
    return {
        "entry_reference": reference,
        "transaction_amount": {"currency": "EUR", "amount": amount},
        "credit_debit_indicator": "DBIT",
        "status": "BOOK",
        "booking_date": (TODAY - datetime.timedelta(days=days_ago)).isoformat(),
        "creditor": {"name": "Coffee Island"},
        **fields,
    }


def seed(db_session: Session, household: HouseholdContext) -> tuple[BankConnection, BankAccount]:
    account = make_account(db_session, household.household_id, opening_balance_date=TODAY - datetime.timedelta(days=60))
    connection = BankConnection(
        household_id=household.household_id,
        aspsp_name="Mock ASPSP",
        aspsp_country="GR",
        status=BankConnectionStatus.ACTIVE,
        session_id=str(uuid.uuid4()),
    )
    db_session.add(connection)
    db_session.flush()
    bank_account = BankAccount(
        household_id=household.household_id,
        connection_id=connection.id,
        provider_account_uid="uid-1",
        identity_key=f"hash-{household.household_id}",
        account_id=account.id,
        import_from=TODAY - datetime.timedelta(days=30),
        currency_code="EUR",
    )
    db_session.add(bank_account)
    db_session.flush()
    return connection, bank_account


def inbox(db_session: Session, household: HouseholdContext) -> list[BankTransaction]:
    statement = select(BankTransaction).where(BankTransaction.household_id == household.household_id)
    return list(db_session.exec(statement).all())


def test_overlapping_syncs_add_each_row_once(db_session: Session, household_a: HouseholdContext) -> None:
    """Test that rows fetched again, with or without a reference, are recognised."""
    connection, bank_account = seed(db_session, household_a)
    provider = MagicMock()
    service = BankSyncService.for_session(db_session, provider, overlap_days=10)

    # Two identical coffees with no reference on one day, and one with a reference.
    first_fetch = [booked(None, 3), booked(None, 3), booked("r-1", 2)]
    provider.transactions.return_value = iter(first_fetch)
    first = service.sync(household_a.household_id, connection.id, BankSyncTrigger.MANUAL, None)

    # The same days again, plus a third identical coffee booked late and a new row.
    provider.transactions.return_value = iter([*first_fetch, booked(None, 3), booked("r-2", 0)])
    second = service.sync(household_a.household_id, connection.id, BankSyncTrigger.AUTO, None)

    assert first.new_count == 3
    assert second.fetched_count == 5
    assert second.new_count == 2
    rows = inbox(db_session, household_a)
    assert len(rows) == 5
    assert all(row.review_status == BankReviewStatus.PENDING for row in rows)
    assert all(row.raw is not None for row in rows)
    db_session.refresh(bank_account)
    assert bank_account.last_booked_on == TODAY


def test_the_second_sync_starts_from_the_last_booked_day_less_the_overlap(
    db_session: Session, household_a: HouseholdContext
) -> None:
    """Test that a sync after the first fetches a short window rather than everything again."""
    connection, _ = seed(db_session, household_a)
    provider = MagicMock()
    service = BankSyncService.for_session(db_session, provider, overlap_days=5)
    provider.transactions.return_value = iter([booked("r-1", 1)])
    service.sync(household_a.household_id, connection.id, BankSyncTrigger.MANUAL, None)

    provider.transactions.return_value = iter([])
    service.sync(household_a.household_id, connection.id, BankSyncTrigger.MANUAL, None)

    date_from = provider.transactions.call_args.args[1]
    assert date_from == TODAY - datetime.timedelta(days=6)


def test_households_do_not_see_each_others_rows(
    db_session: Session, household_a: HouseholdContext, household_b: HouseholdContext
) -> None:
    """Test that the same reference in two households is two rows, each in its own household."""
    connection_a, _ = seed(db_session, household_a)
    connection_b, _ = seed(db_session, household_b)
    provider = MagicMock()
    service = BankSyncService.for_session(db_session, provider, overlap_days=10)

    provider.transactions.return_value = iter([booked("same", 1)])
    service.sync(household_a.household_id, connection_a.id, BankSyncTrigger.MANUAL, None)
    provider.transactions.return_value = iter([booked("same", 1)])
    result_b = service.sync(household_b.household_id, connection_b.id, BankSyncTrigger.MANUAL, None)

    assert result_b.new_count == 1
    assert len(inbox(db_session, household_a)) == 1
    assert len(inbox(db_session, household_b)) == 1
