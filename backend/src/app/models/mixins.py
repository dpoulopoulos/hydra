import uuid
from datetime import UTC, datetime

from sqlalchemy import func
from sqlmodel import Field


class PrimaryKeyMixin:
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)


class CreatedAtMixin:
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column_kwargs={"server_default": func.now()},
    )


class UpdatedAtMixin:
    updated_at: datetime | None = Field(default=None, sa_column_kwargs={"onupdate": func.now()})
