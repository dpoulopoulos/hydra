import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from app.core.config import settings
from app.core.security import (
    TokenType,
    create_password_reset_token,
    decode_token,
    get_password_hash,
    verify_typed_token,
)
from app.exceptions import (
    PasswordResetExpiredError,
    PasswordResetNotFoundError,
    PasswordResetTokenNotValidError,
    PasswordResetUsedError,
    UserNotFoundError,
)
from app.models import Message, PasswordReset, PasswordResetStatus
from app.repositories.password_reset import PasswordResetRepository
from app.services.email_outbox import EmailOutboxService
from app.services.user import UserService
from app.utils import generate_password_reset_email


class PasswordResetService:
    """Provide services for password reset management."""

    def __init__(self, session: Session, password_reset_repository: PasswordResetRepository) -> None:
        """Initialize the password reset service.

        Args:
            session: The database session.
            password_reset_repository: The password reset repository instance.
        """
        self.session = session
        self.password_reset_repository = password_reset_repository

    def _mark_password_reset(self, password_reset_id: uuid.UUID, status: PasswordResetStatus) -> None:
        """Mark password reset with a specific status.

        Args:
            password_reset_id: The password reset ID.
            status: The password reset status.

        Raises:
            PasswordResetNotFoundError: If the password reset is not found.
        """
        password_reset = self.password_reset_repository.get_by_id(password_reset_id)
        if not password_reset:
            raise PasswordResetNotFoundError from None

        self.password_reset_repository.update_status(password_reset, status)
        self.session.commit()

    def invalidate_pending_for_user(self, user_id: uuid.UUID) -> None:
        """Expire the pending password reset of a user, if there is one.

        Args:
            user_id: The user whose pending reset is no longer redeemable.
        """
        pending_reset = self.password_reset_repository.get_pending_by_user_id(user_id)
        if pending_reset:
            self._mark_password_reset(password_reset_id=pending_reset.id, status=PasswordResetStatus.EXPIRED)

    def request_password_reset(self, user_service: UserService, email: str) -> Message:
        """Request a password reset.

        For security reasons, this always returns success even if the email doesn't exist.
        This prevents user enumeration attacks.

        Args:
            user_service: A user service instance.
            email: The email address to send the password reset to.

        Returns:
            Success message.
        """
        user = user_service.get_user_by_email(email=email)

        if user:
            existing_reset = self.password_reset_repository.get_pending_by_user_id(user.id)

            # Mark existing pending resets as expired and create a new one
            if existing_reset:
                self._mark_password_reset(password_reset_id=existing_reset.id, status=PasswordResetStatus.EXPIRED)

            token = create_password_reset_token(subject=email)

            password_reset = PasswordReset(
                email=email,
                user_id=user.id,
                status=PasswordResetStatus.PENDING,
                expires_at=datetime.now(UTC) + timedelta(hours=settings.EMAIL_PASSWORD_RESET_TOKEN_EXPIRE_HOURS),
                token=token,
            )

            password_reset = self.password_reset_repository.save(password_reset)
            self.session.commit()

            # A delivery failure is queued rather than raised: the reset row is
            # already committed, and the reply below says nothing about whether
            # the address resolved to a user, so there is nothing to reveal.
            if settings.emails_enabled:
                email_data = generate_password_reset_email(email=email, token=token)
                EmailOutboxService.for_session(self.session).deliver_or_queue(
                    email_to=email,
                    subject=email_data.subject,
                    html_content=email_data.html_content,
                )

        return Message(message="If an account exists with this email, you will receive password reset instructions.")

    def verify_token(self, token: str) -> Message:
        """Verify a password reset token is valid.

        Args:
            token: The password reset token.

        Returns:
            Success message.

        Raises:
            PasswordResetTokenNotValidError: If the token is invalid.
            PasswordResetNotFoundError: If the password reset is not found.
            PasswordResetExpiredError: If the password reset has expired.
            PasswordResetUsedError: If the password reset has already been used.
        """
        verify_typed_token(token, TokenType.PASSWORD_RESET, PasswordResetTokenNotValidError)

        password_reset = self.password_reset_repository.get_by_token(token)

        if not password_reset:
            raise PasswordResetNotFoundError from None

        if password_reset.status == PasswordResetStatus.USED:
            raise PasswordResetUsedError from None

        if password_reset.status == PasswordResetStatus.EXPIRED:
            raise PasswordResetExpiredError from None

        # Check if token has expired
        if password_reset.expires_at < datetime.now(UTC):
            self._mark_password_reset(password_reset_id=password_reset.id, status=PasswordResetStatus.EXPIRED)
            raise PasswordResetExpiredError from None

        return Message(message="Token is valid.")

    def reset_password(self, user_service: UserService, token: str, new_password: str) -> Message:
        """Reset a user's password.

        Args:
            user_service: A user service instance.
            token: The password reset token.
            new_password: The new password.

        Returns:
            Success message.

        Raises:
            PasswordResetTokenNotValidError: If the token is invalid.
            PasswordResetNotFoundError: If the password reset is not found.
            PasswordResetExpiredError: If the password reset has expired.
            PasswordResetUsedError: If the password reset has already been used.
            UserNotFoundError: If the user is not found.
        """
        self.verify_token(token)

        decoded_token = decode_token(token, expected_type=TokenType.PASSWORD_RESET)

        password_reset = self.password_reset_repository.get_by_token(token)
        if not password_reset:
            raise PasswordResetNotFoundError from None

        # The row names the account the reset was issued for. Looking the
        # account up by the token's subject instead would hand the reset to
        # whoever holds that address at redemption time, and addresses change
        # hands: release one with a reset still pending and the next holder's
        # account is what the old token would rewrite.
        if not password_reset.user_id:
            raise UserNotFoundError from None

        user = user_service.user_repository.get_by_id(password_reset.user_id)
        if not user:
            raise UserNotFoundError from None

        # The subject is only ever cross-checked, never resolved: a reset whose
        # address the account no longer holds is no longer about that account.
        if decoded_token["sub"] != user.email:
            raise PasswordResetTokenNotValidError from None

        user.hashed_password = get_password_hash(new_password)
        user_service.user_repository.save(user)

        self._mark_password_reset(password_reset_id=password_reset.id, status=PasswordResetStatus.USED)

        return Message(message="Password reset successfully.")
