import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, func
from sqlmodel import Field


class UtcDateTime(DateTime):
    """The column type every stored timestamp uses.

    Every moment the app writes is UTC and tz-aware. A plain ``DateTime`` is
    ``timestamp without time zone``, which keeps the wall clock and throws the
    offset away: the row then records nothing about which zone it is in, and
    the API serialises it the same way. ECMAScript reads a date-time with no
    offset as *local* time, so ``new Date(value)`` in a browser shifts the
    instant by the viewer's own offset. ``timestamptz`` stores a moment rather
    than a reading, psycopg reads it back tz-aware, and the response then
    carries an offset the caller does not have to guess at.

    A type of its own rather than ``DateTime(timezone=True)`` beside each
    column, because ``sa_type`` takes a class: passing the type by name is what
    keeps a new timestamp column from quietly defaulting to the naive one.
    """

    def __init__(self) -> None:
        super().__init__(timezone=True)


class PrimaryKeyMixin:
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)


class CreatedAtMixin:
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_type=UtcDateTime,
        sa_column_kwargs={"server_default": func.now()},
    )


class UpdatedAtMixin:
    updated_at: datetime | None = Field(
        default=None,
        sa_type=UtcDateTime,
        sa_column_kwargs={"onupdate": func.now()},
    )
