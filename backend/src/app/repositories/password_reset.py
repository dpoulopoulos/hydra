from uuid import UUID

from sqlmodel import Session, select

from app.models import PasswordReset, PasswordResetStatus
from app.repositories.base import BaseRepository


class PasswordResetRepository(BaseRepository[PasswordReset]):
    """Repository for PasswordReset database operations."""

    def __init__(self, session: Session) -> None:
        """Initialize the password reset repository.

        Args:
            session: The database session.
        """
        super().__init__(session, PasswordReset)

    def get_by_token(self, token: str) -> PasswordReset | None:
        """Get a password reset by token.

        Args:
            token: The password reset token.

        Returns:
            The password reset if found, None otherwise.
        """
        statement = select(PasswordReset).where(PasswordReset.token == token)
        return self.session.exec(statement).first()

    def get_pending_by_user_id(self, user_id: UUID) -> PasswordReset | None:
        """Get a pending password reset for a user.

        Args:
            user_id: The user ID.

        Returns:
            The pending password reset if found, None otherwise.
        """
        statement = select(PasswordReset).where(
            PasswordReset.user_id == user_id, PasswordReset.status == PasswordResetStatus.PENDING
        )
        return self.session.exec(statement).first()

    def update_status(self, password_reset: PasswordReset, status: PasswordResetStatus) -> PasswordReset:
        """Update password reset status.

        Updates the status and flushes changes.
        Does NOT commit - caller must commit.

        Args:
            password_reset: The password reset entity to update.
            status: The new status.

        Returns:
            The updated password reset.
        """
        password_reset.status = status
        return self.save(password_reset)
