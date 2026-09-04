import uuid
from collections.abc import Sequence

from sqlmodel import Session, col, func, select

from app.models import Household, HouseholdMember, HouseholdRole, User
from app.repositories.base import BaseRepository


class HouseholdRepository(BaseRepository[Household]):
    """Repository for Household database operations."""

    def __init__(self, session: Session) -> None:
        """Initialize the household repository.

        Args:
            session: The database session.
        """
        super().__init__(session, Household)

    def count_members(self, household_id: uuid.UUID) -> int:
        """Count the members of a household.

        Args:
            household_id: The ID of the household.

        Returns:
            The number of members.
        """
        statement = (
            select(func.count()).select_from(HouseholdMember).where(HouseholdMember.household_id == household_id)
        )
        return self.session.exec(statement).one()


class HouseholdMemberRepository(BaseRepository[HouseholdMember]):
    """Repository for HouseholdMember database operations."""

    def __init__(self, session: Session) -> None:
        """Initialize the household member repository.

        Args:
            session: The database session.
        """
        super().__init__(session, HouseholdMember)

    def get_by_user_id(self, user_id: uuid.UUID) -> HouseholdMember | None:
        """Get the membership of a user.

        A user belongs to at most one household, so there is at most one row.

        Args:
            user_id: The ID of the user.

        Returns:
            The membership if the user belongs to a household, None otherwise.
        """
        statement = select(HouseholdMember).where(HouseholdMember.user_id == user_id)
        return self.session.exec(statement).first()

    def get_with_user(self, household_id: uuid.UUID, user_id: uuid.UUID) -> tuple[HouseholdMember, User] | None:
        """Get a membership within a household together with its user row.

        Joined so the caller does not need a second query for the email and
        name a member response carries.

        Args:
            household_id: The ID of the household.
            user_id: The ID of the user.

        Returns:
            The membership and its user if the user belongs to that household,
            None otherwise.
        """
        statement = (
            select(HouseholdMember, User)
            .join(User, col(HouseholdMember.user_id) == col(User.id))
            .where(HouseholdMember.household_id == household_id, HouseholdMember.user_id == user_id)
        )
        return self.session.exec(statement).first()

    def list_with_users(self, household_id: uuid.UUID) -> Sequence[tuple[HouseholdMember, User]]:
        """List the members of a household together with their user rows.

        Joined in one query so rendering the member list does not fan out into
        one user lookup per member.

        Args:
            household_id: The ID of the household.

        Returns:
            Pairs of membership and user, oldest membership first.
        """
        statement = (
            select(HouseholdMember, User)
            .join(User, col(HouseholdMember.user_id) == col(User.id))
            .where(HouseholdMember.household_id == household_id)
            .order_by(col(HouseholdMember.created_at))
        )
        return self.session.exec(statement).all()

    def count_by_role(self, household_id: uuid.UUID, role: HouseholdRole) -> int:
        """Count the members of a household holding a role.

        Args:
            household_id: The ID of the household.
            role: The role to count.

        Returns:
            The number of members with that role.
        """
        statement = (
            select(func.count())
            .select_from(HouseholdMember)
            .where(HouseholdMember.household_id == household_id, HouseholdMember.role == role)
        )
        return self.session.exec(statement).one()

    def list_users_without_a_household(self) -> Sequence[User]:
        """List the users that do not belong to any household.

        Used by the startup routine to keep the "every user has a household"
        invariant true for accounts that existed before households did.

        Returns:
            The users with no membership row.
        """
        statement = (
            select(User)
            .outerjoin(HouseholdMember, col(HouseholdMember.user_id) == col(User.id))
            .where(col(HouseholdMember.id).is_(None))
        )
        return self.session.exec(statement).all()
