from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from app.core.config import settings
from app.logging import get_logger
from app.models import MailRateLimitKind
from app.repositories.mail_rate_limit import MailRateLimitRepository

logger = get_logger(__name__)


class MailRateLimitService:
    """Bound how much mail an unauthenticated request can make the app send.

    Three endpoints send a message to an address their caller names, without
    anyone having signed in: signing up, asking for a password reset and asking
    for another verification link. Left alone they will do it as fast as they
    are asked, which is a way to flood somebody else's mailbox, and a way to
    spend the sending domain's reputation and the provider's quota.

    Two budgets, both of them per window. The caller's bounds how much one
    client can ask for at all, so a script cannot spray a list of addresses.
    The recipient's bounds how much can be aimed at one mailbox, however many
    callers do the aiming, which is what protects a person whose address
    somebody else is posting.

    Both budgets are shared across the three endpoints rather than kept per
    endpoint: they exist to bound how much mail leaves, and a caller who could
    spend a fresh budget on each of them would simply rotate.
    """

    def __init__(self, session: Session, mail_rate_limit_repository: MailRateLimitRepository) -> None:
        """Initialize the mail rate limit service.

        Args:
            session: The database session.
            mail_rate_limit_repository: The mail rate limit repository instance.
        """
        self.session = session
        self.mail_rate_limit_repository = mail_rate_limit_repository

    @classmethod
    def for_session(cls, session: Session) -> "MailRateLimitService":
        """Build the service around a session a caller already holds.

        Args:
            session: The database session to count the attempt in.

        Returns:
            A mail rate limit service using that session.
        """
        return cls(session=session, mail_rate_limit_repository=MailRateLimitRepository(session=session))

    def allows_mail(self, *, source: str | None, recipient: str) -> bool:
        """Count a request against both budgets and say whether it may send.

        The caller's budget is checked first and the recipient's is only spent
        when it passes, so a client that is already over its own limit cannot
        also spend the budget of every address it names.

        Args:
            source: The address the request came from, or None when it cannot
                be worked out. A request with no source spends the recipient's
                budget only.
            recipient: The address the mail would go to.

        Returns:
            True if the message may be sent, False once either budget is spent.
        """
        now = datetime.now(UTC)
        window_start = now - timedelta(minutes=settings.MAIL_RATE_LIMIT_WINDOW_MINUTES)

        if source is not None and not self._within_budget(
            kind=MailRateLimitKind.SOURCE,
            subject=source,
            limit=settings.MAIL_RATE_LIMIT_PER_SOURCE,
            now=now,
            window_start=window_start,
        ):
            return False

        return self._within_budget(
            kind=MailRateLimitKind.RECIPIENT,
            # Addresses are compared case-insensitively everywhere they are
            # looked up, so a budget that was not would be doubled by asking
            # again in capitals.
            subject=recipient.strip().lower(),
            limit=settings.MAIL_RATE_LIMIT_PER_RECIPIENT,
            now=now,
            window_start=window_start,
        )

    def prune_expired(self) -> int:
        """Drop the counters whose window has passed.

        Returns:
            The number of rows removed.
        """
        removed = self.mail_rate_limit_repository.delete_expired(
            window_start=datetime.now(UTC) - timedelta(minutes=settings.MAIL_RATE_LIMIT_WINDOW_MINUTES)
        )
        self.session.commit()

        return removed

    def _within_budget(
        self, *, kind: MailRateLimitKind, subject: str, limit: int, now: datetime, window_start: datetime
    ) -> bool:
        """Count one attempt against a subject and say whether it fits.

        The count is committed on its own, before the request does anything
        else. What follows may well roll back - a signup that loses a race
        does - and an attempt that was not counted is an attempt that was free.

        Args:
            kind: Whether the subject is the caller or the recipient.
            subject: The address the budget belongs to.
            limit: The most attempts the window allows.
            now: The moment of the attempt.
            window_start: The earliest moment a window still running can have
                started at.

        Returns:
            True while the subject is inside its budget, False once it is not.
        """
        attempts = self.mail_rate_limit_repository.count_attempt(
            kind=kind, subject=subject, now=now, window_start=window_start
        )
        self.session.commit()

        if attempts > limit:
            logger.warning(
                "Refused to send mail: the %s budget of %s is spent (%d attempts this window)",
                kind.value,
                subject,
                attempts,
            )
            return False

        return True
