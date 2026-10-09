import datetime
import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.exceptions import (
    BankConnectionInactiveError,
    BankConnectionNotFoundError,
    BankProviderError,
    BankRateLimitedError,
    BankSessionExpiredError,
)
from app.models import (
    Account,
    AccountType,
    BankAccount,
    BankConnection,
    BankConnectionStatus,
    BankDirection,
    BankReviewStatus,
    BankSyncStatus,
    BankSyncTrigger,
)
from app.services.bank_sync import BankSyncService, dedupe_keys, fingerprint, is_booked, map_row, sync_window
from app.services.enable_banking import Psu

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
TODAY = datetime.date.today()


def bank_row(**fields: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "entry_reference": "ref-1",
        "transaction_amount": {"currency": "EUR", "amount": "12.50"},
        "credit_debit_indicator": "DBIT",
        "status": "BOOK",
        "booking_date": "2026-10-01",
        "value_date": "2026-09-30",
        "creditor": {"name": "Coffee Island"},
        "creditor_account": {"iban": "GR16 0110 1250 0000 0001 2300 695"},
        "debtor": {"name": "Me"},
        "remittance_information": ["CARD 1234", "  ATHENS "],
    }
    row.update(fields)
    return row


class TestIsBooked:
    """Tests for is_booked."""

    @pytest.mark.parametrize(
        ("fields", "expected"),
        [
            ({"status": "BOOK"}, True),
            ({"status": "PDNG"}, False),
            ({"status": None, "booking_date": "2026-10-01"}, True),
            ({"status": None, "booking_date": None}, False),
        ],
    )
    def test_status(self, fields: dict[str, Any], expected: bool) -> None:
        assert is_booked(bank_row(**fields)) is expected


class TestMapRow:
    """Tests for map_row."""

    def test_reads_a_card_payment(self) -> None:
        row = map_row(bank_row())

        assert row is not None
        assert row.direction == BankDirection.DEBIT
        assert row.amount_minor == 1250
        assert row.currency_code == "EUR"
        assert row.occurred_on == datetime.date(2026, 10, 1)
        assert row.counterparty_name == "Coffee Island"
        assert row.counterparty_iban == "GR1601101250000000012300695"
        assert row.description == "CARD 1234 ATHENS"
        assert row.reference == "ref:ref-1"

    def test_money_in_takes_the_debtor_as_counterparty(self) -> None:
        row = map_row(
            bank_row(credit_debit_indicator="CRDT", debtor={"name": "Employer"}, debtor_account={"iban": "DE89"})
        )

        assert row is not None
        assert row.direction == BankDirection.CREDIT
        assert row.counterparty_name == "Employer"
        assert row.counterparty_iban == "DE89"

    @pytest.mark.parametrize(("amount", "direction"), [("-5.00", BankDirection.DEBIT), ("5.00", BankDirection.CREDIT)])
    def test_no_indicator_falls_back_to_the_sign(self, amount: str, direction: BankDirection) -> None:
        row = map_row(bank_row(credit_debit_indicator=None, transaction_amount={"currency": "EUR", "amount": amount}))

        assert row is not None
        assert row.direction == direction
        assert row.amount_minor == 500

    def test_a_currency_without_minor_units_is_scaled_by_its_own_digits(self) -> None:
        row = map_row(bank_row(transaction_amount={"currency": "JPY", "amount": "1500"}))

        assert row is not None
        assert row.amount_minor == 1500

    def test_transaction_id_is_the_reference_without_an_entry_reference(self) -> None:
        row = map_row(bank_row(entry_reference=None, transaction_id="tx-9"))

        assert row is not None
        assert row.reference == "id:tx-9"

    def test_no_reference_at_all(self) -> None:
        row = map_row(bank_row(entry_reference=None))

        assert row is not None
        assert row.reference is None

    def test_dates_fall_back_in_order(self) -> None:
        row = map_row(bank_row(booking_date=None, value_date=None, transaction_date="2026-09-29T10:00:00"))

        assert row is not None
        assert row.occurred_on == datetime.date(2026, 9, 29)

    def test_an_iban_given_as_a_scheme(self) -> None:
        row = map_row(bank_row(creditor_account={"identification": "gr16 0110", "scheme_name": "IBAN"}))

        assert row is not None
        assert row.counterparty_iban == "GR160110"

    def test_text_is_trimmed_to_fit(self) -> None:
        row = map_row(bank_row(creditor={"name": "x" * 300}, remittance_information=["y" * 2000]))

        assert row is not None
        assert row.counterparty_name is not None and len(row.counterparty_name) == 255
        assert row.description is not None and len(row.description) == 1024

    @pytest.mark.parametrize(
        "fields",
        [
            {"transaction_amount": None},
            {"transaction_amount": {"currency": "EUR", "amount": "abc"}},
            {"transaction_amount": {"currency": "EUR", "amount": "0.00"}},
            {"transaction_amount": {"currency": "EUR", "amount": "1.005"}},
            {"transaction_amount": {"currency": "EUR", "amount": "NaN"}},
            {"transaction_amount": {"currency": "EU", "amount": "1.00"}},
            {"booking_date": None, "value_date": None, "transaction_date": None},
            {"booking_date": "not a date", "value_date": None},
        ],
    )
    def test_rows_that_cannot_be_stored(self, fields: dict[str, Any]) -> None:
        assert map_row(bank_row(**fields)) is None


class TestDedupeKeys:
    """Tests for dedupe_keys and fingerprint."""

    def test_references_are_kept_as_they_are(self) -> None:
        rows = [map_row(bank_row(entry_reference="a")), map_row(bank_row(entry_reference="b"))]

        assert dedupe_keys([r for r in rows if r]) == ["ref:a", "ref:b"]

    def test_a_repeated_reference_is_numbered(self) -> None:
        row = map_row(bank_row(entry_reference="a"))
        assert row is not None

        assert dedupe_keys([row, row]) == ["ref:a", "ref:a#1"]

    def test_identical_rows_without_a_reference_stay_distinct_and_stable(self) -> None:
        coffee = map_row(bank_row(entry_reference=None))
        lunch = map_row(bank_row(entry_reference=None, transaction_amount={"currency": "EUR", "amount": "9.00"}))
        assert coffee is not None and lunch is not None

        first = dedupe_keys([coffee, lunch, coffee])
        again = dedupe_keys([coffee, lunch, coffee])

        assert first[0].endswith("#0")
        assert first[2].endswith("#1")
        assert first[0].rsplit("#", 1)[0] == first[2].rsplit("#", 1)[0]
        assert first[1] != first[0]
        assert first == again

    def test_fingerprint_ignores_case_and_spacing_in_text(self) -> None:
        a = map_row(bank_row(entry_reference=None, remittance_information=["Card  1234"]))
        b = map_row(bank_row(entry_reference=None, remittance_information=["card 1234"]))
        assert a is not None and b is not None

        assert fingerprint(a) == fingerprint(b)


class TestSyncWindow:
    """Tests for sync_window."""

    def make(
        self, import_from: datetime.date | None, last_booked_on: datetime.date | None
    ) -> tuple[BankAccount, Account]:
        bank_account = BankAccount(
            household_id=HOUSEHOLD_ID,
            connection_id=uuid.uuid4(),
            provider_account_uid="u",
            identity_key="k",
            import_from=import_from,
            last_booked_on=last_booked_on,
        )
        account = Account(
            household_id=HOUSEHOLD_ID,
            name="A",
            type=AccountType.CURRENT,
            opening_balance_date=datetime.date(2024, 1, 1),
        )
        return bank_account, account

    def test_first_sync_starts_at_the_import_date(self) -> None:
        bank_account, account = self.make(datetime.date(2026, 9, 1), None)

        assert sync_window(bank_account, account, datetime.date(2026, 10, 9), 10) == (
            datetime.date(2026, 9, 1),
            datetime.date(2026, 10, 9),
        )

    def test_later_syncs_overlap_the_last_booked_day(self) -> None:
        bank_account, account = self.make(datetime.date(2026, 1, 1), datetime.date(2026, 10, 5))

        assert sync_window(bank_account, account, datetime.date(2026, 10, 9), 10)[0] == datetime.date(2026, 9, 25)

    def test_the_overlap_never_reaches_before_the_import_date(self) -> None:
        bank_account, account = self.make(datetime.date(2026, 10, 1), datetime.date(2026, 10, 3))

        assert sync_window(bank_account, account, datetime.date(2026, 10, 9), 10)[0] == datetime.date(2026, 10, 1)

    def test_no_import_date_falls_back_to_the_opening_balance(self) -> None:
        bank_account, account = self.make(None, None)

        assert sync_window(bank_account, account, datetime.date(2026, 10, 9), 10)[0] == datetime.date(2024, 1, 1)


@pytest.fixture
def provider() -> MagicMock:
    return MagicMock()


@pytest.fixture
def service(mock_db_session: MagicMock, provider: MagicMock) -> BankSyncService:
    service = BankSyncService(
        session=mock_db_session,
        provider=provider,
        connection_repository=MagicMock(),
        bank_account_repository=MagicMock(),
        sync_run_repository=MagicMock(),
        bank_transaction_repository=MagicMock(),
        overlap_days=10,
    )
    service.sync_run_repository.save.side_effect = lambda entity: entity
    service.bank_transaction_repository.insert_new.side_effect = lambda rows: len(rows)
    return service


def make_connection(status: BankConnectionStatus = BankConnectionStatus.ACTIVE) -> BankConnection:
    return BankConnection(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        aspsp_name="Mock ASPSP",
        aspsp_country="GR",
        status=status,
        session_id="s",
        next_auto_sync_at=datetime.datetime.now(datetime.UTC),
    )


def make_pair(name: str = "Main", currency: str = "EUR") -> tuple[BankAccount, Account]:
    bank_account = BankAccount(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        connection_id=uuid.uuid4(),
        provider_account_uid=f"uid-{name}",
        identity_key=name,
        name=name,
        import_from=TODAY - datetime.timedelta(days=30),
    )
    account = Account(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        name=name,
        type=AccountType.CURRENT,
        opening_balance_date=datetime.date(2024, 1, 1),
        currency_code=currency,
    )
    return bank_account, account


class TestSync:
    """Tests for BankSyncService.sync."""

    def test_stores_booked_rows_and_records_the_run(self, service: BankSyncService, provider: MagicMock) -> None:
        connection = make_connection()
        bank_account, account = make_pair()
        service.connection_repository.get_for_household.return_value = connection
        service.bank_account_repository.list_syncable.return_value = [(bank_account, account)]
        booked_on = (TODAY - datetime.timedelta(days=2)).isoformat()
        provider.transactions.return_value = iter(
            [
                bank_row(entry_reference="a", booking_date=booked_on),
                bank_row(entry_reference="b", status="PDNG"),
                bank_row(entry_reference="c", transaction_amount={"currency": "USD", "amount": "1.00"}),
                bank_row(entry_reference="d", booking_date="2020-01-01"),
            ]
        )
        psu = Psu("203.0.113.9", "Firefox")

        result = service.sync(HOUSEHOLD_ID, connection.id, BankSyncTrigger.MANUAL, psu)

        assert result.status == BankSyncStatus.SUCCEEDED
        assert result.fetched_count == 1
        assert result.new_count == 1
        inserted = service.bank_transaction_repository.insert_new.call_args.args[0]
        assert [r["dedupe_key"] for r in inserted] == ["ref:a"]
        assert inserted[0]["review_status"] == BankReviewStatus.PENDING
        assert inserted[0]["sync_run_id"] == result.id
        assert bank_account.last_booked_on == TODAY - datetime.timedelta(days=2)
        assert connection.last_synced_at is not None
        assert connection.last_sync_error is None
        uid, date_from, date_to, passed_psu = provider.transactions.call_args.args
        assert uid == "uid-Main"
        assert date_from == TODAY - datetime.timedelta(days=30)
        assert date_to == TODAY
        assert passed_psu is psu
        service.session.commit.assert_called_once()

    def test_an_ended_login_expires_the_connection(self, service: BankSyncService, provider: MagicMock) -> None:
        connection = make_connection()
        service.connection_repository.get_for_household.return_value = connection
        service.bank_account_repository.list_syncable.return_value = [make_pair("A"), make_pair("B")]
        provider.transactions.side_effect = BankSessionExpiredError("EXPIRED_SESSION")

        result = service.sync(HOUSEHOLD_ID, connection.id, BankSyncTrigger.AUTO, None)

        assert result.status == BankSyncStatus.FAILED
        assert result.error is not None and "Connect the bank again" in result.error
        assert connection.status == BankConnectionStatus.EXPIRED
        assert connection.next_auto_sync_at is None
        assert provider.transactions.call_count == 1

    def test_a_failing_account_does_not_stop_the_others(self, service: BankSyncService, provider: MagicMock) -> None:
        connection = make_connection()
        service.connection_repository.get_for_household.return_value = connection
        service.bank_account_repository.list_syncable.return_value = [make_pair("A"), make_pair("B")]
        provider.transactions.side_effect = [BankRateLimitedError(), iter([bank_row(booking_date=TODAY.isoformat())])]

        result = service.sync(HOUSEHOLD_ID, connection.id, BankSyncTrigger.AUTO, None)

        assert result.status == BankSyncStatus.FAILED
        assert result.new_count == 1
        assert connection.status == BankConnectionStatus.ACTIVE
        assert connection.last_sync_error is not None and "Try again tomorrow" in connection.last_sync_error

    def test_nothing_new_leaves_the_last_booked_day(self, service: BankSyncService, provider: MagicMock) -> None:
        connection = make_connection()
        bank_account, account = make_pair()
        bank_account.last_booked_on = TODAY
        service.connection_repository.get_for_household.return_value = connection
        service.bank_account_repository.list_syncable.return_value = [(bank_account, account)]
        provider.transactions.return_value = iter(
            [bank_row(booking_date=(TODAY - datetime.timedelta(days=3)).isoformat())]
        )

        service.sync(HOUSEHOLD_ID, connection.id, BankSyncTrigger.MANUAL, None)

        assert bank_account.last_booked_on == TODAY

    @pytest.mark.parametrize("status", [None, BankConnectionStatus.PENDING, BankConnectionStatus.REVOKED])
    def test_a_missing_connection_is_not_found(
        self, service: BankSyncService, status: BankConnectionStatus | None
    ) -> None:
        service.connection_repository.get_for_household.return_value = (
            None if status is None else make_connection(status)
        )

        with pytest.raises(BankConnectionNotFoundError):
            service.sync(HOUSEHOLD_ID, uuid.uuid4(), BankSyncTrigger.MANUAL, None)

    @pytest.mark.parametrize("status", [BankConnectionStatus.EXPIRED, BankConnectionStatus.FAILED])
    def test_an_inactive_connection_is_refused(self, service: BankSyncService, status: BankConnectionStatus) -> None:
        service.connection_repository.get_for_household.return_value = make_connection(status)

        with pytest.raises(BankConnectionInactiveError):
            service.sync(HOUSEHOLD_ID, uuid.uuid4(), BankSyncTrigger.MANUAL, None)

    def test_for_session_builds_its_own_repositories(self, mock_db_session: MagicMock, provider: MagicMock) -> None:
        service = BankSyncService.for_session(mock_db_session, provider, overlap_days=3)

        assert service.overlap_days == 3
        assert service.bank_transaction_repository.session is mock_db_session

    def test_provider_errors_are_not_raised(self, service: BankSyncService, provider: MagicMock) -> None:
        connection = make_connection()
        service.connection_repository.get_for_household.return_value = connection
        service.bank_account_repository.list_syncable.return_value = [make_pair()]
        provider.transactions.side_effect = BankProviderError("Bank is down", "ASPSP_ERROR")

        result = service.sync(HOUSEHOLD_ID, connection.id, BankSyncTrigger.MANUAL, None)

        assert result.status == BankSyncStatus.FAILED
        assert result.error is not None and "Bank is down" in result.error


class TestSyncDueAndPrune:
    """Tests for the automatic sync round and the clean-up."""

    def test_expired_login_is_marked_without_calling_the_bank(
        self, service: BankSyncService, provider: MagicMock
    ) -> None:
        connection = make_connection()
        connection.valid_until = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=1)
        service.connection_repository.get_for_household.return_value = connection

        with pytest.raises(BankConnectionInactiveError):
            service.sync(HOUSEHOLD_ID, connection.id, BankSyncTrigger.AUTO, None)

        assert connection.status == BankConnectionStatus.EXPIRED
        assert connection.next_auto_sync_at is None
        provider.transactions.assert_not_called()

    def test_sync_due_claims_commits_then_syncs_each_due_connection(
        self, service: BankSyncService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first, second = make_connection(), make_connection()
        service.connection_repository.claim_due.side_effect = [first, second, None]
        calls: list[str] = []
        service.session.commit.side_effect = lambda: calls.append("commit")
        sync = MagicMock(side_effect=lambda *args, **kwargs: calls.append("sync"))
        monkeypatch.setattr(service, "sync", sync)
        now = datetime.datetime.now(datetime.UTC)

        synced = service.sync_due(now, datetime.timedelta(hours=24), limit=5)

        assert synced == 2
        assert calls == ["commit", "sync", "commit", "sync"]
        assert sync.call_args_list[0].args == (HOUSEHOLD_ID, first.id, BankSyncTrigger.AUTO)
        assert sync.call_args_list[0].kwargs == {"psu": None}

    def test_sync_due_stops_at_the_limit_and_skips_inactive_ones(
        self, service: BankSyncService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service.connection_repository.claim_due.side_effect = lambda now, interval: make_connection()
        monkeypatch.setattr(service, "sync", MagicMock(side_effect=[BankConnectionInactiveError(), None, None]))

        synced = service.sync_due(datetime.datetime.now(datetime.UTC), datetime.timedelta(hours=24), limit=3)

        assert synced == 2
        assert service.connection_repository.claim_due.call_count == 3

    def test_prune_removes_abandoned_logins_and_clears_old_rows(self, service: BankSyncService) -> None:
        service.connection_repository.delete_abandoned.return_value = 2
        service.bank_transaction_repository.clear_raw.return_value = 7
        now = datetime.datetime(2026, 10, 9, 12, tzinfo=datetime.UTC)

        pruned = service.prune(now, datetime.timedelta(minutes=60), datetime.timedelta(days=90))

        assert pruned == 9
        service.connection_repository.delete_abandoned.assert_called_once_with(now - datetime.timedelta(minutes=60))
        service.bank_transaction_repository.clear_raw.assert_called_once_with(now - datetime.timedelta(days=90))
        service.session.commit.assert_called_once()
