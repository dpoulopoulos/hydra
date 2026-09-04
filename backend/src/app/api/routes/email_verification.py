from fastapi import APIRouter, status

from app.api.deps import EmailVerificationServiceDep, UserServiceDep
from app.exceptions import (
    EmailVerificationExpiredError,
    EmailVerificationNotFoundError,
    EmailVerificationTokenNotValidError,
    EmailVerificationUsedError,
    ServiceError,
)
from app.models import EmailVerificationConfirm, EmailVerificationRequest, Message

router = APIRouter(prefix="/email-verification", tags=["email-verification"])


def email_verification_exception_mappings() -> dict[type[ServiceError], int]:
    """Map service exceptions to appropriate HTTP status codes.

    Returns:
        A dictionary mapping exception types to HTTP status codes.
    """
    return {
        EmailVerificationNotFoundError: status.HTTP_404_NOT_FOUND,
        EmailVerificationExpiredError: status.HTTP_400_BAD_REQUEST,
        EmailVerificationUsedError: status.HTTP_400_BAD_REQUEST,
        EmailVerificationTokenNotValidError: status.HTTP_400_BAD_REQUEST,
    }


@router.post("/send", response_model=Message)
def resend_verification_email(
    *,
    email_verification_service: EmailVerificationServiceDep,
    user_service: UserServiceDep,
    email_verification_request: EmailVerificationRequest,
) -> Message:
    """Send or resend an email verification.

    For security reasons, this always returns success even if the email doesn't exist.
    This prevents user enumeration attacks.

    Args:
        email_verification_service: The email verification service dependency.
        user_service: The user service dependency.
        email_verification_request: The email verification request payload.

    Returns:
        A message indicating that the request was successful.
    """
    return email_verification_service.resend_verification_email(
        user_service=user_service, email=email_verification_request.email
    )


@router.post("/verify", response_model=Message)
def verify_email(
    *,
    email_verification_service: EmailVerificationServiceDep,
    user_service: UserServiceDep,
    email_verification_confirm: EmailVerificationConfirm,
) -> Message:
    """Verify a user's email address.

    Args:
        email_verification_service: The email verification service dependency.
        user_service: The user service dependency.
        email_verification_confirm: The email verification confirmation payload.

    Returns:
        A message indicating that the email was verified successfully.

    Raises:
        HTTPException: If the token is invalid (400), expired (400), already used (400), or not found (404).
    """
    return email_verification_service.verify_email(user_service=user_service, token=email_verification_confirm.token)
