"""Connecting a bank, and choosing which Hydra account each of its accounts feeds."""

import datetime
import secrets
import uuid
from collections.abc import Sequence

from sqlmodel import Session

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
    AspspPublic,
    AspspsPublic,
    BankAccount,
    BankAccountPublic,
    BankAccountUpdate,
    BankAuthorizationStarted,
    BankConnection,
    BankConnectionComplete,
    BankConnectionPublic,
    BankConnectionsPublic,
    BankConnectionStart,
    BankConnectionStatus,
    BankStatus,
    HouseholdContext,
    HouseholdRole,
    Message,
)
from app.repositories.account import AccountRepository
from app.repositories.bank import BankAccountRepository, BankConnectionRepository
from app.services.enable_banking import BankProvider, BankSession, Psu, SessionAccount

# How far back a newly linked account imports by default. Further back than a
# month is rarely wanted, and a bank may refuse to serve much more than 90
# days without a fresh login.
DEFAULT_IMPORT_DAYS = 30


def identity_key_of(account: SessionAccount) -> str:
    """Work out what recognises a bank account across logins.

    Args:
        account: The account as a session listed it.

    Returns:
        The bank's identification hash, else the IBAN, else the session uid.
        The uid changes with every login, so it is a last resort: an account
        known only by it is found again as a new account on a reconnect.
    """
    if account.identification_hash:
        return account.identification_hash
    if account.iban:
        return f"iban:{account.iban.replace(' ', '').upper()}"
    return f"uid:{account.uid}"


def to_public(connection: BankConnection, accounts: Sequence[BankAccount]) -> BankConnectionPublic:
    """Build the response for a connection.

    Args:
        connection: The connection.
        accounts: The bank accounts it reaches.

    Returns:
        The connection with its accounts.
    """
    return BankConnectionPublic(
        id=connection.id,
        aspsp_name=connection.aspsp_name,
        aspsp_country=connection.aspsp_country,
        status=connection.status,
        valid_until=connection.valid_until,
        authorized_at=connection.authorized_at,
        last_synced_at=connection.last_synced_at,
        last_sync_error=connection.last_sync_error,
        created_by_user_id=connection.created_by_user_id,
        accounts=[BankAccountPublic.model_validate(account, from_attributes=True) for account in accounts],
        created_at=connection.created_at,
    )


class BankConnectionService:
    """Provide services for connecting banks.

    Connecting is two requests with a trip to the bank in between. The first
    records a pending connection with an unguessable state and returns the
    bank's login URL. The bank sends the browser back with a code and that
    state; the second request finds the connection by its state, turns the
    code into a session, and records the accounts the login reached.
    """

    def __init__(
        self,
        session: Session,
        provider: BankProvider,
        connection_repository: BankConnectionRepository,
        bank_account_repository: BankAccountRepository,
        account_repository: AccountRepository,
        redirect_url: str,
        consent_days: int,
        pending_ttl_minutes: int,
        auto_sync_interval_hours: int,
    ) -> None:
        """Initialize the bank connection service.

        Args:
            session: The database session.
            provider: Where bank data comes from.
            connection_repository: The bank connection repository instance.
            bank_account_repository: The bank account repository instance.
            account_repository: The account repository instance.
            redirect_url: Where the bank sends the browser back to.
            consent_days: How long a login is asked to last.
            pending_ttl_minutes: How long the trip to the bank may take.
            auto_sync_interval_hours: How long after connecting the first automatic sync runs.
        """
        self.session = session
        self.provider = provider
        self.connection_repository = connection_repository
        self.bank_account_repository = bank_account_repository
        self.account_repository = account_repository
        self.redirect_url = redirect_url
        self.consent_days = consent_days
        self.pending_ttl = datetime.timedelta(minutes=pending_ttl_minutes)
        self.auto_sync_interval = datetime.timedelta(hours=auto_sync_interval_hours)

    def get_status(self) -> BankStatus:
        """Say whether bank sync is configured.

        Returns:
            The status.
        """
        return BankStatus(enabled=self.provider.is_configured)

    def list_aspsps(self, country: str) -> AspspsPublic:
        """List the banks that can be connected in a country.

        Args:
            country: The ISO 3166 two-letter country code.

        Returns:
            The banks.
        """
        aspsps = [
            AspspPublic(name=aspsp.name, country=aspsp.country, logo=aspsp.logo)
            for aspsp in self.provider.list_aspsps(country)
        ]
        return AspspsPublic(data=aspsps, count=len(aspsps))

    def start(
        self, household: HouseholdContext, start: BankConnectionStart, psu: Psu | None
    ) -> BankAuthorizationStarted:
        """Start connecting a bank.

        Args:
            household: The household context.
            start: The bank to connect.
            psu: The account holder at the browser.

        Returns:
            Where to send the browser to log in.

        Raises:
            AspspNotFoundError: If the bank is not one that can be connected.
        """
        country = start.aspsp_country.upper()
        aspsp = next((a for a in self.provider.list_aspsps(country) if a.name == start.aspsp_name), None)
        if aspsp is None:
            raise AspspNotFoundError(start.aspsp_name, country) from None

        consent = datetime.timedelta(days=self.consent_days)
        if aspsp.maximum_consent_seconds is not None:
            consent = min(consent, datetime.timedelta(seconds=aspsp.maximum_consent_seconds))

        state = secrets.token_urlsafe(32)
        authorization = self.provider.start_authorization(
            aspsp_name=aspsp.name,
            aspsp_country=aspsp.country,
            valid_until=datetime.datetime.now(datetime.UTC) + consent,
            state=state,
            redirect_url=self.redirect_url,
            psu=psu,
        )

        # Recorded only once the provider has accepted the request, so a
        # refusal leaves nothing behind to prune.
        self.connection_repository.save(
            BankConnection(
                household_id=household.household_id,
                created_by_user_id=household.user.id,
                aspsp_name=aspsp.name,
                aspsp_country=aspsp.country,
                state=state,
            )
        )
        self.session.commit()
        return BankAuthorizationStarted(url=authorization.url)

    def complete(self, household: HouseholdContext, complete: BankConnectionComplete) -> BankConnectionPublic:
        """Finish connecting a bank, with what the bank put in the redirect.

        Completing twice with the same state returns the connection the first
        call made. A browser can deliver the same callback twice, and the code
        in it can only be spent once.

        Args:
            household: The household context.
            complete: The code and state from the redirect.

        Returns:
            The connection, with the accounts the login reached.

        Raises:
            BankAuthorizationError: If the state is unknown, belongs to someone
                else, has expired, or the bank refused the code.
        """
        connection = self.connection_repository.lock_by_state(complete.state, household.household_id)
        if connection is None or connection.created_by_user_id != household.user.id:
            raise BankAuthorizationError("this login was not started here. Start again.") from None

        if connection.status == BankConnectionStatus.ACTIVE:
            return self._public(connection, household.household_id)
        if connection.status != BankConnectionStatus.PENDING:
            raise BankAuthorizationError("this login was already used. Start again.") from None

        now = datetime.datetime.now(datetime.UTC)
        if now - connection.created_at > self.pending_ttl:
            self._fail(connection)
            raise BankAuthorizationError("it took too long. Start again.") from None

        try:
            bank_session = self.provider.create_session(complete.code)
        except BankAuthorizationError:
            self._fail(connection)
            raise

        connection.session_id = bank_session.session_id
        connection.valid_until = bank_session.valid_until
        connection.authorized_at = now
        connection.status = BankConnectionStatus.ACTIVE
        connection.next_auto_sync_at = now + self.auto_sync_interval
        self.connection_repository.save(connection)

        self._record_accounts(connection, bank_session)
        self.session.commit()
        return self._public(connection, household.household_id)

    def list_connections(self, household: HouseholdContext) -> BankConnectionsPublic:
        """List the household's bank connections, with their accounts.

        Args:
            household: The household context.

        Returns:
            The active and expired connections.
        """
        connections = self.connection_repository.list_for_household(household.household_id)
        accounts = self.bank_account_repository.list_for_connections(
            [c.id for c in connections], household.household_id
        )
        by_connection: dict[uuid.UUID, list[BankAccount]] = {}
        for account in accounts:
            by_connection.setdefault(account.connection_id, []).append(account)
        data = [to_public(c, by_connection.get(c.id, [])) for c in connections]
        return BankConnectionsPublic(data=data, count=len(data))

    def update_bank_account(
        self, household: HouseholdContext, bank_account_id: uuid.UUID, update: BankAccountUpdate
    ) -> BankAccountPublic:
        """Link a bank account to a Hydra account, unlink it, or change how it imports.

        Args:
            household: The household context.
            bank_account_id: The ID of the bank account.
            update: What to change. Only the fields sent are changed, and an
                `account_id` sent as null unlinks.

        Returns:
            The bank account.

        Raises:
            BankAccountNotFoundError: If the bank account does not exist in the household.
            AccountNotFoundError: If the Hydra account does not exist in the household.
            AccountArchivedError: If the Hydra account is archived.
            BankAccountAlreadyMappedError: If another bank account feeds the Hydra account.
            BankAccountMappingError: If the currencies differ, or the import date is
                before the account's opening balance or in the future.
        """
        bank_account = self.bank_account_repository.get_for_household(bank_account_id, household.household_id)
        if bank_account is None:
            raise BankAccountNotFoundError from None

        fields = update.model_fields_set
        if "account_id" in fields and update.account_id != bank_account.account_id:
            if update.account_id is None:
                bank_account.account_id = None
                bank_account.import_from = None
            else:
                account = self.account_repository.get_for_household(update.account_id, household.household_id)
                if account is None:
                    raise AccountNotFoundError from None
                if account.archived_at is not None:
                    raise AccountArchivedError(name=account.name) from None
                if bank_account.currency_code and bank_account.currency_code != account.currency_code:
                    raise BankAccountMappingError(
                        f"The bank account is in {bank_account.currency_code} and {account.name} is in "
                        f"{account.currency_code}."
                    ) from None
                if self.bank_account_repository.get_by_account(account.id, household.household_id) is not None:
                    raise BankAccountAlreadyMappedError from None
                bank_account.account_id = account.id
                # A different account means a different history. What was
                # imported into the last one says nothing about this one.
                bank_account.last_booked_on = None
                if "import_from" not in fields:
                    today = datetime.date.today()
                    bank_account.import_from = max(
                        account.opening_balance_date, today - datetime.timedelta(days=DEFAULT_IMPORT_DAYS)
                    )

        if "import_from" in fields and update.import_from is not None:
            self._check_import_from(bank_account, update.import_from, household.household_id)
            bank_account.import_from = update.import_from

        if "sync_enabled" in fields and update.sync_enabled is not None:
            bank_account.sync_enabled = update.sync_enabled

        self.bank_account_repository.save(bank_account)
        self.session.commit()
        return BankAccountPublic.model_validate(bank_account, from_attributes=True)

    def disconnect(self, household: HouseholdContext, connection_id: uuid.UUID) -> Message:
        """Disconnect a bank, withdrawing the app's access to it.

        The bank accounts keep their links, so connecting the same bank again
        picks up where this left off.

        Args:
            household: The household context.
            connection_id: The ID of the connection.

        Returns:
            A confirmation message.

        Raises:
            BankConnectionNotFoundError: If the connection does not exist in the household.
            BankConnectionNotPermittedError: If the user neither connected it nor owns the household.
        """
        connection = self.connection_repository.get_for_household(connection_id, household.household_id)
        if connection is None or connection.status == BankConnectionStatus.REVOKED:
            raise BankConnectionNotFoundError from None
        if connection.created_by_user_id != household.user.id and household.role != HouseholdRole.OWNER:
            raise BankConnectionNotPermittedError from None

        if connection.session_id and connection.status == BankConnectionStatus.ACTIVE:
            try:
                self.provider.delete_session(connection.session_id)
            except BankProviderError:
                # Best effort. The session ends at the bank by itself, and the
                # app stops using it either way.
                pass

        connection.status = BankConnectionStatus.REVOKED
        connection.session_id = None
        connection.next_auto_sync_at = None
        self.connection_repository.save(connection)
        self.session.commit()
        return Message(message="Bank disconnected.")

    def _record_accounts(self, connection: BankConnection, bank_session: BankSession) -> None:
        """Record the accounts a login reached, finding the ones seen before.

        A bank account found again moves to this connection, keeping its link
        and its history. A connection left with no accounts by that is retired.

        Args:
            connection: The connection the login completed.
            bank_session: The session and its accounts.
        """
        replaced: set[uuid.UUID] = set()
        for session_account in bank_session.accounts:
            identity_key = identity_key_of(session_account)
            bank_account = self.bank_account_repository.get_by_identity(connection.household_id, identity_key)
            if bank_account is None:
                bank_account = BankAccount(
                    household_id=connection.household_id,
                    connection_id=connection.id,
                    provider_account_uid=session_account.uid,
                    identity_key=identity_key,
                )
            elif bank_account.connection_id != connection.id:
                replaced.add(bank_account.connection_id)
            bank_account.connection_id = connection.id
            bank_account.provider_account_uid = session_account.uid
            bank_account.iban = session_account.iban
            bank_account.name = session_account.name
            bank_account.currency_code = session_account.currency
            self.bank_account_repository.save(bank_account)

        if not replaced:
            return
        still_used = {
            account.connection_id
            for account in self.bank_account_repository.list_for_connections(list(replaced), connection.household_id)
        }
        for old_id in replaced - still_used:
            old = self.connection_repository.get_for_household(old_id, connection.household_id)
            if old is not None and old.status != BankConnectionStatus.ACTIVE:
                old.status = BankConnectionStatus.REVOKED
                old.next_auto_sync_at = None
                self.connection_repository.save(old)

    def _check_import_from(
        self, bank_account: BankAccount, import_from: datetime.date, household_id: uuid.UUID
    ) -> None:
        """Check that an import date fits the Hydra account the bank account feeds.

        Args:
            bank_account: The bank account.
            import_from: The first day to import.
            household_id: The ID of the household.

        Raises:
            BankAccountMappingError: If the bank account is not linked, or the date
                is before the opening balance or in the future.
        """
        if bank_account.account_id is None:
            raise BankAccountMappingError("Link the bank account to an account before choosing a start date.")
        account = self.account_repository.get_for_household(bank_account.account_id, household_id)
        if account is not None and import_from < account.opening_balance_date:
            raise BankAccountMappingError(
                f"Rows before {account.opening_balance_date.isoformat()} are already part of the opening balance."
            )
        if import_from > datetime.date.today():
            raise BankAccountMappingError("The start date cannot be in the future.")

    def _fail(self, connection: BankConnection) -> None:
        """Mark a pending connection as failed, and commit that.

        Args:
            connection: The connection.
        """
        connection.status = BankConnectionStatus.FAILED
        self.connection_repository.save(connection)
        self.session.commit()

    def _public(self, connection: BankConnection, household_id: uuid.UUID) -> BankConnectionPublic:
        """Build the response for one connection, with its accounts.

        Args:
            connection: The connection.
            household_id: The ID of the household.

        Returns:
            The connection with its accounts.
        """
        return to_public(connection, self.bank_account_repository.list_for_connections([connection.id], household_id))
