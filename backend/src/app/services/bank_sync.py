"""Pulling booked transactions from a bank into the inbox.

A sync fetches every linked account of one connection, from a little before
the last booked row it has seen up to today, and keeps only what the bank has
booked. Pending rows are left for a later sync: their amount and reference
often change before they settle, and some never do.

Each row is recognised by a dedupe key, so fetching the same day twice adds
nothing. The bank's entry reference is the key when it sends one. Otherwise it
is a fingerprint of what the row says, numbered among identical rows on the
same day, so two identical coffees stay two rows.
"""

import datetime
import hashlib
import uuid
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlmodel import Session

from app.exceptions import (
    BankConnectionInactiveError,
    BankConnectionNotFoundError,
    BankProviderError,
    BankSessionExpiredError,
)
from app.models import (
    Account,
    BankAccount,
    BankConnectionStatus,
    BankDirection,
    BankReviewStatus,
    BankSyncRun,
    BankSyncRunPublic,
    BankSyncStatus,
    BankSyncTrigger,
)
from app.models.fields import IBAN_MAX_LENGTH, MAX_AMOUNT_MINOR, minor_digits
from app.repositories.bank import (
    BankAccountRepository,
    BankConnectionRepository,
    BankSyncRunRepository,
    BankTransactionRepository,
)
from app.services.enable_banking import BankProvider, Psu

_NAME_MAX_LENGTH = 255
_DESCRIPTION_MAX_LENGTH = 1024
_ERROR_MAX_LENGTH = 1024


@dataclass(frozen=True)
class MappedRow:
    """A booked bank row, read into what the inbox stores."""

    direction: BankDirection
    amount_minor: int
    currency_code: str
    occurred_on: datetime.date
    booking_date: datetime.date | None
    value_date: datetime.date | None
    transaction_date: datetime.date | None
    counterparty_name: str | None
    counterparty_iban: str | None
    description: str | None
    # The bank's own key for the row, when it gave one.
    reference: str | None
    raw: dict[str, Any]


def is_booked(raw: dict[str, Any]) -> bool:
    """Tell whether the bank has booked a row.

    Args:
        raw: The row as the bank sent it.

    Returns:
        True for a booked row. A row with no status counts as booked when it
        has a booking date, since some banks leave the status out.
    """
    status = raw.get("status")
    if status is None:
        return bool(raw.get("booking_date"))
    return bool(status == "BOOK")


def map_row(raw: dict[str, Any]) -> MappedRow | None:
    """Read a bank row into what the inbox stores.

    Args:
        raw: The row as the bank sent it.

    Returns:
        The row, or None when it cannot be stored: no amount, a zero or
        unrepresentable amount, or no date at all.
    """
    amount_field = raw.get("transaction_amount")
    if not isinstance(amount_field, dict):
        return None
    currency_code = _text(amount_field.get("currency"), 3)
    if currency_code is None or len(currency_code) != 3:
        return None
    try:
        amount = Decimal(str(amount_field.get("amount")))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite():
        return None

    scaled = abs(amount) * (10 ** minor_digits(currency_code))
    if scaled != scaled.to_integral_value() or not 0 < scaled <= MAX_AMOUNT_MINOR:
        return None

    indicator = raw.get("credit_debit_indicator")
    if indicator == "CRDT":
        direction = BankDirection.CREDIT
    elif indicator == "DBIT":
        direction = BankDirection.DEBIT
    else:
        direction = BankDirection.DEBIT if amount < 0 else BankDirection.CREDIT

    booking_date = _date(raw.get("booking_date"))
    value_date = _date(raw.get("value_date"))
    transaction_date = _date(raw.get("transaction_date"))
    # The booking date is the statement's, and the one the bank balance moves
    # on, so the ledger agrees with the bank day by day.
    occurred_on = booking_date or value_date or transaction_date
    if occurred_on is None:
        return None

    # The other side: who was paid for money out, who paid for money in.
    party, party_account = ("creditor", "creditor_account")
    if direction == BankDirection.CREDIT:
        party, party_account = ("debtor", "debtor_account")
    party_field = raw.get(party)
    counterparty_name = _text(party_field.get("name") if isinstance(party_field, dict) else None, _NAME_MAX_LENGTH)

    remittance = raw.get("remittance_information")
    lines = (
        [line.strip() for line in remittance if isinstance(line, str) and line.strip()]
        if isinstance(remittance, list)
        else []
    )
    description = _text(" ".join(lines), _DESCRIPTION_MAX_LENGTH)

    reference: str | None = None
    if (entry_reference := _text(raw.get("entry_reference"), 200)) is not None:
        reference = f"ref:{entry_reference}"
    elif (transaction_id := _text(raw.get("transaction_id"), 200)) is not None:
        reference = f"id:{transaction_id}"

    return MappedRow(
        direction=direction,
        amount_minor=int(scaled),
        currency_code=currency_code.upper(),
        occurred_on=occurred_on,
        booking_date=booking_date,
        value_date=value_date,
        transaction_date=transaction_date,
        counterparty_name=counterparty_name,
        counterparty_iban=_iban(raw.get(party_account)),
        description=description,
        reference=reference,
        raw=raw,
    )


def fingerprint(row: MappedRow) -> str:
    """Summarise what a row says, for a bank that gives it no reference.

    Args:
        row: The row.

    Returns:
        A hash of the dates, direction, amount, currency, counterparty and text.
    """
    parts = [
        row.booking_date.isoformat() if row.booking_date else "",
        row.value_date.isoformat() if row.value_date else "",
        row.transaction_date.isoformat() if row.transaction_date else "",
        row.direction.value,
        str(row.amount_minor),
        row.currency_code,
        (row.counterparty_name or "").casefold(),
        row.counterparty_iban or "",
        " ".join((row.description or "").casefold().split()),
    ]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:48]


def dedupe_keys(rows: Iterable[MappedRow]) -> list[str]:
    """Give each row of one fetch the key that recognises it on the next.

    Args:
        rows: The rows of one fetch of one account, in the order the bank sent them.

    Returns:
        One key per row, in the same order. A row without a reference gets its
        fingerprint and its place among identical ones, so the third identical
        row of a day is the third again next time.
    """
    seen: Counter[str] = Counter()
    keys = []
    for row in rows:
        base = row.reference if row.reference is not None else f"fp:{fingerprint(row)}"
        place = seen[base]
        seen[base] += 1
        if row.reference is not None:
            # A reference is unique by itself. Numbering only a repeat keeps
            # the key the bank's own, and keeps two rows the bank gave the
            # same reference from collapsing into one.
            keys.append(base if place == 0 else f"{base}#{place}")
        else:
            keys.append(f"{base}#{place}")
    return keys


def sync_window(
    bank_account: BankAccount, account: Account, today: datetime.date, overlap_days: int
) -> tuple[datetime.date, datetime.date]:
    """Work out which days to fetch for an account.

    Args:
        bank_account: The bank account.
        account: The Hydra account it feeds.
        today: The current day.
        overlap_days: How many days before the last booked row to fetch again.

    Returns:
        The first and last day to fetch, both included.
    """
    start = bank_account.import_from or account.opening_balance_date
    if bank_account.last_booked_on is not None:
        start = max(start, bank_account.last_booked_on - datetime.timedelta(days=overlap_days))
    return min(start, today), today


class BankSyncService:
    """Provide services for pulling bank transactions into the inbox."""

    def __init__(
        self,
        session: Session,
        provider: BankProvider,
        connection_repository: BankConnectionRepository,
        bank_account_repository: BankAccountRepository,
        sync_run_repository: BankSyncRunRepository,
        bank_transaction_repository: BankTransactionRepository,
        overlap_days: int,
    ) -> None:
        """Initialize the bank sync service.

        Args:
            session: The database session.
            provider: Where bank data comes from.
            connection_repository: The bank connection repository instance.
            bank_account_repository: The bank account repository instance.
            sync_run_repository: The bank sync run repository instance.
            bank_transaction_repository: The bank transaction repository instance.
            overlap_days: How many days before the last booked row each sync fetches again.
        """
        self.session = session
        self.provider = provider
        self.connection_repository = connection_repository
        self.bank_account_repository = bank_account_repository
        self.sync_run_repository = sync_run_repository
        self.bank_transaction_repository = bank_transaction_repository
        self.overlap_days = overlap_days

    @classmethod
    def for_session(cls, session: Session, provider: BankProvider, overlap_days: int) -> "BankSyncService":
        """Build a service on a session of its own, for work outside a request.

        Args:
            session: The database session.
            provider: Where bank data comes from.
            overlap_days: How many days before the last booked row each sync fetches again.

        Returns:
            A bank sync service.
        """
        return cls(
            session=session,
            provider=provider,
            connection_repository=BankConnectionRepository(session),
            bank_account_repository=BankAccountRepository(session),
            sync_run_repository=BankSyncRunRepository(session),
            bank_transaction_repository=BankTransactionRepository(session),
            overlap_days=overlap_days,
        )

    def sync(
        self,
        household_id: uuid.UUID,
        connection_id: uuid.UUID,
        trigger: BankSyncTrigger,
        psu: Psu | None,
    ) -> BankSyncRunPublic:
        """Pull a connection's booked transactions into the inbox.

        A failure at the bank does not raise. It is recorded on the run and on
        the connection, and what was fetched from other accounts before it is
        kept. An ended login marks the connection expired.

        Args:
            household_id: The ID of the household.
            connection_id: The ID of the connection.
            trigger: Whether a person asked for this or the schedule did.
            psu: The account holder at the browser, for a sync they asked for.

        Returns:
            What the sync did.

        Raises:
            BankConnectionNotFoundError: If the connection does not exist in the household.
            BankConnectionInactiveError: If the connection is not active.
        """
        connection = self.connection_repository.get_for_household(connection_id, household_id)
        if connection is None or connection.status in (BankConnectionStatus.PENDING, BankConnectionStatus.REVOKED):
            raise BankConnectionNotFoundError from None
        if connection.status != BankConnectionStatus.ACTIVE:
            raise BankConnectionInactiveError from None

        now = datetime.datetime.now(datetime.UTC)
        if connection.valid_until is not None and connection.valid_until <= now:
            # Past the end of the login, the bank would only refuse. Saying so
            # without asking spends none of its daily budget.
            connection.status = BankConnectionStatus.EXPIRED
            connection.next_auto_sync_at = None
            self.connection_repository.save(connection)
            self.session.commit()
            raise BankConnectionInactiveError from None

        run = BankSyncRun(
            household_id=household_id,
            connection_id=connection.id,
            trigger=trigger,
            started_at=now,
        )
        self.sync_run_repository.save(run)

        error: str | None = None
        for bank_account, account in self.bank_account_repository.list_syncable(connection.id, household_id):
            try:
                fetched, new = self._sync_account(run, bank_account, account, now.date(), psu)
            except BankSessionExpiredError as exc:
                connection.status = BankConnectionStatus.EXPIRED
                connection.next_auto_sync_at = None
                error = exc.message
                break
            except BankProviderError as exc:
                error = exc.message
                continue
            run.fetched_count += fetched
            run.new_count += new

        run.status = BankSyncStatus.FAILED if error else BankSyncStatus.SUCCEEDED
        run.error = error[:_ERROR_MAX_LENGTH] if error else None
        run.finished_at = datetime.datetime.now(datetime.UTC)
        self.sync_run_repository.save(run)

        connection.last_synced_at = run.finished_at
        connection.last_sync_error = run.error
        self.connection_repository.save(connection)
        self.session.commit()
        return BankSyncRunPublic.model_validate(run, from_attributes=True)

    def sync_due(self, now: datetime.datetime, interval: datetime.timedelta, limit: int) -> int:
        """Run the automatic sync of each connection that came due, in any household.

        Args:
            now: The current moment.
            interval: How long until a synced connection is due again.
            limit: The most connections to sync in this round. The rest wait
                for the next round.

        Returns:
            The number of connections synced.
        """
        synced = 0
        for _ in range(limit):
            connection = self.connection_repository.claim_due(now, interval)
            if connection is None:
                break
            household_id, connection_id = connection.household_id, connection.id
            # Committed before the bank is called. See claim_due.
            self.session.commit()
            try:
                self.sync(household_id, connection_id, BankSyncTrigger.AUTO, psu=None)
            except BankConnectionInactiveError:
                continue
            synced += 1
        return synced

    def prune(self, now: datetime.datetime, pending_ttl: datetime.timedelta, raw_retention: datetime.timedelta) -> int:
        """Remove abandoned logins and clear old bank data, in every household.

        Args:
            now: The current moment.
            pending_ttl: How long a started login may take before it is abandoned.
            raw_retention: How long what the bank sent for a row is kept.

        Returns:
            The number of rows removed or cleared.
        """
        removed = self.connection_repository.delete_abandoned(now - pending_ttl)
        cleared = self.bank_transaction_repository.clear_raw(now - raw_retention)
        self.session.commit()
        return removed + cleared

    def _sync_account(
        self, run: BankSyncRun, bank_account: BankAccount, account: Account, today: datetime.date, psu: Psu | None
    ) -> tuple[int, int]:
        """Fetch one account's booked rows and add the new ones to the inbox.

        Args:
            run: The sync run the rows come in with.
            bank_account: The bank account.
            account: The Hydra account it feeds.
            today: The current day.
            psu: The account holder at the browser, if present.

        Returns:
            How many booked rows the bank returned, and how many were new.
        """
        date_from, date_to = sync_window(bank_account, account, today, self.overlap_days)
        raw_rows = list(self.provider.transactions(bank_account.provider_account_uid, date_from, date_to, psu))

        mapped = [
            row
            for row in (map_row(raw) for raw in raw_rows if is_booked(raw))
            if row is not None
            # A row in another currency has nowhere to go in this account,
            # and a row before the start date is part of the opening balance.
            and row.currency_code == account.currency_code
            and row.occurred_on >= date_from
        ]
        keys = dedupe_keys(mapped)
        new = self.bank_transaction_repository.insert_new(
            [_row_values(run, bank_account, row, key) for row, key in zip(mapped, keys, strict=True)]
        )

        if mapped:
            latest = max(row.occurred_on for row in mapped)
            if bank_account.last_booked_on is None or latest > bank_account.last_booked_on:
                bank_account.last_booked_on = latest
                self.bank_account_repository.save(bank_account)
        return len(mapped), new


def _row_values(run: BankSyncRun, bank_account: BankAccount, row: MappedRow, dedupe_key: str) -> dict[str, Any]:
    return {
        "id": uuid.uuid4(),
        "household_id": bank_account.household_id,
        "bank_account_id": bank_account.id,
        "sync_run_id": run.id,
        "dedupe_key": dedupe_key,
        # The key above was made from the bank's own direction, so flipping
        # an account later still recognises every row it already holds.
        "direction": _flipped(row.direction) if bank_account.flip_direction else row.direction,
        "amount_minor": row.amount_minor,
        "currency_code": row.currency_code,
        "occurred_on": row.occurred_on,
        "booking_date": row.booking_date,
        "value_date": row.value_date,
        "transaction_date": row.transaction_date,
        "counterparty_name": row.counterparty_name,
        "counterparty_iban": row.counterparty_iban,
        "description": row.description,
        "raw": row.raw,
        "review_status": BankReviewStatus.PENDING,
    }


def _flipped(direction: BankDirection) -> BankDirection:
    return BankDirection.DEBIT if direction == BankDirection.CREDIT else BankDirection.CREDIT


def _text(value: Any, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:max_length] if value else None


def _date(value: Any) -> datetime.date | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.date.fromisoformat(value[:10])
    except ValueError:
        return None


def _iban(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    iban = value.get("iban")
    if not iban and value.get("scheme_name") == "IBAN":
        iban = value.get("identification")
    if not isinstance(iban, str):
        return None
    iban = iban.replace(" ", "").upper()
    return iban if 0 < len(iban) <= IBAN_MAX_LENGTH else None
