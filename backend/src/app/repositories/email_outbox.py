from collections.abc import Sequence
from datetime import datetime

from sqlmodel import Session, select

from app.models import EmailOutbox, EmailOutboxStatus
from app.repositories.base import BaseRepository


class EmailOutboxRepository(BaseRepository[EmailOutbox]):
    """Repository for EmailOutbox database operations."""

    def __init__(self, session: Session) -> None:
        """Initialize the email outbox repository.

        Args:
            session: The database session.
        """
        super().__init__(session, EmailOutbox)

    def claim_due(self, *, now: datetime, limit: int) -> Sequence[EmailOutbox]:
        """Take the messages that are ready to be sent.

        The rows are locked for the caller's transaction, and rows another
        dispatcher already holds are skipped rather than waited for, so two
        processes draining the outbox never send the same message twice.

        Args:
            now: The moment to consider "due"; rows scheduled later are left.
            limit: The most rows to take in one batch.

        Returns:
            The claimed rows, the ones that came due first.
        """
        statement = (
            select(EmailOutbox)
            .where(
                EmailOutbox.status == EmailOutboxStatus.PENDING,
                EmailOutbox.next_attempt_at <= now,
            )
            .order_by(EmailOutbox.next_attempt_at)  # type: ignore[arg-type]
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return self.session.exec(statement).all()
