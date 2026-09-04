import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.core.security import JWT, create_password_reset_token
from app.exceptions import (
    PasswordResetExpiredError,
    PasswordResetNotFoundError,
    PasswordResetTokenNotValidError,
    PasswordResetUsedError,
    UserNotFoundError,
)
from app.models import Message, PasswordReset, PasswordResetStatus, User
from app.services import PasswordResetService


class TestMarkPasswordReset:
    """Tests for the _mark_password_reset method."""

    def test_mark_password_reset_success(
        self, mock_password_reset_service: PasswordResetService
    ) -> None:
        """Test successfully marking a password reset."""
        # Arrange: Create a mock password reset
        password_reset_id = uuid.UUID("44444444-4444-4444-4444-444444444444")
        mock_password_reset = MagicMock(spec=PasswordReset)
        mock_password_reset.id = password_reset_id
        mock_password_reset.status = PasswordResetStatus.PENDING

        mock_password_reset_service.session.get = MagicMock(
            return_value=mock_password_reset
        )
        mock_password_reset_service.session.add = MagicMock()
        mock_password_reset_service.session.commit = MagicMock()
        mock_password_reset_service.session.refresh = MagicMock()

        # Act: Mark password reset as used
        mock_password_reset_service._mark_password_reset(
            password_reset_id=password_reset_id, status=PasswordResetStatus.USED
        )

        # Assert: Verify status was updated and database operations were called
        assert mock_password_reset.status == PasswordResetStatus.USED
        mock_password_reset_service.session.get.assert_called_once_with(
            PasswordReset, password_reset_id
        )
        mock_password_reset_service.session.add.assert_called_once_with(
            mock_password_reset
        )
        mock_password_reset_service.session.commit.assert_called_once()
        mock_password_reset_service.session.refresh.assert_called_once_with(
            mock_password_reset
        )

    def test_mark_password_reset_not_found(
        self, mock_password_reset_service: PasswordResetService
    ) -> None:
        """Test marking password reset when not found."""
        # Arrange: Mock database to return None
        password_reset_id = uuid.UUID("44444444-4444-4444-4444-444444444444")
        mock_password_reset_service.session.get = MagicMock(return_value=None)

        # Act & Assert: Verify PasswordResetNotFoundError is raised
        with pytest.raises(PasswordResetNotFoundError):
            mock_password_reset_service._mark_password_reset(
                password_reset_id=password_reset_id, status=PasswordResetStatus.USED
            )


class TestRequestPasswordReset:
    """Tests for the request_password_reset method."""

    def test_request_password_reset_user_exists(
        self,
        mock_password_reset_service: PasswordResetService,
        mock_user_service: MagicMock,
        test_user: User,
    ) -> None:
        """Test requesting password reset for existing user."""
        # Arrange: Mock user service to return test user
        mock_user_service.get_user_by_email = MagicMock(return_value=test_user)

        # Mock session.exec to return no existing pending resets
        mock_password_reset_service.session.exec = MagicMock()
        mock_password_reset_service.session.exec.return_value.first.return_value = None

        mock_password_reset_service.session.add = MagicMock()
        mock_password_reset_service.session.commit = MagicMock()
        mock_password_reset_service.session.refresh = MagicMock()

        # Act: Request password reset
        with patch("app.services.password_reset.settings") as mock_settings:
            mock_settings.emails_enabled = False
            result = mock_password_reset_service.request_password_reset(
                user_service=mock_user_service, email=test_user.email
            )

        # Assert: Verify success message is returned
        assert isinstance(result, Message)
        assert "If an account exists" in result.message
        mock_password_reset_service.session.add.assert_called_once()
        mock_password_reset_service.session.commit.assert_called_once()
        mock_password_reset_service.session.refresh.assert_called_once()

    def test_request_password_reset_with_existing_pending(
        self,
        mock_password_reset_service: PasswordResetService,
        mock_user_service: MagicMock,
        test_user: User,
    ) -> None:
        """Test requesting password reset when existing pending reset exists."""
        # Arrange: Mock user service to return test user
        mock_user_service.get_user_by_email = MagicMock(return_value=test_user)

        # Mock existing pending reset
        existing_reset = MagicMock(spec=PasswordReset)
        existing_reset.id = uuid.UUID("55555555-5555-5555-5555-555555555555")
        existing_reset.status = PasswordResetStatus.PENDING

        mock_password_reset_service.session.exec = MagicMock()
        mock_password_reset_service.session.exec.return_value.first.return_value = (
            existing_reset
        )

        # Mock _mark_password_reset
        mock_password_reset_service._mark_password_reset = MagicMock()

        mock_password_reset_service.session.get = MagicMock(return_value=existing_reset)
        mock_password_reset_service.session.add = MagicMock()
        mock_password_reset_service.session.commit = MagicMock()
        mock_password_reset_service.session.refresh = MagicMock()

        # Act: Request password reset
        with patch("app.services.password_reset.settings") as mock_settings:
            mock_settings.emails_enabled = False
            result = mock_password_reset_service.request_password_reset(
                user_service=mock_user_service, email=test_user.email
            )

        # Assert: Verify existing reset was marked as expired
        assert isinstance(result, Message)
        mock_password_reset_service._mark_password_reset.assert_called_once_with(
            password_reset_id=existing_reset.id, status=PasswordResetStatus.EXPIRED
        )

    def test_request_password_reset_user_not_found(
        self,
        mock_password_reset_service: PasswordResetService,
        mock_user_service: MagicMock,
    ) -> None:
        """Test requesting password reset for non-existent user."""
        # Arrange: Mock user service to return None
        mock_user_service.get_user_by_email = MagicMock(return_value=None)

        # Act: Request password reset for non-existent user
        result = mock_password_reset_service.request_password_reset(
            user_service=mock_user_service, email="nonexistent@example.com"
        )

        # Assert: Verify success message is returned (no user enumeration)
        assert isinstance(result, Message)
        assert "If an account exists" in result.message

    def test_request_password_reset_with_email_enabled(
        self,
        mock_password_reset_service: PasswordResetService,
        mock_user_service: MagicMock,
        test_user: User,
    ) -> None:
        """Test requesting password reset with email sending enabled."""
        # Arrange: Mock user service to return test user
        mock_user_service.get_user_by_email = MagicMock(return_value=test_user)

        mock_password_reset_service.session.exec = MagicMock()
        mock_password_reset_service.session.exec.return_value.first.return_value = None

        mock_password_reset_service.session.add = MagicMock()
        mock_password_reset_service.session.commit = MagicMock()
        mock_password_reset_service.session.refresh = MagicMock()

        # Act: Request password reset with emails enabled
        with patch("app.services.password_reset.settings") as mock_settings:
            mock_settings.emails_enabled = True
            with patch("app.services.password_reset.generate_password_reset_email") as mock_generate:
                with patch("app.services.password_reset.send_email") as mock_send:
                    mock_email_data = MagicMock()
                    mock_email_data.subject = "Reset your password"
                    mock_email_data.html_content = "<html>Reset link</html>"
                    mock_generate.return_value = mock_email_data

                    result = mock_password_reset_service.request_password_reset(
                        user_service=mock_user_service, email=test_user.email
                    )

                    # Assert: Verify email was sent
                    mock_generate.assert_called_once()
                    mock_send.assert_called_once()

    def test_request_password_reset_email_fails_silently(
        self,
        mock_password_reset_service: PasswordResetService,
        mock_user_service: MagicMock,
        test_user: User,
    ) -> None:
        """Test that email sending failures are handled silently."""
        # Arrange: Mock user service to return test user
        mock_user_service.get_user_by_email = MagicMock(return_value=test_user)

        mock_password_reset_service.session.exec = MagicMock()
        mock_password_reset_service.session.exec.return_value.first.return_value = None

        mock_password_reset_service.session.add = MagicMock()
        mock_password_reset_service.session.commit = MagicMock()
        mock_password_reset_service.session.refresh = MagicMock()

        # Act: Request password reset with email sending failure
        with patch("app.services.password_reset.settings") as mock_settings:
            mock_settings.emails_enabled = True
            with patch("app.services.password_reset.send_email") as mock_send:
                mock_send.side_effect = Exception("Email sending failed")

                result = mock_password_reset_service.request_password_reset(
                    user_service=mock_user_service, email=test_user.email
                )

                # Assert: Verify success message is returned despite email failure
                assert isinstance(result, Message)
                assert "If an account exists" in result.message


class TestVerifyTokenMethod:
    """Tests for the verify_token method."""

    def test_verify_token_success(
        self, mock_password_reset_service: PasswordResetService, test_user: User
    ) -> None:
        """Test successfully verifying a password reset token."""
        # Arrange: Create a valid token and mock password reset
        email = test_user.email
        token = create_password_reset_token(subject=email)

        mock_password_reset = MagicMock(spec=PasswordReset)
        mock_password_reset.id = uuid.UUID("44444444-4444-4444-4444-444444444444")
        mock_password_reset.status = PasswordResetStatus.PENDING
        mock_password_reset.expires_at = datetime.now(UTC) + timedelta(hours=1)
        mock_password_reset.token = token

        mock_password_reset_service.session.exec = MagicMock()
        mock_password_reset_service.session.exec.return_value.first.return_value = (
            mock_password_reset
        )

        # Act: Verify the token
        result = mock_password_reset_service.verify_token(token=token)

        # Assert: Verify success message is returned
        assert isinstance(result, Message)
        assert result.message == "Token is valid."

    def test_verify_token_not_found(
        self, mock_password_reset_service: PasswordResetService
    ) -> None:
        """Test verifying token when password reset not found."""
        # Arrange: Create a valid token but mock no password reset in DB
        token = create_password_reset_token(subject="test@example.com")

        mock_password_reset_service.session.exec = MagicMock()
        mock_password_reset_service.session.exec.return_value.first.return_value = None

        # Act & Assert: Verify PasswordResetNotFoundError is raised
        with pytest.raises(PasswordResetNotFoundError):
            mock_password_reset_service.verify_token(token=token)

    def test_verify_token_used(
        self, mock_password_reset_service: PasswordResetService
    ) -> None:
        """Test verifying a token that has already been used."""
        # Arrange: Create token and mock used password reset
        token = create_password_reset_token(subject="test@example.com")

        mock_password_reset = MagicMock(spec=PasswordReset)
        mock_password_reset.status = PasswordResetStatus.USED

        mock_password_reset_service.session.exec = MagicMock()
        mock_password_reset_service.session.exec.return_value.first.return_value = (
            mock_password_reset
        )

        # Act & Assert: Verify PasswordResetUsedError is raised
        with pytest.raises(PasswordResetUsedError):
            mock_password_reset_service.verify_token(token=token)

    def test_verify_token_expired_status(
        self, mock_password_reset_service: PasswordResetService
    ) -> None:
        """Test verifying a token with expired status."""
        # Arrange: Create token and mock expired password reset
        token = create_password_reset_token(subject="test@example.com")

        mock_password_reset = MagicMock(spec=PasswordReset)
        mock_password_reset.status = PasswordResetStatus.EXPIRED

        mock_password_reset_service.session.exec = MagicMock()
        mock_password_reset_service.session.exec.return_value.first.return_value = (
            mock_password_reset
        )

        # Act & Assert: Verify PasswordResetExpiredError is raised
        with pytest.raises(PasswordResetExpiredError):
            mock_password_reset_service.verify_token(token=token)

    def test_verify_token_expired_by_time(
        self, mock_password_reset_service: PasswordResetService
    ) -> None:
        """Test verifying a token that has expired by time."""
        # Arrange: Create token and mock password reset with past expiration
        token = create_password_reset_token(subject="test@example.com")
        password_reset_id = uuid.UUID("44444444-4444-4444-4444-444444444444")

        mock_password_reset = MagicMock(spec=PasswordReset)
        mock_password_reset.id = password_reset_id
        mock_password_reset.status = PasswordResetStatus.PENDING
        mock_password_reset.expires_at = datetime.now(UTC) - timedelta(hours=1)

        mock_password_reset_service.session.exec = MagicMock()
        mock_password_reset_service.session.exec.return_value.first.return_value = (
            mock_password_reset
        )

        # Mock _mark_password_reset
        mock_password_reset_service._mark_password_reset = MagicMock()

        # Act & Assert: Verify PasswordResetExpiredError is raised
        with pytest.raises(PasswordResetExpiredError):
            mock_password_reset_service.verify_token(token=token)

        # Verify token was marked as expired
        mock_password_reset_service._mark_password_reset.assert_called_once_with(
            password_reset_id=password_reset_id, status=PasswordResetStatus.EXPIRED
        )

    def test_verify_token_expired_by_time_naive_datetime(
        self, mock_password_reset_service: PasswordResetService
    ) -> None:
        """Test verifying a token with naive datetime expiration that converts to UTC."""
        # Arrange: Create token and mock password reset with naive datetime
        token = create_password_reset_token(subject="test@example.com")
        password_reset_id = uuid.UUID("44444444-4444-4444-4444-444444444444")

        mock_password_reset = MagicMock(spec=PasswordReset)
        mock_password_reset.id = password_reset_id
        mock_password_reset.status = PasswordResetStatus.PENDING
        # Use naive datetime (no timezone) set to a future time to verify timezone handling works
        mock_password_reset.expires_at = datetime.now() + timedelta(hours=1)

        mock_password_reset_service.session.exec = MagicMock()
        mock_password_reset_service.session.exec.return_value.first.return_value = (
            mock_password_reset
        )

        # Act: Verify the token succeeds with naive datetime conversion
        result = mock_password_reset_service.verify_token(token=token)

        # Assert: Verify token is valid when naive datetime is converted properly
        assert isinstance(result, Message)
        assert result.message == "Token is valid."

    def test_verify_token_invalid_token_format(
        self, mock_password_reset_service: PasswordResetService
    ) -> None:
        """Test verifying an invalid token format."""
        # Arrange: Use invalid token
        invalid_token = "invalid_token"

        # Act & Assert: Verify PasswordResetTokenNotValidError is raised
        with pytest.raises(PasswordResetTokenNotValidError):
            mock_password_reset_service.verify_token(token=invalid_token)


class TestResetPassword:
    """Tests for the reset_password method."""

    def test_reset_password_success(
        self,
        mock_password_reset_service: PasswordResetService,
        mock_user_service: MagicMock,
        test_user: User,
    ) -> None:
        """Test successfully resetting a password."""
        # Arrange: Create valid token and mock password reset
        email = test_user.email
        token = create_password_reset_token(subject=email)
        password_reset_id = uuid.UUID("44444444-4444-4444-4444-444444444444")

        mock_password_reset = MagicMock(spec=PasswordReset)
        mock_password_reset.id = password_reset_id
        mock_password_reset.status = PasswordResetStatus.PENDING
        mock_password_reset.expires_at = datetime.now(UTC) + timedelta(hours=1)
        mock_password_reset.token = token

        # Mock verify_token to succeed
        mock_password_reset_service.verify_token = MagicMock(
            return_value=Message(message="Token is valid.")
        )

        mock_password_reset_service.session.exec = MagicMock()
        mock_password_reset_service.session.exec.return_value.first.return_value = (
            mock_password_reset
        )

        mock_user_service.get_user_by_email = MagicMock(return_value=test_user)

        mock_password_reset_service.session.add = MagicMock()
        mock_password_reset_service._mark_password_reset = MagicMock()

        # Act: Reset password
        with patch("app.services.password_reset.get_password_hash") as mock_hash:
            mock_hash.return_value = "new_hashed_password"
            result = mock_password_reset_service.reset_password(
                user_service=mock_user_service,
                token=token,
                new_password="newpassword123",
            )

        # Assert: Verify password was reset
        assert isinstance(result, Message)
        assert result.message == "Password reset successfully."
        assert test_user.hashed_password == "new_hashed_password"
        mock_password_reset_service._mark_password_reset.assert_called_once_with(
            password_reset_id=password_reset_id, status=PasswordResetStatus.USED
        )

    def test_reset_password_user_not_found(
        self,
        mock_password_reset_service: PasswordResetService,
        mock_user_service: MagicMock,
    ) -> None:
        """Test resetting password when user not found."""
        # Arrange: Create valid token but user doesn't exist
        email = "nonexistent@example.com"
        token = create_password_reset_token(subject=email)

        mock_password_reset = MagicMock(spec=PasswordReset)
        mock_password_reset.token = token

        mock_password_reset_service.verify_token = MagicMock(
            return_value=Message(message="Token is valid.")
        )

        mock_password_reset_service.session.exec = MagicMock()
        mock_password_reset_service.session.exec.return_value.first.return_value = (
            mock_password_reset
        )

        mock_user_service.get_user_by_email = MagicMock(return_value=None)

        # Act & Assert: Verify UserNotFoundError is raised
        with pytest.raises(UserNotFoundError):
            mock_password_reset_service.reset_password(
                user_service=mock_user_service,
                token=token,
                new_password="newpassword123",
            )

    def test_reset_password_invalid_token(
        self,
        mock_password_reset_service: PasswordResetService,
        mock_user_service: MagicMock,
    ) -> None:
        """Test resetting password with invalid token."""
        # Arrange: Use invalid token
        invalid_token = "invalid_token"

        mock_password_reset_service.verify_token = MagicMock(
            side_effect=PasswordResetTokenNotValidError
        )

        # Act & Assert: Verify PasswordResetTokenNotValidError is raised
        with pytest.raises(PasswordResetTokenNotValidError):
            mock_password_reset_service.reset_password(
                user_service=mock_user_service,
                token=invalid_token,
                new_password="newpassword123",
            )

    def test_reset_password_expired_token(
        self,
        mock_password_reset_service: PasswordResetService,
        mock_user_service: MagicMock,
    ) -> None:
        """Test resetting password with expired token."""
        # Arrange: Create expired token
        token = create_password_reset_token(subject="test@example.com")

        mock_password_reset_service.verify_token = MagicMock(
            side_effect=PasswordResetExpiredError
        )

        # Act & Assert: Verify PasswordResetExpiredError is raised
        with pytest.raises(PasswordResetExpiredError):
            mock_password_reset_service.reset_password(
                user_service=mock_user_service,
                token=token,
                new_password="newpassword123",
            )

    def test_reset_password_used_token(
        self,
        mock_password_reset_service: PasswordResetService,
        mock_user_service: MagicMock,
    ) -> None:
        """Test resetting password with used token."""
        # Arrange: Create used token
        token = create_password_reset_token(subject="test@example.com")

        mock_password_reset_service.verify_token = MagicMock(
            side_effect=PasswordResetUsedError
        )

        # Act & Assert: Verify PasswordResetUsedError is raised
        with pytest.raises(PasswordResetUsedError):
            mock_password_reset_service.reset_password(
                user_service=mock_user_service,
                token=token,
                new_password="newpassword123",
            )
