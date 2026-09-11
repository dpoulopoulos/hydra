import datetime
from enum import StrEnum

from pydantic import EmailStr
from sqlmodel import Field, SQLModel

from .mixins import CreatedAtMixin, PrimaryKeyMixin, UpdatedAtMixin, UtcDateTime

# Subjects live in a bounded column, so one that is too long is trimmed to fit
# rather than costing the request that asked for the mail.
SUBJECT_MAX_LENGTH = 255


class EmailOutboxStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class EmailOutboxStats(SQLModel):
    """What the outbox holds right now.

    A message that gave up announces itself once, in the log, and after that
    the only way to find out that somebody never got their invite is to query
    the table by hand. This is that query, for whoever administers the
    deployment.
    """

    pending: int = 0
    failed: int = 0
    # How long the oldest unresolved failure has been sitting there, which is
    # what says whether this is a blip or a provider that has been refusing
    # our mail all week. Null when nothing has failed.
    oldest_failed_at: datetime.datetime | None = None


class EmailOutbox(PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, SQLModel, table=True):
    """One outbound message, kept until the provider accepts it.

    The row is written in the same transaction as the change that asks for the
    mail, so a message can never be lost by a process that dies between the
    commit and the send. What is still ``PENDING`` is what still owes someone
    an email.
    """

    email_to: EmailStr = Field(index=True, max_length=255)
    subject: str = Field(max_length=SUBJECT_MAX_LENGTH)
    # The rendered message, and only for as long as it may still have to be
    # sent: a reset, a verification and an invite each spell a single-use
    # credential out in their body, so a settled row is emptied of it rather
    # than left holding it until retention comes around.
    html_content: str
    status: EmailOutboxStatus = Field(default=EmailOutboxStatus.PENDING, index=True)
    attempts: int = 0
    # When the dispatcher may next try. A fresh row is due immediately; a failed
    # attempt pushes it into the future by the backoff.
    next_attempt_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC), sa_type=UtcDateTime, index=True
    )
    # The last provider error, truncated: it is a breadcrumb for whoever reads
    # the row, not a place to keep a whole traceback.
    last_error: str | None = Field(default=None, max_length=500)
    sent_at: datetime.datetime | None = Field(default=None, sa_type=UtcDateTime)
