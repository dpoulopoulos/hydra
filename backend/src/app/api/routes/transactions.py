import uuid

from fastapi import APIRouter, status

from app.api.deps import (
    CurrentHousehold,
    TransactionFiltersDep,
    TransactionServiceDep,
)
from app.exceptions import (
    SameAccountTransferError,
    ServiceError,
    TransactionCategoryKindError,
    TransactionNotFoundError,
    TransferShapeError,
)
from app.models import (
    Message,
    TransactionCreate,
    TransactionPublic,
    TransactionsPublic,
    TransactionUpdate,
)

router = APIRouter(prefix="/transactions", tags=["transactions"])


def transaction_exception_mappings() -> dict[type[ServiceError], int]:
    """Map service exceptions to appropriate HTTP status codes.

    Returns:
        A dictionary mapping exception types to HTTP status codes.
    """
    return {
        TransactionNotFoundError: status.HTTP_404_NOT_FOUND,
        SameAccountTransferError: status.HTTP_400_BAD_REQUEST,
        TransferShapeError: status.HTTP_400_BAD_REQUEST,
        TransactionCategoryKindError: status.HTTP_400_BAD_REQUEST,
    }


@router.post("/", response_model=TransactionPublic)
def create_transaction(
    *,
    transaction_service: TransactionServiceDep,
    household: CurrentHousehold,
    transaction_in: TransactionCreate,
) -> TransactionPublic:
    """Record an expense, some income, or a transfer between accounts.

    A transfer is an ordinary transaction with kind "transfer" and a
    destination account, so it needs no separate endpoint.

    Args:
        transaction_service: The transaction service dependency.
        household: The current household context.
        transaction_in: The transaction to record.

    Returns:
        The recorded transaction.

    Raises:
        HTTPException: If an account or category does not exist in the household
            (404), or the transaction does not match its kind (400).
    """
    return transaction_service.create_transaction(household=household, transaction_create=transaction_in)


@router.get("/", response_model=TransactionsPublic)
def list_transactions(
    *,
    transaction_service: TransactionServiceDep,
    household: CurrentHousehold,
    filters: TransactionFiltersDep,
) -> TransactionsPublic:
    """List the transactions of the household.

    Filtering by a parent category includes the spending filed under its
    subcategories, unless include_subcategories is set to false.

    Args:
        transaction_service: The transaction service dependency.
        household: The current household context.
        filters: The date range, account, category, kind, amount range, search
            text, ordering and paging to apply.

    Returns:
        The matching transactions and the total number of matches.

    Raises:
        HTTPException: If the category filter names a category outside the
            household (404), or a filter is not recognised (422).
    """
    return transaction_service.list_transactions(household=household, filters=filters)


@router.get("/{transaction_id}", response_model=TransactionPublic)
def get_transaction(
    *,
    transaction_service: TransactionServiceDep,
    household: CurrentHousehold,
    transaction_id: uuid.UUID,
) -> TransactionPublic:
    """Get one transaction of the household.

    Args:
        transaction_service: The transaction service dependency.
        household: The current household context.
        transaction_id: The ID of the transaction.

    Returns:
        The transaction.

    Raises:
        HTTPException: If the transaction does not exist in the household (404).
    """
    return transaction_service.get_transaction(household=household, transaction_id=transaction_id)


@router.patch("/{transaction_id}", response_model=TransactionPublic)
def update_transaction(
    *,
    transaction_service: TransactionServiceDep,
    household: CurrentHousehold,
    transaction_id: uuid.UUID,
    transaction_in: TransactionUpdate,
) -> TransactionPublic:
    """Edit a transaction.

    Args:
        transaction_service: The transaction service dependency.
        household: The current household context.
        transaction_id: The ID of the transaction to edit.
        transaction_in: The fields to change.

    Returns:
        The updated transaction.

    Raises:
        HTTPException: If the transaction, an account or a category does not
            exist in the household (404), or the change does not match the kind
            (400).
    """
    return transaction_service.update_transaction(
        household=household, transaction_id=transaction_id, transaction_update=transaction_in
    )


@router.delete("/{transaction_id}", response_model=Message)
def delete_transaction(
    *,
    transaction_service: TransactionServiceDep,
    household: CurrentHousehold,
    transaction_id: uuid.UUID,
) -> Message:
    """Delete a transaction.

    Args:
        transaction_service: The transaction service dependency.
        household: The current household context.
        transaction_id: The ID of the transaction to delete.

    Returns:
        A confirmation message.

    Raises:
        HTTPException: If the transaction does not exist in the household (404).
    """
    return transaction_service.delete_transaction(household=household, transaction_id=transaction_id)
