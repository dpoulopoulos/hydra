import datetime
import uuid

from pydantic import EmailStr
from sqlmodel import Field, SQLModel

from .email_verification import VerificationDelivery
from .fields import BCRYPT_MAX_PASSWORD_BYTES, MIN_PASSWORD_LENGTH, Password
from .mixins import CreatedAtMixin, PrimaryKeyMixin, UpdatedAtMixin


class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    is_active: bool = True
    is_superuser: bool = False


class UserCreate(UserBase):
    password: Password = Field(min_length=MIN_PASSWORD_LENGTH, max_length=BCRYPT_MAX_PASSWORD_BYTES)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: Password = Field(min_length=MIN_PASSWORD_LENGTH, max_length=BCRYPT_MAX_PASSWORD_BYTES)
    full_name: str | None = Field(default=None, max_length=255)
    # Set when the account is being created from a household invitation link,
    # so the new user joins that household rather than getting one of their own.
    invite_token: str | None = Field(default=None)


class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None


class UserUpdatedMe(UserPublic):
    """An account as an update left it, and what became of the mail it sent.

    An update that asks for a new address mails a link to it, and that
    message may only be queued when the provider is down. Reporting the
    outcome here is what lets the screen say the link is on its way rather
    than sending someone to look in an inbox that has nothing in it yet.
    """

    # Unset when the update asked for no new address, so nothing was sent.
    email_delivery: VerificationDelivery | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UserUpdate(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)
    password: Password | None = Field(
        default=None, min_length=MIN_PASSWORD_LENGTH, max_length=BCRYPT_MAX_PASSWORD_BYTES
    )
    is_active: bool | None = Field(default=None)
    is_superuser: bool | None = Field(default=None)


class User(UserBase, PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, table=True):
    hashed_password: str
