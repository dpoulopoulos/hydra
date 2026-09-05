import datetime
import uuid
from dataclasses import dataclass
from enum import StrEnum

from pydantic import EmailStr
from sqlmodel import Field, SQLModel

from .mixins import CreatedAtMixin, PrimaryKeyMixin, UpdatedAtMixin
from .user import User


class HouseholdRole(StrEnum):
    OWNER = "owner"
    MEMBER = "member"


class HouseholdInviteStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"


class HouseholdBase(SQLModel):
    name: str = Field(max_length=255)
    # ISO 4217. Single currency per household in this version; the column exists
    # so adding a second one later does not have to restructure the ledger.
    currency_code: str = Field(default="EUR", min_length=3, max_length=3)
    # What a paid session is called on the Transactions page. The client's name
    # cannot go there: it is encrypted by the browser, and writing it into the
    # ledger would undo that. One label for the whole household, never one per
    # client, because a per-client label is the name again under another field.
    session_merchant_label: str = Field(default="Session", min_length=1, max_length=255)


class HouseholdCreate(HouseholdBase):
    pass


class HouseholdUpdate(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    session_merchant_label: str | None = Field(default=None, min_length=1, max_length=255)


class HouseholdPublic(HouseholdBase):
    id: uuid.UUID
    member_count: int = 1
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None


class Household(HouseholdBase, PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, table=True):
    pass


class HouseholdMemberBase(SQLModel):
    role: HouseholdRole = HouseholdRole.MEMBER


class HouseholdMemberUpdate(SQLModel):
    role: HouseholdRole


class HouseholdMemberPublic(HouseholdMemberBase):
    id: uuid.UUID
    household_id: uuid.UUID
    user_id: uuid.UUID
    email: EmailStr
    full_name: str | None = None
    created_at: datetime.datetime


class HouseholdMembersPublic(SQLModel):
    data: list[HouseholdMemberPublic]
    count: int


class HouseholdMember(HouseholdMemberBase, PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, table=True):
    household_id: uuid.UUID = Field(foreign_key="household.id", ondelete="CASCADE", index=True)
    # Unique, not just indexed: a user belongs to exactly one household in this
    # version. That is what lets every request derive its scope from the token
    # alone, with no household selector. Dropping this constraint is the
    # migration that would allow a user to join several households.
    user_id: uuid.UUID = Field(foreign_key="user.id", ondelete="CASCADE", unique=True, index=True)


class HouseholdInviteBase(SQLModel):
    email: EmailStr = Field(index=True, max_length=255)
    role: HouseholdRole = HouseholdRole.MEMBER
    expires_at: datetime.datetime
    status: HouseholdInviteStatus = HouseholdInviteStatus.PENDING


class HouseholdInviteCreate(SQLModel):
    email: EmailStr = Field(max_length=255)
    role: HouseholdRole = HouseholdRole.MEMBER


class HouseholdInviteAccept(SQLModel):
    token: str


class HouseholdInvitePublic(HouseholdInviteBase):
    id: uuid.UUID
    household_id: uuid.UUID
    created_at: datetime.datetime


class HouseholdInvitesPublic(SQLModel):
    data: list[HouseholdInvitePublic]
    count: int


class HouseholdInvitePreview(SQLModel):
    """What the join page may show before the recipient has signed in.

    Deliberately thin: anyone holding the link can read this, so it carries
    only what is needed to decide whether to accept, and nothing about the
    household's money.
    """

    household_name: str
    invited_by: EmailStr
    email: EmailStr
    role: HouseholdRole
    expires_at: datetime.datetime


class HouseholdInvite(HouseholdInviteBase, PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, table=True):
    token: str = Field(unique=True, index=True)
    household_id: uuid.UUID = Field(foreign_key="household.id", ondelete="CASCADE", index=True)
    invited_by_user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id", ondelete="SET NULL")


@dataclass(frozen=True, slots=True)
class HouseholdContext:
    """The household scope of a request.

    Lives with the models rather than in ``app.api.deps`` so services can be
    typed against it without the business logic depending on the web framework.
    """

    user: User
    household_id: uuid.UUID
    membership_id: uuid.UUID
    role: HouseholdRole

    @property
    def user_id(self) -> uuid.UUID:
        """Get the ID of the user the request is authenticated as.

        Returns:
            The user's ID.
        """
        return self.user.id

    @property
    def is_owner(self) -> bool:
        """Check whether the user owns the household.

        Returns:
            True if the user's role is owner.
        """
        return self.role is HouseholdRole.OWNER
