import datetime
from enum import StrEnum

from pydantic import EmailStr
from sqlmodel import Field, SQLModel

from .mixins import CreatedAtMixin, PrimaryKeyMixin, UpdatedAtMixin

# Subjects live in a bounded column, so one that is too long is trimmed to fit
# rather than costing the request that asked for the mail.
SUBJECT_MAX_LENGTH = 255


class EmailOutboxStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class EmailOutbox(PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, SQLModel, table=True):
    """One outbound message, kept until the provider accepts it.

    The row is written in the same transaction as the change that asks for the
    mail, so a message can never be lost by a process that dies between the
    commit and the send. What is still ``PENDING`` is what still owes someone
    an email.
    """

    email_to: EmailStr = Field(index=True, max_length=255)
    subject: str = Field(max_length=SUBJECT_MAX_LENGTH)
    html_content: str
    status: EmailOutboxStatus = Field(default=EmailOutboxStatus.PENDING, index=True)
    attempts: int = 0
    # When the dispatcher may next try. A fresh row is due immediately; a failed
    # attempt pushes it into the future by the backoff.
    next_attempt_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC), index=True)
    # The last provider error, truncated: it is a breadcrumb for whoever reads
    # the row, not a place to keep a whole traceback.
    last_error: str | None = Field(default=None, max_length=500)
    sent_at: datetime.datetime | None = None
