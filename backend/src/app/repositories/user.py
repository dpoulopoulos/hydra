from collections.abc import Sequence

from sqlmodel import Session, col, func, select

from app.models import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Repository for User database operations."""

    def __init__(self, session: Session) -> None:
        """Initialize the user repository.

        Args:
            session: The database session.
        """
        super().__init__(session, User)

    def get_by_email(self, email: str) -> User | None:
        """Get a user by email address.

        Args:
            email: The user's email address.

        Returns:
            The user if found, None otherwise.
        """
        statement = select(User).where(User.email == email)
        return self.session.exec(statement).first()

    def get_by_email_ignoring_case(self, email: str) -> User | None:
        """Get a user by email address, whatever case either side is stored in.

        Addresses are stored as they were typed, so a caller that has
        normalised one cannot match with an equality comparison.

        Args:
            email: The user's email address.

        Returns:
            The user if found, None otherwise.
        """
        statement = select(User).where(func.lower(col(User.email)) == email.lower())
        return self.session.exec(statement).first()

    def get_all_paginated(self, skip: int = 0, limit: int = 100) -> tuple[Sequence[User], int]:
        """Get all users with pagination.

        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.

        Returns:
            Tuple of (users, total_count).
        """
        count_statement = select(func.count()).select_from(User)
        count = self.session.exec(count_statement).one()

        statement = select(User).offset(skip).limit(limit)
        users = self.session.exec(statement).all()

        return users, count
