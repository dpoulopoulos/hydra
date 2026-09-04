from uuid import UUID

from sqlalchemy import func
from sqlmodel import Session, col, select

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

    def get_pending_by_user_id(self, user_id: UUID) -> EmailVerification | None:
        """Get a pending email verification for a user.

        Args:
            user_id: The user ID.

        Returns:
            The pending email verification if found, None otherwise.
        """
        statement = select(EmailVerification).where(
            EmailVerification.user_id == user_id, EmailVerification.status == EmailVerificationStatus.PENDING
        )
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
