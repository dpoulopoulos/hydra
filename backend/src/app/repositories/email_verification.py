from uuid import UUID

from sqlmodel import Session, select

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
