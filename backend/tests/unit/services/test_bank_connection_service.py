import datetime
import uuid
from unittest.mock import MagicMock

import pytest

from app.exceptions import (
    AccountArchivedError,
    AccountNotFoundError,
    AspspNotFoundError,
    BankAccountAlreadyMappedError,
    BankAccountMappingError,
    BankAccountNotFoundError,
    BankAuthorizationError,
    BankConnectionNotFoundError,
    BankConnectionNotPermittedError,
    BankProviderError,
)
from app.models import (
    Account,
    AccountType,
    BankAccount,
    BankAccountUpdate,
    BankConnection,
    BankConnectionComplete,
    BankConnectionStart,
    BankConnectionStatus,
    HouseholdContext,
    HouseholdRole,
    User,
)
from app.services import BankConnectionService
from app.services.bank_connection import identity_key_of
from app.services.enable_banking import Aspsp, Authorization, BankSession, Psu, SessionAccount

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
NOW = datetime.datetime.now(datetime.UTC)


@pytest.fixture
def provider() -> MagicMock:
    provider = MagicMock()
    provider.is_configured = True
    provider.list_aspsps.return_value = [
        Aspsp(name="Mock ASPSP", country="GR", logo=None, maximum_consent_seconds=90 * 86400)
    ]
    provider.start_authorization.return_value = Authorization(url="https://bank.test/login", authorization_id="a")
    return provider


@pytest.fixture
def service(mock_db_session: MagicMock, provider: MagicMock) -> BankConnectionService:
    service = BankConnectionService(
        session=mock_db_session,
        provider=provider,
        connection_repository=MagicMock(),
        bank_account_repository=MagicMock(),
        account_repository=MagicMock(),
        redirect_url="http://localhost:5173/settings/bank/callback",
        consent_days=180,
        pending_ttl_minutes=60,
        auto_sync_interval_hours=24,
    )
    service.connection_repository.save.side_effect = lambda entity: entity
    service.bank_account_repository.save.side_effect = lambda entity: entity
    service.bank_account_repository.list_for_connections.return_value = []
    service.bank_account_repository.get_by_identity.return_value = None
    service.bank_account_repository.get_by_account.return_value = None
    return service


def make_connection(household: HouseholdContext, **fields: object) -> BankConnection:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "household_id": HOUSEHOLD_ID,
        "created_by_user_id": household.user.id,
        "aspsp_name": "Mock ASPSP",
        "aspsp_country": "GR",
        "state": "state-1",
        "created_at": NOW - datetime.timedelta(minutes=2),
    }
    values.update(fields)
    return BankConnection(**values)


def make_bank_account(**fields: object) -> BankAccount:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "household_id": HOUSEHOLD_ID,
        "connection_id": uuid.uuid4(),
        "provider_account_uid": "uid-1",
        "identity_key": "hash-1",
        "currency_code": "EUR",
    }
    values.update(fields)
    return BankAccount(**values)


def make_account(**fields: object) -> Account:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "household_id": HOUSEHOLD_ID,
        "name": "Current",
        "type": AccountType.CURRENT,
        "opening_balance_date": datetime.date(2024, 1, 1),
        "currency_code": "EUR",
    }
    values.update(fields)
    return Account(**values)


class TestIdentityKey:
    """Tests for identity_key_of."""

    def test_prefers_the_identification_hash(self) -> None:
        account = SessionAccount(uid="u", identification_hash="h", iban="GR16 0110", name=None, currency=None)
        assert identity_key_of(account) == "h"

    def test_falls_back_to_a_compact_iban(self) -> None:
        account = SessionAccount(uid="u", identification_hash=None, iban="gr16 0110", name=None, currency=None)
        assert identity_key_of(account) == "iban:GR160110"

    def test_falls_back_to_the_uid(self) -> None:
        account = SessionAccount(uid="u", identification_hash=None, iban=None, name=None, currency=None)
        assert identity_key_of(account) == "uid:u"


class TestStatusAndAspsps:
    """Tests for the status and the bank list."""

    def test_status_follows_the_provider(self, service: BankConnectionService) -> None:
        assert service.get_status().enabled is True

    def test_lists_banks(self, service: BankConnectionService) -> None:
        result = service.list_aspsps("GR")

        assert result.count == 1
        assert result.data[0].name == "Mock ASPSP"


class TestStart:
    """Tests for starting a connection."""

    def test_records_a_pending_connection_and_returns_the_login_url(
        self, service: BankConnectionService, provider: MagicMock, household_context: HouseholdContext
    ) -> None:
        psu = Psu("203.0.113.9", "Firefox")

        result = service.start(household_context, BankConnectionStart(aspsp_name="Mock ASPSP", aspsp_country="gr"), psu)

        assert result.url == "https://bank.test/login"
        saved = service.connection_repository.save.call_args.args[0]
        assert saved.status == BankConnectionStatus.PENDING
        assert saved.created_by_user_id == household_context.user.id
        kwargs = provider.start_authorization.call_args.kwargs
        assert kwargs["state"] == saved.state
        assert len(saved.state) >= 32
        assert kwargs["redirect_url"] == "http://localhost:5173/settings/bank/callback"
        assert kwargs["psu"] is psu
        service.session.commit.assert_called_once()

    def test_consent_is_capped_by_the_bank(
        self, service: BankConnectionService, provider: MagicMock, household_context: HouseholdContext
    ) -> None:
        service.start(household_context, BankConnectionStart(aspsp_name="Mock ASPSP", aspsp_country="GR"), None)

        valid_until = provider.start_authorization.call_args.kwargs["valid_until"]
        assert valid_until - datetime.datetime.now(datetime.UTC) <= datetime.timedelta(days=90)
        assert valid_until - datetime.datetime.now(datetime.UTC) > datetime.timedelta(days=89)

    def test_an_unknown_bank_is_refused(
        self, service: BankConnectionService, provider: MagicMock, household_context: HouseholdContext
    ) -> None:
        with pytest.raises(AspspNotFoundError):
            service.start(household_context, BankConnectionStart(aspsp_name="Nope", aspsp_country="GR"), None)

        provider.start_authorization.assert_not_called()

    def test_a_provider_refusal_records_nothing(
        self, service: BankConnectionService, provider: MagicMock, household_context: HouseholdContext
    ) -> None:
        provider.start_authorization.side_effect = BankProviderError("down")

        with pytest.raises(BankProviderError):
            service.start(household_context, BankConnectionStart(aspsp_name="Mock ASPSP", aspsp_country="GR"), None)

        service.connection_repository.save.assert_not_called()


class TestComplete:
    """Tests for completing a connection."""

    def test_activates_the_connection_and_records_its_accounts(
        self, service: BankConnectionService, provider: MagicMock, household_context: HouseholdContext
    ) -> None:
        connection = make_connection(household_context)
        service.connection_repository.lock_by_state.return_value = connection
        valid_until = NOW + datetime.timedelta(days=180)
        provider.create_session.return_value = BankSession(
            session_id="sess-1",
            valid_until=valid_until,
            accounts=[SessionAccount(uid="uid-1", identification_hash="h1", iban="GR16", name="Main", currency="EUR")],
        )

        service.complete(household_context, BankConnectionComplete(code="c", state="state-1"))

        assert connection.status == BankConnectionStatus.ACTIVE
        assert connection.session_id == "sess-1"
        assert connection.valid_until == valid_until
        assert connection.next_auto_sync_at is not None
        assert connection.next_auto_sync_at > NOW + datetime.timedelta(hours=23)
        recorded = service.bank_account_repository.save.call_args.args[0]
        assert recorded.identity_key == "h1"
        assert recorded.connection_id == connection.id
        assert recorded.name == "Main"
        service.session.commit.assert_called_once()

    def test_completing_twice_returns_the_first_result(
        self, service: BankConnectionService, provider: MagicMock, household_context: HouseholdContext
    ) -> None:
        connection = make_connection(household_context, status=BankConnectionStatus.ACTIVE, session_id="s")
        service.connection_repository.lock_by_state.return_value = connection

        result = service.complete(household_context, BankConnectionComplete(code="c", state="state-1"))

        assert result.id == connection.id
        provider.create_session.assert_not_called()

    def test_an_unknown_state_is_refused(
        self, service: BankConnectionService, household_context: HouseholdContext
    ) -> None:
        service.connection_repository.lock_by_state.return_value = None

        with pytest.raises(BankAuthorizationError, match="not started here"):
            service.complete(household_context, BankConnectionComplete(code="c", state="x"))

    def test_someone_elses_state_is_refused(
        self, service: BankConnectionService, provider: MagicMock, household_context: HouseholdContext
    ) -> None:
        connection = make_connection(household_context, created_by_user_id=uuid.uuid4())
        service.connection_repository.lock_by_state.return_value = connection

        with pytest.raises(BankAuthorizationError, match="not started here"):
            service.complete(household_context, BankConnectionComplete(code="c", state="state-1"))

        provider.create_session.assert_not_called()

    def test_a_used_state_is_refused(self, service: BankConnectionService, household_context: HouseholdContext) -> None:
        service.connection_repository.lock_by_state.return_value = make_connection(
            household_context, status=BankConnectionStatus.FAILED
        )

        with pytest.raises(BankAuthorizationError, match="already used"):
            service.complete(household_context, BankConnectionComplete(code="c", state="state-1"))

    def test_a_late_return_fails_the_connection(
        self, service: BankConnectionService, provider: MagicMock, household_context: HouseholdContext
    ) -> None:
        connection = make_connection(household_context, created_at=NOW - datetime.timedelta(hours=2))
        service.connection_repository.lock_by_state.return_value = connection

        with pytest.raises(BankAuthorizationError, match="too long"):
            service.complete(household_context, BankConnectionComplete(code="c", state="state-1"))

        assert connection.status == BankConnectionStatus.FAILED
        provider.create_session.assert_not_called()

    def test_a_refused_code_fails_the_connection(
        self, service: BankConnectionService, provider: MagicMock, household_context: HouseholdContext
    ) -> None:
        connection = make_connection(household_context)
        service.connection_repository.lock_by_state.return_value = connection
        provider.create_session.side_effect = BankAuthorizationError("wrong code")

        with pytest.raises(BankAuthorizationError):
            service.complete(household_context, BankConnectionComplete(code="c", state="state-1"))

        assert connection.status == BankConnectionStatus.FAILED

    def test_a_known_account_moves_over_and_its_old_connection_retires(
        self, service: BankConnectionService, provider: MagicMock, household_context: HouseholdContext
    ) -> None:
        connection = make_connection(household_context)
        old_connection = make_connection(household_context, status=BankConnectionStatus.EXPIRED, state=None)
        known = make_bank_account(connection_id=old_connection.id, account_id=uuid.uuid4(), provider_account_uid="old")
        service.connection_repository.lock_by_state.return_value = connection
        service.connection_repository.get_for_household.return_value = old_connection
        service.bank_account_repository.get_by_identity.return_value = known
        provider.create_session.return_value = BankSession(
            session_id="sess-2",
            valid_until=None,
            accounts=[SessionAccount(uid="new", identification_hash="hash-1", iban=None, name="Main", currency="EUR")],
        )

        service.complete(household_context, BankConnectionComplete(code="c", state="state-1"))

        assert known.connection_id == connection.id
        assert known.provider_account_uid == "new"
        assert known.account_id is not None
        assert old_connection.status == BankConnectionStatus.REVOKED


class TestListConnections:
    """Tests for listing connections."""

    def test_groups_accounts_under_their_connections(
        self, service: BankConnectionService, household_context: HouseholdContext
    ) -> None:
        first = make_connection(household_context, status=BankConnectionStatus.ACTIVE, created_at=NOW)
        second = make_connection(household_context, status=BankConnectionStatus.EXPIRED, created_at=NOW)
        service.connection_repository.list_for_household.return_value = [first, second]
        service.bank_account_repository.list_for_connections.return_value = [
            make_bank_account(connection_id=first.id, name="A"),
            make_bank_account(connection_id=first.id, name="B", identity_key="hash-2"),
        ]

        result = service.list_connections(household_context)

        assert result.count == 2
        assert [a.name for a in result.data[0].accounts] == ["A", "B"]
        assert result.data[1].accounts == []


class TestUpdateBankAccount:
    """Tests for linking a bank account."""

    def test_links_and_defaults_the_import_date(
        self, service: BankConnectionService, household_context: HouseholdContext
    ) -> None:
        bank_account = make_bank_account(last_booked_on=datetime.date(2026, 1, 1))
        account = make_account()
        service.bank_account_repository.get_for_household.return_value = bank_account
        service.account_repository.get_for_household.return_value = account

        result = service.update_bank_account(
            household_context, bank_account.id, BankAccountUpdate(account_id=account.id)
        )

        assert result.account_id == account.id
        assert bank_account.last_booked_on is None
        assert bank_account.import_from == datetime.date.today() - datetime.timedelta(days=30)

    def test_default_import_date_is_not_before_the_opening_balance(
        self, service: BankConnectionService, household_context: HouseholdContext
    ) -> None:
        bank_account = make_bank_account()
        opened = datetime.date.today() - datetime.timedelta(days=3)
        account = make_account(opening_balance_date=opened)
        service.bank_account_repository.get_for_household.return_value = bank_account
        service.account_repository.get_for_household.return_value = account

        service.update_bank_account(household_context, bank_account.id, BankAccountUpdate(account_id=account.id))

        assert bank_account.import_from == opened

    def test_null_unlinks(self, service: BankConnectionService, household_context: HouseholdContext) -> None:
        bank_account = make_bank_account(account_id=uuid.uuid4(), import_from=datetime.date(2026, 1, 1))
        service.bank_account_repository.get_for_household.return_value = bank_account

        service.update_bank_account(household_context, bank_account.id, BankAccountUpdate(account_id=None))

        assert bank_account.account_id is None
        assert bank_account.import_from is None

    def test_leaving_account_id_out_keeps_the_link(
        self, service: BankConnectionService, household_context: HouseholdContext
    ) -> None:
        linked = uuid.uuid4()
        bank_account = make_bank_account(account_id=linked)
        service.bank_account_repository.get_for_household.return_value = bank_account

        service.update_bank_account(household_context, bank_account.id, BankAccountUpdate(sync_enabled=False))

        assert bank_account.account_id == linked
        assert bank_account.sync_enabled is False

    def test_an_explicit_import_date_is_checked_and_kept(
        self, service: BankConnectionService, household_context: HouseholdContext
    ) -> None:
        bank_account = make_bank_account()
        account = make_account()
        service.bank_account_repository.get_for_household.return_value = bank_account
        service.account_repository.get_for_household.return_value = account

        service.update_bank_account(
            household_context,
            bank_account.id,
            BankAccountUpdate(account_id=account.id, import_from=datetime.date(2025, 6, 1)),
        )

        assert bank_account.import_from == datetime.date(2025, 6, 1)

    @pytest.mark.parametrize(
        ("import_from", "message"),
        [
            (datetime.date(2023, 12, 31), "opening balance"),
            (datetime.date.today() + datetime.timedelta(days=1), "future"),
        ],
    )
    def test_an_import_date_outside_the_account_is_refused(
        self,
        service: BankConnectionService,
        household_context: HouseholdContext,
        import_from: datetime.date,
        message: str,
    ) -> None:
        account = make_account()
        bank_account = make_bank_account(account_id=account.id)
        service.bank_account_repository.get_for_household.return_value = bank_account
        service.account_repository.get_for_household.return_value = account

        with pytest.raises(BankAccountMappingError, match=message):
            service.update_bank_account(household_context, bank_account.id, BankAccountUpdate(import_from=import_from))

    def test_an_import_date_needs_a_link(
        self, service: BankConnectionService, household_context: HouseholdContext
    ) -> None:
        service.bank_account_repository.get_for_household.return_value = make_bank_account()

        with pytest.raises(BankAccountMappingError, match="Link the bank account"):
            service.update_bank_account(
                household_context, uuid.uuid4(), BankAccountUpdate(import_from=datetime.date(2026, 1, 1))
            )

    def test_an_unknown_bank_account_is_refused(
        self, service: BankConnectionService, household_context: HouseholdContext
    ) -> None:
        service.bank_account_repository.get_for_household.return_value = None

        with pytest.raises(BankAccountNotFoundError):
            service.update_bank_account(household_context, uuid.uuid4(), BankAccountUpdate(sync_enabled=True))

    def test_an_unknown_account_is_refused(
        self, service: BankConnectionService, household_context: HouseholdContext
    ) -> None:
        service.bank_account_repository.get_for_household.return_value = make_bank_account()
        service.account_repository.get_for_household.return_value = None

        with pytest.raises(AccountNotFoundError):
            service.update_bank_account(household_context, uuid.uuid4(), BankAccountUpdate(account_id=uuid.uuid4()))

    def test_an_archived_account_is_refused(
        self, service: BankConnectionService, household_context: HouseholdContext
    ) -> None:
        service.bank_account_repository.get_for_household.return_value = make_bank_account()
        service.account_repository.get_for_household.return_value = make_account(archived_at=NOW)

        with pytest.raises(AccountArchivedError):
            service.update_bank_account(household_context, uuid.uuid4(), BankAccountUpdate(account_id=uuid.uuid4()))

    def test_a_different_currency_is_refused(
        self, service: BankConnectionService, household_context: HouseholdContext
    ) -> None:
        service.bank_account_repository.get_for_household.return_value = make_bank_account(currency_code="USD")
        service.account_repository.get_for_household.return_value = make_account()

        with pytest.raises(BankAccountMappingError, match="USD"):
            service.update_bank_account(household_context, uuid.uuid4(), BankAccountUpdate(account_id=uuid.uuid4()))

    def test_an_account_fed_by_another_bank_account_is_refused(
        self, service: BankConnectionService, household_context: HouseholdContext
    ) -> None:
        service.bank_account_repository.get_for_household.return_value = make_bank_account()
        service.account_repository.get_for_household.return_value = make_account()
        service.bank_account_repository.get_by_account.return_value = make_bank_account(identity_key="other")

        with pytest.raises(BankAccountAlreadyMappedError):
            service.update_bank_account(household_context, uuid.uuid4(), BankAccountUpdate(account_id=uuid.uuid4()))


class TestDisconnect:
    """Tests for disconnecting a bank."""

    def test_ends_the_session_and_revokes(
        self, service: BankConnectionService, provider: MagicMock, household_context: HouseholdContext
    ) -> None:
        connection = make_connection(
            household_context, status=BankConnectionStatus.ACTIVE, session_id="sess-1", next_auto_sync_at=NOW
        )
        service.connection_repository.get_for_household.return_value = connection

        service.disconnect(household_context, connection.id)

        provider.delete_session.assert_called_once_with("sess-1")
        assert connection.status == BankConnectionStatus.REVOKED
        assert connection.session_id is None
        assert connection.next_auto_sync_at is None

    def test_a_provider_failure_still_revokes(
        self, service: BankConnectionService, provider: MagicMock, household_context: HouseholdContext
    ) -> None:
        connection = make_connection(household_context, status=BankConnectionStatus.ACTIVE, session_id="sess-1")
        service.connection_repository.get_for_household.return_value = connection
        provider.delete_session.side_effect = BankProviderError("down")

        service.disconnect(household_context, connection.id)

        assert connection.status == BankConnectionStatus.REVOKED

    def test_an_expired_connection_is_revoked_without_calling_the_bank(
        self, service: BankConnectionService, provider: MagicMock, household_context: HouseholdContext
    ) -> None:
        connection = make_connection(household_context, status=BankConnectionStatus.EXPIRED, session_id="sess-1")
        service.connection_repository.get_for_household.return_value = connection

        service.disconnect(household_context, connection.id)

        provider.delete_session.assert_not_called()
        assert connection.status == BankConnectionStatus.REVOKED

    def test_an_owner_may_disconnect_someone_elses_bank(
        self, service: BankConnectionService, household_context: HouseholdContext
    ) -> None:
        connection = make_connection(household_context, status=BankConnectionStatus.ACTIVE, created_by_user_id=None)
        service.connection_repository.get_for_household.return_value = connection

        service.disconnect(household_context, connection.id)

        assert connection.status == BankConnectionStatus.REVOKED

    def test_a_member_may_not_disconnect_someone_elses_bank(self, service: BankConnectionService) -> None:
        member = HouseholdContext(
            user=User(email="m@example.com", hashed_password="x"),
            household_id=HOUSEHOLD_ID,
            membership_id=uuid.uuid4(),
            role=HouseholdRole.MEMBER,
        )
        connection = make_connection(member, created_by_user_id=uuid.uuid4(), status=BankConnectionStatus.ACTIVE)
        service.connection_repository.get_for_household.return_value = connection

        with pytest.raises(BankConnectionNotPermittedError):
            service.disconnect(member, connection.id)

    @pytest.mark.parametrize("found", [None, BankConnectionStatus.REVOKED])
    def test_a_missing_or_revoked_connection_is_not_found(
        self, service: BankConnectionService, household_context: HouseholdContext, found: BankConnectionStatus | None
    ) -> None:
        service.connection_repository.get_for_household.return_value = (
            None if found is None else make_connection(household_context, status=found)
        )

        with pytest.raises(BankConnectionNotFoundError):
            service.disconnect(household_context, uuid.uuid4())
