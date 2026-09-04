from fastapi import APIRouter, status

from app.api.deps import PasswordResetServiceDep, UserServiceDep
from app.exceptions import (
    PasswordResetExpiredError,
    PasswordResetNotFoundError,
    PasswordResetTokenNotValidError,
    PasswordResetUsedError,
    ServiceError,
)
from app.models import Message, PasswordResetConfirm, PasswordResetRequest, PasswordResetVerify

router = APIRouter(prefix="/password-reset", tags=["password-reset"])


def password_reset_exception_mappings() -> dict[type[ServiceError], int]:
    """Map service exceptions to appropriate HTTP status codes.

    Returns:
        A dictionary mapping exception types to HTTP status codes.
    """
    return {
        PasswordResetNotFoundError: status.HTTP_404_NOT_FOUND,
        PasswordResetExpiredError: status.HTTP_400_BAD_REQUEST,
        PasswordResetUsedError: status.HTTP_400_BAD_REQUEST,
        PasswordResetTokenNotValidError: status.HTTP_400_BAD_REQUEST,
    }


@router.post("/request", response_model=Message)
def request_password_reset(
    *,
    password_reset_service: PasswordResetServiceDep,
    user_service: UserServiceDep,
    password_reset_in: PasswordResetRequest,
) -> Message:
    """Request a password reset.

    For security reasons, this always returns success even if the email doesn't exist.
    This prevents user enumeration attacks.

    Args:
        password_reset_service: The password reset service dependency.
        user_service: The user service dependency.
        password_reset_in: The password reset request payload.

    Returns:
        A message indicating that the request was successful.
    """
    return password_reset_service.request_password_reset(user_service=user_service, email=password_reset_in.email)


@router.post("/verify", response_model=Message)
def verify_password_reset_token(
    *, password_reset_service: PasswordResetServiceDep, password_reset_verify: PasswordResetVerify
) -> Message:
    """Verify a password reset token is valid.

    Args:
        password_reset_service: The password reset service dependency.
        password_reset_verify: The password reset verification payload.

    Returns:
        A message indicating that the token is valid.

    Raises:
        HTTPException: If the token is invalid (400), expired (400), used (400), or not found (404).
    """
    return password_reset_service.verify_token(token=password_reset_verify.token)


@router.post("/confirm", response_model=Message)
def confirm_password_reset(
    *,
    password_reset_service: PasswordResetServiceDep,
    user_service: UserServiceDep,
    password_reset_confirm: PasswordResetConfirm,
) -> Message:
    """Reset a user's password.

    Args:
        password_reset_service: The password reset service dependency.
        user_service: The user service dependency.
        password_reset_confirm: The password reset confirmation payload.

    Returns:
        A message indicating that the password was reset successfully.

    Raises:
        HTTPException: If the token is invalid (400), expired (400), used (400), or not found (404).
    """
    return password_reset_service.reset_password(
        user_service=user_service, token=password_reset_confirm.token, new_password=password_reset_confirm.new_password
    )
