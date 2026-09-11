import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.core.config import settings
from app.models import SUBJECT_MAX_LENGTH, EmailOutbox, EmailOutboxStatus
from app.repositories import EmailOutboxRepository
from app.services import EmailOutboxService


@pytest.fixture
def mock_email_outbox_repository(mock_db_session: MagicMock) -> EmailOutboxRepository:
    """Create an EmailOutboxRepository instance with a mocked session.

    Args:
        mock_db_session: The mock database session.

    Returns:
        An EmailOutboxRepository instance with a mocked session.
    """
    return EmailOutboxRepository(session=mock_db_session)


@pytest.fixture
def mock_email_outbox_service(
    mock_db_session: MagicMock, mock_email_outbox_repository: EmailOutboxRepository
) -> EmailOutboxService:
    """Create an EmailOutboxService instance with a mocked session and repository.

    Args:
        mock_db_session: The mock database session.
        mock_email_outbox_repository: The mock email outbox repository.

    Returns:
        An EmailOutboxService instance with a mocked session and repository.
    """
    return EmailOutboxService(session=mock_db_session, email_outbox_repository=mock_email_outbox_repository)


def rate_limited() -> httpx.HTTPStatusError:
    """Build the error a provider raises when it is rate limiting us.

    Returns:
        An HTTP 429 error as httpx reports it.
    """
    request = httpx.Request("POST", "https://api.resend.com/emails")
    return httpx.HTTPStatusError("429", request=request, response=httpx.Response(429))


class TestDeliverOrQueue:
    """Test handing a message to the provider from inside a request."""

    def test_a_delivered_message_is_recorded_as_sent(
        self, mock_email_outbox_service: EmailOutboxService, mock_db_session: MagicMock
    ) -> None:
        """The provider accepted the message, so nothing is left to retry."""
        # Act: Send a message while the provider is healthy
        with patch("app.services.email_outbox.send_email") as mock_send_email:
            delivered = mock_email_outbox_service.deliver_or_queue(
                email_to="recipient@example.com",
                subject="Test Subject",
                html_content="<p>Test content</p>",
            )

        # Assert: Verify the message went out and the row records that it did
        assert delivered is True
        mock_send_email.assert_called_once_with(
            email_to="recipient@example.com",
            subject="Test Subject",
            html_content="<p>Test content</p>",
        )
        entry = mock_db_session.add.call_args.args[0]
        assert entry.status == EmailOutboxStatus.SENT
        assert entry.attempts == 1
        assert entry.sent_at is not None

    def test_an_undelivered_message_is_left_for_a_retry(
        self,
        mock_email_outbox_service: EmailOutboxService,
        mock_db_session: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A provider outage delays the message instead of losing it."""
        # Arrange: The provider is rate limiting us
        error = rate_limited()

        # Act: Send a message
        with patch("app.services.email_outbox.send_email", side_effect=error):
            with caplog.at_level(logging.WARNING, logger="app.services.email_outbox"):
                delivered = mock_email_outbox_service.deliver_or_queue(
                    email_to="recipient@example.com",
                    subject="Test Subject",
                    html_content="<p>Test content</p>",
                )

        # Assert: Verify the caller is told, and the row is still owed to someone
        assert delivered is False
        entry = mock_db_session.add.call_args.args[0]
        assert entry.status == EmailOutboxStatus.PENDING
        assert entry.attempts == 1
        assert entry.next_attempt_at > datetime.now(UTC)
        assert entry.last_error
        assert "recipient@example.com" in caplog.text

    def test_the_message_is_committed_before_it_is_attempted(
        self, mock_email_outbox_service: EmailOutboxService, mock_db_session: MagicMock
    ) -> None:
        """A process that dies during the send still leaves the message behind."""
        # Arrange: Record whether the row was committed by the time we send
        committed_before_send = False

        def record(**_: str) -> None:
            nonlocal committed_before_send
            committed_before_send = mock_db_session.commit.called

        # Act: Send a message
        with patch("app.services.email_outbox.send_email", side_effect=record):
            mock_email_outbox_service.deliver_or_queue(
                email_to="recipient@example.com",
                subject="Test Subject",
                html_content="<p>Test content</p>",
            )

        # Assert: Verify the queued row was durable before the provider was called
        assert committed_before_send

    def test_an_unexpected_error_does_not_reach_the_caller(
        self,
        mock_email_outbox_service: EmailOutboxService,
        mock_db_session: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The write that asked for the mail is committed: it must not 500."""
        # Arrange: The message breaks our own code rather than the provider's
        poison = UnicodeEncodeError("utf-8", "x", 0, 1, "bad content")

        # Act: Send a message
        with patch("app.services.email_outbox.send_email", side_effect=poison):
            with caplog.at_level(logging.ERROR, logger="app.services.email_outbox"):
                delivered = mock_email_outbox_service.deliver_or_queue(
                    email_to="recipient@example.com",
                    subject="Test Subject",
                    html_content="<p>Test content</p>",
                )

        # Assert: Verify the caller is told, and the row is left for the dispatcher
        assert delivered is False
        entry = mock_db_session.add.call_args.args[0]
        assert entry.status == EmailOutboxStatus.PENDING
        assert entry.attempts == 1
        assert entry.next_attempt_at > datetime.now(UTC)
        assert "recipient@example.com" in caplog.text
        assert "UnicodeEncodeError" in caplog.text

    def test_a_long_subject_is_trimmed_to_fit_the_column(
        self, mock_email_outbox_service: EmailOutboxService, mock_db_session: MagicMock
    ) -> None:
        """A household named to the hilt must not fail the invite it belongs to."""
        # Arrange: A subject longer than the column holds
        subject = "You have been invited to " + "a" * SUBJECT_MAX_LENGTH

        # Act: Send a message
        with patch("app.services.email_outbox.send_email") as mock_send_email:
            delivered = mock_email_outbox_service.deliver_or_queue(
                email_to="recipient@example.com",
                subject=subject,
                html_content="<p>Test content</p>",
            )

        # Assert: Verify the row fits the column and the subject kept its head
        assert delivered is True
        entry = mock_db_session.add.call_args.args[0]
        assert len(entry.subject) == SUBJECT_MAX_LENGTH
        assert entry.subject == subject[:SUBJECT_MAX_LENGTH]
        assert mock_send_email.call_args.kwargs["subject"] == subject[:SUBJECT_MAX_LENGTH]


class TestDispatchDue:
    """Test draining the messages that are waiting to be sent."""

    def test_dispatch_due_sends_the_claimed_messages(
        self, mock_email_outbox_service: EmailOutboxService, mock_db_session: MagicMock
    ) -> None:
        """Whatever is due is handed to the provider and marked as sent."""
        # Arrange: One message has been waiting since a failed attempt
        entry = EmailOutbox(
            email_to="recipient@example.com",
            subject="Test Subject",
            html_content="<p>Test content</p>",
            attempts=1,
        )
        mock_db_session.exec.return_value.all.side_effect = [[entry], []]

        # Act: Drain the outbox
        with patch("app.services.email_outbox.send_email") as mock_send_email:
            delivered = mock_email_outbox_service.dispatch_due()

        # Assert: Verify the message left and the row was closed out
        assert delivered == 1
        mock_send_email.assert_called_once_with(
            email_to="recipient@example.com",
            subject="Test Subject",
            html_content="<p>Test content</p>",
        )
        assert entry.status == EmailOutboxStatus.SENT
        assert entry.attempts == 2
        mock_db_session.commit.assert_called()

    def test_dispatch_due_does_nothing_when_the_outbox_is_empty(
        self, mock_email_outbox_service: EmailOutboxService, mock_db_session: MagicMock
    ) -> None:
        """An idle dispatcher talks to neither the provider nor the transaction."""
        # Arrange: Nothing is waiting
        mock_db_session.exec.return_value.all.return_value = []

        # Act: Drain the outbox
        with patch("app.services.email_outbox.send_email") as mock_send_email:
            delivered = mock_email_outbox_service.dispatch_due()

        # Assert: Verify the round did nothing at all
        assert delivered == 0
        mock_send_email.assert_not_called()
        mock_db_session.commit.assert_not_called()

    def test_each_failure_waits_longer_than_the_one_before(
        self, mock_email_outbox_service: EmailOutboxService, mock_db_session: MagicMock
    ) -> None:
        """Backoff keeps a struggling provider from being hammered."""
        # Arrange: A message that has already failed twice fails again
        entry = EmailOutbox(
            email_to="recipient@example.com",
            subject="Test Subject",
            html_content="<p>Test content</p>",
            attempts=2,
        )
        mock_db_session.exec.return_value.all.side_effect = [[entry], []]
        before = datetime.now(UTC)

        # Act: Drain the outbox
        with patch("app.services.email_outbox.send_email", side_effect=rate_limited()):
            delivered = mock_email_outbox_service.dispatch_due()

        # Assert: Verify the third attempt waits four times the base delay
        assert delivered == 0
        assert entry.status == EmailOutboxStatus.PENDING
        expected = before + timedelta(seconds=settings.EMAIL_OUTBOX_RETRY_BASE_SECONDS * 4)
        assert entry.next_attempt_at >= expected

    def test_the_backoff_is_capped(
        self, mock_email_outbox_service: EmailOutboxService, mock_db_session: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A long backlog does not push the next attempt days into the future."""
        # Arrange: Allow enough attempts for the doubling to run past the cap
        monkeypatch.setattr(settings, "EMAIL_OUTBOX_MAX_ATTEMPTS", 30)
        entry = EmailOutbox(
            email_to="recipient@example.com",
            subject="Test Subject",
            html_content="<p>Test content</p>",
            attempts=20,
        )
        mock_db_session.exec.return_value.all.side_effect = [[entry], []]
        before = datetime.now(UTC)

        # Act: Drain the outbox
        with patch("app.services.email_outbox.send_email", side_effect=rate_limited()):
            mock_email_outbox_service.dispatch_due()

        # Assert: Verify the wait stops growing at the configured ceiling
        assert entry.next_attempt_at <= before + timedelta(seconds=settings.EMAIL_OUTBOX_RETRY_MAX_SECONDS + 1)

    def test_a_message_is_given_up_on_after_the_last_attempt(
        self,
        mock_email_outbox_service: EmailOutboxService,
        mock_db_session: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A permanently undeliverable message stops being retried, loudly."""
        # Arrange: The message has one attempt left, and it fails
        entry = EmailOutbox(
            email_to="recipient@example.com",
            subject="Test Subject",
            html_content="<p>Test content</p>",
            attempts=settings.EMAIL_OUTBOX_MAX_ATTEMPTS - 1,
        )
        mock_db_session.exec.return_value.all.side_effect = [[entry], []]

        # Act: Drain the outbox
        with patch("app.services.email_outbox.send_email", side_effect=rate_limited()):
            with caplog.at_level(logging.ERROR, logger="app.services.email_outbox"):
                mock_email_outbox_service.dispatch_due()

        # Assert: Verify the row is closed as failed and says so in the log
        assert entry.status == EmailOutboxStatus.FAILED
        assert entry.attempts == settings.EMAIL_OUTBOX_MAX_ATTEMPTS
        assert "recipient@example.com" in caplog.text

    def test_dispatch_due_asks_for_the_messages_that_are_due_now(
        self, mock_email_outbox_service: EmailOutboxService, mock_db_session: MagicMock
    ) -> None:
        """Rows that have come due are claimed one at a time."""
        # Arrange: Watch the claim the service makes
        claim = MagicMock(return_value=[])
        mock_email_outbox_service.email_outbox_repository.claim_due = claim
        before = datetime.now(UTC)

        # Act: Drain the outbox
        mock_email_outbox_service.dispatch_due()

        # Assert: Verify a single currently due row was asked for
        assert claim.call_args.kwargs["limit"] == 1
        assert claim.call_args.kwargs["now"] >= before

    def test_dispatch_due_stops_at_the_batch_size(
        self, mock_email_outbox_service: EmailOutboxService, mock_db_session: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A backlog is drained a batch at a time rather than all at once."""
        # Arrange: More messages are due than a single round may take
        monkeypatch.setattr(settings, "EMAIL_OUTBOX_BATCH_SIZE", 3)

        def a_due_message(**_: object) -> list[EmailOutbox]:
            return [
                EmailOutbox(
                    email_to="recipient@example.com",
                    subject="Test Subject",
                    html_content="<p>Test content</p>",
                )
            ]

        claim = MagicMock(side_effect=a_due_message)
        mock_email_outbox_service.email_outbox_repository.claim_due = claim

        # Act: Drain the outbox
        with patch("app.services.email_outbox.send_email"):
            delivered = mock_email_outbox_service.dispatch_due()

        # Assert: Verify the round stopped at the configured batch size
        assert delivered == 3
        assert claim.call_count == 3

    def test_each_message_is_committed_on_its_own(
        self, mock_email_outbox_service: EmailOutboxService, mock_db_session: MagicMock
    ) -> None:
        """A message the provider took is durable before the next is tried."""
        # Arrange: Two messages are waiting, and record commits as they happen
        entries = [
            EmailOutbox(
                email_to=f"recipient{index}@example.com",
                subject="Test Subject",
                html_content="<p>Test content</p>",
            )
            for index in range(2)
        ]
        claim = MagicMock(side_effect=[[entries[0]], [entries[1]], []])
        mock_email_outbox_service.email_outbox_repository.claim_due = claim
        commits_when_sending = []

        def record(**_: str) -> None:
            commits_when_sending.append(mock_db_session.commit.call_count)

        # Act: Drain the outbox
        with patch("app.services.email_outbox.send_email", side_effect=record):
            delivered = mock_email_outbox_service.dispatch_due()

        # Assert: Verify the first message was committed before the second was sent
        assert delivered == 2
        assert commits_when_sending == [0, 1]

    def test_an_unexpected_error_does_not_cost_the_messages_around_it(
        self,
        mock_email_outbox_service: EmailOutboxService,
        mock_db_session: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A message that breaks our own code advances and lets the rest through."""
        # Arrange: The second of three messages fails in a way that is not the provider's
        entries = [
            EmailOutbox(
                email_to=f"recipient{index}@example.com",
                subject="Test Subject",
                html_content="<p>Test content</p>",
            )
            for index in range(3)
        ]
        claim = MagicMock(side_effect=[[entries[0]], [entries[1]], [entries[2]], []])
        mock_email_outbox_service.email_outbox_repository.claim_due = claim

        def send(*, email_to: str, **_: str) -> None:
            if email_to == "recipient1@example.com":
                raise UnicodeEncodeError("utf-8", "x", 0, 1, "bad content")

        # Act: Drain the outbox
        with patch("app.services.email_outbox.send_email", side_effect=send):
            with caplog.at_level(logging.ERROR, logger="app.services.email_outbox"):
                delivered = mock_email_outbox_service.dispatch_due()

        # Assert: Verify the other two were sent and the poison message was rescheduled
        assert delivered == 2
        assert [entry.status for entry in entries] == [
            EmailOutboxStatus.SENT,
            EmailOutboxStatus.PENDING,
            EmailOutboxStatus.SENT,
        ]
        assert entries[1].attempts == 1
        assert entries[1].next_attempt_at > datetime.now(UTC)
        assert "recipient1@example.com" in caplog.text

    def test_a_committed_message_is_not_rolled_back_by_a_later_failure(
        self, mock_email_outbox_service: EmailOutboxService, mock_db_session: MagicMock
    ) -> None:
        """The rows already marked sent survive whatever comes after them."""
        # Arrange: The first message goes out, the second breaks
        entries = [
            EmailOutbox(
                email_to=f"recipient{index}@example.com",
                subject="Test Subject",
                html_content="<p>Test content</p>",
            )
            for index in range(2)
        ]
        claim = MagicMock(side_effect=[[entries[0]], [entries[1]], []])
        mock_email_outbox_service.email_outbox_repository.claim_due = claim
        commits_before_the_failure = 0

        def send(*, email_to: str, **_: str) -> None:
            nonlocal commits_before_the_failure
            if email_to == "recipient1@example.com":
                commits_before_the_failure = mock_db_session.commit.call_count
                raise RuntimeError("boom")

        # Act: Drain the outbox
        with patch("app.services.email_outbox.send_email", side_effect=send):
            mock_email_outbox_service.dispatch_due()

        # Assert: Verify the delivered message was already committed, and stayed sent
        assert commits_before_the_failure == 1
        assert entries[0].status == EmailOutboxStatus.SENT


class TestPruneExpired:
    """Test the retention windows the outbox is kept to."""

    def test_prune_expired_reports_what_it_removed(
        self, mock_email_outbox_service: EmailOutboxService, mock_db_session: MagicMock
    ) -> None:
        """The caller logs the figure, so it has to come back."""
        # Arrange: Four rows are past their window
        mock_db_session.exec.return_value.rowcount = 4

        # Act: Apply the retention policy
        removed = mock_email_outbox_service.prune_expired()

        # Assert: Verify the count came back
        assert removed == 4

    def test_prune_expired_keeps_a_failed_message_longer_than_a_sent_one(
        self, mock_email_outbox_service: EmailOutboxService, mock_email_outbox_repository: EmailOutboxRepository
    ) -> None:
        """A failure is the row somebody still has to act on."""
        # Arrange: Watch the cutoffs the service works out
        with patch.object(mock_email_outbox_repository, "delete_expired", return_value=0) as mock_delete:
            # Act: Apply the retention policy
            mock_email_outbox_service.prune_expired()

        # Assert: Verify the failed cutoff reaches further back than the sent one
        cutoffs = mock_delete.call_args.kwargs
        assert cutoffs["failed_before"] < cutoffs["sent_before"]

    def test_prune_expired_uses_the_configured_windows(
        self, mock_email_outbox_service: EmailOutboxService, mock_email_outbox_repository: EmailOutboxRepository
    ) -> None:
        """A deployment that has to keep mail longer only changes a setting."""
        # Arrange: Watch the cutoffs the service works out
        with patch.object(mock_email_outbox_repository, "delete_expired", return_value=0) as mock_delete:
            # Act: Apply the retention policy
            mock_email_outbox_service.prune_expired()

        # Assert: Verify each cutoff is its setting's worth of days ago
        now = datetime.now(UTC)
        cutoffs = mock_delete.call_args.kwargs
        expected_sent = now - timedelta(days=settings.EMAIL_OUTBOX_SENT_RETENTION_DAYS)
        expected_failed = now - timedelta(days=settings.EMAIL_OUTBOX_FAILED_RETENTION_DAYS)
        assert abs((cutoffs["sent_before"] - expected_sent).total_seconds()) < 5
        assert abs((cutoffs["failed_before"] - expected_failed).total_seconds()) < 5

    def test_prune_expired_commits_the_deletion(
        self, mock_email_outbox_service: EmailOutboxService, mock_db_session: MagicMock
    ) -> None:
        """The pruner runs outside a request, so nothing else will commit for it."""
        # Arrange: Some rows are past their window
        mock_db_session.exec.return_value.rowcount = 1

        # Act: Apply the retention policy
        mock_email_outbox_service.prune_expired()

        # Assert: Verify the removal was committed
        mock_db_session.commit.assert_called_once()


class TestStats:
    """Test the report of what the outbox is holding."""

    def test_stats_counts_the_backlog_and_the_failures(
        self, mock_email_outbox_service: EmailOutboxService, mock_email_outbox_repository: EmailOutboxRepository
    ) -> None:
        """These are the two figures somebody has to act on."""
        # Arrange: The table holds a bit of everything
        counts = {EmailOutboxStatus.PENDING: 2, EmailOutboxStatus.SENT: 40, EmailOutboxStatus.FAILED: 3}
        with patch.object(mock_email_outbox_repository, "count_by_status", return_value=counts):
            with patch.object(mock_email_outbox_repository, "oldest_created_at", return_value=None):
                # Act: Ask what the outbox is holding
                stats = mock_email_outbox_service.stats()

        # Assert: Verify the report carries what is owed and what gave up
        assert stats.pending == 2
        assert stats.failed == 3

    def test_stats_dates_the_oldest_failure(
        self, mock_email_outbox_service: EmailOutboxService, mock_email_outbox_repository: EmailOutboxRepository
    ) -> None:
        """A week-old failure is a different problem from this morning's."""
        # Arrange: The oldest failure is from a week ago
        moment = datetime.now(UTC) - timedelta(days=7)
        with patch.object(mock_email_outbox_repository, "count_by_status", return_value={EmailOutboxStatus.FAILED: 1}):
            with patch.object(mock_email_outbox_repository, "oldest_created_at", return_value=moment) as mock_oldest:
                # Act: Ask what the outbox is holding
                stats = mock_email_outbox_service.stats()

        # Assert: Verify the failures were dated, and only the failures
        assert stats.oldest_failed_at == moment
        mock_oldest.assert_called_once_with(status=EmailOutboxStatus.FAILED)

    def test_stats_reports_an_empty_outbox_as_zeroes(
        self, mock_email_outbox_service: EmailOutboxService, mock_email_outbox_repository: EmailOutboxRepository
    ) -> None:
        """A status with no rows is absent from the tally, not zero in it."""
        # Arrange: Nothing has ever been queued
        with patch.object(mock_email_outbox_repository, "count_by_status", return_value={}):
            # Act: Ask what the outbox is holding
            stats = mock_email_outbox_service.stats()

        # Assert: Verify the report reads as empty rather than failing
        assert stats.pending == 0
        assert stats.failed == 0
        assert stats.oldest_failed_at is None

    def test_stats_does_not_date_failures_that_are_not_there(
        self, mock_email_outbox_service: EmailOutboxService, mock_email_outbox_repository: EmailOutboxRepository
    ) -> None:
        """The healthy case is the common one, and should cost one query."""
        # Arrange: Everything that was queued was delivered
        with patch.object(mock_email_outbox_repository, "count_by_status", return_value={EmailOutboxStatus.SENT: 9}):
            with patch.object(mock_email_outbox_repository, "oldest_created_at") as mock_oldest:
                # Act: Ask what the outbox is holding
                mock_email_outbox_service.stats()

        # Assert: Verify the second query was never made
        mock_oldest.assert_not_called()
