from datetime import datetime

from sqlalchemy import case, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, col

from app.models import MailRateLimit, MailRateLimitKind
from app.repositories.base import BaseRepository, table_of


class MailRateLimitRepository(BaseRepository[MailRateLimit]):
    """Repository for the counters that bound how much mail a request can ask for."""

    def __init__(self, session: Session) -> None:
        """Initialize the mail rate limit repository.

        Args:
            session: The database session.
        """
        super().__init__(session, MailRateLimit)

    def count_attempt(self, *, kind: MailRateLimitKind, subject: str, now: datetime, window_start: datetime) -> int:
        """Count one attempt against a subject's budget and report the tally.

        One statement, so that two requests arriving together cannot both read
        the same tally and write it back: the row is inserted if the subject
        has none, and otherwise updated in place by the database. A row whose
        window has passed is reset rather than deleted and written again, which
        keeps the unique constraint from being raced.

        Args:
            kind: Whether the subject is the caller or the recipient.
            subject: The address the budget belongs to.
            now: The moment of the attempt.
            window_start: The earliest moment a window still running can have
                started at. A row older than this has expired.

        Returns:
            How many attempts the subject has made in the window it is now in,
            this one included.
        """
        table = table_of(MailRateLimit)
        expired = table.c.window_start < window_start

        statement = (
            pg_insert(table)
            .values(kind=kind, subject=subject, window_start=now, attempts=1)
            .on_conflict_do_update(
                constraint="uq_mailratelimit_kind_subject",
                set_={
                    "attempts": case((expired, 1), else_=table.c.attempts + 1),
                    "window_start": case((expired, now), else_=table.c.window_start),
                    # Set by hand: a column's ``onupdate`` is not applied to
                    # the SET clause of an upsert.
                    "updated_at": now,
                },
            )
            .returning(table.c.attempts)
        )
        return int(self.session.execute(statement).scalar_one())

    def delete_expired(self, *, window_start: datetime) -> int:
        """Remove the counters whose window has passed.

        A row is only ever a running total: once its window is over it says
        nothing about what the subject may do next, and the table would
        otherwise keep one row for every address the app has ever answered or
        written to.

        Args:
            window_start: The earliest moment a window still running can have
                started at. Rows older than this go.

        Returns:
            The number of rows removed.
        """
        statement = delete(MailRateLimit).where(col(MailRateLimit.window_start) < window_start)
        return int(self.session.exec(statement).rowcount)
