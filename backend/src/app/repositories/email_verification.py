from uuid import UUID

from sqlalchemy import func
from sqlmodel import Session, col, select
from sqlmodel.sql.expression import SelectOfScalar

from app.models import EmailVerification, EmailVerificationStatus
from app.repositories.base import BaseRepository


class EmailVerificationRepository(BaseRepository[EmailVerification]):
    """Repository for EmailVerification database operations."""

    def __init__(self, session: Session) -> None:
        """Initialize the email verification repository.

        Args:
            session: The database session.
        """
        super().__init__(session, EmailVerification)

    def get_by_token(self, token: str) -> EmailVerification | None:
        """Get an email verification by token.

        Args:
            token: The email verification token.

        Returns:
            The email verification if found, None otherwise.
        """
        statement = select(EmailVerification).where(EmailVerification.token == token)
        return self.session.exec(statement).first()

    def _pending_for_user(self, user_id: UUID) -> SelectOfScalar[EmailVerification]:
        """Select the verifications of a user that are still redeemable.

        An account can have one of each kind outstanding at a time, and a
        lookup that takes the first of several rows has to say which first it
        means. Newest first: an account with more than one row of a kind got
        there by asking again, and the latest ask is the live one.

        Args:
            user_id: The user ID.

        Returns:
            A statement the kind-specific lookups narrow further.
        """
        return (
            select(EmailVerification)
            .where(EmailVerification.user_id == user_id, EmailVerification.status == EmailVerificationStatus.PENDING)
            .order_by(col(EmailVerification.created_at).desc())
        )

    def get_pending_by_user_id(self, user_id: UUID) -> EmailVerification | None:
        """Get the newest pending email verification for a user, of either kind.

        Callers that mean one kind should ask for it by name: both kinds can be
        outstanding at once, and this hands back whichever was asked for last.

        Args:
            user_id: The user ID.

        Returns:
            The pending email verification if found, None otherwise.
        """
        return self.session.exec(self._pending_for_user(user_id)).first()

    def get_pending_activation_by_user_id(self, user_id: UUID) -> EmailVerification | None:
        """Get the pending verification that would activate a user's account.

        An activation proves the address the account already holds, so its row
        names no other address. A row that names one stands for a change of
        address, which activates nothing.

        Args:
            user_id: The user ID.

        Returns:
            The pending activation if found, None otherwise.
        """
        statement = self._pending_for_user(user_id).where(col(EmailVerification.new_email).is_(None))
        return self.session.exec(statement).first()

    def get_pending_change_by_user_id(self, user_id: UUID) -> EmailVerification | None:
        """Get the pending verification that would move a user to another address.

        Args:
            user_id: The user ID.

        Returns:
            The pending change of address if found, None otherwise.
        """
        statement = self._pending_for_user(user_id).where(col(EmailVerification.new_email).is_not(None))
        return self.session.exec(statement).first()

    def has_verified(self, user_id: UUID, email: str) -> bool:
        """Report whether an account has proved that it holds an address.

        Compared case-insensitively: the row records the address as the account
        held it, while an invited address is normalised, so an equality
        comparison would miss the very proof being looked for.

        Args:
            user_id: The account.
            email: The address it is said to hold.

        Returns:
            True if that account has verified that address.
        """
        statement = select(EmailVerification).where(
            EmailVerification.user_id == user_id,
            func.lower(col(EmailVerification.email)) == email.lower(),
            EmailVerification.status == EmailVerificationStatus.VERIFIED,
        )
        return self.session.exec(statement).first() is not None

    def update_status(
        self, email_verification: EmailVerification, status: EmailVerificationStatus
    ) -> EmailVerification:
        """Update email verification status.

        Updates the status and flushes changes.
        Does NOT commit - caller must commit.

        Args:
            email_verification: The email verification entity to update.
            status: The new status.

        Returns:
            The updated email verification.
        """
        email_verification.status = status
        return self.save(email_verification)
