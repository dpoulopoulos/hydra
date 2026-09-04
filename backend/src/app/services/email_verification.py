import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from app.core.config import settings
from app.core.security import TokenType, create_email_verification_token, verify_typed_token
from app.exceptions import (
    EmailVerificationExpiredError,
    EmailVerificationNotFoundError,
    EmailVerificationTokenNotValidError,
    EmailVerificationUsedError,
    UserNotFoundError,
)
from app.models import EmailVerification, EmailVerificationStatus, Message
from app.repositories.email_verification import EmailVerificationRepository
from app.services.user import UserService
from app.utils import generate_email_verification_email, send_email

EXPIRATION_TIME = datetime.now(UTC) + timedelta(hours=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS)


class EmailVerificationService:
    """Provide services for email verification management."""

    def __init__(self, session: Session, email_verification_repository: EmailVerificationRepository) -> None:
        """Initialize the email verification service.

        Args:
            session: The database session.
            email_verification_repository: The email verification repository instance.
        """
        self.session = session
        self.email_verification_repository = email_verification_repository

    def _mark_email_verification(self, email_verification_id: uuid.UUID, status: EmailVerificationStatus) -> None:
        """Mark email verification with a specific status.

        Args:
            email_verification_id: The email verification ID.
            status: The email verification status.

        Raises:
            EmailVerificationNotFoundError: If the email verification is not found.
        """
        email_verification = self.email_verification_repository.get_by_id(email_verification_id)
        if not email_verification:
            raise EmailVerificationNotFoundError from None

        self.email_verification_repository.update_status(email_verification, status)
        self.session.commit()

    def get_pending_verification_by_user_id(self, user_id: uuid.UUID) -> EmailVerification | None:
        """Get a pending email verification for a user.

        Args:
            user_id: The user ID to check.

        Returns:
            The pending email verification if one exists, None otherwise.
        """
        return self.email_verification_repository.get_pending_by_user_id(user_id)

    def send_verification_email(self, user_service: UserService, user_email: str) -> Message:
        """Send an email verification to a user.

        Args:
            user_service: A user service instance.
            user_id: The user ID to send the verification to.

        Returns:
            Success message.

        Raises:
            UserNotFoundError: If the user is not found.
        """
        user = user_service.get_user_by_email(email=user_email)
        if not user:
            raise UserNotFoundError from None

        # Mark existing pending verifications as expired
        existing_verification = self.email_verification_repository.get_pending_by_user_id(user.id)

        if existing_verification:
            self._mark_email_verification(
                email_verification_id=existing_verification.id, status=EmailVerificationStatus.EXPIRED
            )

        token = create_email_verification_token(subject=user.email)

        email_verification = EmailVerification(
            email=user.email,
            user_id=user.id,
            status=EmailVerificationStatus.PENDING,
            expires_at=EXPIRATION_TIME,
            token=token,
        )

        email_verification = self.email_verification_repository.save(email_verification)
        self.session.commit()

        # Send email
        if settings.emails_enabled:
            email_data = generate_email_verification_email(email=user.email, token=token)
            send_email(
                email_to=user.email,
                subject=email_data.subject,
                html_content=email_data.html_content,
            )

        return Message(message="Verification email sent successfully.")

    def resend_verification_email(self, user_service: UserService, email: str) -> Message:
        """Resend verification email.

        For security reasons, this always returns success even if the email doesn't exist.
        This prevents user enumeration attacks.

        Only sends email if:
        1. User exists and is not active
        2. User has a pending email verification (was created via signup, not by admin)

        This prevents users from bypassing admin restrictions by requesting verification emails
        for accounts that were intentionally disabled by administrators.

        Args:
            user_service: A user service instance.
            email: The email address to resend verification to.

        Returns:
            Success message.
        """
        user = user_service.get_user_by_email(email=email)

        if user and not user.is_active:
            # Check if user has a pending verification
            # If they don't, it means they were created by admin and disabled, not via signup
            pending_verification = self.get_pending_verification_by_user_id(user.id)

            if pending_verification:
                try:
                    self.send_verification_email(user_service=user_service, user_email=user.email)
                except Exception:
                    # Silently fail to not reveal if email exists
                    pass

        return Message(
            message=(
                "If an account exists with this email and requires verification, "
                "you will receive verification instructions."
            )
        )

    def verify_email(self, user_service: UserService, token: str) -> Message:
        """Verify a user's email address.

        Args:
            user_service: A user service instance.
            token: The email verification token.

        Returns:
            Success message.

        Raises:
            EmailVerificationTokenNotValidError: If the token is invalid.
            EmailVerificationNotFoundError: If the email verification is not found.
            EmailVerificationExpiredError: If the email verification has expired.
            EmailVerificationUsedError: If the email verification has already been used.
            UserNotFoundError: If the user is not found.
        """
        decoded_token = verify_typed_token(token, TokenType.EMAIL_VERIFICATION, EmailVerificationTokenNotValidError)

        email_verification = self.email_verification_repository.get_by_token(token)

        if not email_verification:
            raise EmailVerificationNotFoundError from None

        if email_verification.status == EmailVerificationStatus.VERIFIED:
            raise EmailVerificationUsedError from None

        if email_verification.status == EmailVerificationStatus.EXPIRED:
            raise EmailVerificationExpiredError from None

        # Check if token has expired
        expires_at = email_verification.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)

        if expires_at < datetime.now(UTC):
            self._mark_email_verification(
                email_verification_id=email_verification.id, status=EmailVerificationStatus.EXPIRED
            )
            raise EmailVerificationExpiredError from None

        # Mark email verification as verified
        self._mark_email_verification(
            email_verification_id=email_verification.id, status=EmailVerificationStatus.VERIFIED
        )

        # Activate user account
        email = decoded_token["sub"]
        user = user_service.get_user_by_email(email=email)
        if not user:
            raise UserNotFoundError from None

        user.is_active = True
        user_service.user_repository.save(user)
        self.session.commit()

        return Message(message="Email verified successfully. Your account is now active.")
