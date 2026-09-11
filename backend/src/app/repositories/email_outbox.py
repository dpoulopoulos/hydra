from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_ as sa_and
from sqlalchemy import delete
from sqlalchemy import or_ as sa_or
from sqlmodel import Session, col, select

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

    def delete_expired(self, *, sent_before: datetime, failed_before: datetime) -> int:
        """Remove the rows whose retention window has passed.

        A row keeps the whole rendered body of its message, so the table grows
        with every registration, invite and reset and is never read again once
        the send is settled. Only rows that have settled are removed: what is
        still ``PENDING`` is still owed to somebody, however old it is.

        Args:
            sent_before: Delivered messages created before this go.
            failed_before: Messages that gave up and were created before this
                go. Later than the other cutoff, because a failure is the one
                a person still has to act on.

        Returns:
            The number of rows removed.
        """
        statement = delete(EmailOutbox).where(
            sa_or(
                sa_and(
                    col(EmailOutbox.status) == EmailOutboxStatus.SENT,
                    col(EmailOutbox.created_at) < sent_before,
                ),
                sa_and(
                    col(EmailOutbox.status) == EmailOutboxStatus.FAILED,
                    col(EmailOutbox.created_at) < failed_before,
                ),
            )
        )
        return int(self.session.exec(statement).rowcount)
