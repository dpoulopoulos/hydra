import datetime
from enum import StrEnum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from .mixins import CreatedAtMixin, PrimaryKeyMixin, UpdatedAtMixin, UtcDateTime

# An IPv6 address is 45 characters and an email address is capped at 255
# elsewhere in the schema, so one bound covers both kinds of subject.
RATE_LIMIT_SUBJECT_MAX_LENGTH = 255


class MailRateLimitKind(StrEnum):
    """Whose budget a row counts against.

    The two answer different questions. ``SOURCE`` is the caller, and bounds
    how much mail one client can make the app send at all. ``RECIPIENT`` is the
    address the mail would go to, and bounds how much of it can be aimed at one
    mailbox by however many callers.
    """

    SOURCE = "source"
    RECIPIENT = "recipient"


class MailRateLimit(PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, SQLModel, table=True):
    """What one caller, or one mailbox, has spent of its budget so far.

    A row is a fixed window: it counts the requests made since
    ``window_start``, and is reset rather than replaced once that window has
    passed. One row per subject, kept by a unique constraint, so counting an
    attempt is a single upsert and two processes counting at once cannot each
    write their own tally.

    The rows are not evidence of anything and are not read back by a person:
    an expired one is pruned, which is also what keeps the table from holding
    an address for every caller the app has ever answered.
    """

    __table_args__ = (UniqueConstraint("kind", "subject", name="uq_mailratelimit_kind_subject"),)

    kind: MailRateLimitKind
    # The caller's address or the recipient's, depending on the kind. An email
    # address is stored lowercased, so that a budget cannot be doubled by
    # changing the case of the address it is spent on.
    subject: str = Field(max_length=RATE_LIMIT_SUBJECT_MAX_LENGTH)
    window_start: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC), sa_type=UtcDateTime, index=True
    )
    attempts: int = 1
