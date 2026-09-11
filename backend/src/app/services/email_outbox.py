from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from app.core.config import settings
from app.logging import get_logger
from app.models import SUBJECT_MAX_LENGTH, EmailOutbox, EmailOutboxStatus
from app.repositories.email_outbox import EmailOutboxRepository
from app.utils.email_utils import DELIVERY_ERRORS, send_email

logger = get_logger(__name__)


class EmailOutboxService:
    """Deliver mail through the outbox, retrying what the provider refused.

    Every message is written down before it is attempted, so a provider that
    is rate limiting us, or a process that dies mid-send, costs a delay rather
    than the message.
    """

    def __init__(self, session: Session, email_outbox_repository: EmailOutboxRepository) -> None:
        """Initialize the email outbox service.

        Args:
            session: The database session.
            email_outbox_repository: The email outbox repository instance.
        """
        self.session = session
        self.email_outbox_repository = email_outbox_repository

    @classmethod
    def for_session(cls, session: Session) -> "EmailOutboxService":
        """Build the service around a session a caller already holds.

        Sending mail is a side effect of some other service's write, and those
        services own a session rather than this repository.

        Args:
            session: The database session to queue the message in.

        Returns:
            An email outbox service using that session.
        """
        return cls(session=session, email_outbox_repository=EmailOutboxRepository(session=session))

    def deliver_or_queue(self, *, email_to: str, subject: str, html_content: str) -> bool:
        """Send a message now, keeping it for a retry if that does not work.

        The message is committed before the provider is called, so it survives
        an outage, a timeout or a process that is killed while sending.

        Args:
            email_to: The recipient's email address.
            subject: The subject of the email.
            html_content: The HTML content of the email.

        Returns:
            True if the provider took the message, False if it is queued for
            another attempt.
        """
        # The subject is stored in a bounded column, and the caller's write is
        # already committed by now: a name long enough to overflow it must cost
        # the tail of a subject line, not the whole request.
        entry = EmailOutbox(email_to=email_to, subject=subject[:SUBJECT_MAX_LENGTH], html_content=html_content)
        self.email_outbox_repository.save(entry)
        self.session.commit()

        delivered = self._attempt_and_record(entry)
        self.session.commit()

        return delivered

    def dispatch_due(self) -> int:
        """Attempt the queued messages that have come due, up to a batch.

        Messages are claimed and committed one at a time. A batch that shared
        a transaction would undo the rows already marked sent as soon as one
        message failed unexpectedly, and would hold its locks - and the
        connection - for as long as every send in it took together.

        Returns:
            The number of messages the provider accepted this round.
        """
        delivered = 0

        for _ in range(settings.EMAIL_OUTBOX_BATCH_SIZE):
            claimed = self.email_outbox_repository.claim_due(now=datetime.now(UTC), limit=1)
            if not claimed:
                # Nothing left to claim: end the read transaction rather than
                # leave the connection sitting idle inside one.
                self.session.rollback()
                break

            delivered += self._dispatch_one(claimed[0])

        return delivered

    def prune_expired(self) -> int:
        """Drop the settled rows whose retention window has passed.

        The outbox is a delivery queue, not an archive: once a message has
        been sent there is nothing left to do with its body, and keeping it
        means keeping a copy of every welcome mail the application ever sent.

        Returns:
            The number of rows removed.
        """
        now = datetime.now(UTC)
        removed = self.email_outbox_repository.delete_expired(
            sent_before=now - timedelta(days=settings.EMAIL_OUTBOX_SENT_RETENTION_DAYS),
            failed_before=now - timedelta(days=settings.EMAIL_OUTBOX_FAILED_RETENTION_DAYS),
        )
        self.session.commit()

        return removed

    def _dispatch_one(self, entry: EmailOutbox) -> bool:
        """Attempt one claimed message and commit whatever became of it.

        Args:
            entry: The claimed message to attempt.

        Returns:
            True if the provider took the message.
        """
        delivered = self._attempt_and_record(entry)
        self.session.commit()

        return delivered

    def _attempt_and_record(self, entry: EmailOutbox) -> bool:
        """Attempt one message, keeping any failure on the row rather than raising.

        A message that breaks our own code is still a message someone is owed,
        and the write that asked for it is already committed. Recording the
        failure keeps the row moving: it burns an attempt and backs off like
        any other failure, instead of failing a request that succeeded or
        being claimed again every round.

        Args:
            entry: The message to attempt.

        Returns:
            True if the provider took the message.
        """
        try:
            return self._attempt(entry)
        except Exception as error:
            # Not a delivery problem, so it is a bug in our own code - but the
            # row still has to advance.
            logger.exception("Unexpected error sending email %r to %s", entry.subject, entry.email_to)
            self._record_failure(entry, error)
            return False

    def _attempt(self, entry: EmailOutbox) -> bool:
        """Hand one queued message to the provider and record what happened.

        Args:
            entry: The queued message to attempt.

        Returns:
            True if the provider took the message.
        """
        entry.attempts += 1

        try:
            send_email(email_to=entry.email_to, subject=entry.subject, html_content=entry.html_content)
        except DELIVERY_ERRORS as error:
            self._record_failure(entry, error)
            return False

        entry.status = EmailOutboxStatus.SENT
        entry.sent_at = datetime.now(UTC)
        entry.last_error = None
        self.email_outbox_repository.save(entry)

        return True

    def _record_failure(self, entry: EmailOutbox, error: Exception) -> None:
        """Schedule another attempt, or give up once there are none left.

        Args:
            entry: The message that could not be delivered.
            error: What the provider or the network said.
        """
        # The column is bounded, and what matters is the head of the message.
        entry.last_error = f"{type(error).__name__}: {error}"[:500]

        if entry.attempts >= settings.EMAIL_OUTBOX_MAX_ATTEMPTS:
            entry.status = EmailOutboxStatus.FAILED
            logger.error(
                "Giving up on email %r to %s after %d attempts: %s",
                entry.subject,
                entry.email_to,
                entry.attempts,
                entry.last_error,
            )
        else:
            entry.next_attempt_at = datetime.now(UTC) + self._backoff(entry.attempts)
            logger.warning(
                "Could not deliver email %r to %s (attempt %d), retrying at %s: %s",
                entry.subject,
                entry.email_to,
                entry.attempts,
                entry.next_attempt_at,
                entry.last_error,
            )

        self.email_outbox_repository.save(entry)

    @staticmethod
    def _backoff(attempts: int) -> timedelta:
        """Work out how long to wait before the next attempt.

        The wait doubles per failed attempt, so a provider that is struggling
        is not hammered, and stops growing at a ceiling, so a message is never
        parked for days.

        Args:
            attempts: How many attempts the message has taken so far.

        Returns:
            How long to wait before attempting it again.
        """
        # 2 ** attempts overflows nothing, but a large exponent is pointless
        # work: anything past the cap is the cap.
        exponent = min(attempts - 1, 32)
        seconds = min(
            settings.EMAIL_OUTBOX_RETRY_BASE_SECONDS * 2**exponent,
            settings.EMAIL_OUTBOX_RETRY_MAX_SECONDS,
        )
        return timedelta(seconds=seconds)
