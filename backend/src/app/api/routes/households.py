import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentHousehold, HouseholdServiceDep, OwnerHousehold
from app.exceptions import (
    HouseholdMemberExistsError,
    HouseholdMemberNotFoundError,
    HouseholdMembershipNotFoundError,
    HouseholdNotFoundError,
    HouseholdRoleRequiredError,
    LastHouseholdOwnerError,
    ServiceError,
)
from app.models import (
    HouseholdMemberPublic,
    HouseholdMembersPublic,
    HouseholdMemberUpdate,
    HouseholdPublic,
    HouseholdUpdate,
    Message,
)

router = APIRouter(prefix="/households", tags=["households"])


def household_exception_mappings() -> dict[type[ServiceError], int]:
    """Map service exceptions to appropriate HTTP status codes.

    Returns:
        A dictionary mapping exception types to HTTP status codes.
    """
    return {
        HouseholdNotFoundError: status.HTTP_404_NOT_FOUND,
        HouseholdMembershipNotFoundError: status.HTTP_404_NOT_FOUND,
        HouseholdMemberNotFoundError: status.HTTP_404_NOT_FOUND,
        HouseholdMemberExistsError: status.HTTP_409_CONFLICT,
        LastHouseholdOwnerError: status.HTTP_400_BAD_REQUEST,
        HouseholdRoleRequiredError: status.HTTP_403_FORBIDDEN,
    }


@router.get("/me", response_model=HouseholdPublic)
def get_household_me(*, household_service: HouseholdServiceDep, household: CurrentHousehold) -> HouseholdPublic:
    """Get the household of the current user.

    Args:
        household_service: The household service dependency.
        household: The current household context.

    Returns:
        The household, with its member count.

    Raises:
        HTTPException: If the user belongs to no household (404).
    """
    return household_service.get_household(household=household)


@router.patch("/me", response_model=HouseholdPublic)
def update_household_me(
    *, household_service: HouseholdServiceDep, household: OwnerHousehold, household_in: HouseholdUpdate
) -> HouseholdPublic:
    """Rename the household of the current user.

    Args:
        household_service: The household service dependency.
        household: The current household context, which must be owned by the user.
        household_in: The fields to update.

    Returns:
        The updated household.

    Raises:
        HTTPException: If the user is not an owner of the household (403), or the
            household no longer exists (404).
    """
    return household_service.update_household(household=household, household_update=household_in)


@router.get("/me/members", response_model=HouseholdMembersPublic)
def list_household_members(
    *, household_service: HouseholdServiceDep, household: CurrentHousehold
) -> HouseholdMembersPublic:
    """List the members of the household.

    Args:
        household_service: The household service dependency.
        household: The current household context.

    Returns:
        The members of the household.

    Raises:
        HTTPException: If the user belongs to no household (404).
    """
    return household_service.list_members(household=household)


# Declared before the "/me/members/{user_id}" routes: FastAPI matches in
# declaration order, so otherwise "me" would be parsed as a user ID and fail.
@router.delete("/me/members/me", response_model=Message)
def leave_household(*, household_service: HouseholdServiceDep, household: CurrentHousehold) -> Message:
    """Leave the household.

    The caller keeps their account and is given a fresh, empty household.

    Args:
        household_service: The household service dependency.
        household: The current household context.

    Returns:
        A confirmation message.

    Raises:
        HTTPException: If the caller is the household's only owner (400), or the
            membership no longer exists (404).
    """
    return household_service.leave_household(household=household)


@router.patch("/me/members/{user_id}", response_model=HouseholdMemberPublic)
def update_household_member(
    *,
    household_service: HouseholdServiceDep,
    household: OwnerHousehold,
    user_id: uuid.UUID,
    member_in: HouseholdMemberUpdate,
) -> HouseholdMemberPublic:
    """Change the role of a household member.

    Args:
        household_service: The household service dependency.
        household: The current household context, which must be owned by the user.
        user_id: The ID of the user whose role changes.
        member_in: The new role.

    Returns:
        The updated membership.

    Raises:
        HTTPException: If the user is not an owner of the household (403), the
            member is not in the household (404), or the change would leave the
            household with no owner (400).
    """
    return household_service.update_member(household=household, user_id=user_id, member_update=member_in)


@router.delete("/me/members/{user_id}", response_model=Message)
def remove_household_member(
    *, household_service: HouseholdServiceDep, household: OwnerHousehold, user_id: uuid.UUID
) -> Message:
    """Remove a member from the household.

    The removed member keeps their account and is given a fresh, empty household.

    Args:
        household_service: The household service dependency.
        household: The current household context, which must be owned by the user.
        user_id: The ID of the user to remove.

    Returns:
        A confirmation message.

    Raises:
        HTTPException: If the user is not an owner of the household (403), the
            member is not in the household (404), or the removal would leave the
            household with no owner (400).
    """
    return household_service.remove_member(household=household, user_id=user_id)
