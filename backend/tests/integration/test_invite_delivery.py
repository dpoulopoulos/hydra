"""What the invite listing says about the mail that carried each invitation.

The unit suite mocks the session, so the outer join between an invitation and
its outbox row is never executed and the ``ON DELETE SET NULL`` behind it never
fires. Both are what decide whether an owner is told the truth about an
invitation that never arrived.
"""

import datetime
import uuid

from sqlmodel import Session

from app.core.config import settings
from app.models import (
    EmailOutbox,
    EmailOutboxStatus,
    HouseholdContext,
    HouseholdInvite,
    HouseholdRole,
)
from app.services import EmailOutboxService, HouseholdService


def seed_invite(
    db_session: Session, household: HouseholdContext, *, email_outbox_id: uuid.UUID | None = None
) -> HouseholdInvite:
    """Store one outstanding invitation, optionally tied to an outbox row.

    Args:
        db_session: The database session.
        household: The household the invitation belongs to.
        email_outbox_id: The message that carried it, if any.

    Returns:
        The stored invitation.
    """
    invite = HouseholdInvite(
        household_id=household.household_id,
        email="invitee@example.com",
        role=HouseholdRole.MEMBER,
        token=uuid.uuid4().hex,
        expires_at=datetime.datetime(2099, 1, 1, tzinfo=datetime.UTC),
        email_outbox_id=email_outbox_id,
    )
    db_session.add(invite)
    db_session.commit()
    return invite


def seed_message(db_session: Session, *, status: EmailOutboxStatus, created_at: datetime.datetime) -> EmailOutbox:
    """Store one outbox row.

    Args:
        db_session: The database session.
        status: What became of the message.
        created_at: When it was written.

    Returns:
        The stored row.
    """
    entry = EmailOutbox(
        email_to="invitee@example.com",
        subject="You have been invited",
        html_content="<p>Body</p>",
        status=status,
        created_at=created_at,
    )
    db_session.add(entry)
    db_session.commit()
    return entry


class TestInviteDeliveryState:
    """Test the delivery state the listing reports per invitation."""

    def test_an_invitation_whose_mail_gave_up_is_reported_as_failed(
        self, db_session: Session, household_service: HouseholdService, household_a: HouseholdContext
    ) -> None:
        """This is the whole point: an owner can see the invite never arrived."""
        # Arrange: An invitation whose message ran out of attempts
        entry = seed_message(
            db_session, status=EmailOutboxStatus.FAILED, created_at=datetime.datetime.now(datetime.UTC)
        )
        seed_invite(db_session, household_a, email_outbox_id=entry.id)

        # Act: List the invitations
        invites = household_service.list_invites(household=household_a)

        # Assert: Verify the failure is reported against the invitation
        assert invites.count == 1
        assert invites.data[0].delivery_status is EmailOutboxStatus.FAILED

    def test_an_invitation_with_no_message_reports_nothing(
        self, db_session: Session, household_service: HouseholdService, household_a: HouseholdContext
    ) -> None:
        """An invitation made with mail off must still appear in the listing."""
        # Arrange: An invitation that carries no outbox row
        seed_invite(db_session, household_a)

        # Act: List the invitations
        invites = household_service.list_invites(household=household_a)

        # Assert: Verify the invitation is listed, with nothing claimed about delivery
        assert invites.count == 1
        assert invites.data[0].delivery_status is None

    def test_pruning_the_message_leaves_the_invitation_alone(
        self, db_session: Session, household_service: HouseholdService, household_a: HouseholdContext
    ) -> None:
        """Retention must not take an invitation with it, or block itself on one."""
        # Arrange: An invitation whose delivered message is past its window
        aged = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            days=settings.EMAIL_OUTBOX_SENT_RETENTION_DAYS + 1
        )
        entry = seed_message(db_session, status=EmailOutboxStatus.SENT, created_at=aged)
        invite = seed_invite(db_session, household_a, email_outbox_id=entry.id)

        # Act: Apply the retention policy, then list the invitations
        removed = EmailOutboxService.for_session(db_session).prune_expired()
        invites = household_service.list_invites(household=household_a)

        # Assert: Verify the message went and the invitation stayed, reporting nothing
        assert removed == 1
        db_session.refresh(invite)
        assert invite.email_outbox_id is None
        assert invites.count == 1
        assert invites.data[0].delivery_status is None
