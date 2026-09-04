import inspect
import re
from collections.abc import Callable
from typing import Any
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


class TestSendEmailViaResend:
    """Test send_email when the provider is Resend."""

    @pytest.fixture(autouse=True)
    def _resend_settings(self, monkeypatch) -> None:
        """Point the settings at Resend, with a key and a sender."""
        monkeypatch.setattr(settings, "EMAIL_PROVIDER", "resend")
        monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test_key")
        monkeypatch.setattr(settings, "EMAILS_FROM_EMAIL", "from@example.com")
        monkeypatch.setattr(settings, "EMAILS_FROM_NAME", "Test Sender")

    def test_send_email_raises_assertion_error_without_api_key(self, monkeypatch) -> None:
        """Send email raises AssertionError when the Resend key is missing."""
        # Arrange: Take the key away, which is all that enables the provider
        monkeypatch.setattr(settings, "RESEND_API_KEY", None)

        # Act & Assert: Verify assertion error is raised when emails are disabled
        with pytest.raises(AssertionError, match="no provided configuration for email variables"):
            send_email(
                email_to="recipient@example.com",
                subject="Test Subject",
                html_content="<p>Test content</p>",
            )

    @patch("app.utils.email_utils.httpx.post")
    def test_send_email_posts_to_resend(self, mock_post: MagicMock) -> None:
        """Send email posts the message to the Resend API."""
        # Act: Send email
        send_email(
            email_to="recipient@example.com",
            subject="Test Subject",
            html_content="<p>Test content</p>",
        )

        # Assert: Verify the request carries the key, the sender and the message
        mock_post.assert_called_once_with(
            "https://api.resend.com/emails",
            headers={"Authorization": "Bearer re_test_key"},
            json={
                "from": "Test Sender <from@example.com>",
                "to": ["recipient@example.com"],
                "subject": "Test Subject",
                "html": "<p>Test content</p>",
            },
            timeout=10,
        )
        mock_post.return_value.raise_for_status.assert_called_once()

    @patch("app.utils.email_utils.httpx.post")
    def test_send_email_omits_display_name_when_unset(self, mock_post: MagicMock, monkeypatch) -> None:
        """Send email sends a bare address when there is no display name."""
        # Arrange: Drop the display name
        monkeypatch.setattr(settings, "EMAILS_FROM_NAME", None)

        # Act: Send email
        send_email(
            email_to="recipient@example.com",
            subject="Test Subject",
            html_content="<p>Test content</p>",
        )

        # Assert: Verify the sender is the address on its own
        assert mock_post.call_args.kwargs["json"]["from"] == "from@example.com"

    @patch("app.utils.email_utils.Message")
    @patch("app.utils.email_utils.httpx.post")
    def test_send_email_does_not_use_smtp(self, mock_post: MagicMock, mock_message_class: MagicMock) -> None:
        """Send email leaves SMTP alone when the provider is Resend."""
        # Act: Send email
        send_email(
            email_to="recipient@example.com",
            subject="Test Subject",
            html_content="<p>Test content</p>",
        )

        # Assert: Verify no message was built for a mail server
        mock_post.assert_called_once()
        mock_message_class.assert_not_called()


class TestDocstringsMatchSignatures:
    """Test that the documented parameters exist.

    Neither ruff nor mypy compares a docstring's ``Args:`` section against the signature it describes, so a
    parameter can be renamed or dropped without anything failing. These tests close that gap for the email
    generators, whose docstrings are the only description a caller gets of what ends up in a message.
    """

    @staticmethod
    def _documented_args(func: Callable[..., Any]) -> list[str]:
        """Collect the parameter names listed in a Google-style ``Args:`` section."""
        docstring = inspect.getdoc(func) or ""
        lines = docstring.splitlines()
        if "Args:" not in lines:
            return []
        body = lines[lines.index("Args:") + 1 :]
        names = []
        for line in body:
            if not line.startswith("    "):  # The section ends at the next unindented line.
                break
            match = re.match(r"    (\w+):", line)
            if match:
                names.append(match.group(1))
        return names

    @pytest.mark.parametrize(
        "func",
        [
            generate_new_account_email,
            generate_password_reset_email,
            generate_email_verification_email,
            send_email,
        ],
    )
    def test_documented_args_match_signature(self, func: Callable[..., Any]) -> None:
        """Every generator documents exactly the parameters it accepts."""
        # Arrange: Read the parameters the function actually takes
        expected = [name for name in inspect.signature(func).parameters]

        # Act: Read the parameters the docstring claims it takes
        documented = self._documented_args(func)

        # Assert: Verify the docstring describes this signature and no other
        assert documented == expected
