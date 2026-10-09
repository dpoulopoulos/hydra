import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import BankConnectionServiceDep, CurrentHousehold, PsuDep, SessionUser
from app.exceptions import (
    AspspNotFoundError,
    BankAccountAlreadyMappedError,
    BankAccountMappingError,
    BankAccountNotFoundError,
    BankAuthorizationError,
    BankConnectionInactiveError,
    BankConnectionNotFoundError,
    BankConnectionNotPermittedError,
    BankProviderError,
    BankRateLimitedError,
    BankSessionExpiredError,
    BankSyncNotConfiguredError,
    ServiceError,
)
from app.models import (
    AspspsPublic,
    BankAccountPublic,
    BankAccountUpdate,
    BankAuthorizationStarted,
    BankConnectionComplete,
    BankConnectionPublic,
    BankConnectionsPublic,
    BankConnectionStart,
    BankStatus,
    Message,
)

router = APIRouter(prefix="/bank", tags=["bank"])


def bank_exception_mappings() -> dict[type[ServiceError], int]:
    """Map service exceptions to appropriate HTTP status codes.

    Returns:
        A dictionary mapping exception types to HTTP status codes.
    """
    return {
        BankSyncNotConfiguredError: status.HTTP_503_SERVICE_UNAVAILABLE,
        BankProviderError: status.HTTP_502_BAD_GATEWAY,
        # The connection needs a new login, which is for the user to do: a
        # conflict with the state of the resource, not a gateway failure.
        BankSessionExpiredError: status.HTTP_409_CONFLICT,
        BankRateLimitedError: status.HTTP_429_TOO_MANY_REQUESTS,
        BankAuthorizationError: status.HTTP_400_BAD_REQUEST,
        AspspNotFoundError: status.HTTP_400_BAD_REQUEST,
        BankConnectionNotFoundError: status.HTTP_404_NOT_FOUND,
        BankAccountNotFoundError: status.HTTP_404_NOT_FOUND,
        BankConnectionNotPermittedError: status.HTTP_403_FORBIDDEN,
        BankConnectionInactiveError: status.HTTP_409_CONFLICT,
        BankAccountMappingError: status.HTTP_400_BAD_REQUEST,
        BankAccountAlreadyMappedError: status.HTTP_409_CONFLICT,
    }


@router.get("/status", response_model=BankStatus)
def get_bank_status(*, bank_connection_service: BankConnectionServiceDep, _household: CurrentHousehold) -> BankStatus:
    """Say whether bank sync is configured on this server.

    Args:
        bank_connection_service: The bank connection service dependency.
        _household: The current household context, for authentication.

    Returns:
        Whether bank sync is on.
    """
    return bank_connection_service.get_status()


@router.get("/aspsps", response_model=AspspsPublic)
def list_aspsps(
    *,
    bank_connection_service: BankConnectionServiceDep,
    _household: CurrentHousehold,
    country: str = Query(min_length=2, max_length=2),
) -> AspspsPublic:
    """List the banks that can be connected in a country.

    Args:
        bank_connection_service: The bank connection service dependency.
        _household: The current household context, for authentication.
        country: The ISO 3166 two-letter country code.

    Returns:
        The banks.

    Raises:
        HTTPException: If bank sync is off (503) or the provider failed (502).
    """
    return bank_connection_service.list_aspsps(country)


@router.post("/connections", response_model=BankAuthorizationStarted)
def start_bank_connection(
    *,
    bank_connection_service: BankConnectionServiceDep,
    household: CurrentHousehold,
    _session_user: SessionUser,
    psu: PsuDep,
    start_in: BankConnectionStart,
) -> BankAuthorizationStarted:
    """Start connecting a bank.

    A browser session only: the login happens at the bank, in a browser.

    Args:
        bank_connection_service: The bank connection service dependency.
        household: The current household context.
        _session_user: The signed-in user, from a browser session.
        psu: The account holder at the browser.
        start_in: The bank to connect.

    Returns:
        Where to send the browser to log in.

    Raises:
        HTTPException: If the bank cannot be connected (400), bank sync is off
            (503), or the provider failed (502).
    """
    return bank_connection_service.start(household=household, start=start_in, psu=psu)


@router.post("/connections/complete", response_model=BankConnectionPublic)
def complete_bank_connection(
    *,
    bank_connection_service: BankConnectionServiceDep,
    household: CurrentHousehold,
    _session_user: SessionUser,
    complete_in: BankConnectionComplete,
) -> BankConnectionPublic:
    """Finish connecting a bank, with what the bank put in the redirect.

    Args:
        bank_connection_service: The bank connection service dependency.
        household: The current household context.
        _session_user: The signed-in user, from a browser session.
        complete_in: The code and state from the redirect.

    Returns:
        The connection, with the accounts the login reached.

    Raises:
        HTTPException: If the login cannot be completed (400), bank sync is off
            (503), or the provider failed (502).
    """
    return bank_connection_service.complete(household=household, complete=complete_in)


@router.get("/connections", response_model=BankConnectionsPublic)
def list_bank_connections(
    *, bank_connection_service: BankConnectionServiceDep, household: CurrentHousehold
) -> BankConnectionsPublic:
    """List the household's bank connections, with their accounts.

    Args:
        bank_connection_service: The bank connection service dependency.
        household: The current household context.

    Returns:
        The active and expired connections.
    """
    return bank_connection_service.list_connections(household=household)


@router.delete("/connections/{connection_id}", response_model=Message)
def disconnect_bank(
    *,
    bank_connection_service: BankConnectionServiceDep,
    household: CurrentHousehold,
    _session_user: SessionUser,
    connection_id: uuid.UUID,
) -> Message:
    """Disconnect a bank.

    Args:
        bank_connection_service: The bank connection service dependency.
        household: The current household context.
        _session_user: The signed-in user, from a browser session.
        connection_id: The ID of the connection.

    Returns:
        A confirmation message.

    Raises:
        HTTPException: If the connection does not exist (404), or the user
            neither connected it nor owns the household (403).
    """
    return bank_connection_service.disconnect(household=household, connection_id=connection_id)


@router.patch("/accounts/{bank_account_id}", response_model=BankAccountPublic)
def update_bank_account(
    *,
    bank_connection_service: BankConnectionServiceDep,
    household: CurrentHousehold,
    bank_account_id: uuid.UUID,
    update_in: BankAccountUpdate,
) -> BankAccountPublic:
    """Link a bank account to an account, unlink it, or change how it imports.

    Args:
        bank_connection_service: The bank connection service dependency.
        household: The current household context.
        bank_account_id: The ID of the bank account.
        update_in: What to change. An `account_id` sent as null unlinks.

    Returns:
        The bank account.

    Raises:
        HTTPException: If the bank account or account does not exist (404),
            another bank account feeds the account (409), or the currencies or
            the start date do not fit (400).
    """
    return bank_connection_service.update_bank_account(
        household=household, bank_account_id=bank_account_id, update=update_in
    )
