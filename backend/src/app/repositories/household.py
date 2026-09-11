import uuid
from collections.abc import Sequence

from sqlmodel import Session, col, func, select

from app.models import (
    Account,
    Budget,
    Household,
    HouseholdInvite,
    HouseholdInviteStatus,
    HouseholdMember,
    HouseholdRole,
    RecurringRule,
    Transaction,
    User,
)
from app.repositories.base import BaseRepository, HouseholdScopedRepository


class HouseholdRepository(BaseRepository[Household]):
    """Repository for Household database operations."""

    def __init__(self, session: Session) -> None:
        """Initialize the household repository.

        Args:
            session: The database session.
        """
        super().__init__(session, Household)

    def has_financial_data(self, household_id: uuid.UUID) -> bool:
        """Check whether a household holds anything worth keeping.

        Seeded categories do not count: every household starts with those, and
        nobody would miss them. Accounts, transactions, budgets and recurring
        rules do.

        Args:
            household_id: The ID of the household.

        Returns:
            True if the household has any financial records.
        """
        for model in (Account, Transaction, Budget, RecurringRule):
            statement = select(func.count()).select_from(model).where(model.household_id == household_id)

            if self.session.exec(statement).one():
                return True

        return False

    def get_by_id_for_update(self, household_id: uuid.UUID) -> Household | None:
        """Get a household, holding a row lock on it until the transaction ends.

        Membership changes decide what happens to the household by counting
        the members that are left, so two of them going at once have to queue
        up: without the lock each transaction still sees the other member in
        place and neither notices that the household ended up empty.

        Args:
            household_id: The ID of the household.

        Returns:
            The household if it still exists, None otherwise.
        """
        return self.session.get(Household, household_id, with_for_update=True)

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

    def get_user(self, user_id: uuid.UUID) -> User | None:
        """Get a user by ID.

        Used to name the person who sent an invite.

        Args:
            user_id: The ID of the user.

        Returns:
            The user if they still exist, None otherwise.
        """
        return self.session.get(User, user_id)

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

    def get_longest_standing(self, household_id: uuid.UUID) -> HouseholdMember | None:
        """Get the member who has been in a household the longest.

        Used to pick a new owner when the last one leaves: seniority is the
        one ordering the household itself gives us, and it matches who is most
        likely to have set the household up with them.

        Args:
            household_id: The ID of the household.

        Returns:
            The oldest membership if the household has any members, None otherwise.
        """
        statement = (
            select(HouseholdMember)
            .where(HouseholdMember.household_id == household_id)
            .order_by(col(HouseholdMember.created_at))
        )
        return self.session.exec(statement).first()

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

    def list_ownerless_household_ids(self) -> Sequence[uuid.UUID]:
        """List the households that have members but nobody holding OWNER.

        Used by the startup routine to repair households that lost their last
        owner before the promotion existed. Nothing they can do puts an owner
        back, so the rows have to be found and fixed here.

        Returns:
            The IDs of the households with at least one member and no owner.
        """
        owned = select(col(HouseholdMember.household_id)).where(HouseholdMember.role == HouseholdRole.OWNER)
        statement = (
            select(col(HouseholdMember.household_id)).distinct().where(col(HouseholdMember.household_id).not_in(owned))
        )
        return self.session.exec(statement).all()


class HouseholdInviteRepository(HouseholdScopedRepository[HouseholdInvite]):
    """Repository for HouseholdInvite database operations."""

    def __init__(self, session: Session) -> None:
        """Initialize the household invite repository.

        Args:
            session: The database session.
        """
        super().__init__(session, HouseholdInvite)

    def get_by_token(self, token: str) -> HouseholdInvite | None:
        """Get an invite by its token.

        Not scoped to a household: the recipient is not a member yet, so the
        token is the only thing identifying which household they are joining.

        Args:
            token: The invite token.

        Returns:
            The invite if one exists with that token, None otherwise.
        """
        statement = select(HouseholdInvite).where(HouseholdInvite.token == token)
        return self.session.exec(statement).first()

    def list_for_household(
        self,
        household_id: uuid.UUID,
        status: HouseholdInviteStatus | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[HouseholdInvite], int]:
        """List the invites of a household.

        Args:
            household_id: The ID of the household.
            status: An optional status to filter on.
            skip: Number of records to skip.
            limit: Maximum number of records to return.

        Returns:
            Tuple of (invites, total_count), newest first.
        """
        conditions = [] if status is None else [HouseholdInvite.status == status]

        count = self.count_for_household(household_id, *conditions)
        statement = self._paginate(
            select(HouseholdInvite)
            .where(self.household_column == household_id, *conditions)
            .order_by(col(HouseholdInvite.created_at).desc()),
            skip=skip,
            limit=limit,
        )

        return self.session.exec(statement).all(), count

    def list_pending_for_email(self, email: str) -> Sequence[HouseholdInvite]:
        """List every outstanding invite sent to an address.

        Not scoped to a household: the address may have been invited by
        several, and the caller is acting on the address rather than from
        inside a household.

        Args:
            email: The invited address.

        Returns:
            The pending invites sent to that address.
        """
        statement = select(HouseholdInvite).where(
            func.lower(col(HouseholdInvite.email)) == email.lower(),
            HouseholdInvite.status == HouseholdInviteStatus.PENDING,
        )
        return self.session.exec(statement).all()

    def get_pending_for_email(self, household_id: uuid.UUID, email: str) -> HouseholdInvite | None:
        """Get the outstanding invite for an address, if there is one.

        Args:
            household_id: The ID of the household.
            email: The invited address.

        Returns:
            The pending invite if one exists, None otherwise.
        """
        statement = select(HouseholdInvite).where(
            HouseholdInvite.household_id == household_id,
            func.lower(col(HouseholdInvite.email)) == email.lower(),
            HouseholdInvite.status == HouseholdInviteStatus.PENDING,
        )
        return self.session.exec(statement).first()
