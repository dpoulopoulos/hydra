import uuid
from typing import Protocol

from sqlmodel import Session

from app.exceptions import (
    HouseholdMemberExistsError,
    HouseholdMemberNotFoundError,
    HouseholdMembershipNotFoundError,
    HouseholdNotFoundError,
    LastHouseholdOwnerError,
)
from app.models import (
    Household,
    HouseholdContext,
    HouseholdMember,
    HouseholdMemberPublic,
    HouseholdMembersPublic,
    HouseholdMemberUpdate,
    HouseholdPublic,
    HouseholdRole,
    HouseholdUpdate,
    Message,
    User,
)
from app.repositories.household import HouseholdMemberRepository, HouseholdRepository


class CategorySeeder(Protocol):
    """The part of the category service that household provisioning depends on.

    Typed as a protocol so this service does not import the category service,
    which would make the two mutually dependent.
    """

    def seed_defaults(self, household_id: uuid.UUID) -> None:
        """Create the default categories of a household, without committing.

        Args:
            household_id: The ID of the household to seed.
        """
        ...


def default_household_name(user: User) -> str:
    """Build the name of the household provisioned for a new user.

    Args:
        user: The user the household is created for.

    Returns:
        A display name based on the user's name, or their email if they have none.
    """
    return f"{user.full_name or user.email}'s household"


class HouseholdService:
    """Provide services for household and membership management."""

    def __init__(
        self,
        session: Session,
        household_repository: HouseholdRepository,
        household_member_repository: HouseholdMemberRepository,
    ) -> None:
        """Initialize the household service.

        Args:
            session: The database session.
            household_repository: The household repository instance.
            household_member_repository: The household member repository instance.
        """
        self.session = session
        self.household_repository = household_repository
        self.household_member_repository = household_member_repository

    def get_context(self, user: User) -> HouseholdContext:
        """Resolve the household scope of a user.

        Args:
            user: The authenticated user.

        Returns:
            The household context of the request.

        Raises:
            HouseholdMembershipNotFoundError: If the user belongs to no household.
        """
        membership = self.household_member_repository.get_by_user_id(user.id)

        if not membership:
            raise HouseholdMembershipNotFoundError from None

        return HouseholdContext(
            user=user,
            household_id=membership.household_id,
            membership_id=membership.id,
            role=membership.role,
        )

    def provision_for_user(
        self,
        user: User,
        name: str | None = None,
        category_service: CategorySeeder | None = None,
    ) -> HouseholdPublic:
        """Create a household for a user and make them its owner.

        Called at signup, so a user always has a household from the moment their
        account exists. That keeps `household_id` non-nullable everywhere and
        spares the frontend an "onboarding required" state.

        Args:
            user: The user to provision a household for.
            name: An optional household name. Defaults to a name based on the user.
            category_service: The category service, used to seed the default
                categories in the same transaction. A household is never
                observable without its categories.

        Returns:
            The created household.

        Raises:
            HouseholdMemberExistsError: If the user already belongs to a household.
        """
        if self.household_member_repository.get_by_user_id(user.id):
            raise HouseholdMemberExistsError(email=user.email) from None

        household = self.create_for_user(user=user, name=name, category_service=category_service)
        self.session.commit()

        return self._to_public(household=household, member_count=1)

    def get_household(self, household: HouseholdContext) -> HouseholdPublic:
        """Get the household of the current request.

        Args:
            household: The household context.

        Returns:
            The household.

        Raises:
            HouseholdNotFoundError: If the household no longer exists.
        """
        return self._to_public(
            household=self._require_household(household),
            member_count=self.household_repository.count_members(household.household_id),
        )

    def update_household(self, household: HouseholdContext, household_update: HouseholdUpdate) -> HouseholdPublic:
        """Rename the household.

        Args:
            household: The household context.
            household_update: The fields to update.

        Returns:
            The updated household.

        Raises:
            HouseholdNotFoundError: If the household no longer exists.
        """
        entity = self._require_household(household)
        entity.sqlmodel_update(household_update.model_dump(exclude_unset=True))
        self.household_repository.save(entity)
        self.session.commit()

        return self._to_public(
            household=entity,
            member_count=self.household_repository.count_members(household.household_id),
        )

    def list_members(self, household: HouseholdContext) -> HouseholdMembersPublic:
        """List the members of the household.

        Args:
            household: The household context.

        Returns:
            The members, with the email and name of each.
        """
        rows = self.household_member_repository.list_with_users(household.household_id)
        data = [self._member_to_public(membership=membership, user=user) for membership, user in rows]

        return HouseholdMembersPublic(data=data, count=len(data))

    def update_member(
        self, household: HouseholdContext, user_id: uuid.UUID, member_update: HouseholdMemberUpdate
    ) -> HouseholdMemberPublic:
        """Change the role of a household member.

        Args:
            household: The household context.
            user_id: The ID of the user whose role changes.
            member_update: The new role.

        Returns:
            The updated membership.

        Raises:
            HouseholdMemberNotFoundError: If the user is not a member of the household.
            LastHouseholdOwnerError: If the change would leave the household with no owner.
        """
        membership, user = self._require_member(household=household, user_id=user_id)

        if membership.role is HouseholdRole.OWNER and member_update.role is not HouseholdRole.OWNER:
            self._require_another_owner(household=household)

        membership.role = member_update.role
        self.household_member_repository.save(membership)
        self.session.commit()

        return self._member_to_public(membership=membership, user=user)

    def remove_member(
        self, household: HouseholdContext, user_id: uuid.UUID, category_service: CategorySeeder | None = None
    ) -> Message:
        """Remove a member from the household.

        The removed member keeps their account and is given a fresh, empty
        household, so the "every user has a household" invariant still holds.

        Args:
            household: The household context.
            user_id: The ID of the user to remove.
            category_service: The category service, used to seed the categories
                of the replacement household.

        Returns:
            A confirmation message.

        Raises:
            HouseholdMemberNotFoundError: If the user is not a member of the household.
            LastHouseholdOwnerError: If the removal would leave the household with no owner.
        """
        membership, user = self._require_member(household=household, user_id=user_id)

        if membership.role is HouseholdRole.OWNER:
            self._require_another_owner(household=household)

        self._detach(membership=membership, user=user, category_service=category_service)

        return Message(message="Member removed from the household.")

    def leave_household(self, household: HouseholdContext, category_service: CategorySeeder | None = None) -> Message:
        """Leave the household.

        Args:
            household: The household context.
            category_service: The category service, used to seed the categories
                of the replacement household.

        Returns:
            A confirmation message.

        Raises:
            HouseholdMemberNotFoundError: If the membership no longer exists.
            LastHouseholdOwnerError: If the caller is the household's only owner.
        """
        if household.is_owner:
            self._require_another_owner(household=household)

        membership, user = self._require_member(household=household, user_id=household.user_id)
        self._detach(membership=membership, user=user, category_service=category_service)

        return Message(message="You have left the household.")

    def ensure_every_user_has_a_household(self, category_service: CategorySeeder | None = None) -> int:
        """Provision a household for every user that does not have one.

        Run at startup. Accounts that existed before households did, and any
        account whose provisioning failed part way, are repaired here rather
        than from a migration, so the default categories are seeded by the same
        business logic that seeds them at signup.

        Args:
            category_service: The category service, used to seed the default categories.

        Returns:
            The number of households created.
        """
        users = self.household_member_repository.list_users_without_a_household()

        if not users:
            return 0

        for user in users:
            self.create_for_user(user=user, category_service=category_service)

        self.session.commit()

        return len(users)

    def create_for_user(
        self, user: User, name: str | None = None, category_service: CategorySeeder | None = None
    ) -> Household:
        """Create a household owned by a user, without committing.

        The caller owns the transaction, so signing up can create the user, the
        household and its categories together. A user is therefore never
        observable without a household.

        Args:
            user: The owner of the new household.
            name: An optional household name. Defaults to a name based on the user.
            category_service: The category service, used to seed the default categories.

        Returns:
            The created household.
        """
        household = Household(name=name or default_household_name(user))
        self.household_repository.save(household)

        membership = HouseholdMember(household_id=household.id, user_id=user.id, role=HouseholdRole.OWNER)
        self.household_member_repository.save(membership)

        if category_service:
            category_service.seed_defaults(household_id=household.id)

        return household

    def _detach(self, membership: HouseholdMember, user: User, category_service: CategorySeeder | None) -> None:
        """Remove a membership and provision a replacement household, in one transaction.

        Args:
            membership: The membership to remove.
            user: The user the membership belongs to.
            category_service: The category service, used to seed the default categories.
        """
        self.household_member_repository.delete(membership)
        self.household_member_repository.flush()
        self.create_for_user(user=user, category_service=category_service)
        self.session.commit()

    def _require_household(self, household: HouseholdContext) -> Household:
        """Load the household of the current request.

        Args:
            household: The household context.

        Returns:
            The household.

        Raises:
            HouseholdNotFoundError: If the household no longer exists.
        """
        entity = self.household_repository.get_by_id(household.household_id)

        if not entity:
            raise HouseholdNotFoundError from None

        return entity

    def _require_member(self, household: HouseholdContext, user_id: uuid.UUID) -> tuple[HouseholdMember, User]:
        """Load a membership within the household of the current request.

        Args:
            household: The household context.
            user_id: The ID of the user whose membership to load.

        Returns:
            The membership and the user it belongs to.

        Raises:
            HouseholdMemberNotFoundError: If the user is not a member of the household.
        """
        row = self.household_member_repository.get_with_user(household_id=household.household_id, user_id=user_id)

        if not row:
            raise HouseholdMemberNotFoundError from None

        return row

    def _require_another_owner(self, household: HouseholdContext) -> None:
        """Check that the household would still have an owner.

        Args:
            household: The household context.

        Raises:
            LastHouseholdOwnerError: If the household has only one owner.
        """
        if self.household_member_repository.count_by_role(household.household_id, HouseholdRole.OWNER) <= 1:
            raise LastHouseholdOwnerError from None

    def _to_public(self, household: Household, member_count: int) -> HouseholdPublic:
        """Build the public representation of a household.

        Args:
            household: The household.
            member_count: The number of members it has.

        Returns:
            The public household.
        """
        return HouseholdPublic.model_validate(household, update={"member_count": member_count})

    def _member_to_public(self, membership: HouseholdMember, user: User) -> HouseholdMemberPublic:
        """Build the public representation of a membership.

        Args:
            membership: The membership.
            user: The user it belongs to.

        Returns:
            The public membership.
        """
        return HouseholdMemberPublic.model_validate(
            membership, update={"email": user.email, "full_name": user.full_name}
        )
