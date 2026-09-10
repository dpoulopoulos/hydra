import datetime
import uuid
from enum import StrEnum

from pydantic import EmailStr
from sqlmodel import Field, SQLModel

from .fields import BCRYPT_MAX_PASSWORD_BYTES, MIN_PASSWORD_LENGTH, Password
from .mixins import CreatedAtMixin, PrimaryKeyMixin, UpdatedAtMixin, UtcDateTime


class PasswordUpdate(SQLModel):
    current_password: Password = Field(min_length=MIN_PASSWORD_LENGTH, max_length=BCRYPT_MAX_PASSWORD_BYTES)
    new_password: Password = Field(min_length=MIN_PASSWORD_LENGTH, max_length=BCRYPT_MAX_PASSWORD_BYTES)


class PasswordResetStatus(StrEnum):
    PENDING = "pending"
    USED = "used"
    EXPIRED = "expired"


class PasswordResetBase(SQLModel):
    email: EmailStr = Field(index=True, max_length=255)
    expires_at: datetime.datetime = Field(sa_type=UtcDateTime)
    status: PasswordResetStatus = PasswordResetStatus.PENDING


class PasswordResetRequest(SQLModel):
    email: EmailStr


class PasswordResetVerify(SQLModel):
    token: str


class PasswordResetConfirm(SQLModel):
    token: str
    new_password: Password = Field(min_length=MIN_PASSWORD_LENGTH, max_length=BCRYPT_MAX_PASSWORD_BYTES)


class PasswordResetPublic(PasswordResetBase):
    id: uuid.UUID
    created_at: datetime.datetime


class PasswordReset(PasswordResetBase, PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, table=True):
    token: str = Field(unique=True, index=True)
    user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id", ondelete="CASCADE")
