import datetime
import uuid
from enum import StrEnum

from pydantic import EmailStr
from sqlmodel import Field, SQLModel

from .mixins import CreatedAtMixin, PrimaryKeyMixin, UpdatedAtMixin, UtcDateTime


class EmailVerificationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    EXPIRED = "expired"


class EmailVerificationBase(SQLModel):
    email: EmailStr = Field(index=True, max_length=255)
    expires_at: datetime.datetime = Field(sa_type=UtcDateTime)
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
    # Set only when the verification stands for a change of address: `email` is
    # then the address the account held when the change was asked for, and this
    # is the one it moves to once the token is redeemed. Left unset, the row is
    # an account activation, which verifies the address the account already has.
    new_email: EmailStr | None = Field(default=None, max_length=255)
