from datetime import UTC, datetime

from app.models import MailRateLimit, MailRateLimitKind


class TestMailRateLimitDefaults:
    """Test the defaults a fresh budget row starts with."""

    def test_a_new_row_counts_the_attempt_that_created_it(self) -> None:
        """A row is written by an attempt, so it is never worth zero."""
        # Arrange: Note the time the row is created
        before = datetime.now(UTC)

        # Act: Count a first attempt against an address
        row = MailRateLimit(kind=MailRateLimitKind.RECIPIENT, subject="recipient@example.com")

        # Assert: Verify the attempt is counted and its window has just opened
        assert row.attempts == 1
        assert before <= row.window_start <= datetime.now(UTC)

    def test_a_source_and_a_recipient_are_separate_budgets(self) -> None:
        """One address may be both a caller and a recipient without sharing a tally."""
        # Arrange: Take one subject that could be either kind
        subject = "203.0.113.7"

        # Act: Count it against each kind
        source = MailRateLimit(kind=MailRateLimitKind.SOURCE, subject=subject)
        recipient = MailRateLimit(kind=MailRateLimitKind.RECIPIENT, subject=subject)

        # Assert: Verify the rows are told apart by their kind
        assert source.kind is MailRateLimitKind.SOURCE
        assert recipient.kind is MailRateLimitKind.RECIPIENT
        assert source.subject == recipient.subject
