import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import BudgetServiceDep, CurrentHousehold
from app.exceptions import (
    BudgetCategoryKindError,
    BudgetExistsError,
    BudgetNotFoundError,
    BudgetOverlapError,
    DuplicateBudgetCategoryError,
    ServiceError,
)
from app.models import (
    BudgetBulkUpsert,
    BudgetCopyRequest,
    BudgetCreate,
    BudgetPublic,
    BudgetsPublic,
    BudgetUpdate,
    Message,
)
from app.models.fields import MONTH_KEY_PATTERN

router = APIRouter(prefix="/budgets", tags=["budgets"])


def budget_exception_mappings() -> dict[type[ServiceError], int]:
    """Map service exceptions to appropriate HTTP status codes.

    Returns:
        A dictionary mapping exception types to HTTP status codes.
    """
    return {
        BudgetNotFoundError: status.HTTP_404_NOT_FOUND,
        BudgetExistsError: status.HTTP_409_CONFLICT,
        BudgetOverlapError: status.HTTP_409_CONFLICT,
        BudgetCategoryKindError: status.HTTP_400_BAD_REQUEST,
        DuplicateBudgetCategoryError: status.HTTP_400_BAD_REQUEST,
    }


@router.post("/", response_model=BudgetPublic)
def create_budget(
    *, budget_service: BudgetServiceDep, household: CurrentHousehold, budget_in: BudgetCreate
) -> BudgetPublic:
    """Set the spending limit of a category for a month.

    A limit on a parent category covers the spending filed under its
    subcategories, so a parent and one of its children cannot both be
    budgeted in the same month.

    Args:
        budget_service: The budget service dependency.
        household: The current household context.
        budget_in: The category, month and limit.

    Returns:
        The created budget.

    Raises:
        HTTPException: If the category does not exist in the household (404),
            the category or an overlapping one is already budgeted that month
            (409), or the category is an income category (400).
    """
    return budget_service.create_budget(household=household, budget_create=budget_in)


@router.get("/", response_model=BudgetsPublic)
def list_budgets(
    *,
    budget_service: BudgetServiceDep,
    household: CurrentHousehold,
    month: str = Query(pattern=MONTH_KEY_PATTERN),
) -> BudgetsPublic:
    """List the budgets of the household for one month.

    Args:
        budget_service: The budget service dependency.
        household: The current household context.
        month: The month, in "YYYY-MM" form.

    Returns:
        The budgets, and the total of the limits.

    Raises:
        HTTPException: If the month is not in "YYYY-MM" form (422).
    """
    return budget_service.list_budgets(household=household, month=month)


# Declared before "/{budget_id}" so these words are not parsed as budget IDs.
@router.put("/bulk", response_model=BudgetsPublic)
def bulk_upsert_budgets(
    *, budget_service: BudgetServiceDep, household: CurrentHousehold, bulk_in: BudgetBulkUpsert
) -> BudgetsPublic:
    """Replace the whole set of budgets for one month.

    This is what a month-at-a-time editing screen saves, so it is one request
    rather than one per category. A category left out of the set has its limit
    removed.

    Args:
        budget_service: The budget service dependency.
        household: The current household context.
        bulk_in: The month and the complete set of limits.

    Returns:
        The budgets now set for that month.

    Raises:
        HTTPException: If a category does not exist in the household (404), the
            set budgets both a parent and its subcategory (409), or it names a
            category twice or an income category (400).
    """
    return budget_service.bulk_upsert(household=household, bulk=bulk_in)


@router.post("/copy", response_model=BudgetsPublic)
def copy_budgets(
    *, budget_service: BudgetServiceDep, household: CurrentHousehold, copy_in: BudgetCopyRequest
) -> BudgetsPublic:
    """Copy the budgets of one month onto another.

    Budgets do not roll over, so this is what makes "same as last month" a
    single action rather than retyping every limit. Overwriting replaces the
    target month with the source: a limit the source does not set is removed.

    Args:
        budget_service: The budget service dependency.
        household: The current household context.
        copy_in: The source month, the target month, and whether to replace
            limits already set on the target.

    Returns:
        The budgets now set for the target month.

    Raises:
        HTTPException: If the target month already has budgets and overwrite was
            not requested (409).
    """
    return budget_service.copy_month(household=household, copy_request=copy_in)


@router.get("/{budget_id}", response_model=BudgetPublic)
def get_budget(*, budget_service: BudgetServiceDep, household: CurrentHousehold, budget_id: uuid.UUID) -> BudgetPublic:
    """Get one budget of the household.

    Args:
        budget_service: The budget service dependency.
        household: The current household context.
        budget_id: The ID of the budget.

    Returns:
        The budget.

    Raises:
        HTTPException: If the budget does not exist in the household (404).
    """
    return budget_service.get_budget(household=household, budget_id=budget_id)


@router.patch("/{budget_id}", response_model=BudgetPublic)
def update_budget(
    *,
    budget_service: BudgetServiceDep,
    household: CurrentHousehold,
    budget_id: uuid.UUID,
    budget_in: BudgetUpdate,
) -> BudgetPublic:
    """Change the limit of a budget.

    The category and month identify the budget, so changing either means
    setting a different budget rather than editing this one.

    Args:
        budget_service: The budget service dependency.
        household: The current household context.
        budget_id: The ID of the budget to change.
        budget_in: The new limit.

    Returns:
        The updated budget.

    Raises:
        HTTPException: If the budget does not exist in the household (404).
    """
    return budget_service.update_budget(household=household, budget_id=budget_id, budget_update=budget_in)


@router.delete("/{budget_id}", response_model=Message)
def delete_budget(*, budget_service: BudgetServiceDep, household: CurrentHousehold, budget_id: uuid.UUID) -> Message:
    """Remove a budget.

    Args:
        budget_service: The budget service dependency.
        household: The current household context.
        budget_id: The ID of the budget to remove.

    Returns:
        A confirmation message.

    Raises:
        HTTPException: If the budget does not exist in the household (404).
    """
    return budget_service.delete_budget(household=household, budget_id=budget_id)
