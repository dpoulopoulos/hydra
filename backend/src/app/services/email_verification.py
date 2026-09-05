import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlmodel import Session

from app.core.config import settings
from app.core.security import TokenType, create_email_verification_token, verify_typed_token
from app.exceptions import (
    EmailVerificationExpiredError,
    EmailVerificationNotFoundError,
    EmailVerificationTokenNotValidError,
    EmailVerificationUsedError,
    UserExistsError,
    UserNotFoundError,
)
from app.models import EmailVerification, EmailVerificationStatus, Message, User
from app.repositories.email_verification import EmailVerificationRepository
from app.services.email_outbox import EmailOutboxService
from app.services.user import UserService
from app.utils import generate_email_verification_email


class InviteClaimer(Protocol):
    """The part of the household service that verifying an address depends on.

    Typed as a protocol so this service does not import the household service,
    which would make the two mutually dependent.
    """

    def claim_invites_for_verified_email(self, user: User) -> None:
        """Point the invites sent to a user's address at their account, without committing.

        Args:
            user: The user who has just proved they hold the address.
        """
        ...


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

    def invalidate_pending_for_user(self, user_id: uuid.UUID) -> None:
        """Expire the pending email verification of a user, if there is one.

        Args:
            user_id: The user whose pending verification is no longer redeemable.
        """
        pending_verification = self.email_verification_repository.get_pending_by_user_id(user_id)
        if pending_verification:
            self._mark_email_verification(
                email_verification_id=pending_verification.id, status=EmailVerificationStatus.EXPIRED
            )

    def send_verification_email(self, user_service: UserService, user_email: str) -> Message:
        """Send an email verification to a user.

        Args:
            user_service: A user service instance.
            user_email: The email address to send the verification to.

        Returns:
            Success message.

        Raises:
            UserNotFoundError: If the user is not found.
        """
        user = user_service.get_user_by_email(email=user_email)
        if not user:
            raise UserNotFoundError from None

        self._issue_verification(user=user, address=user.email)

        return Message(message="Verification email sent successfully.")

    def send_email_change_verification(self, user: User, new_email: str) -> Message:
        """Send a verification to an address a user has asked to move to.

        The account keeps its current address until the token is redeemed, so
        an address nobody has proven can reach is never one a security flow
        will deliver to.

        Args:
            user: The account asking for the change.
            new_email: The address the account wants to move to.

        Returns:
            Success message.
        """
        self._issue_verification(user=user, address=new_email, new_email=new_email)

        return Message(message="Verification email sent to the new address.")

    def _issue_verification(self, user: User, address: str, new_email: str | None = None) -> None:
        """Write a pending verification for a user and mail its token out.

        Args:
            user: The account the verification is issued for.
            address: The address the token is issued for and delivered to. It
                is the account's own address for an activation, and the
                requested one for a change of address.
            new_email: The address the account moves to once the token is
                redeemed, or None when the verification activates the account.
        """
        # Mark existing pending verifications as expired
        existing_verification = self.email_verification_repository.get_pending_by_user_id(user.id)

        if existing_verification:
            self._mark_email_verification(
                email_verification_id=existing_verification.id, status=EmailVerificationStatus.EXPIRED
            )

        token = create_email_verification_token(subject=address)

        email_verification = EmailVerification(
            email=user.email,
            new_email=new_email,
            user_id=user.id,
            status=EmailVerificationStatus.PENDING,
            expires_at=datetime.now(UTC) + timedelta(hours=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS),
            token=token,
        )

        email_verification = self.email_verification_repository.save(email_verification)
        self.session.commit()

        # The verification row is committed by now, so a provider that is down
        # must not turn this into a 500: the caller would retry, expire the row
        # it just created and write another one for mail that never leaves. The
        # outbox keeps the message instead, and it is retried from there.
        if settings.emails_enabled:
            email_data = generate_email_verification_email(email=address, token=token)
            EmailOutboxService.for_session(self.session).deliver_or_queue(
                email_to=address,
                subject=email_data.subject,
                html_content=email_data.html_content,
            )

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

    def verify_email(
        self, user_service: UserService, token: str, invite_claimer: InviteClaimer | None = None
    ) -> Message:
        """Verify a user's email address.

        A verification issued for a change of address moves the account to that
        address; one issued for an account's own address activates it.

        Args:
            user_service: A user service instance.
            token: The email verification token.
            invite_claimer: The household service, which hands the invitations
                sent to the address over to the account that just proved it.

        Returns:
            Success message.

        Raises:
            EmailVerificationTokenNotValidError: If the token is invalid.
            EmailVerificationNotFoundError: If the email verification is not found.
            EmailVerificationExpiredError: If the email verification has expired.
            EmailVerificationUsedError: If the email verification has already been used.
            UserNotFoundError: If the user is not found.
            UserExistsError: If another account holds the address a change would move to.
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

        # The row names the account the verification was issued for. Looking
        # the account up by the token's subject instead would activate whoever
        # holds that address at redemption time, so a stale token could stand
        # in for a proof the present holder never gave.
        user = user_service.user_repository.get_by_id(email_verification.user_id)
        if not user:
            raise UserNotFoundError from None

        if email_verification.new_email:
            return self._redeem_address_change(
                user_service=user_service,
                email_verification=email_verification,
                user=user,
                subject=decoded_token["sub"],
            )

        # The subject is only ever cross-checked, never resolved: a
        # verification of an address the account no longer holds proves
        # nothing about the address it holds now.
        if decoded_token["sub"] != user.email:
            raise EmailVerificationTokenNotValidError from None

        # Mark email verification as verified
        self._mark_email_verification(
            email_verification_id=email_verification.id, status=EmailVerificationStatus.VERIFIED
        )

        # Activate user account
        user.is_active = True
        user_service.user_repository.save(user)

        # The mailbox is proved as of now, so an invitation sent to it is one
        # this account may redeem. Nothing else establishes that: an address on
        # a profile is a claim, not a proof.
        if invite_claimer:
            invite_claimer.claim_invites_for_verified_email(user=user)

        self.session.commit()

        return Message(message="Email verified successfully. Your account is now active.")

    def _redeem_address_change(
        self,
        user_service: UserService,
        email_verification: EmailVerification,
        user: User,
        subject: str,
    ) -> Message:
        """Move an account to the address a redeemed verification proves.

        Args:
            user_service: A user service instance.
            email_verification: The verification row being redeemed, which
                names the address the account is moving to.
            user: The account the row was issued for.
            subject: The address the token was issued for.

        Returns:
            Success message.

        Raises:
            EmailVerificationTokenNotValidError: If the token was issued for
                another address, or the account has moved on since the change
                was asked for.
            UserExistsError: If another account holds the new address by now.
        """
        # What a change of address has to prove is the new address, so that is
        # what the token names. `email` is the address the account held when
        # the change was asked for: an account that has moved since is no
        # longer the one this row describes, and its holder never asked to end
        # up here.
        if subject != email_verification.new_email or email_verification.email != user.email:
            raise EmailVerificationTokenNotValidError from None

        # The address was free when the change was asked for, which says
        # nothing about now: a token redeemed hours later must not walk an
        # account onto an address someone else registered in between.
        existing_user = user_service.get_user_by_email(email=email_verification.new_email)
        if existing_user and existing_user.id != user.id:
            raise UserExistsError(user=existing_user) from None

        self._mark_email_verification(
            email_verification_id=email_verification.id, status=EmailVerificationStatus.VERIFIED
        )

        # Only the address moves. Whether the account is active is a separate
        # question, and a proof of address is not an answer to it.
        user.email = email_verification.new_email
        user_service.user_repository.save(user)
        self.session.commit()

        return Message(message="Email address updated successfully.")
