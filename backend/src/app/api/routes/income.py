import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import (
    CurrentHousehold,
    IncomeClientFiltersDep,
    IncomeServiceDep,
    IncomeSessionFiltersDep,
)
from app.exceptions import (
    AccountArchivedError,
    AccountNotFoundError,
    CategoryNotFoundError,
    ClientCadenceError,
    IncomeClientInUseError,
    IncomeClientNotFoundError,
    IncomeClientNotOwnedError,
    IncomeSessionNotFoundError,
    IncomeVaultNotFoundError,
    ServiceError,
    SessionPaymentDateError,
    TransactionCategoryKindError,
)
from app.models import (
    IncomeClientCreate,
    IncomeClientPublic,
    IncomeClientsPublic,
    IncomeClientUpdate,
    IncomeForecast,
    IncomeSessionCreate,
    IncomeSessionPublic,
    IncomeSessionsPublic,
    IncomeSessionUpdate,
    IncomeSummary,
    IncomeVaultPublic,
    IncomeVaultUpsert,
    Message,
)
from app.models.fields import MONTH_KEY_PATTERN
from app.services.income_forecast import DEFAULT_HISTORY_MONTHS, MAX_HISTORY_MONTHS, MIN_HISTORY_MONTHS

router = APIRouter(prefix="/income", tags=["income"])


def income_exception_mappings() -> dict[type[ServiceError], int]:
    """Map service exceptions to appropriate HTTP status codes.

    Returns:
        A dictionary mapping exception types to HTTP status codes.
    """
    return {
        IncomeClientNotFoundError: status.HTTP_404_NOT_FOUND,
        IncomeSessionNotFoundError: status.HTTP_404_NOT_FOUND,
        IncomeVaultNotFoundError: status.HTTP_404_NOT_FOUND,
        IncomeClientInUseError: status.HTTP_409_CONFLICT,
        # Not a 404: everyone in the household can see the row, and its
        # figures are shared money. It is the name that is private.
        IncomeClientNotOwnedError: status.HTTP_403_FORBIDDEN,
        SessionPaymentDateError: status.HTTP_422_UNPROCESSABLE_ENTITY,
        ClientCadenceError: status.HTTP_422_UNPROCESSABLE_ENTITY,
        # Raised from this router too, because a client points at an account and
        # a category, so the same failures reach it by a different road.
        AccountNotFoundError: status.HTTP_404_NOT_FOUND,
        AccountArchivedError: status.HTTP_400_BAD_REQUEST,
        CategoryNotFoundError: status.HTTP_404_NOT_FOUND,
        TransactionCategoryKindError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    }


@router.get("/vault", response_model=IncomeVaultPublic)
def get_vault(*, income_service: IncomeServiceDep, household: CurrentHousehold) -> IncomeVaultPublic:
    """Get the key material the browser needs to unlock your client names.

    Everything returned is opaque to the server. The PIN that turns it into a
    key never leaves the browser, so this endpoint hands back a locked box and
    the instructions for its lock, and nothing else.

    The key is yours, not the household's. Another member has their own, and it
    opens their own clients.

    Args:
        income_service: The income service dependency.
        household: The current household context.

    Returns:
        The vault, or a 404 when no PIN has been set up yet.
    """
    return income_service.get_vault(household=household)


@router.put("/vault", response_model=IncomeVaultPublic)
def upsert_vault(
    *, income_service: IncomeServiceDep, household: CurrentHousehold, vault_in: IncomeVaultUpsert
) -> IncomeVaultPublic:
    """Set up the PIN, or change it.

    Changing a PIN re-wraps the same key and touches no client row: the names
    were never encrypted with the PIN itself.

    Args:
        income_service: The income service dependency.
        household: The current household context.
        vault_in: The key material.

    Returns:
        The stored vault.
    """
    return income_service.upsert_vault(household=household, vault_upsert=vault_in)


@router.delete("/vault")
def reset_vault(
    *,
    income_service: IncomeServiceDep,
    household: CurrentHousehold,
    confirm: bool = Query(default=False, description="Must be true. Every client name is lost."),
) -> Message:
    """Forget your key, and with it your own client names.

    For the PIN nobody can remember. The names become unreadable ciphertext the
    moment the key is gone, so they are cleared rather than left behind as
    rubbish no future PIN could decode. Every fee, session and euro survives,
    and another member's names are untouched.

    The confirmation flag is required because this cannot be undone.

    Args:
        income_service: The income service dependency.
        household: The current household context.
        confirm: Must be true, as an explicit acknowledgement.

    Returns:
        A confirmation message.
    """
    if not confirm:
        return Message(message="Nothing was reset. Send confirm=true to lose every client name.")

    return income_service.reset_vault(household=household)


@router.post("/clients", response_model=IncomeClientPublic)
def create_client(
    *, income_service: IncomeServiceDep, household: CurrentHousehold, client_in: IncomeClientCreate
) -> IncomeClientPublic:
    """Add a client.

    The name arrives encrypted under your key and is stored as it came. Other
    members of the household will see the row and its figures with the name
    blanked out.

    A client can carry how often you see them — every week, every other week,
    once a month — pinned to the date it started, which is what makes "every
    Monday" expressible. Leave it out for somebody seen as and when.

    Args:
        income_service: The income service dependency.
        household: The current household context.
        client_in: The client to add.

    Returns:
        The added client.
    """
    return income_service.create_client(household=household, client_create=client_in)


@router.get("/clients", response_model=IncomeClientsPublic)
def list_clients(
    *, income_service: IncomeServiceDep, household: CurrentHousehold, filters: IncomeClientFiltersDep
) -> IncomeClientsPublic:
    """List the clients of the household.

    There is no search by name and there cannot be one: the server holds
    ciphertext. The page filters and sorts after decrypting.

    Args:
        income_service: The income service dependency.
        household: The current household context.
        filters: The filters to apply.

    Returns:
        The matching clients.
    """
    return income_service.list_clients(household=household, filters=filters)


@router.get("/clients/{client_id}", response_model=IncomeClientPublic)
def get_client(
    *, income_service: IncomeServiceDep, household: CurrentHousehold, client_id: uuid.UUID
) -> IncomeClientPublic:
    """Get one client.

    Args:
        income_service: The income service dependency.
        household: The current household context.
        client_id: The ID of the client.

    Returns:
        The client.
    """
    return income_service.get_client(household=household, client_id=client_id)


@router.patch("/clients/{client_id}", response_model=IncomeClientPublic)
def update_client(
    *,
    income_service: IncomeServiceDep,
    household: CurrentHousehold,
    client_id: uuid.UUID,
    client_in: IncomeClientUpdate,
) -> IncomeClientPublic:
    """Edit a client, or archive them.

    Only the person who added them. Their name is under that person's key, so
    saving from anybody else's screen would write over a name they cannot read.

    Args:
        income_service: The income service dependency.
        household: The current household context.
        client_id: The ID of the client to edit.
        client_in: The fields to change.

    Returns:
        The updated client.
    """
    return income_service.update_client(household=household, client_id=client_id, client_update=client_in)


@router.delete("/clients/{client_id}")
def delete_client(*, income_service: IncomeServiceDep, household: CurrentHousehold, client_id: uuid.UUID) -> Message:
    """Delete a client who has no sessions.

    A client with sessions is refused. Those sessions record work that was done
    and money that was taken, and tidying a list is not a reason to destroy
    them. Archive instead. Only the person who added the client may do either.

    Args:
        income_service: The income service dependency.
        household: The current household context.
        client_id: The ID of the client to delete.

    Returns:
        A confirmation message.
    """
    return income_service.delete_client(household=household, client_id=client_id)


@router.post("/sessions", response_model=IncomeSessionPublic)
def create_session(
    *, income_service: IncomeServiceDep, household: CurrentHousehold, session_in: IncomeSessionCreate
) -> IncomeSessionPublic:
    """Record a session.

    A session becomes income only once it is paid. Recording one that has
    happened but not been settled leaves the ledger alone and puts the fee in
    what you are owed.

    Args:
        income_service: The income service dependency.
        household: The current household context.
        session_in: The session to record.

    Returns:
        The recorded session.
    """
    return income_service.create_session(household=household, session_create=session_in)


@router.get("/sessions", response_model=IncomeSessionsPublic)
def list_sessions(
    *, income_service: IncomeServiceDep, household: CurrentHousehold, filters: IncomeSessionFiltersDep
) -> IncomeSessionsPublic:
    """List sessions.

    Filtering on `payment_status=pending` is the debtors list.

    Args:
        income_service: The income service dependency.
        household: The current household context.
        filters: The filters to apply.

    Returns:
        The matching sessions, with the totals for the footer.
    """
    return income_service.list_sessions(household=household, filters=filters)


@router.get("/sessions/{session_id}", response_model=IncomeSessionPublic)
def get_session(
    *, income_service: IncomeServiceDep, household: CurrentHousehold, session_id: uuid.UUID
) -> IncomeSessionPublic:
    """Get one session.

    Args:
        income_service: The income service dependency.
        household: The current household context.
        session_id: The ID of the session.

    Returns:
        The session.
    """
    return income_service.get_session(household=household, session_id=session_id)


@router.patch("/sessions/{session_id}", response_model=IncomeSessionPublic)
def update_session(
    *,
    income_service: IncomeServiceDep,
    household: CurrentHousehold,
    session_id: uuid.UUID,
    session_in: IncomeSessionUpdate,
) -> IncomeSessionPublic:
    """Edit a session, including marking it attended, missed, paid or waived.

    Marking a session paid writes the income to the ledger; taking that back
    removes it again. There is no separate status endpoint, because one state
    machine behind one method is one fewer place for the ledger and the diary to
    disagree.

    Args:
        income_service: The income service dependency.
        household: The current household context.
        session_id: The ID of the session to edit.
        session_in: The fields to change.

    Returns:
        The updated session.
    """
    return income_service.update_session(household=household, session_id=session_id, session_update=session_in)


@router.delete("/sessions/{session_id}")
def delete_session(*, income_service: IncomeServiceDep, household: CurrentHousehold, session_id: uuid.UUID) -> Message:
    """Delete a session, and the ledger row it produced.

    Args:
        income_service: The income service dependency.
        household: The current household context.
        session_id: The ID of the session to delete.

    Returns:
        A confirmation message.
    """
    return income_service.delete_session(household=household, session_id=session_id)


@router.get("/summary", response_model=IncomeSummary)
def get_summary(
    *,
    income_service: IncomeServiceDep,
    household: CurrentHousehold,
    month: str | None = Query(default=None, pattern=MONTH_KEY_PATTERN),
) -> IncomeSummary:
    """Get the figures for one month, and what is owed across all of them.

    `earned` is what the month's work was worth, `received` is what arrived and
    is the figure the reports agree with, and what is owed is the difference.
    They are reported apart because a month can be busy and still leave you
    short, and one merged number would hide exactly that.

    Args:
        income_service: The income service dependency.
        household: The current household context.
        month: The month in "YYYY-MM" form. Defaults to the current one.

    Returns:
        The summary.
    """
    return income_service.get_summary(household=household, month=month)


@router.get("/forecast", response_model=IncomeForecast)
def get_forecast(
    *,
    income_service: IncomeServiceDep,
    household: CurrentHousehold,
    month: str | None = Query(default=None, pattern=MONTH_KEY_PATTERN),
    months: int = Query(default=DEFAULT_HISTORY_MONTHS, ge=MIN_HISTORY_MONTHS, le=MAX_HISTORY_MONTHS),
) -> IncomeForecast:
    """Estimate what a month will bring.

    Built from the complete months before it, never from the month in progress.
    The answer is a likely figure with a band around it rather than a single
    number, because a freelance month that lands exactly on its average is the
    exception.

    Args:
        income_service: The income service dependency.
        household: The current household context.
        month: The month to forecast, in "YYYY-MM" form. Defaults to next month.
        months: How many complete months to average over.

    Returns:
        The forecast, its band, and the history behind it.
    """
    return income_service.get_forecast(household=household, month=month, months=months)
