import smtplib
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.utils.email_utils import (
    EmailData,
    generate_email_verification_email,
    generate_new_account_email,
    generate_password_reset_email,
    generate_signup_attempt_email,
    mask_email,
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


class TestGenerateSignupAttemptEmail:
    """Test the generate_signup_attempt_email function."""

    def test_generate_signup_attempt_email_returns_email_data(self) -> None:
        """Generate signup attempt email returns EmailData with correct content."""
        # Arrange: Set up test data
        email = "existing@example.com"

        # Act: Generate the notice sent to an address that already has an account
        result = generate_signup_attempt_email(email=email)

        # Assert: Verify email data is correct
        assert isinstance(result, EmailData)
        assert result.subject == f"Your Account - {settings.PROJECT_NAME}"
        assert email in result.html_content
        assert f"{settings.FRONTEND_HOST}/login" in result.html_content
        assert f"{settings.FRONTEND_HOST}/forgot-password" in result.html_content
        assert settings.PROJECT_NAME in result.html_content

    def test_generate_signup_attempt_email_mentions_a_waiting_invitation(self) -> None:
        """Generate signup attempt email says the invitation is still waiting when there was one."""
        # Arrange: Set up test data
        email = "existing@example.com"

        # Act: Generate the notice for an attempt that followed an invitation link
        result = generate_signup_attempt_email(email=email, invited=True)

        # Assert: Verify the invitation is mentioned, and is left out when there was none
        assert "invitation" in result.html_content
        assert "invitation" not in generate_signup_attempt_email(email=email).html_content

    def test_generate_signup_attempt_email_includes_assets_base_url(self) -> None:
        """Generate signup attempt email includes assets base URL in content."""
        # Arrange: Set up test data
        email = "existing@example.com"

        # Act: Generate the notice sent to an address that already has an account
        result = generate_signup_attempt_email(email=email)

        # Assert: Verify assets base URL is included
        assert settings.assets_base_url in result.html_content


class TestGenerateEmailVerificationEmailWithUnusableInvite:
    """Test the invitation paragraph of the email verification email."""

    def test_verification_email_says_the_invitation_was_not_applied(self) -> None:
        """The verification email carries the news about a dropped invitation itself."""
        # Act: Generate the message a signup with an unusable invitation gets
        result = generate_email_verification_email(
            email="invited@example.com", token="verification-token", invite_unusable=True
        )

        # Assert: Verify it still verifies the address and mentions the invitation as well
        assert isinstance(result, EmailData)
        assert result.subject == f"Verify Your Email - {settings.PROJECT_NAME}"
        assert "verification-token" in result.html_content
        assert "invitation" in result.html_content

    def test_verification_email_does_not_say_which_reason_applied(self) -> None:
        """The invitation paragraph lists the possible reasons instead of naming one."""
        # Act: Generate the message a signup with an unusable invitation gets
        result = generate_email_verification_email(
            email="invited@example.com", token="verification-token", invite_unusable=True
        )

        # Assert: Verify every possibility is offered, so the message tells the sender nothing
        assert "may have expired" in result.html_content
        assert "may already have been used" in result.html_content
        assert "sent to a different address" in result.html_content

    def test_verification_email_omits_the_invitation_paragraph_by_default(self) -> None:
        """An ordinary signup gets the verification email with nothing about an invitation."""
        # Act: Generate the message an ordinary signup gets
        result = generate_email_verification_email(email="newuser@example.com", token="verification-token")

        # Assert: Verify the invitation is not mentioned at all
        assert "invitation" not in result.html_content


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
    def test_send_email_raises_what_the_mail_server_refused_with(
        self, mock_message_class: MagicMock, monkeypatch
    ) -> None:
        """A mail server that never took the message must not read as delivered."""
        # Arrange: The library reports a refusal in its return value, not by raising
        monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
        monkeypatch.setattr(settings, "EMAILS_FROM_EMAIL", "from@example.com")

        response = MagicMock()
        response.success = False
        response.error = ConnectionRefusedError("[Errno 111] Connection refused")
        mock_message_class.return_value.send.return_value = response

        # Act & Assert: Verify the refusal reaches the caller as a delivery error
        with pytest.raises(ConnectionRefusedError, match="Connection refused"):
            send_email(
                email_to="recipient@example.com",
                subject="Test Subject",
                html_content="<p>Test content</p>",
            )

    @patch("app.utils.email_utils.Message")
    def test_send_email_raises_when_the_mail_server_only_gives_a_status(
        self, mock_message_class: MagicMock, monkeypatch
    ) -> None:
        """A rejection without an exception behind it is still a rejection."""
        # Arrange: The server answered, and what it said was no
        monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
        monkeypatch.setattr(settings, "EMAILS_FROM_EMAIL", "from@example.com")

        response = MagicMock()
        response.success = False
        response.error = None
        response.status_code = 451
        response.status_text = "Requested action aborted"
        mock_message_class.return_value.send.return_value = response

        # Act & Assert: Verify the caller sees a delivery failure with the reason
        with pytest.raises(smtplib.SMTPException, match="451"):
            send_email(
                email_to="recipient@example.com",
                subject="Test Subject",
                html_content="<p>Test content</p>",
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


class TestMaskEmail:
    """Tests for mask_email."""

    def test_keeps_only_the_first_character_and_the_domain(self) -> None:
        """Enough to recognise your own address, not enough to learn somebody else's."""
        assert mask_email("partner@example.com") == "p*****@example.com"

    def test_hides_how_long_the_local_part_is(self) -> None:
        """A variable number of stars would narrow the guess down."""
        assert mask_email("jo@example.com") == "j*****@example.com"
        assert mask_email("a-very-long-address@example.com") == "a*****@example.com"

    def test_masks_a_single_character_local_part_entirely(self) -> None:
        assert mask_email("a@example.com") == "*****@example.com"

    def test_masks_a_string_that_is_not_an_address(self) -> None:
        """It is only ever fed stored addresses, but it must not leak one if it is not."""
        assert mask_email("not-an-address") == "*****"
