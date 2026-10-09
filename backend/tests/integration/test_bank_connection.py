"""Connecting a bank against a real database, with the bank itself faked."""

import datetime
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session

from app.exceptions import BankAuthorizationError
from app.models import (
    BankAccountUpdate,
    BankConnectionComplete,
    BankConnectionStart,
    BankConnectionStatus,
    HouseholdContext,
)
from app.repositories import (
    AccountRepository,
    BankAccountRepository,
    BankConnectionRepository,
    BankTransactionRepository,
)
from app.services import BankConnectionService
from app.services.enable_banking import Aspsp, Authorization, BankSession, SessionAccount
from tests.integration.conftest import make_account


@pytest.fixture
def provider() -> MagicMock:
    provider = MagicMock()
    provider.list_aspsps.return_value = [
        Aspsp(name="Mock ASPSP", country="GR", logo=None, maximum_consent_seconds=None)
    ]
    provider.start_authorization.return_value = Authorization(url="https://bank.test/login", authorization_id="a")
    return provider


@pytest.fixture
def service(db_session: Session, provider: MagicMock) -> BankConnectionService:
    return BankConnectionService(
        session=db_session,
        provider=provider,
        connection_repository=BankConnectionRepository(db_session),
        bank_account_repository=BankAccountRepository(db_session),
        account_repository=AccountRepository(db_session),
        bank_transaction_repository=BankTransactionRepository(db_session),
        redirect_url="http://localhost:5173/settings/bank/callback",
        consent_days=180,
        pending_ttl_minutes=60,
        auto_sync_interval_hours=24,
    )


def connect(
    service: BankConnectionService,
    provider: MagicMock,
    household: HouseholdContext,
    session_id: str,
    uid: str,
    iban: str = "GR16",
) -> str:
    """Start and complete a login, returning the state it used."""
    service.start(household, BankConnectionStart(aspsp_name="Mock ASPSP", aspsp_country="GR"), None)
    state: str = provider.start_authorization.call_args.kwargs["state"]
    provider.create_session.return_value = BankSession(
        session_id=session_id,
        valid_until=datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=180),
        accounts=[SessionAccount(uid=uid, identification_hash="hash-1", iban=iban, name="Main", currency="EUR")],
    )
    service.complete(household, BankConnectionComplete(code="code", state=state))
    return state


def test_connect_then_link_then_list(
    db_session: Session, service: BankConnectionService, provider: MagicMock, household_a: HouseholdContext
) -> None:
    """Test the whole path: start, complete, link the account, and see it listed."""
    account = make_account(db_session, household_a.household_id)

    connect(service, provider, household_a, "sess-1", "uid-1")
    listed = service.list_connections(household_a)

    assert listed.count == 1
    connection = listed.data[0]
    assert connection.status == BankConnectionStatus.ACTIVE
    bank_account = connection.accounts[0]
    service.update_bank_account(household_a, bank_account.id, BankAccountUpdate(account_id=account.id))

    relisted = service.list_connections(household_a)
    assert relisted.data[0].accounts[0].account_id == account.id


def test_linking_stores_the_banks_iban_on_the_account(
    db_session: Session, service: BankConnectionService, provider: MagicMock, household_a: HouseholdContext
) -> None:
    """Test that an account with no IBAN keeps the bank's once linked."""
    account = make_account(db_session, household_a.household_id)
    connect(service, provider, household_a, "sess-1", "uid-1", iban="GR1601101250000000012300695")
    bank_account = service.list_connections(household_a).data[0].accounts[0]

    service.update_bank_account(household_a, bank_account.id, BankAccountUpdate(account_id=account.id))

    db_session.expire_all()
    stored = AccountRepository(db_session).get_for_household(account.id, household_a.household_id)
    assert stored is not None
    assert stored.iban == "GR1601101250000000012300695"


def test_completing_twice_spends_the_code_once(
    service: BankConnectionService, provider: MagicMock, household_a: HouseholdContext
) -> None:
    """Test that a second callback with the same state returns the first connection."""
    state = connect(service, provider, household_a, "sess-1", "uid-1")

    again = service.complete(household_a, BankConnectionComplete(code="code", state=state))

    assert again.status == BankConnectionStatus.ACTIVE
    assert provider.create_session.call_count == 1


def test_another_household_cannot_complete_the_login(
    service: BankConnectionService,
    provider: MagicMock,
    household_a: HouseholdContext,
    household_b: HouseholdContext,
) -> None:
    """Test that a state is only found inside the household that started it."""
    service.start(household_a, BankConnectionStart(aspsp_name="Mock ASPSP", aspsp_country="GR"), None)
    state = provider.start_authorization.call_args.kwargs["state"]

    with pytest.raises(BankAuthorizationError):
        service.complete(household_b, BankConnectionComplete(code="code", state=state))

    provider.create_session.assert_not_called()


def test_reconnecting_keeps_the_link_and_retires_the_old_login(
    db_session: Session, service: BankConnectionService, provider: MagicMock, household_a: HouseholdContext
) -> None:
    """Test that a new login finds the bank account again, with its link."""
    account = make_account(db_session, household_a.household_id)
    connect(service, provider, household_a, "sess-1", "uid-1")
    first = service.list_connections(household_a).data[0]
    service.update_bank_account(household_a, first.accounts[0].id, BankAccountUpdate(account_id=account.id))
    connection_repository = BankConnectionRepository(db_session)
    old = connection_repository.get_for_household(first.id, household_a.household_id)
    assert old is not None
    old.status = BankConnectionStatus.EXPIRED
    db_session.add(old)
    db_session.flush()

    connect(service, provider, household_a, "sess-2", "uid-2")
    listed = service.list_connections(household_a)

    assert listed.count == 1
    assert listed.data[0].id != first.id
    assert listed.data[0].accounts[0].id == first.accounts[0].id
    assert listed.data[0].accounts[0].account_id == account.id
    db_session.refresh(old)
    assert old.status == BankConnectionStatus.REVOKED
