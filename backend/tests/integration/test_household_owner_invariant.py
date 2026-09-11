"""The "a household always has an owner" invariant, run against real SQL.

The unit suite drives the same paths over a mocked session: it feeds the member
counts in as a ``side_effect`` and asserts on the role of an object the test
built itself, so it pins the order of the calls the service makes rather than
what a database answers. The queries the invariant rests on -- the ``NOT IN``
over a subquery behind ``list_ownerless_household_ids``, the ordering behind
``get_longest_standing``, the counts, and the ``SELECT ... FOR UPDATE`` that
serialises two members leaving at once -- are never executed by it.

These tests seed households in Postgres and take the members out through the
services, so a mistyped column, an ordering that picks the wrong successor or a
lock that is not taken shows up as a failing assertion rather than as a passing
mock.
"""

import datetime
import uuid

import pytest
from sqlmodel import Session, select

from app.exceptions import LastHouseholdOwnerError
from app.models import (
    Account,
    Household,
    HouseholdContext,
    HouseholdMember,
    HouseholdRole,
    Transaction,
    TransactionKind,
    User,
)
from app.services import CategoryService, HouseholdService, UserService
from tests.integration.conftest import make_account

# The seniority the successor is picked by. Written explicitly rather than left
# to the column default, which would give every membership of a test the same
# timestamp to the microsecond and make the ordering a coin toss.
JOINED_FIRST = datetime.datetime(2024, 1, 1, 9, 0, tzinfo=datetime.UTC)
JOINED_SECOND = datetime.datetime(2024, 6, 1, 9, 0, tzinfo=datetime.UTC)


def add_member(
    session: Session,
    household_id: uuid.UUID,
    email: str,
    joined_at: datetime.datetime,
    role: HouseholdRole = HouseholdRole.MEMBER,
) -> tuple[User, HouseholdMember]:
    """Seed another member of a household, bypassing the invitation flow.

    Args:
        session: The database session.
        household_id: The household to join.
        email: The email address of the user to create.
        joined_at: When the membership was made, which is what seniority is
            read from.
        role: The role the member holds.

    Returns:
        The stored user and their membership.
    """
    user = User(email=email, full_name=email, hashed_password="not-a-real-hash", is_active=True)
    session.add(user)
    session.flush()

    membership = HouseholdMember(household_id=household_id, user_id=user.id, role=role, created_at=joined_at)
    session.add(membership)
    session.flush()

    return user, membership


def role_of(session: Session, user_id: uuid.UUID) -> HouseholdRole | None:
    """Read back the role a user holds, without going through the service.

    Args:
        session: The database session.
        user_id: The ID of the user.

    Returns:
        The role stored against their membership, or None if they have none.
    """
    membership = session.exec(select(HouseholdMember).where(HouseholdMember.user_id == user_id)).first()
    return membership.role if membership else None


class TestDeletingTheLastOwner:
    """A household that loses its last owner gets another one."""

    def test_deleting_the_sole_owner_promotes_the_longest_standing_member(
        self,
        db_session: Session,
        user_service: UserService,
        household_service: HouseholdService,
        household_a: HouseholdContext,
    ) -> None:
        """The successor is the member who joined first, not whoever comes back."""
        senior, _ = add_member(db_session, household_a.household_id, "senior@example.com", JOINED_FIRST)
        junior, _ = add_member(db_session, household_a.household_id, "junior@example.com", JOINED_SECOND)

        user_service.delete_user(user_id=household_a.user_id, household_service=household_service)

        assert role_of(db_session, senior.id) is HouseholdRole.OWNER
        assert role_of(db_session, junior.id) is HouseholdRole.MEMBER
        assert db_session.get(Household, household_a.household_id) is not None

    def test_deleting_a_member_leaves_the_owner_alone(
        self,
        db_session: Session,
        user_service: UserService,
        household_service: HouseholdService,
        household_a: HouseholdContext,
    ) -> None:
        """A household that still has its owner is not touched on the way out."""
        member, _ = add_member(db_session, household_a.household_id, "member@example.com", JOINED_FIRST)

        user_service.delete_user(user_id=member.id, household_service=household_service)

        assert role_of(db_session, household_a.user_id) is HouseholdRole.OWNER
        assert db_session.get(Household, household_a.household_id) is not None

    def test_the_only_owner_cannot_leave_the_household(
        self,
        db_session: Session,
        household_service: HouseholdService,
        category_service: CategoryService,
        household_a: HouseholdContext,
    ) -> None:
        """The owner-only routes stay reachable: the last owner is refused the door.

        The count this rests on is a ``COUNT`` filtered on the role column, and
        the household has a second member here, so a count that forgot the
        filter would let the owner out and strand the household.
        """
        add_member(db_session, household_a.household_id, "member@example.com", JOINED_FIRST)

        with pytest.raises(LastHouseholdOwnerError):
            household_service.leave_household(household=household_a, category_service=category_service)

        assert role_of(db_session, household_a.user_id) is HouseholdRole.OWNER

    def test_an_owner_can_leave_once_there_is_a_second_one(
        self,
        db_session: Session,
        household_service: HouseholdService,
        category_service: CategoryService,
        household_a: HouseholdContext,
    ) -> None:
        """With two owners the same count lets the first of them go."""
        add_member(db_session, household_a.household_id, "co-owner@example.com", JOINED_FIRST, HouseholdRole.OWNER)

        household_service.leave_household(household=household_a, category_service=category_service)

        assert db_session.exec(
            select(HouseholdMember).where(HouseholdMember.household_id == household_a.household_id)
        ).one()


class TestDeletingTheLastMember:
    """A household nobody is left in goes, and takes its ledger with it."""

    def test_deleting_the_last_member_deletes_the_household(
        self,
        db_session: Session,
        user_service: UserService,
        household_service: HouseholdService,
        household_a: HouseholdContext,
    ) -> None:
        """Nothing could reach the household again, so it does not survive."""
        user_service.delete_user(user_id=household_a.user_id, household_service=household_service)

        assert db_session.get(Household, household_a.household_id) is None

    def test_deleting_the_last_member_cascades_the_ledger(
        self,
        db_session: Session,
        user_service: UserService,
        household_service: HouseholdService,
        household_a: HouseholdContext,
    ) -> None:
        """The financial rows are keyed on the household, so they go with it.

        The service deletes the household row and nothing else: what happens to
        the account and the transaction hanging off it is decided by the
        ``ON DELETE`` clauses, which only a database can answer.
        """
        account = make_account(db_session, household_id=household_a.household_id)
        db_session.add(
            Transaction(
                household_id=household_a.household_id,
                account_id=account.id,
                kind=TransactionKind.EXPENSE,
                amount_minor=1_500,
                occurred_on=datetime.date(2024, 3, 1),
            )
        )
        db_session.flush()

        user_service.delete_user(user_id=household_a.user_id, household_service=household_service)

        remaining_accounts = db_session.exec(
            select(Account).where(Account.household_id == household_a.household_id)
        ).all()
        remaining_transactions = db_session.exec(
            select(Transaction).where(Transaction.household_id == household_a.household_id)
        ).all()
        assert remaining_accounts == []
        assert remaining_transactions == []

    def test_the_household_of_another_member_is_left_standing(
        self,
        db_session: Session,
        user_service: UserService,
        household_service: HouseholdService,
        household_a: HouseholdContext,
        household_b: HouseholdContext,
    ) -> None:
        """Only the emptied household goes: the delete is not a table sweep."""
        foreign_account = make_account(db_session, household_id=household_b.household_id)

        user_service.delete_user(user_id=household_a.user_id, household_service=household_service)

        assert db_session.get(Household, household_b.household_id) is not None
        assert db_session.get(Account, foreign_account.id) is not None
