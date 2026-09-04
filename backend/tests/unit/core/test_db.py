from unittest.mock import MagicMock

from app.core.config import settings
from app.core.db import init_db
from app.models import User, UserCreate
from app.services import UserService


class TestInitDb:
    """Test the init_db function."""

    def test_init_db_with_existing_superuser(
        self, mock_user_service: UserService, test_superuser: User
    ):
        """Test that init_db does not create a superuser when one already exists."""
        # Arrange: Mock the service to return an existing superuser
        mock_user_service.get_user_by_email = MagicMock(return_value=test_superuser)
        mock_user_service.create_user = MagicMock()

        # Act: Call init_db
        init_db(user_service=mock_user_service)

        # Assert: Verify get_user_by_email was called with the correct email
        mock_user_service.get_user_by_email.assert_called_once_with(
            email=settings.FIRST_SUPERUSER
        )

        # Assert: Verify create_user was NOT called since superuser exists
        mock_user_service.create_user.assert_not_called()

    def test_init_db_creates_superuser_when_none_exists(
        self, mock_user_service: UserService, test_superuser: User
    ):
        """Test that init_db creates a superuser when none exists."""
        # Arrange: Mock the service to return None (no existing superuser)
        mock_user_service.get_user_by_email = MagicMock(return_value=None)
        mock_user_service.create_user = MagicMock(return_value=test_superuser)

        # Act: Call init_db
        init_db(user_service=mock_user_service)

        # Assert: Verify get_user_by_email was called with the correct email
        mock_user_service.get_user_by_email.assert_called_once_with(
            email=settings.FIRST_SUPERUSER
        )

        # Assert: Verify create_user was called with the correct parameters
        mock_user_service.create_user.assert_called_once()

        # Get the actual UserCreate object passed to create_user
        call_args = mock_user_service.create_user.call_args
        user_create_arg = call_args.kwargs["user_create"]

        # Verify the UserCreate object has the correct values
        assert isinstance(user_create_arg, UserCreate)
        assert user_create_arg.email == settings.FIRST_SUPERUSER
        assert user_create_arg.password == settings.FIRST_SUPERUSER_PASSWORD
        assert user_create_arg.is_superuser is True
