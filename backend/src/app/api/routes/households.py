import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import (
    CategoryServiceDep,
    CurrentHousehold,
    CurrentUser,
    HouseholdServiceDep,
    OwnerHousehold,
)
from app.exceptions import (
    HouseholdInviteEmailMismatchError,
    HouseholdInviteExistsError,
    HouseholdInviteExpiredError,
    HouseholdInviteNotFoundError,
    HouseholdInviteUsedError,
    HouseholdMemberExistsError,
    HouseholdMemberNotFoundError,
    HouseholdMembershipNotFoundError,
    HouseholdNotEmptyError,
    HouseholdNotFoundError,
    HouseholdRoleRequiredError,
    LastHouseholdOwnerError,
    ServiceError,
)
from app.models import (
    HouseholdInviteAccept,
    HouseholdInviteCreate,
    HouseholdInvitePreview,
    HouseholdInvitePublic,
    HouseholdInvitesPublic,
    HouseholdInviteStatus,
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
        HouseholdInviteNotFoundError: status.HTTP_404_NOT_FOUND,
        HouseholdInviteExistsError: status.HTTP_409_CONFLICT,
        HouseholdNotEmptyError: status.HTTP_409_CONFLICT,
        HouseholdInviteExpiredError: status.HTTP_400_BAD_REQUEST,
        HouseholdInviteUsedError: status.HTTP_400_BAD_REQUEST,
        LastHouseholdOwnerError: status.HTTP_400_BAD_REQUEST,
        HouseholdRoleRequiredError: status.HTTP_403_FORBIDDEN,
        HouseholdInviteEmailMismatchError: status.HTTP_403_FORBIDDEN,
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
def leave_household(
    *,
    household_service: HouseholdServiceDep,
    category_service: CategoryServiceDep,
    household: CurrentHousehold,
) -> Message:
    """Leave the household.

    The caller keeps their account and is given a fresh, empty household.

    Args:
        household_service: The household service dependency.
        category_service: The category service dependency, used to seed the
            categories of the replacement household.
        household: The current household context.

    Returns:
        A confirmation message.

    Raises:
        HTTPException: If the caller is the household's only owner (400), or the
            membership no longer exists (404).
    """
    return household_service.leave_household(household=household, category_service=category_service)


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
    *,
    household_service: HouseholdServiceDep,
    category_service: CategoryServiceDep,
    household: OwnerHousehold,
    user_id: uuid.UUID,
) -> Message:
    """Remove a member from the household.

    The removed member keeps their account and is given a fresh, empty household.

    Args:
        household_service: The household service dependency.
        category_service: The category service dependency, used to seed the
            categories of the replacement household.
        household: The current household context, which must be owned by the user.
        user_id: The ID of the user to remove.

    Returns:
        A confirmation message.

    Raises:
        HTTPException: If the user is not an owner of the household (403), the
            member is not in the household (404), or the removal would leave the
            household with no owner (400).
    """
    return household_service.remove_member(household=household, user_id=user_id, category_service=category_service)


@router.get("/me/invites", response_model=HouseholdInvitesPublic)
def list_household_invites(
    *,
    household_service: HouseholdServiceDep,
    household: CurrentHousehold,
    invite_status: HouseholdInviteStatus | None = Query(default=None, alias="status"),
) -> HouseholdInvitesPublic:
    """List the invitations sent from this household.

    Args:
        household_service: The household service dependency.
        household: The current household context.
        invite_status: An optional status to filter on.

    Returns:
        The invitations, newest first.

    Raises:
        HTTPException: If the user belongs to no household (404).
    """
    return household_service.list_invites(household=household, status=invite_status)


@router.post("/me/invites", response_model=HouseholdInvitePublic)
def create_household_invite(
    *,
    household_service: HouseholdServiceDep,
    household: OwnerHousehold,
    invite_in: HouseholdInviteCreate,
) -> HouseholdInvitePublic:
    """Invite someone to share the household, and email them a link.

    Args:
        household_service: The household service dependency.
        household: The current household context, which must be owned by the user.
        invite_in: The address to invite and the role to give them.

    Returns:
        The created invitation.

    Raises:
        HTTPException: If the user is not an owner of the household (403), the
            household no longer exists (404), or that address already has an
            invitation or is already a member (409).
    """
    return household_service.create_invite(household=household, invite_create=invite_in)


@router.delete("/me/invites/{invite_id}", response_model=Message)
def revoke_household_invite(
    *, household_service: HouseholdServiceDep, household: OwnerHousehold, invite_id: uuid.UUID
) -> Message:
    """Withdraw an invitation that has not been accepted.

    Args:
        household_service: The household service dependency.
        household: The current household context, which must be owned by the user.
        invite_id: The ID of the invitation to withdraw.

    Returns:
        A confirmation message.

    Raises:
        HTTPException: If the user is not an owner of the household (403), the
            invitation does not exist in the household (404), or it was already
            accepted or withdrawn (400).
    """
    return household_service.revoke_invite(household=household, invite_id=invite_id)


# Declared before "/invites/{token}" so "accept" is not read as a token.
@router.post("/invites/accept", response_model=HouseholdPublic)
def accept_household_invite(
    *,
    household_service: HouseholdServiceDep,
    current_user: CurrentUser,
    accept_in: HouseholdInviteAccept,
) -> HouseholdPublic:
    """Accept an invitation and join the household.

    The household created when you signed up is discarded if it is still
    empty. If you have already recorded anything in it, joining is refused
    rather than silently leaving that behind.

    Args:
        household_service: The household service dependency.
        current_user: The current authenticated user.
        accept_in: The invitation token.

    Returns:
        The household you joined.

    Raises:
        HTTPException: If the token is not recognised (404), the invitation was
            sent to a different address (403), it has expired or was already
            used (400), or your current household holds data (409).
    """
    return household_service.accept_invite(user=current_user, token=accept_in.token)


@router.get("/invites/{token}", response_model=HouseholdInvitePreview)
def preview_household_invite(*, household_service: HouseholdServiceDep, token: str) -> HouseholdInvitePreview:
    """Describe an invitation, for the page that offers to accept it.

    Public, because the recipient may not have an account yet. It carries only
    what somebody needs in order to decide, and nothing about the household's
    money.

    Args:
        household_service: The household service dependency.
        token: The invitation token.

    Returns:
        The household name, who invited them, and when it expires.

    Raises:
        HTTPException: If the token is not recognised (404), or the invitation
            has expired or was already used (400).
    """
    return household_service.preview_invite(token=token)
