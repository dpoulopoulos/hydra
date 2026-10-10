"""The invitations an account is offered in the app, and accepting one by its ID.

The unit suite mocks the session, so the query that picks the invitations out
is never executed. It is what decides that only a pending, unexpired invitation
attributed to the account is offered, and nobody else's.
"""

import datetime
import uuid

from sqlmodel import Session

from app.models import HouseholdContext, HouseholdInvite, HouseholdInviteStatus, HouseholdMember, HouseholdRole
from app.services import HouseholdService


def seed_invite(
    db_session: Session,
    household: HouseholdContext,
    *,
    invited_user_id: uuid.UUID | None,
    status: HouseholdInviteStatus = HouseholdInviteStatus.PENDING,
    expires_in: datetime.timedelta = datetime.timedelta(days=7),
) -> HouseholdInvite:
    """Store one invitation sent from a household.

    Args:
        db_session: The database session.
        household: The household the invitation belongs to.
        invited_user_id: The account it was attributed to, if any.
        status: Where the invitation stands.
        expires_in: How long from now until it expires.

    Returns:
        The stored invitation.
    """
    invite = HouseholdInvite(
        household_id=household.household_id,
        email="owner-b@example.com",
        role=HouseholdRole.MEMBER,
        token=uuid.uuid4().hex,
        status=status,
        expires_at=datetime.datetime.now(datetime.UTC) + expires_in,
        invited_by_user_id=household.user_id,
        invited_user_id=invited_user_id,
    )
    db_session.add(invite)
    db_session.commit()
    return invite


class TestReceivedInvites:
    """Test which invitations an account is offered, and accepting one."""

    def test_offers_only_the_pending_invitations_attributed_to_the_account(
        self,
        db_session: Session,
        household_service: HouseholdService,
        household_a: HouseholdContext,
        household_b: HouseholdContext,
    ) -> None:
        """Unclaimed, expired, used and somebody else's invitations are all left out."""
        # Arrange: One invitation that should be offered, and one of every kind that should not
        offered = seed_invite(db_session, household_a, invited_user_id=household_b.user_id)
        seed_invite(db_session, household_a, invited_user_id=None)
        seed_invite(
            db_session, household_a, invited_user_id=household_b.user_id, expires_in=datetime.timedelta(hours=-1)
        )
        seed_invite(db_session, household_a, invited_user_id=household_b.user_id, status=HouseholdInviteStatus.REVOKED)
        seed_invite(db_session, household_a, invited_user_id=household_a.user_id)

        # Act: List what the account is offered
        received = household_service.list_received_invites(user=household_b.user)

        # Assert: Verify only the one invitation is offered, described for the banner
        assert [invite.id for invite in received.data] == [offered.id]
        assert received.data[0].household_name == "Household A"
        assert received.data[0].invited_by == "owner-a@example.com"

    def test_accepting_by_id_moves_the_account_into_the_household(
        self,
        db_session: Session,
        household_service: HouseholdService,
        household_a: HouseholdContext,
        household_b: HouseholdContext,
    ) -> None:
        """The empty household it signed up with is left behind."""
        # Arrange: An invitation attributed to the owner of the other household
        invite = seed_invite(db_session, household_a, invited_user_id=household_b.user_id)

        # Act: Accept it by its ID
        joined = household_service.accept_received_invite(user=household_b.user, invite_id=invite.id)

        # Assert: Verify the account now belongs to the inviting household, and the invite is used
        assert joined.id == household_a.household_id
        membership = db_session.get(HouseholdMember, household_b.membership_id)
        assert membership is None
        db_session.refresh(invite)
        assert invite.status is HouseholdInviteStatus.ACCEPTED
        assert household_service.list_received_invites(user=household_b.user).count == 0
