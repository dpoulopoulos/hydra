from datetime import UTC, datetime

from app.models import EmailOutbox, EmailOutboxStatus


class TestEmailOutboxDefaults:
    """Test the defaults a queued email starts with."""

    def test_a_new_row_is_pending_and_due_now(self) -> None:
        """A queued email is picked up by the next dispatch, not held back."""
        # Arrange: Note the time the row is created
        before = datetime.now(UTC)

        # Act: Queue a message the way a caller would
        entry = EmailOutbox(
            email_to="recipient@example.com",
            subject="Test Subject",
            html_content="<p>Test content</p>",
        )

        # Assert: Verify it is waiting to be sent, with no attempt behind it
        assert entry.status == EmailOutboxStatus.PENDING
        assert entry.attempts == 0
        assert entry.last_error is None
        assert entry.sent_at is None
        assert before <= entry.next_attempt_at <= datetime.now(UTC)
