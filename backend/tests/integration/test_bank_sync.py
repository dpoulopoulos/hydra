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
    BankDirection,
    BankReviewStatus,
    BankSyncTrigger,
    BankTransaction,
    HouseholdContext,
)
from app.repositories import BankConnectionRepository, BankTransactionRepository
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


def test_a_flipped_account_turns_rows_around_and_still_recognises_them(
    db_session: Session, household_a: HouseholdContext
) -> None:
    """Test that flipping turns around stored and new rows, and a refetch adds no copies."""
    connection, bank_account = seed(db_session, household_a)
    provider = MagicMock()
    service = BankSyncService.for_session(db_session, provider, overlap_days=10)
    # A card that labels a purchase as money in. One row has no reference, so
    # it is known only by its fingerprint.
    purchases = [booked(None, 3, credit_debit_indicator="CRDT"), booked("r-1", 2, credit_debit_indicator="CRDT")]
    provider.transactions.return_value = iter(purchases)
    service.sync(household_a.household_id, connection.id, BankSyncTrigger.MANUAL, None)

    bank_account.flip_direction = True
    flipped = BankTransactionRepository(db_session).flip_directions(bank_account.id, household_a.household_id)
    provider.transactions.return_value = iter([*purchases, booked("r-2", 0, credit_debit_indicator="CRDT")])
    again = service.sync(household_a.household_id, connection.id, BankSyncTrigger.MANUAL, None)

    assert flipped == 2
    assert again.new_count == 1
    db_session.expire_all()
    rows = inbox(db_session, household_a)
    assert len(rows) == 3
    assert all(row.direction == BankDirection.DEBIT for row in rows)


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


def test_claiming_moves_the_next_sync_on_and_skips_what_is_not_due(
    db_session: Session, household_a: HouseholdContext
) -> None:
    """Test that a due connection is claimed once, and an idle or inactive one is not."""
    now = datetime.datetime.now(datetime.UTC)
    due, _ = seed(db_session, household_a)
    due.next_auto_sync_at = now - datetime.timedelta(minutes=5)
    later = BankConnection(
        household_id=household_a.household_id,
        aspsp_name="Mock ASPSP",
        aspsp_country="GR",
        status=BankConnectionStatus.ACTIVE,
        next_auto_sync_at=now + datetime.timedelta(hours=1),
    )
    expired = BankConnection(
        household_id=household_a.household_id,
        aspsp_name="Mock ASPSP",
        aspsp_country="GR",
        status=BankConnectionStatus.EXPIRED,
        next_auto_sync_at=now - datetime.timedelta(hours=1),
    )
    db_session.add_all([due, later, expired])
    db_session.flush()
    repository = BankConnectionRepository(db_session)

    claimed = repository.claim_due(now, datetime.timedelta(hours=24))
    again = repository.claim_due(now, datetime.timedelta(hours=24))

    assert claimed is not None and claimed.id == due.id
    assert claimed.next_auto_sync_at == now + datetime.timedelta(hours=24)
    assert again is None


def test_prune_drops_abandoned_logins_and_clears_old_bank_data(
    db_session: Session, household_a: HouseholdContext
) -> None:
    """Test that only old pending or failed logins go, and only old rows lose their raw data."""
    connection, _ = seed(db_session, household_a)
    provider = MagicMock()
    service = BankSyncService.for_session(db_session, provider, overlap_days=10)
    provider.transactions.return_value = iter([booked("old", 2), booked("new", 1)])
    service.sync(household_a.household_id, connection.id, BankSyncTrigger.MANUAL, None)
    old_row, new_row = sorted(inbox(db_session, household_a), key=lambda r: r.dedupe_key, reverse=True)
    now = datetime.datetime.now(datetime.UTC)
    old_row.created_at = now - datetime.timedelta(days=100)
    abandoned = BankConnection(
        household_id=household_a.household_id,
        aspsp_name="Mock ASPSP",
        aspsp_country="GR",
        status=BankConnectionStatus.PENDING,
        state="abandoned",
        created_at=now - datetime.timedelta(hours=3),
    )
    fresh = BankConnection(
        household_id=household_a.household_id,
        aspsp_name="Mock ASPSP",
        aspsp_country="GR",
        status=BankConnectionStatus.PENDING,
        state="fresh",
    )
    db_session.add_all([old_row, abandoned, fresh])
    db_session.flush()

    pruned = service.prune(now, datetime.timedelta(minutes=60), datetime.timedelta(days=90))

    assert pruned == 2
    db_session.expire_all()
    assert db_session.get(BankConnection, abandoned.id) is None
    assert db_session.get(BankConnection, fresh.id) is not None
    assert db_session.get(BankConnection, connection.id) is not None
    assert db_session.get(BankTransaction, old_row.id).raw is None  # type: ignore[union-attr]
    assert db_session.get(BankTransaction, old_row.id).dedupe_key == "ref:old"  # type: ignore[union-attr]
    assert db_session.get(BankTransaction, new_row.id).raw is not None  # type: ignore[union-attr]
