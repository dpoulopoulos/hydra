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


class HouseholdBase(SQLModel):
    name: str = Field(max_length=255)
    # ISO 4217. Single currency per household in this version; the column exists
    # so adding a second one later does not have to restructure the ledger.
    currency_code: str = Field(default="EUR", min_length=3, max_length=3)


class HouseholdCreate(HouseholdBase):
    pass


class HouseholdUpdate(SQLModel):
    name: str | None = Field(default=None, max_length=255)


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
