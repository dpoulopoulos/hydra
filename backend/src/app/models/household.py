import datetime
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated

from pydantic import EmailStr, StringConstraints
from sqlmodel import Field, SQLModel

from .email_outbox import EmailOutboxStatus
from .mixins import CreatedAtMixin, PrimaryKeyMixin, UpdatedAtMixin, UtcDateTime
from .user import User

# A BCP 47 language tag of the shapes a household is offered: a language, with
# an optional script and an optional region, e.g. "el", "en-US", "sr-Latn-RS",
# "es-419". The extensions and variants the full grammar allows are left out:
# nothing here needs them, and the value is handed to `Intl` in the browser,
# where a tag it cannot parse would silently format every amount some other way.
LOCALE_PATTERN = r"^[A-Za-z]{2,3}(-[A-Za-z]{4})?(-([A-Za-z]{2}|[0-9]{3}))?$"

# Room for the longest tag the pattern above admits, and then some, so the
# column never has to be widened to store a shape it already accepts.
MAX_LOCALE_LENGTH = 35

# The locale as it is accepted on the way in. Annotated rather than declared on
# each field, so the shape a household may be given is written once.
Locale = Annotated[str, StringConstraints(pattern=LOCALE_PATTERN, max_length=MAX_LOCALE_LENGTH)]


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
    # How the household writes numbers: which character separates a decimal
    # from a group, and where the groups fall. Null means the household has not
    # said, and each reader's browser decides for them, which is what every
    # household did before this column existed.
    #
    # Unconstrained here on purpose: the shape is checked on the way in, by
    # `HouseholdUpdate`, so a tag stored before that check existed still reads
    # back rather than turning a household into a 500.
    locale: str | None = Field(default=None, max_length=MAX_LOCALE_LENGTH)


class HouseholdCreate(HouseholdBase):
    pass


class HouseholdUpdate(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    session_merchant_label: str | None = Field(default=None, min_length=1, max_length=255)
    # Null is a value here rather than a way of leaving the field alone: it is
    # how a household goes back to letting each reader's browser decide. What
    # leaves the field alone is not sending it, which `exclude_unset` keeps out
    # of the update.
    locale: Locale | None = Field(default=None)


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
    # When the household was handed to this member because it had none left.
    # Null for everybody else, including an owner another owner chose, so the
    # members page can say ownership changed by itself and when.
    promoted_to_owner_at: datetime.datetime | None = None


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
    # Stamped when the household was handed to this member for want of an
    # owner, and cleared as soon as an owner sets their role by hand. It is
    # the difference between a household somebody chose to run and one that
    # fell to whoever had been in it longest, which is what the members page
    # has to be able to tell.
    promoted_to_owner_at: datetime.datetime | None = Field(default=None, sa_type=UtcDateTime)


class HouseholdInviteBase(SQLModel):
    email: EmailStr = Field(index=True, max_length=255)
    role: HouseholdRole = HouseholdRole.MEMBER
    expires_at: datetime.datetime = Field(sa_type=UtcDateTime)
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
    # What became of the invitation mail. Null when there is nothing to report:
    # mail was off when the invitation was made, the invitation predates the
    # column, or the outbox row has since been pruned. An owner is only told
    # about a delivery state that is actually known.
    delivery_status: EmailOutboxStatus | None = None


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
    # Masked, never the address itself. Returning it in full would tell
    # whoever holds a leaked link which address the invitation is for, which
    # only helps somebody trying to pass themselves off as its recipient.
    masked_email: str
    role: HouseholdRole
    expires_at: datetime.datetime


class HouseholdInvite(HouseholdInviteBase, PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, table=True):
    token: str = Field(unique=True, index=True)
    household_id: uuid.UUID = Field(foreign_key="household.id", ondelete="CASCADE", index=True)
    invited_by_user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id", ondelete="SET NULL")
    # The account the invitation is for, once one has proved it holds the
    # invited address. An address is a profile field its owner can change at
    # will, so it identifies nobody; this column is what the accept path
    # compares against. Null while nobody has proved the address: such an
    # invitation is redeemable by no one until the address is verified and the
    # invitation is claimed.
    invited_user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id", ondelete="SET NULL", index=True)
    # The outbox row that carries the invitation mail, so the listing can say
    # whether the message actually reached the address. Null when mail is not
    # configured, and again once the outbox row has been pruned: a delivery
    # state is only reported for as long as the evidence for it is kept.
    email_outbox_id: uuid.UUID | None = Field(
        default=None, foreign_key="emailoutbox.id", ondelete="SET NULL", index=True
    )


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
