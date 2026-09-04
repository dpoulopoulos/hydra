from sqlmodel import SQLModel

from .email_verification import (
    EmailVerification,
    EmailVerificationConfirm,
    EmailVerificationPublic,
    EmailVerificationRequest,
    EmailVerificationStatus,
)
from .household import (
    Household,
    HouseholdBase,
    HouseholdContext,
    HouseholdCreate,
    HouseholdMember,
    HouseholdMemberBase,
    HouseholdMemberPublic,
    HouseholdMembersPublic,
    HouseholdMemberUpdate,
    HouseholdPublic,
    HouseholdRole,
    HouseholdUpdate,
)
from .password import (
    PasswordReset,
    PasswordResetConfirm,
    PasswordResetPublic,
    PasswordResetRequest,
    PasswordResetStatus,
    PasswordResetVerify,
    PasswordUpdate,
)
from .token import Token, TokenPayload
from .user import (
    User,
    UserBase,
    UserCreate,
    UserPublic,
    UserRegister,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
)


class Message(SQLModel):
    message: str


__all__ = [
    "Message",
    "EmailVerification",
    "EmailVerificationConfirm",
    "EmailVerificationPublic",
    "EmailVerificationRequest",
    "EmailVerificationStatus",
    "Household",
    "HouseholdBase",
    "HouseholdContext",
    "HouseholdCreate",
    "HouseholdMember",
    "HouseholdMemberBase",
    "HouseholdMemberPublic",
    "HouseholdMemberUpdate",
    "HouseholdMembersPublic",
    "HouseholdPublic",
    "HouseholdRole",
    "HouseholdUpdate",
    "PasswordUpdate",
    "PasswordReset",
    "PasswordResetConfirm",
    "PasswordResetPublic",
    "PasswordResetRequest",
    "PasswordResetStatus",
    "PasswordResetVerify",
    "Token",
    "TokenPayload",
    "User",
    "UserBase",
    "UserCreate",
    "UserPublic",
    "UserRegister",
    "UsersPublic",
    "UserUpdate",
    "UserUpdateMe",
]
