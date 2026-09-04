from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.api.deps import (
    get_current_active_superuser,
    get_current_user,
    get_password_reset_service,
    get_user_service,
)
from app.exceptions import UserNotAuthorizedError
from app.exceptions.password_exceptions import InvalidCredentialsError
from app.models import User
from app.repositories import PasswordResetRepository, UserRepository
from app.services import PasswordResetService, UserService


class TestGetUserService:
    """Test cases for get_user_service dependency."""

    def test_get_user_service_returns_service(self, mock_db_session: MagicMock, mock_user_repository: UserRepository):
        """Test that get_user_service returns a UserService instance."""
        # Act: Get user service with mock database session and repository
        result = get_user_service(mock_db_session, mock_user_repository)

        # Assert: Verify service is correct type and has correct session
        assert isinstance(result, UserService)
        assert result.session == mock_db_session
        assert result.user_repository == mock_user_repository


class TestGetPasswordResetService:
    """Test cases for get_password_reset_service dependency."""

    def test_get_password_reset_service_returns_service(
        self, mock_db_session: MagicMock, mock_password_reset_repository: PasswordResetRepository
    ):
        """Test that get_password_reset_service returns a PasswordResetService instance."""
        # Act: Get password reset service with mock database session and repository
        result = get_password_reset_service(mock_db_session, mock_password_reset_repository)

        # Assert: Verify service is correct type and has correct session
        assert isinstance(result, PasswordResetService)
        assert result.session == mock_db_session
        assert result.password_reset_repository == mock_password_reset_repository


class TestGetCurrentUser:
    """Test cases for get_current_user dependency."""

    def test_get_current_user_with_valid_token(
        self, mock_user_service: UserService, user_token: str, test_user: User
    ):
        """Test get_current_user with a valid token."""
        # Arrange: Mock user service to return test user
        mock_user_service.get_authenticated_user = MagicMock(return_value=test_user)

        # Act: Get current user with valid token
        result = get_current_user(mock_user_service, user_token)

        # Assert: Verify correct user is returned and service was called
        assert result == test_user
        mock_user_service.get_authenticated_user.assert_called_once()

    def test_get_current_user_with_malformed_token(
        self, mock_user_service: UserService
    ):
        """Test get_current_user with a malformed token."""
        # Arrange: Set up malformed token
        malformed_token = "not-a-jwt-token"

        # Act & Assert: Verify InvalidCredentialsError is raised
        with pytest.raises(InvalidCredentialsError):
            get_current_user(mock_user_service, malformed_token)

    @patch("app.api.deps.TokenPayload")
    @patch("app.api.deps.decode_token")
    def test_get_current_user_with_validation_error(
        self, mock_jwt_decode: MagicMock, mock_token_payload: MagicMock, mock_user_service: UserService
    ):
        """Test get_current_user when token payload fails validation."""
        # Arrange: Mock decode_token to return a valid payload and TokenPayload to raise ValidationError
        mock_jwt_decode.decode_token = {"sub": "some-id"}
        mock_token_payload.side_effect = ValidationError.from_exception_data(
            title="TokenPayload",
            line_errors=[
                {
                    "type": "missing",
                    "loc": ("sub",),
                    "input": {},
                }
            ],
        )

        # Act & Assert: Verify InvalidCredentialsError is raised for validation failure
        with pytest.raises(InvalidCredentialsError):
            get_current_user(mock_user_service, "some.token.here")

    def test_get_current_user_with_expired_token(
        self, mock_user_service: UserService, expired_user_token: str
    ):
        """Test get_current_user with an expired JWT token."""
        # Act & Assert: Verify InvalidCredentialsError is raised for expired token
        with pytest.raises(InvalidCredentialsError):
            get_current_user(mock_user_service, expired_user_token)


class TestGetCurrentActiveSuperuser:
    """Test cases for get_current_active_superuser dependency."""

    def test_get_current_active_superuser_with_superuser(self, test_superuser: User):
        """Test get_current_active_superuser with a valid superuser."""
        # Act: Get current active superuser with valid superuser
        result = get_current_active_superuser(test_superuser)

        # Assert: Verify superuser is returned and has correct privileges
        assert result == test_superuser
        assert result.is_superuser is True

    def test_get_current_active_superuser_with_regular_user(self, test_user: User):
        """Test get_current_active_superuser with a regular user raises error."""
        # Act & Assert: Verify UserNotAuthorizedError is raised for regular user
        with pytest.raises(UserNotAuthorizedError):
            get_current_active_superuser(test_user)
