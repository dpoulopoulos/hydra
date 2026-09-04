from .base_exceptions import ServiceError
from .category_exceptions import (
    CategoryDepthExceededError,
    CategoryExistsError,
    CategoryInUseError,
    CategoryKindMismatchError,
    CategoryNotFoundError,
    CategorySelfParentError,
    SystemCategoryError,
)
from .email_verification_exceptions import (
    EmailVerificationExpiredError,
    EmailVerificationNotFoundError,
    EmailVerificationTokenNotValidError,
    EmailVerificationUsedError,
)
from .household_exceptions import (
    HouseholdMemberExistsError,
    HouseholdMemberNotFoundError,
    HouseholdMembershipNotFoundError,
    HouseholdNotFoundError,
    HouseholdRoleRequiredError,
    LastHouseholdOwnerError,
)
from .password_exceptions import (
    InvalidCredentialsError,
    PasswordIsWrongError,
    PasswordResetExpiredError,
    PasswordResetNotFoundError,
    PasswordResetTokenNotValidError,
    PasswordResetUsedError,
    PasswordUnmodifiedError,
)
from .user_exceptions import (
    DeleteSuperUserError,
    UserExistsError,
    UserNotActiveError,
    UserNotAuthorizedError,
    UserNotFoundError,
)

__all__ = [
    "ServiceError",
    "CategoryDepthExceededError",
    "CategoryExistsError",
    "CategoryInUseError",
    "CategoryKindMismatchError",
    "CategoryNotFoundError",
    "CategorySelfParentError",
    "SystemCategoryError",
    "EmailVerificationExpiredError",
    "EmailVerificationNotFoundError",
    "EmailVerificationTokenNotValidError",
    "EmailVerificationUsedError",
    "HouseholdMemberExistsError",
    "HouseholdMemberNotFoundError",
    "HouseholdMembershipNotFoundError",
    "HouseholdNotFoundError",
    "HouseholdRoleRequiredError",
    "LastHouseholdOwnerError",
    "PasswordUnmodifiedError",
    "PasswordIsWrongError",
    "PasswordResetExpiredError",
    "PasswordResetNotFoundError",
    "PasswordResetTokenNotValidError",
    "PasswordResetUsedError",
    "DeleteSuperUserError",
    "InvalidCredentialsError",
    "UserExistsError",
    "UserNotActiveError",
    "UserNotAuthorizedError",
    "UserNotFoundError",
]
