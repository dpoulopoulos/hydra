"""What the outbox columns accept, verified against a real Postgres.

The unit suite mocks the session, so a value that is too wide for its column is
never sent to a server and the insert that would fail never happens. The subject
of a household invite carries a household name, and a household name is allowed
to fill its own column, so the two together can outgrow ``email_outbox.subject``
and turn a committed invite into a 500.
"""

from unittest.mock import patch

from sqlmodel import Session, select

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
