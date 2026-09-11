import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CategoryServiceDep, CurrentHousehold
from app.exceptions import (
    CategoryDepthExceededError,
    CategoryExistsError,
    CategoryInUseError,
    CategoryKindMismatchError,
    CategoryLimitReachedError,
    CategoryNotFoundError,
    CategorySelfParentError,
    ServiceError,
    SystemCategoryError,
)
from app.models import (
    CategoriesPublic,
    CategoryCreate,
    CategoryKind,
    CategoryPublic,
    CategoryTreePublic,
    CategoryUpdate,
    Message,
)

router = APIRouter(prefix="/categories", tags=["categories"])


def category_exception_mappings() -> dict[type[ServiceError], int]:
    """Map service exceptions to appropriate HTTP status codes.

    Returns:
        A dictionary mapping exception types to HTTP status codes.
    """
    return {
        CategoryNotFoundError: status.HTTP_404_NOT_FOUND,
        CategoryExistsError: status.HTTP_409_CONFLICT,
        CategoryInUseError: status.HTTP_409_CONFLICT,
        CategoryLimitReachedError: status.HTTP_409_CONFLICT,
        CategoryDepthExceededError: status.HTTP_400_BAD_REQUEST,
        CategorySelfParentError: status.HTTP_400_BAD_REQUEST,
        CategoryKindMismatchError: status.HTTP_400_BAD_REQUEST,
        SystemCategoryError: status.HTTP_400_BAD_REQUEST,
    }


@router.post("/", response_model=CategoryPublic)
def create_category(
    *, category_service: CategoryServiceDep, household: CurrentHousehold, category_in: CategoryCreate
) -> CategoryPublic:
    """Create a category or subcategory.

    Args:
        category_service: The category service dependency.
        household: The current household context.
        category_in: The category to create.

    Returns:
        The created category.

    Raises:
        HTTPException: If a sibling already has that name or the household is at
            its category limit (409), or the parent is missing (404) or invalid
            (400).
    """
    return category_service.create_category(household=household, category_create=category_in)


@router.get("/", response_model=CategoriesPublic)
def list_categories(
    *,
    category_service: CategoryServiceDep,
    household: CurrentHousehold,
    include_archived: bool = Query(default=False),
    kind: CategoryKind | None = Query(default=None),
    parent_id: uuid.UUID | None = Query(default=None),
) -> CategoriesPublic:
    """List the categories of the household as a flat list.

    Args:
        category_service: The category service dependency.
        household: The current household context.
        include_archived: Whether to include archived categories.
        kind: An optional kind to filter on.
        parent_id: An optional parent to filter on.

    Returns:
        The categories.

    Raises:
        HTTPException: If the user belongs to no household, or the parent
            filter names a category outside it (404).
    """
    return category_service.list_categories(
        household=household, include_archived=include_archived, kind=kind, parent_id=parent_id
    )


# Declared before "/{category_id}" so "tree" is not parsed as a category ID.
@router.get("/tree", response_model=CategoryTreePublic)
def get_category_tree(
    *,
    category_service: CategoryServiceDep,
    household: CurrentHousehold,
    include_archived: bool = Query(default=False),
    kind: CategoryKind | None = Query(default=None),
) -> CategoryTreePublic:
    """Get the categories of the household as a two level tree.

    Args:
        category_service: The category service dependency.
        household: The current household context.
        include_archived: Whether to include archived categories.
        kind: An optional kind to filter on.

    Returns:
        The top level categories, each with its subcategories.

    Raises:
        HTTPException: If the user belongs to no household (404).
    """
    return category_service.get_category_tree(household=household, include_archived=include_archived, kind=kind)


@router.get("/{category_id}", response_model=CategoryPublic)
def get_category(
    *, category_service: CategoryServiceDep, household: CurrentHousehold, category_id: uuid.UUID
) -> CategoryPublic:
    """Get one category of the household.

    Args:
        category_service: The category service dependency.
        household: The current household context.
        category_id: The ID of the category.

    Returns:
        The category.

    Raises:
        HTTPException: If the category does not exist in the household (404).
    """
    return category_service.get_category(household=household, category_id=category_id)


@router.patch("/{category_id}", response_model=CategoryPublic)
def update_category(
    *,
    category_service: CategoryServiceDep,
    household: CurrentHousehold,
    category_id: uuid.UUID,
    category_in: CategoryUpdate,
) -> CategoryPublic:
    """Rename, re-parent, archive or restore a category.

    Archiving a top level category also archives its subcategories, and
    restoring it restores the ones that archive took down. A subcategory
    archived on its own is left alone by both.

    Args:
        category_service: The category service dependency.
        household: The current household context.
        category_id: The ID of the category to update.
        category_in: The fields to update.

    Returns:
        The updated category.

    Raises:
        HTTPException: If the category or the new parent does not exist in the
            household (404), a sibling already has the new name (409), or the
            change is not allowed (400).
    """
    return category_service.update_category(household=household, category_id=category_id, category_update=category_in)


@router.delete("/{category_id}", response_model=Message)
def delete_category(
    *, category_service: CategoryServiceDep, household: CurrentHousehold, category_id: uuid.UUID
) -> Message:
    """Delete a category that nothing references.

    Args:
        category_service: The category service dependency.
        household: The current household context.
        category_id: The ID of the category to delete.

    Returns:
        A confirmation message.

    Raises:
        HTTPException: If the category does not exist in the household (404), it
            still has subcategories (409), or it is built in (400).
    """
    return category_service.delete_category(household=household, category_id=category_id)
