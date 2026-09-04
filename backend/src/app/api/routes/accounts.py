import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import AccountServiceDep, CurrentHousehold
from app.exceptions import (
    AccountArchivedError,
    AccountExistsError,
    AccountInUseError,
    AccountNotFoundError,
    ServiceError,
)
from app.models import (
    AccountCreate,
    AccountPublic,
    AccountsPublic,
    AccountType,
    AccountUpdate,
    Message,
)

router = APIRouter(prefix="/accounts", tags=["accounts"])


def account_exception_mappings() -> dict[type[ServiceError], int]:
    """Map service exceptions to appropriate HTTP status codes.

    Returns:
        A dictionary mapping exception types to HTTP status codes.
    """
    return {
        AccountNotFoundError: status.HTTP_404_NOT_FOUND,
        AccountExistsError: status.HTTP_409_CONFLICT,
        AccountInUseError: status.HTTP_409_CONFLICT,
        AccountArchivedError: status.HTTP_400_BAD_REQUEST,
    }


@router.post("/", response_model=AccountPublic)
def create_account(
    *, account_service: AccountServiceDep, household: CurrentHousehold, account_in: AccountCreate
) -> AccountPublic:
    """Create an account.

    Args:
        account_service: The account service dependency.
        household: The current household context.
        account_in: The account to create, with the balance it already held.

    Returns:
        The created account.

    Raises:
        HTTPException: If the household already has an account with that name
            (409), or the household no longer exists (404).
    """
    return account_service.create_account(household=household, account_create=account_in)


@router.get("/", response_model=AccountsPublic)
def list_accounts(
    *,
    account_service: AccountServiceDep,
    household: CurrentHousehold,
    include_archived: bool = Query(default=False),
    account_type: AccountType | None = Query(default=None, alias="type"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> AccountsPublic:
    """List the accounts of the household with their balances.

    Args:
        account_service: The account service dependency.
        household: The current household context.
        include_archived: Whether to include archived accounts.
        account_type: An optional type to filter on.
        skip: Number of records to skip.
        limit: Maximum number of records to return.

    Returns:
        The accounts, and the total of the balances returned.

    Raises:
        HTTPException: If the user belongs to no household (404).
    """
    return account_service.list_accounts(
        household=household,
        include_archived=include_archived,
        account_type=account_type,
        skip=skip,
        limit=limit,
    )


@router.get("/{account_id}", response_model=AccountPublic)
def get_account(
    *, account_service: AccountServiceDep, household: CurrentHousehold, account_id: uuid.UUID
) -> AccountPublic:
    """Get one account of the household with its balance.

    Args:
        account_service: The account service dependency.
        household: The current household context.
        account_id: The ID of the account.

    Returns:
        The account.

    Raises:
        HTTPException: If the account does not exist in the household (404).
    """
    return account_service.get_account(household=household, account_id=account_id)


@router.patch("/{account_id}", response_model=AccountPublic)
def update_account(
    *,
    account_service: AccountServiceDep,
    household: CurrentHousehold,
    account_id: uuid.UUID,
    account_in: AccountUpdate,
) -> AccountPublic:
    """Rename, re-type, archive or restore an account.

    The opening balance cannot be changed, since that would rewrite every
    historical balance. Record an adjustment transaction instead.

    Args:
        account_service: The account service dependency.
        household: The current household context.
        account_id: The ID of the account to update.
        account_in: The fields to update.

    Returns:
        The updated account.

    Raises:
        HTTPException: If the account does not exist in the household (404), or
            the household already has an account with the new name (409).
    """
    return account_service.update_account(household=household, account_id=account_id, account_update=account_in)


@router.delete("/{account_id}", response_model=Message)
def delete_account(
    *, account_service: AccountServiceDep, household: CurrentHousehold, account_id: uuid.UUID
) -> Message:
    """Delete an account that has no history.

    Args:
        account_service: The account service dependency.
        household: The current household context.
        account_id: The ID of the account to delete.

    Returns:
        A confirmation message.

    Raises:
        HTTPException: If the account does not exist in the household (404), or
            it still has transactions (409).
    """
    return account_service.delete_account(household=household, account_id=account_id)
