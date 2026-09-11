"""What the mail rate limit counters do against a real Postgres.

Counting an attempt is one ``INSERT ... ON CONFLICT DO UPDATE``, so what it
does is decided by the server rather than by the code that builds it: the
unit suite mocks the session and never executes it. Whether a second attempt
increments the row the first one wrote, and whether an expired window is reset
rather than continued, are therefore checked here.
"""

from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.models import MailRateLimit, MailRateLimitKind
from app.repositories import MailRateLimitRepository


class TestCountAttempt:
    """Test the upsert that counts one attempt against a budget."""

    def test_the_first_attempt_opens_the_window(self, db_session: Session) -> None:
        """A subject with no row gets one, worth the attempt that created it."""
        # Arrange: A subject the table has never seen
        repository = MailRateLimitRepository(session=db_session)
        now = datetime.now(UTC)

        # Act: Count one attempt against it
        attempts = repository.count_attempt(
            kind=MailRateLimitKind.RECIPIENT,
            subject="victim@example.com",
            now=now,
            window_start=now - timedelta(hours=1),
        )

        # Assert: Verify the tally is one and the row says when the window opened
        assert attempts == 1
        row = db_session.exec(select(MailRateLimit)).one()
        assert row.attempts == 1
        assert row.window_start == now

    def test_further_attempts_add_to_the_same_row(self, db_session: Session) -> None:
        """The tally is what the unique constraint keeps a single row of."""
        # Arrange: A subject and a window that is still running
        repository = MailRateLimitRepository(session=db_session)
        now = datetime.now(UTC)
        window_start = now - timedelta(hours=1)

        # Act: Count three attempts against it
        tallies = [
            repository.count_attempt(
                kind=MailRateLimitKind.SOURCE,
                subject="203.0.113.7",
                now=now + timedelta(seconds=second),
                window_start=window_start,
            )
            for second in range(3)
        ]

        # Assert: Verify each attempt saw the one before it, on one row
        assert tallies == [1, 2, 3]
        row = db_session.exec(select(MailRateLimit)).one()
        assert row.attempts == 3
        # The window is the one the first attempt opened, so a caller cannot
        # hold a budget open by spending it.
        assert row.window_start == now

    def test_a_window_that_has_passed_starts_again(self, db_session: Session) -> None:
        """A budget is spent per window, so an old row is reset and not continued."""
        # Arrange: A subject that spent its budget an hour ago
        repository = MailRateLimitRepository(session=db_session)
        spent_at = datetime.now(UTC) - timedelta(hours=2)
        for _ in range(5):
            repository.count_attempt(
                kind=MailRateLimitKind.RECIPIENT,
                subject="victim@example.com",
                now=spent_at,
                window_start=spent_at - timedelta(hours=1),
            )

        # Act: Come back once that window has passed
        now = datetime.now(UTC)
        attempts = repository.count_attempt(
            kind=MailRateLimitKind.RECIPIENT,
            subject="victim@example.com",
            now=now,
            window_start=now - timedelta(hours=1),
        )

        # Assert: Verify the tally starts again, in a window that opens now
        assert attempts == 1
        row = db_session.exec(select(MailRateLimit)).one()
        assert row.attempts == 1
        assert row.window_start == now

    def test_a_caller_and_a_recipient_are_counted_apart(self, db_session: Session) -> None:
        """The two budgets bound different things and must not spend each other."""
        # Arrange: One string that is both an address and a subject of each kind
        repository = MailRateLimitRepository(session=db_session)
        now = datetime.now(UTC)
        window_start = now - timedelta(hours=1)

        # Act: Count an attempt against each kind
        source = repository.count_attempt(
            kind=MailRateLimitKind.SOURCE, subject="both@example.com", now=now, window_start=window_start
        )
        recipient = repository.count_attempt(
            kind=MailRateLimitKind.RECIPIENT, subject="both@example.com", now=now, window_start=window_start
        )

        # Assert: Verify each kind opened a budget of its own
        assert source == 1
        assert recipient == 1
        assert len(db_session.exec(select(MailRateLimit)).all()) == 2


class TestDeleteExpired:
    """Test the retention of counters against a real server."""

    def test_only_the_windows_that_have_passed_are_removed(self, db_session: Session) -> None:
        """A running budget is what stops the next request, so it has to survive."""
        # Arrange: One counter from a window that has passed and one still running
        now = datetime.now(UTC)
        db_session.add(
            MailRateLimit(
                kind=MailRateLimitKind.SOURCE, subject="old@example.com", window_start=now - timedelta(days=1)
            )
        )
        db_session.add(
            MailRateLimit(
                kind=MailRateLimitKind.SOURCE, subject="current@example.com", window_start=now - timedelta(minutes=1)
            )
        )
        db_session.flush()

        # Act: Prune everything whose window opened more than an hour ago
        removed = MailRateLimitRepository(session=db_session).delete_expired(window_start=now - timedelta(hours=1))

        # Assert: Verify the expired counter is gone and the running one is not
        assert removed == 1
        subjects = [row.subject for row in db_session.exec(select(MailRateLimit)).all()]
        assert subjects == ["current@example.com"]
