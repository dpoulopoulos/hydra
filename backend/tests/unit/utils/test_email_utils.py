from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.utils.email_utils import (
    EmailData,
    generate_email_verification_email,
    generate_new_account_email,
    generate_password_reset_email,
    send_email,
)


class TestGenerateNewAccountEmail:
    """Test the generate_new_account_email function."""

    def test_generate_new_account_email_returns_email_data(self) -> None:
        """Generate new account email returns EmailData with correct content."""
        # Arrange: Set up test data
        username = "newuser"

        # Act: Generate new account email
        result = generate_new_account_email(username=username)

        # Assert: Verify email data is correct
        assert isinstance(result, EmailData)
        assert result.subject == f"Welcome to {settings.PROJECT_NAME}!"
        assert username in result.html_content
        assert settings.FRONTEND_HOST in result.html_content
        assert settings.PROJECT_NAME in result.html_content

    def test_generate_new_account_email_includes_assets_base_url(self) -> None:
        """Generate new account email includes assets base URL in content."""
        # Arrange: Set up test data
        username = "newuser"

        # Act: Generate new account email
        result = generate_new_account_email(username=username)

        # Assert: Verify assets base URL is included
        assert settings.assets_base_url in result.html_content


class TestGeneratePasswordResetEmail:
    """Test the generate_password_reset_email function."""

    def test_generate_password_reset_email_returns_email_data(self) -> None:
        """Generate password reset email returns EmailData with correct content."""
        # Arrange: Set up test data
        email = "user@example.com"
        token = "reset-token-12345"

        # Act: Generate password reset email
        result = generate_password_reset_email(email=email, token=token)

        # Assert: Verify email data is correct
        assert isinstance(result, EmailData)
        assert result.subject == f"Password Reset - {settings.PROJECT_NAME}"
        assert email in result.html_content
        assert token in result.html_content
        assert f"{settings.FRONTEND_HOST}/reset-password?token={token}" in result.html_content
        assert settings.PROJECT_NAME in result.html_content

    def test_generate_password_reset_email_includes_assets_base_url(self) -> None:
        """Generate password reset email includes assets base URL in content."""
        # Arrange: Set up test data
        email = "user@example.com"
        token = "reset-token-12345"

        # Act: Generate password reset email
        result = generate_password_reset_email(email=email, token=token)

        # Assert: Verify assets base URL is included
        assert settings.assets_base_url in result.html_content


class TestGenerateEmailVerificationEmail:
    """Test the generate_email_verification_email function."""

    def test_generate_email_verification_email_returns_email_data(self) -> None:
        """Generate email verification email returns EmailData with correct content."""
        # Arrange: Set up test data
        email = "verify@example.com"
        token = "verify-token-12345"

        # Act: Generate email verification email
        result = generate_email_verification_email(email=email, token=token)

        # Assert: Verify email data is correct
        assert isinstance(result, EmailData)
        assert result.subject == f"Verify Your Email - {settings.PROJECT_NAME}"
        assert email in result.html_content
        assert token in result.html_content
        assert f"{settings.FRONTEND_HOST}/verify-email?token={token}" in result.html_content
        assert settings.PROJECT_NAME in result.html_content

    def test_generate_email_verification_email_includes_assets_base_url(self) -> None:
        """Generate email verification email includes assets base URL in content."""
        # Arrange: Set up test data
        email = "verify@example.com"
        token = "verify-token-12345"

        # Act: Generate email verification email
        result = generate_email_verification_email(email=email, token=token)

        # Assert: Verify assets base URL is included
        assert settings.assets_base_url in result.html_content


class TestSendEmail:
    """Test the send_email function."""

    def test_send_email_raises_assertion_error_when_emails_disabled(self, monkeypatch) -> None:
        """Send email raises AssertionError when emails are disabled."""
        # Arrange & Act & Assert: Verify assertion error is raised when emails are disabled
        monkeypatch.setattr(settings, "SMTP_HOST", None)

        with pytest.raises(AssertionError, match="no provided configuration for email variables"):
            send_email(
                email_to="test@example.com",
                subject="Test Subject",
                html_content="<p>Test content</p>",
            )

    @patch("app.utils.email_utils.Message")
    def test_send_email_with_tls(self, mock_message_class: MagicMock, monkeypatch) -> None:
        """Send email with TLS enabled."""
        # Arrange: Set up email settings with TLS
        monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
        monkeypatch.setattr(settings, "SMTP_PORT", 587)
        monkeypatch.setattr(settings, "SMTP_TLS", True)
        monkeypatch.setattr(settings, "SMTP_SSL", False)
        monkeypatch.setattr(settings, "SMTP_USER", "user@example.com")
        monkeypatch.setattr(settings, "SMTP_PASSWORD", "password123")
        monkeypatch.setattr(settings, "EMAILS_FROM_NAME", "Test Sender")
        monkeypatch.setattr(settings, "EMAILS_FROM_EMAIL", "from@example.com")

        mock_message = MagicMock()
        mock_message_class.return_value = mock_message

        # Act: Send email
        send_email(
            email_to="recipient@example.com",
            subject="Test Subject",
            html_content="<p>Test content</p>",
        )

        # Assert: Verify message was created and sent correctly
        mock_message_class.assert_called_once_with(
            subject="Test Subject",
            html="<p>Test content</p>",
            mail_from=("Test Sender", "from@example.com"),
        )

        mock_message.send.assert_called_once_with(
            to="recipient@example.com",
            smtp={
                "host": "smtp.example.com",
                "port": 587,
                "tls": True,
                "user": "user@example.com",
                "password": "password123",
            },
        )

    @patch("app.utils.email_utils.Message")
    def test_send_email_with_ssl(self, mock_message_class: MagicMock, monkeypatch) -> None:
        """Send email with SSL enabled."""
        # Arrange: Set up email settings with SSL
        monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
        monkeypatch.setattr(settings, "SMTP_PORT", 465)
        monkeypatch.setattr(settings, "SMTP_TLS", False)
        monkeypatch.setattr(settings, "SMTP_SSL", True)
        monkeypatch.setattr(settings, "SMTP_USER", "user@example.com")
        monkeypatch.setattr(settings, "SMTP_PASSWORD", "password123")
        monkeypatch.setattr(settings, "EMAILS_FROM_NAME", "Test Sender")
        monkeypatch.setattr(settings, "EMAILS_FROM_EMAIL", "from@example.com")

        mock_message = MagicMock()
        mock_message_class.return_value = mock_message

        # Act: Send email
        send_email(
            email_to="recipient@example.com",
            subject="Test Subject",
            html_content="<p>Test content</p>",
        )

        # Assert: Verify message was sent with SSL
        mock_message.send.assert_called_once_with(
            to="recipient@example.com",
            smtp={
                "host": "smtp.example.com",
                "port": 465,
                "ssl": True,
                "user": "user@example.com",
                "password": "password123",
            },
        )

    @patch("app.utils.email_utils.Message")
    def test_send_email_without_auth(self, mock_message_class: MagicMock, monkeypatch) -> None:
        """Send email without SMTP authentication."""
        # Arrange: Set up email settings without authentication
        monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
        monkeypatch.setattr(settings, "SMTP_PORT", 25)
        monkeypatch.setattr(settings, "SMTP_TLS", False)
        monkeypatch.setattr(settings, "SMTP_SSL", False)
        monkeypatch.setattr(settings, "SMTP_USER", None)
        monkeypatch.setattr(settings, "SMTP_PASSWORD", None)
        monkeypatch.setattr(settings, "EMAILS_FROM_NAME", "Test Sender")
        monkeypatch.setattr(settings, "EMAILS_FROM_EMAIL", "from@example.com")

        mock_message = MagicMock()
        mock_message_class.return_value = mock_message

        # Act: Send email
        send_email(
            email_to="recipient@example.com",
            subject="Test Subject",
            html_content="<p>Test content</p>",
        )

        # Assert: Verify message was sent without authentication
        mock_message.send.assert_called_once_with(
            to="recipient@example.com",
            smtp={
                "host": "smtp.example.com",
                "port": 25,
            },
        )

    @patch("app.utils.email_utils.Message")
    def test_send_email_with_user_without_password(self, mock_message_class: MagicMock, monkeypatch) -> None:
        """Send email with SMTP user but no password."""
        # Arrange: Set up email settings with user but no password
        monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
        monkeypatch.setattr(settings, "SMTP_PORT", 587)
        monkeypatch.setattr(settings, "SMTP_TLS", True)
        monkeypatch.setattr(settings, "SMTP_SSL", False)
        monkeypatch.setattr(settings, "SMTP_USER", "user@example.com")
        monkeypatch.setattr(settings, "SMTP_PASSWORD", None)
        monkeypatch.setattr(settings, "EMAILS_FROM_NAME", "Test Sender")
        monkeypatch.setattr(settings, "EMAILS_FROM_EMAIL", "from@example.com")

        mock_message = MagicMock()
        mock_message_class.return_value = mock_message

        # Act: Send email
        send_email(
            email_to="recipient@example.com",
            subject="Test Subject",
            html_content="<p>Test content</p>",
        )

        # Assert: Verify message was sent with user but no password
        mock_message.send.assert_called_once_with(
            to="recipient@example.com",
            smtp={
                "host": "smtp.example.com",
                "port": 587,
                "tls": True,
                "user": "user@example.com",
            },
        )
