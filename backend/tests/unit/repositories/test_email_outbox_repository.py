from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.models import EmailOutbox
from app.repositories import EmailOutboxRepository


@pytest.fixture
def repository(mock_db_session: MagicMock) -> EmailOutboxRepository:
    """Create an EmailOutboxRepository instance with a mocked session.

    Args:
        mock_db_session: The mock database session.

    Returns:
        An EmailOutboxRepository instance with a mocked session.
    """
    return EmailOutboxRepository(session=mock_db_session)


class TestClaimDue:
    """Test the query that picks up the messages waiting to be sent."""

    def test_claim_due_returns_the_rows(self, repository: EmailOutboxRepository, mock_db_session: MagicMock) -> None:
        """The claimed rows are handed back to the caller."""
        # Arrange: One message is waiting
        entry = EmailOutbox(email_to="recipient@example.com", subject="Subject", html_content="<p>Body</p>")
        mock_db_session.exec.return_value.all.return_value = [entry]

        # Act: Ask for whatever is due
        claimed = repository.claim_due(now=datetime.now(UTC), limit=10)

        # Assert: Verify the waiting message came back
        assert list(claimed) == [entry]

    def test_claim_due_only_takes_pending_rows_that_are_due(
        self, repository: EmailOutboxRepository, mock_db_session: MagicMock
    ) -> None:
        """Sent messages and messages still backing off are left alone."""
        # Act: Ask for whatever is due
        repository.claim_due(now=datetime.now(UTC), limit=10)

        # Assert: Verify both the status and the schedule are in the WHERE clause
        compiled = str(mock_db_session.exec.call_args.args[0])
        assert "emailoutbox.status = " in compiled
        assert "emailoutbox.next_attempt_at <= " in compiled

    def test_claim_due_locks_the_rows_it_takes(
        self, repository: EmailOutboxRepository, mock_db_session: MagicMock
    ) -> None:
        """Two dispatchers running at once must not send the same message twice."""
        # Act: Ask for whatever is due
        repository.claim_due(now=datetime.now(UTC), limit=10)

        # Assert: Verify rows another transaction already holds are skipped.
        # SKIP LOCKED is Postgres syntax, so the statement has to be compiled
        # against that dialect to see it.
        compiled = str(mock_db_session.exec.call_args.args[0].compile(dialect=postgresql.dialect()))
        assert "FOR UPDATE" in compiled
        assert "SKIP LOCKED" in compiled

    def test_claim_due_takes_the_oldest_first_and_no_more_than_the_limit(
        self, repository: EmailOutboxRepository, mock_db_session: MagicMock
    ) -> None:
        """A backlog is drained in order, a batch at a time."""
        # Act: Ask for a small batch
        repository.claim_due(now=datetime.now(UTC), limit=5)

        # Assert: Verify the batch is bounded and ordered by when the row came due
        compiled = str(mock_db_session.exec.call_args.args[0])
        assert "ORDER BY emailoutbox.next_attempt_at" in compiled
        assert "LIMIT" in compiled
