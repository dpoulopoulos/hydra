import datetime
import uuid
from enum import StrEnum

from pydantic import EmailStr
from sqlmodel import Field, SQLModel

from .mixins import CreatedAtMixin, PrimaryKeyMixin, UpdatedAtMixin


class EmailVerificationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    EXPIRED = "expired"


class EmailVerificationBase(SQLModel):
    email: EmailStr = Field(index=True, max_length=255)
    expires_at: datetime.datetime
    status: EmailVerificationStatus = EmailVerificationStatus.PENDING


class EmailVerificationRequest(SQLModel):
    email: EmailStr


class EmailVerificationConfirm(SQLModel):
    token: str


class EmailVerificationPublic(EmailVerificationBase):
    id: uuid.UUID
    created_at: datetime.datetime


class EmailVerification(EmailVerificationBase, PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, table=True):
    token: str = Field(unique=True, index=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", ondelete="CASCADE")
