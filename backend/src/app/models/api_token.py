import datetime
import uuid
from enum import StrEnum

from sqlmodel import Field, SQLModel

from .mixins import CreatedAtMixin, PrimaryKeyMixin, UpdatedAtMixin, UtcDateTime

# How many live tokens one person may hold. A bound rather than a judgement:
# nobody needs more, and an unbounded list is a way to fill the table.
MAX_ACTIVE_TOKENS_PER_USER = 10
# How long a token may live when the caller asks for an expiry.
MIN_TOKEN_LIFETIME_DAYS = 1
MAX_TOKEN_LIFETIME_DAYS = 730
DEFAULT_TOKEN_LIFETIME_DAYS = 90


class ApiTokenStatus(StrEnum):
    """The lifecycle of an API token."""

    ACTIVE = "active"
    REVOKED = "revoked"


class ApiTokenScope(StrEnum):
    """What a token is allowed to do.

    A read token may only make safe requests. The check is applied once, where
    the credential is resolved, rather than route by route, so a route added
    later is covered without being told about scopes.

    Safe is the method rather than the effect: reading the transactions or a
    report materialises any recurring occurrence now due, so a read token can
    still cause those rows to be written. See SAFE_HTTP_METHODS.
    """

    READ = "read"
    READ_WRITE = "read_write"


class ApiTokenBase(SQLModel):
    # What the token is for, as its owner would describe it: "Claude Desktop".
    # Never part of the credential.
    name: str = Field(min_length=1, max_length=255)
    scope: ApiTokenScope = ApiTokenScope.READ
    status: ApiTokenStatus = ApiTokenStatus.ACTIVE
    expires_at: datetime.datetime | None = Field(default=None, sa_type=UtcDateTime)


class ApiTokenCreate(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    scope: ApiTokenScope = ApiTokenScope.READ
    # None means the token does not expire. Bounded so a typo cannot mint a
    # century.
    expires_in_days: int | None = Field(
        default=DEFAULT_TOKEN_LIFETIME_DAYS,
        ge=MIN_TOKEN_LIFETIME_DAYS,
        le=MAX_TOKEN_LIFETIME_DAYS,
    )


class ApiTokenPublic(ApiTokenBase):
    id: uuid.UUID
    # The lookup half alone. Enough to recognise which token a line in a log is
    # about, and useless on its own: the secret half is stored nowhere.
    token_id: str
    last_used_at: datetime.datetime | None = None
    created_at: datetime.datetime


class ApiTokensPublic(SQLModel):
    data: list[ApiTokenPublic]
    count: int


class ApiTokenCreated(SQLModel):
    """The only response that ever carries the secret.

    It is shown once, at creation. Nothing can reproduce it afterwards, because
    only a hash of the secret half is kept.
    """

    token: ApiTokenPublic
    secret: str


class ApiToken(ApiTokenBase, PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, table=True):
    # The public half of the credential, and all a lookup needs. Unique and
    # indexed, so authenticating is one index probe rather than a scan
    # comparing hashes row by row, which is what a salted hash would force.
    token_id: str = Field(unique=True, index=True, max_length=64)
    # SHA-256 of the secret half, as hex. Not bcrypt: see hash_api_token_secret.
    secret_hash: str = Field(max_length=64)
    user_id: uuid.UUID = Field(foreign_key="user.id", ondelete="CASCADE", index=True)
    last_used_at: datetime.datetime | None = Field(default=None, sa_type=UtcDateTime)
