"""What the outbox does against a real Postgres.

The unit suite mocks the session, so no statement it builds is executed: a
value too wide for its column never reaches a server, and a ``DELETE`` is never
matched against real rows. Both are checked here.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from sqlmodel import Session, select

from app.core.config import settings
from app.models import SUBJECT_MAX_LENGTH, EmailOutbox, EmailOutboxStatus
from app.services import EmailOutboxService


class TestSubjectLength:
    """Test a subject longer than the column that holds it."""

    def test_a_subject_longer_than_the_column_is_still_queued(self, db_session: Session) -> None:
        """A household named to the hilt must not fail the invite it belongs to."""
        # Arrange: The subject an invite to a maximum-length household name builds
        subject = f"You have been invited to {'a' * 255} - Hydra"
        assert len(subject) > SUBJECT_MAX_LENGTH

        # Act: Queue the message
        with patch("app.services.email_outbox.send_email"):
            delivered = EmailOutboxService.for_session(db_session).deliver_or_queue(
                email_to="invitee@example.com",
                subject=subject,
                html_content="<p>Test content</p>",
            )

        # Assert: Verify Postgres took the row and it kept the head of the subject
        assert delivered is True
        entry = db_session.exec(select(EmailOutbox).where(EmailOutbox.email_to == "invitee@example.com")).one()
        assert entry.status == EmailOutboxStatus.SENT
        assert entry.subject == subject[:SUBJECT_MAX_LENGTH]


class TestRetention:
    """Test the retention windows against a real server.

    The unit suite mocks the session, so the ``DELETE`` the pruner builds is
    never executed and nothing checks which rows it would actually take.
    """

    def test_prune_removes_only_what_is_past_its_window(self, db_session: Session) -> None:
        """A delivered message goes, a failure is kept longer, and pending mail stays."""
        # Arrange: One row per status, all of them older than the sent window
        aged = datetime.now(UTC) - timedelta(days=settings.EMAIL_OUTBOX_SENT_RETENTION_DAYS + 1)
        for status in EmailOutboxStatus:
            db_session.add(
                EmailOutbox(
                    email_to=f"{status.value}@example.com",
                    subject=status.value,
                    html_content="<p>Body</p>",
                    status=status,
                    created_at=aged,
                )
            )
        db_session.commit()

        # Act: Apply the retention policy
        removed = EmailOutboxService.for_session(db_session).prune_expired()

        # Assert: Verify only the delivered message was dropped
        assert removed == 1
        left = db_session.exec(select(EmailOutbox.status)).all()
        assert set(left) == {EmailOutboxStatus.PENDING, EmailOutboxStatus.FAILED}

    def test_prune_removes_a_failure_once_its_longer_window_passes(self, db_session: Session) -> None:
        """A message that gave up is kept for a while, not forever."""
        # Arrange: A failure older than the window that keeps it
        aged = datetime.now(UTC) - timedelta(days=settings.EMAIL_OUTBOX_FAILED_RETENTION_DAYS + 1)
        db_session.add(
            EmailOutbox(
                email_to="gave-up@example.com",
                subject="Subject",
                html_content="<p>Body</p>",
                status=EmailOutboxStatus.FAILED,
                created_at=aged,
            )
        )
        db_session.commit()

        # Act: Apply the retention policy
        removed = EmailOutboxService.for_session(db_session).prune_expired()

        # Assert: Verify the row is gone
        assert removed == 1
        assert db_session.exec(select(EmailOutbox)).all() == []

    def test_prune_keeps_a_message_that_is_inside_its_window(self, db_session: Session) -> None:
        """Yesterday's send is still there to answer "did that go out?"."""
        # Arrange: A message delivered well inside the retention window
        db_session.add(
            EmailOutbox(
                email_to="recent@example.com",
                subject="Subject",
                html_content="<p>Body</p>",
                status=EmailOutboxStatus.SENT,
            )
        )
        db_session.commit()

        # Act: Apply the retention policy
        removed = EmailOutboxService.for_session(db_session).prune_expired()

        # Assert: Verify nothing was dropped
        assert removed == 0
        assert len(db_session.exec(select(EmailOutbox)).all()) == 1
