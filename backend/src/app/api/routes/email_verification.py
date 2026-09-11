from fastapi import APIRouter, status

from app.api.deps import (
    CurrentUser,
    EmailVerificationServiceDep,
    HouseholdServiceDep,
    MailRateLimitServiceDep,
    SourceAddressDep,
    UserServiceDep,
)
from app.exceptions import (
    EmailVerificationExpiredError,
    EmailVerificationNotFoundError,
    EmailVerificationTokenNotValidError,
    EmailVerificationUsedError,
    ServiceError,
    UserExistsError,
)
from app.models import EmailVerificationConfirm, EmailVerificationRequest, Message, PendingEmailChange
from app.services.email_verification import VERIFICATION_RESEND_MESSAGE

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
        UserExistsError: status.HTTP_409_CONFLICT,
    }


@router.post("/send", response_model=Message)
def resend_verification_email(
    *,
    email_verification_service: EmailVerificationServiceDep,
    user_service: UserServiceDep,
    mail_rate_limit_service: MailRateLimitServiceDep,
    source_address: SourceAddressDep,
    email_verification_request: EmailVerificationRequest,
) -> Message:
    """Send or resend an email verification.

    For security reasons, this always returns success even if the email doesn't exist.
    This prevents user enumeration attacks.

    Nobody is signed in and the body names the mailbox, so an unbounded endpoint would mail whoever
    it was pointed at, as fast as it was asked. Once a budget is spent nothing is sent, and the
    caller is told what it would have been told anyway: a refusal of its own would say that the
    address had asked for a link recently, which the shared reply exists to keep quiet about.

    Args:
        email_verification_service: The email verification service dependency.
        user_service: The user service dependency.
        mail_rate_limit_service: The mail rate limit service dependency, which
            bounds how much mail this endpoint can be made to send.
        source_address: The address the request came from.
        email_verification_request: The email verification request payload.

    Returns:
        A message indicating that the request was successful.
    """
    if not mail_rate_limit_service.allows_mail(source=source_address, recipient=email_verification_request.email):
        return Message(message=VERIFICATION_RESEND_MESSAGE)

    return email_verification_service.resend_verification_email(
        user_service=user_service, email=email_verification_request.email
    )


@router.post("/me/send", response_model=Message)
def send_verification_email_me(
    *,
    email_verification_service: EmailVerificationServiceDep,
    user_service: UserServiceDep,
    current_user: CurrentUser,
) -> Message:
    """Send a confirmation email for the address the current account holds.

    The public resend endpoint serves only accounts that are waiting to be
    activated, so an active account has no way to prove the address it holds
    now. Two kinds of account need one: those an administrator created, which
    are active without ever having been sent a confirmation, and those that
    changed their address, whose earlier confirmation proves an address they no
    longer hold. Until they have a proof, anything that asks for one is out of
    reach, including redeeming a household invitation.

    Requesting it needs no payload: the address is the one on the caller's own
    account, so this can neither be aimed at somebody else's mailbox nor used
    to find out whose addresses exist.

    Args:
        email_verification_service: The email verification service dependency.
        user_service: The user service dependency.
        current_user: The current authenticated user.

    Returns:
        A message indicating that the confirmation email was sent.

    Raises:
        HTTPException: If the user's token is invalid (401), the user is not found (404),
            or the user is inactive (403).
    """
    return email_verification_service.send_verification_email(user_service=user_service, user_email=current_user.email)


@router.get("/me/email-change", response_model=PendingEmailChange | None)
def get_pending_email_change_me(
    *,
    email_verification_service: EmailVerificationServiceDep,
    current_user: CurrentUser,
) -> PendingEmailChange | None:
    """Report the change of address the current account is waiting on.

    Asking to change the address does not move the account: it mails a link to
    the new address and waits. Nothing else says so once the reply to that
    request is gone, which leaves an account that mistyped the address with no
    sign that the link went somewhere it cannot read.

    Args:
        email_verification_service: The email verification service dependency.
        current_user: The current authenticated user.

    Returns:
        The address the account is waiting on, or null when no change is
        outstanding.

    Raises:
        HTTPException: If the user's token is invalid (401), the user is not found (404),
            or the user is inactive (403).
    """
    return email_verification_service.get_pending_email_change(user=current_user)


@router.delete("/me/email-change", response_model=Message)
def cancel_pending_email_change_me(
    *,
    email_verification_service: EmailVerificationServiceDep,
    current_user: CurrentUser,
) -> Message:
    """Call off the change of address the current account is waiting on.

    Until now the only ways out of a change asked for by mistake were to ask
    for another one or to wait the link out. Cancelling expires the pending
    row, so the link stops working straight away.

    Args:
        email_verification_service: The email verification service dependency.
        current_user: The current authenticated user.

    Returns:
        A message indicating that the pending change was called off.

    Raises:
        HTTPException: If the account has no change of address outstanding (404),
            the user's token is invalid (401), or the user is inactive (403).
    """
    return email_verification_service.cancel_pending_email_change(user=current_user)


@router.post("/me/email-change/resend", response_model=Message)
def resend_pending_email_change_me(
    *,
    email_verification_service: EmailVerificationServiceDep,
    current_user: CurrentUser,
) -> Message:
    """Send another link to the address the current account has asked to move to.

    The unauthenticated resend endpoint serves activations only: a change
    belongs to an account that is signed in, and serving one from there would
    mail an activation for the address the account currently holds. Here the
    caller is known, so the pending change is read off their own account and
    nothing has to be named — there is no address to guess at and none to
    enumerate.

    Args:
        email_verification_service: The email verification service dependency.
        current_user: The current authenticated user.

    Returns:
        A message saying what became of the email.

    Raises:
        HTTPException: If the account has asked for no change of address (404).
    """
    return email_verification_service.resend_pending_email_change(user=current_user)


@router.post("/verify", response_model=Message)
def verify_email(
    *,
    email_verification_service: EmailVerificationServiceDep,
    user_service: UserServiceDep,
    household_service: HouseholdServiceDep,
    email_verification_confirm: EmailVerificationConfirm,
) -> Message:
    """Verify a user's email address.

    A token issued for a change of address moves the account to that address.

    Args:
        email_verification_service: The email verification service dependency.
        user_service: The user service dependency.
        household_service: The household service dependency, which claims the
            invitations sent to the address now that it has been proved.
        email_verification_confirm: The email verification confirmation payload.

    Returns:
        A message indicating that the email was verified successfully.

    Raises:
        HTTPException: If the token is invalid (400), expired (400), already used (400), not found (404),
            or another account holds the address the change would move to (409).
    """
    return email_verification_service.verify_email(
        user_service=user_service,
        token=email_verification_confirm.token,
        invite_claimer=household_service,
    )
