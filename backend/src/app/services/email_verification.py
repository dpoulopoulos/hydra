import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
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
from app.models import EmailVerification, EmailVerificationStatus, Message, PendingEmailChange, User
from app.repositories.email_verification import EmailVerificationRepository
from app.services.email_outbox import EmailOutboxService
from app.services.user import UserService
from app.utils import generate_email_verification_email


class VerificationDelivery(StrEnum):
    """What became of a verification message once the outbox had it."""

    NOT_CONFIGURED = "not_configured"
    SENT = "sent"
    QUEUED = "queued"


def _delivery_message(delivery: VerificationDelivery, destination: str = "") -> Message:
    """Report what became of a verification message.

    Say what happened rather than what was hoped for: a message still in the
    outbox has not reached anyone yet, and telling a user it has sends them to
    look in an inbox that has nothing in it.

    Args:
        delivery: What the outbox did with the message.
        destination: A phrase naming where the message went, appended to the
            report when the account is not simply mailed at its own address.

    Returns:
        The message the caller is answered with.
    """
    if delivery is VerificationDelivery.NOT_CONFIGURED:
        return Message(message="Email delivery is not configured, so no verification email was sent.")

    if delivery is VerificationDelivery.QUEUED:
        return Message(message=f"Verification email queued for delivery{destination}.")

    return Message(message=f"Verification email sent{destination}.")


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

    def _outstanding_email_change(self, user: User) -> EmailVerification | None:
        """Find the change of address a user could still finish, if any.

        Only a change the user could still finish counts. A verification of
        the address the account already holds moves nothing, a link whose
        deadline has gone by cannot be redeemed, and a row asked for from an
        address the account has since left is refused at redemption time, so
        none of them is something to say the account is waiting on. Reporting
        and cancelling both answer for the same row, so they ask the same
        question here rather than each keeping its own idea of what is
        outstanding.

        Args:
            user: The account being asked about.

        Returns:
            The pending verification that would move the account, or None.
        """
        # Both kinds can be outstanding at once, so the lookup has to say
        # which it means: asking for whatever is pending would hand back an
        # activation as often as not, and call a live change of address none.
        pending_verification = self.email_verification_repository.get_pending_change_by_user_id(user.id)

        if not pending_verification or not pending_verification.new_email:
            return None

        if pending_verification.email != user.email:
            return None

        if pending_verification.expires_at < datetime.now(UTC):
            return None

        return pending_verification

    def get_pending_email_change(self, user: User) -> PendingEmailChange | None:
        """Report the change of address a user is waiting on, if any.

        Args:
            user: The account being asked about.

        Returns:
            The address the account is waiting on and the deadline on its
            link, or None when no change is outstanding.
        """
        pending_verification = self._outstanding_email_change(user)

        if not pending_verification or not pending_verification.new_email:
            return None

        return PendingEmailChange(new_email=pending_verification.new_email, expires_at=pending_verification.expires_at)

    def cancel_pending_email_change(self, user: User) -> Message:
        """Call off the change of address a user is waiting on.

        Expiring the row is all it takes: the account never moved, so there is
        nothing to put back, and the link that was mailed out stops working.
        Only a change the screen would have reported can be called off, so a
        pending activation is deliberately left alone: withdrawing one would
        leave an account with no way left to prove the address it holds.

        Args:
            user: The account calling the change off.

        Returns:
            Success message.

        Raises:
            EmailVerificationNotFoundError: If the account has no change of
                address outstanding.
        """
        pending_verification = self._outstanding_email_change(user)

        if not pending_verification:
            raise EmailVerificationNotFoundError from None

        self._mark_email_verification(
            email_verification_id=pending_verification.id, status=EmailVerificationStatus.EXPIRED
        )

        return Message(message="Email change cancelled.")

    def get_pending_activation_by_user_id(self, user_id: uuid.UUID) -> EmailVerification | None:
        """Get the pending verification that would activate a user's account.

        Args:
            user_id: The user ID to check.

        Returns:
            The pending activation if one exists, None otherwise. A pending
            change of address is not one: it proves an address the account has
            asked to move to, and says nothing about whether the account is
            waiting to be activated.
        """
        return self.email_verification_repository.get_pending_activation_by_user_id(user_id)

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

    def send_verification_email(
        self, user_service: UserService, user_email: str, invite_unusable: bool = False
    ) -> Message:
        """Send an email verification to a user.

        Args:
            user_service: A user service instance.
            user_email: The address to send the verification to.
            invite_unusable: Whether the signup carried an invitation that could not be applied. The
                verification email says so as well when it did, so that a signup sends one message
                whatever happened to its invitation and cannot be told apart by how long the send
                took.

        Returns:
            What became of the message: sent, queued for another attempt, or
            not sent at all because no provider is configured.

        Raises:
            UserNotFoundError: If the user is not found.
        """
        user = user_service.get_user_by_email(email=user_email)
        if not user:
            raise UserNotFoundError from None

        return _delivery_message(
            self._issue_verification(user=user, address=user.email, invite_unusable=invite_unusable)
        )

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
        return _delivery_message(
            self._issue_verification(user=user, address=new_email, new_email=new_email),
            destination=" to the new address",
        )

    def resend_pending_email_change(self, user: User) -> Message:
        """Send another link to the address a user has asked to move to.

        The address is read from the pending row rather than taken from the
        caller, so a resend can only ever reach the address the account already
        asked for, and cannot be aimed somewhere new without going through the
        profile form. Only a change the screen would have reported can be sent
        again, so a row that has lapsed is nothing to send rather than a fresh
        link for a request the account was already told was over.

        Args:
            user: The account asking for another link.

        Returns:
            What became of the message.

        Raises:
            EmailVerificationNotFoundError: If the account has no change of
                address outstanding, so there is nothing to send again.
        """
        pending_verification = self._outstanding_email_change(user)

        if not pending_verification or not pending_verification.new_email:
            raise EmailVerificationNotFoundError from None

        return self.send_email_change_verification(user=user, new_email=pending_verification.new_email)

    def _issue_verification(
        self, user: User, address: str, new_email: str | None = None, invite_unusable: bool = False
    ) -> VerificationDelivery:
        """Write a pending verification for a user and mail its token out.

        Args:
            user: The account the verification is issued for.
            address: The address the token is issued for and delivered to. It
                is the account's own address for an activation, and the
                requested one for a change of address.
            new_email: The address the account moves to once the token is
                redeemed, or None when the verification activates the account.
            invite_unusable: Whether the signup carried an invitation that could
                not be applied, which the message says so too.

        Returns:
            What became of the message: sent, queued for another attempt, or
            not sent at all because no provider is configured.
        """
        # Expire only what this verification replaces. The two kinds of row
        # answer different questions, so an activation must leave a pending
        # change standing: withdrawing it would let an account that was
        # disabled mid-change walk itself back to active by asking for a
        # resend, without an administrator.
        existing_verification = (
            self.email_verification_repository.get_pending_change_by_user_id(user.id)
            if new_email
            else self.email_verification_repository.get_pending_activation_by_user_id(user.id)
        )

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
        if not settings.emails_enabled:
            return VerificationDelivery.NOT_CONFIGURED

        email_data = generate_email_verification_email(email=address, token=token, invite_unusable=invite_unusable)
        delivered = EmailOutboxService.for_session(self.session).deliver_or_queue(
            email_to=address,
            subject=email_data.subject,
            html_content=email_data.html_content,
        )

        return VerificationDelivery.SENT if delivered else VerificationDelivery.QUEUED

    def resend_verification_email(self, user_service: UserService, email: str) -> Message:
        """Resend verification email.

        For security reasons, this always returns success even if the email doesn't exist.
        This prevents user enumeration attacks.

        Only sends email if:
        1. User exists and is not active
        2. User has a pending activation (was created via signup, not by admin)

        This prevents users from bypassing admin restrictions by requesting verification emails
        for accounts that were intentionally disabled by administrators.

        A pending change of address is not an activation and is deliberately not
        served here: this endpoint takes an address from an unauthenticated
        caller, and the account a change belongs to is signed in. Sending one
        from here would also mail an activation for the address the account
        currently holds, which is how a disabled account would get itself back.
        The signed-in resend endpoint serves a change instead.

        Args:
            user_service: A user service instance.
            email: The email address to resend verification to.

        Returns:
            Success message.
        """
        user = user_service.get_user_by_email(email=email)

        if user and not user.is_active:
            # Check if user has a pending activation
            # If they don't, it means they were created by admin and disabled, not via signup
            pending_activation = self.get_pending_activation_by_user_id(user.id)

            if pending_activation:
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
        if email_verification.expires_at < datetime.now(UTC):
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
