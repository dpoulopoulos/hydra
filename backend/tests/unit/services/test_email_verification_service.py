import logging
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import httpx
import jwt
import pytest

from app.core.config import settings
from app.core.security import ALGORITHM, JWT, create_email_verification_token
from app.exceptions import (
    EmailVerificationExpiredError,
    EmailVerificationNotFoundError,
    EmailVerificationTokenNotValidError,
    EmailVerificationUsedError,
    UserExistsError,
    UserNotFoundError,
)
from app.models import EmailVerification, EmailVerificationStatus, Message, User
from app.services import EmailVerificationService, UserService


@pytest.fixture
def test_email_verification(test_user: User) -> EmailVerification:
    """Create a test email verification.

    Args:
        test_user: The test user.

    Returns:
        A test email verification instance.
    """
    verification = EmailVerification(
        email=test_user.email,
        user_id=test_user.id,
        status=EmailVerificationStatus.PENDING,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        token="test_verification_token",
    )
    verification.id = uuid.UUID("44444444-4444-4444-4444-444444444444")
    return verification


@pytest.fixture
def pending_email_change(test_user: User) -> EmailVerification:
    """Create a pending change of address.

    Args:
        test_user: The test user.

    Returns:
        A pending verification that would move the account to another address.
    """
    verification = EmailVerification(
        email=test_user.email,
        new_email="moved@example.com",
        user_id=test_user.id,
        status=EmailVerificationStatus.PENDING,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        token="pending_change_token",
    )
    verification.id = uuid.UUID("77777777-7777-7777-7777-777777777777")
    return verification


@pytest.fixture
def expired_email_verification(test_user: User) -> EmailVerification:
    """Create an expired email verification.

    Args:
        test_user: The test user.

    Returns:
        An expired email verification instance.
    """
    verification = EmailVerification(
        email=test_user.email,
        user_id=test_user.id,
        status=EmailVerificationStatus.EXPIRED,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
        token="expired_verification_token",
    )
    verification.id = uuid.UUID("55555555-5555-5555-5555-555555555555")
    return verification


@pytest.fixture
def verified_email_verification(test_user: User) -> EmailVerification:
    """Create a verified email verification.

    Args:
        test_user: The test user.

    Returns:
        A verified email verification instance.
    """
    verification = EmailVerification(
        email=test_user.email,
        user_id=test_user.id,
        status=EmailVerificationStatus.VERIFIED,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        token="verified_verification_token",
    )
    verification.id = uuid.UUID("66666666-6666-6666-6666-666666666666")
    return verification


class TestMarkEmailVerification:
    """Tests for the _mark_email_verification private method."""

    def test_mark_email_verification_success(
        self,
        mock_email_verification_service: EmailVerificationService,
        test_email_verification: EmailVerification,
    ) -> None:
        """Test successfully marking an email verification with a status."""
        # Arrange
        mock_email_verification_service.session.get.return_value = test_email_verification

        # Act
        mock_email_verification_service._mark_email_verification(
            test_email_verification.id, EmailVerificationStatus.VERIFIED
        )

        # Assert
        assert test_email_verification.status == EmailVerificationStatus.VERIFIED
        mock_email_verification_service.session.add.assert_called_once_with(test_email_verification)
        mock_email_verification_service.session.commit.assert_called_once()
        mock_email_verification_service.session.refresh.assert_called_once_with(test_email_verification)

    def test_mark_email_verification_not_found(
        self,
        mock_email_verification_service: EmailVerificationService,
    ) -> None:
        """Test marking an email verification that doesn't exist."""
        # Arrange
        mock_email_verification_service.session.get.return_value = None
        verification_id = uuid.UUID("99999999-9999-9999-9999-999999999999")

        # Act & Assert
        with pytest.raises(EmailVerificationNotFoundError):
            mock_email_verification_service._mark_email_verification(verification_id, EmailVerificationStatus.VERIFIED)


class TestGetPendingEmailChange:
    """Tests for the get_pending_email_change method."""

    @pytest.fixture
    def pending_change(self, test_user: User) -> EmailVerification:
        """Create a pending change of address for the test user.

        Args:
            test_user: The test user.

        Returns:
            A pending verification of an address the user asked to move to.
        """
        verification = EmailVerification(
            email=test_user.email,
            new_email="moving-to@example.com",
            user_id=test_user.id,
            status=EmailVerificationStatus.PENDING,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
            token="pending_change_token",
        )
        verification.id = uuid.UUID("88888888-8888-8888-8888-888888888888")
        return verification

    def test_get_pending_email_change_reports_the_address_being_waited_on(
        self,
        mock_email_verification_service: EmailVerificationService,
        test_user: User,
        pending_change: EmailVerification,
    ) -> None:
        """Test the address a change is waiting on is the one reported."""
        # Arrange: The user asked to move to another address
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = pending_change

        # Act
        result = mock_email_verification_service.get_pending_email_change(user=test_user)

        # Assert
        assert result is not None
        assert result.new_email == "moving-to@example.com"
        assert result.expires_at == pending_change.expires_at

    def test_get_pending_email_change_without_anything_pending(
        self,
        mock_email_verification_service: EmailVerificationService,
        test_user: User,
    ) -> None:
        """Test an account with nothing outstanding is waiting on no address."""
        # Arrange: The user has no pending verification
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = None

        # Act
        result = mock_email_verification_service.get_pending_email_change(user=test_user)

        # Assert
        assert result is None

    def test_get_pending_email_change_ignores_an_activation(
        self,
        mock_email_verification_service: EmailVerificationService,
        test_user: User,
        test_email_verification: EmailVerification,
    ) -> None:
        """Test a verification of the address the account holds is not a change."""
        # Arrange: The pending verification activates the account, it moves nothing
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = test_email_verification

        # Act
        result = mock_email_verification_service.get_pending_email_change(user=test_user)

        # Assert
        assert result is None

    def test_get_pending_email_change_ignores_a_change_whose_link_has_lapsed(
        self,
        mock_email_verification_service: EmailVerificationService,
        test_user: User,
        pending_change: EmailVerification,
    ) -> None:
        """Test a change nobody can finish is not reported as one being waited on."""
        # Arrange: The deadline on the link has gone by, whatever the row still says
        pending_change.expires_at = datetime.now(UTC) - timedelta(hours=1)
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = pending_change

        # Act
        result = mock_email_verification_service.get_pending_email_change(user=test_user)

        # Assert
        assert result is None

    def test_get_pending_email_change_ignores_a_change_the_account_has_moved_past(
        self,
        mock_email_verification_service: EmailVerificationService,
        test_user: User,
        pending_change: EmailVerification,
    ) -> None:
        """Test a change asked for from an address the account no longer holds is not reported."""
        # Arrange: The account moved elsewhere after this change was asked for,
        # so redeeming the row is refused and reporting it would mislead
        test_user.email = "already-moved@example.com"
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = pending_change

        # Act
        result = mock_email_verification_service.get_pending_email_change(user=test_user)

        # Assert
        assert result is None


class TestCancelPendingEmailChange:
    """Tests for the cancel_pending_email_change method."""

    @pytest.fixture
    def pending_change(self, test_user: User) -> EmailVerification:
        """Create a pending change of address for the test user.

        Args:
            test_user: The test user.

        Returns:
            A pending verification of an address the user asked to move to.
        """
        verification = EmailVerification(
            email=test_user.email,
            new_email="moving-to@example.com",
            user_id=test_user.id,
            status=EmailVerificationStatus.PENDING,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
            token="cancel_change_token",
        )
        verification.id = uuid.UUID("88888888-8888-8888-8888-888888888888")
        return verification

    def test_cancel_pending_email_change_expires_the_row(
        self,
        mock_email_verification_service: EmailVerificationService,
        test_user: User,
        pending_change: EmailVerification,
    ) -> None:
        """Test calling off a change makes its link unredeemable."""
        # Arrange: The user asked to move to another address
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = pending_change
        mock_email_verification_service.session.get.return_value = pending_change

        # Act
        result = mock_email_verification_service.cancel_pending_email_change(user=test_user)

        # Assert
        assert isinstance(result, Message)
        assert pending_change.status == EmailVerificationStatus.EXPIRED
        assert test_user.email != "moving-to@example.com"

    def test_cancel_pending_email_change_without_anything_pending(
        self,
        mock_email_verification_service: EmailVerificationService,
        test_user: User,
    ) -> None:
        """Test there is nothing to call off when no change is outstanding."""
        # Arrange: The user has no pending verification
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = None

        # Act & Assert
        with pytest.raises(EmailVerificationNotFoundError):
            mock_email_verification_service.cancel_pending_email_change(user=test_user)

    def test_cancel_pending_email_change_leaves_an_activation_alone(
        self,
        mock_email_verification_service: EmailVerificationService,
        test_user: User,
        test_email_verification: EmailVerification,
    ) -> None:
        """Test calling off a change does not withdraw an account's own activation."""
        # Arrange: The pending verification activates the account. Expiring it
        # would leave an account that cannot be activated and never asked to move
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = test_email_verification
        mock_email_verification_service.session.get.return_value = test_email_verification

        # Act & Assert
        with pytest.raises(EmailVerificationNotFoundError):
            mock_email_verification_service.cancel_pending_email_change(user=test_user)

        assert test_email_verification.status == EmailVerificationStatus.PENDING

    def test_cancel_pending_email_change_refuses_a_change_whose_link_has_lapsed(
        self,
        mock_email_verification_service: EmailVerificationService,
        test_user: User,
        pending_change: EmailVerification,
    ) -> None:
        """Test a change nobody can finish is not a change there is anything to call off."""
        # Arrange: The deadline on the link has gone by, so the report says
        # nothing is outstanding and cancelling has to agree
        pending_change.expires_at = datetime.now(UTC) - timedelta(hours=1)
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = pending_change
        mock_email_verification_service.session.get.return_value = pending_change

        # Act & Assert
        with pytest.raises(EmailVerificationNotFoundError):
            mock_email_verification_service.cancel_pending_email_change(user=test_user)

    def test_cancel_pending_email_change_refuses_a_change_the_account_has_moved_past(
        self,
        mock_email_verification_service: EmailVerificationService,
        test_user: User,
        pending_change: EmailVerification,
    ) -> None:
        """Test a change asked for from an address the account no longer holds cannot be called off."""
        # Arrange: The account moved elsewhere after this change was asked for.
        # The report ignores the row, so cancelling it would answer for
        # something the screen never claimed was outstanding
        test_user.email = "already-moved@example.com"
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = pending_change
        mock_email_verification_service.session.get.return_value = pending_change

        # Act & Assert
        with pytest.raises(EmailVerificationNotFoundError):
            mock_email_verification_service.cancel_pending_email_change(user=test_user)

        assert pending_change.status == EmailVerificationStatus.PENDING


class TestGetPendingActivationByUserId:
    """Tests for the get_pending_activation_by_user_id method."""

    def test_asks_the_repository_for_the_activation_kind(
        self,
        mock_email_verification_service: EmailVerificationService,
        test_email_verification: EmailVerification,
        test_user: User,
    ) -> None:
        """Test the activation lookup is the one that answers, not the one for either kind."""
        # Arrange
        repository = mock_email_verification_service.email_verification_repository
        repository.get_pending_activation_by_user_id = MagicMock(return_value=test_email_verification)
        repository.get_pending_by_user_id = MagicMock()

        # Act
        result = mock_email_verification_service.get_pending_activation_by_user_id(test_user.id)

        # Assert
        assert result == test_email_verification
        repository.get_pending_activation_by_user_id.assert_called_once_with(test_user.id)
        repository.get_pending_by_user_id.assert_not_called()


class TestInvalidatePendingForUser:
    """Tests for the invalidate_pending_for_user method."""

    def test_invalidate_pending_for_user_expires_the_pending_verification(
        self,
        mock_email_verification_service: EmailVerificationService,
        test_user: User,
        test_email_verification: EmailVerification,
    ) -> None:
        """Test a pending verification is expired."""
        # Arrange: The user has a pending verification
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = test_email_verification
        mock_email_verification_service.session.get.return_value = test_email_verification

        # Act
        mock_email_verification_service.invalidate_pending_for_user(user_id=test_user.id)

        # Assert
        assert test_email_verification.status == EmailVerificationStatus.EXPIRED

    def test_invalidate_pending_for_user_without_a_pending_verification(
        self,
        mock_email_verification_service: EmailVerificationService,
        test_user: User,
    ) -> None:
        """Test a user with nothing pending is left alone."""
        # Arrange: The user has no pending verification
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = None
        mock_email_verification_service._mark_email_verification = MagicMock()

        # Act
        mock_email_verification_service.invalidate_pending_for_user(user_id=test_user.id)

        # Assert
        mock_email_verification_service._mark_email_verification.assert_not_called()


class TestSendVerificationEmail:
    """Tests for the send_verification_email method."""

    def test_send_verification_email_success_with_emails_enabled(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_user: User,
    ) -> None:
        """Test sending verification email with emails enabled."""
        # Arrange
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = None

        # Act
        with patch.object(mock_user_service, "get_user_by_email", return_value=test_user):
            with patch("app.services.email_verification.EmailOutboxService") as mock_outbox:
                with patch("app.services.email_verification.generate_email_verification_email") as mock_generate:
                    mock_generate.return_value = MagicMock(subject="Verify Email", html_content="<html>Test</html>")
                    result = mock_email_verification_service.send_verification_email(
                        user_service=mock_user_service, user_email=test_user.email
                    )

        # Assert
        assert isinstance(result, Message)
        assert result.message == "Verification email sent."
        mock_outbox.for_session.return_value.deliver_or_queue.assert_called_once()

    def test_send_verification_email_survives_a_delivery_failure(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_user: User,
        caplog,
    ) -> None:
        """Test that a delivery failure is queued for a retry instead of failing the request."""
        # Arrange: The verification row is written, then the provider rate limits us
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = None

        request = httpx.Request("POST", "https://api.resend.com/emails")
        rate_limited = httpx.HTTPStatusError("429", request=request, response=httpx.Response(429))

        # Act
        with patch.object(mock_user_service, "get_user_by_email", return_value=test_user):
            with patch("app.services.email_outbox.send_email", side_effect=rate_limited):
                with caplog.at_level(logging.WARNING, logger="app.services.email_outbox"):
                    result = mock_email_verification_service.send_verification_email(
                        user_service=mock_user_service, user_email=test_user.email
                    )

        # Assert: Verify the caller is told the truth and the log has the reason
        assert isinstance(result, Message)
        assert result.message == "Verification email queued for delivery."
        assert test_user.email in caplog.text
        assert "HTTPStatusError" in caplog.text

    def test_send_verification_email_success_with_emails_disabled(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_user: User,
        monkeypatch,
    ) -> None:
        """Test sending verification email with emails disabled."""
        # Arrange
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = None

        monkeypatch.setattr(settings, "SMTP_HOST", None)

        # Act
        with patch.object(mock_user_service, "get_user_by_email", return_value=test_user):
            with patch("app.services.email_verification.EmailOutboxService") as mock_outbox:
                result = mock_email_verification_service.send_verification_email(
                    user_service=mock_user_service, user_email=test_user.email
                )

        # Assert
        assert isinstance(result, Message)
        assert result.message == "Email delivery is not configured, so no verification email was sent."
        mock_outbox.for_session.return_value.deliver_or_queue.assert_not_called()

    def test_send_verification_email_with_existing_pending_verification(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_user: User,
        test_email_verification: EmailVerification,
    ) -> None:
        """Test sending verification email when a pending verification already exists."""
        # Arrange
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = test_email_verification
        mock_email_verification_service.session.get.return_value = test_email_verification

        # Act
        with patch.object(mock_user_service, "get_user_by_email", return_value=test_user):
            result = mock_email_verification_service.send_verification_email(
                user_service=mock_user_service, user_email=test_user.email
            )

        # Assert
        assert isinstance(result, Message)
        assert test_email_verification.status == EmailVerificationStatus.EXPIRED

    def test_send_verification_email_serves_an_active_account_with_no_history(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_user: User,
    ) -> None:
        """An account created by an administrator was never sent a confirmation, so it needs one now.

        Nothing else can prove the address it holds, and without a proof the
        invitations sent to that address stay unredeemable for ever.
        """
        # Arrange: an active account with no verification of any kind on record.
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = None
        saved: list[EmailVerification] = []
        mock_email_verification_service.email_verification_repository.save = MagicMock(  # type: ignore[method-assign]
            side_effect=lambda verification: saved.append(verification) or verification
        )

        # Act
        with patch.object(mock_user_service, "get_user_by_email", return_value=test_user):
            with patch("app.services.email_verification.EmailOutboxService"):
                result = mock_email_verification_service.send_verification_email(
                    user_service=mock_user_service, user_email=test_user.email
                )

        # Assert: a pending verification of the address the account holds now.
        assert isinstance(result, Message)
        assert len(saved) == 1
        assert saved[0].email == test_user.email
        assert saved[0].user_id == test_user.id
        assert saved[0].status == EmailVerificationStatus.PENDING

    def test_send_verification_email_user_not_found(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
    ) -> None:
        """Test sending verification email when user doesn't exist."""
        # Act & Assert
        with patch.object(mock_user_service, "get_user_by_email", return_value=None):
            with pytest.raises(UserNotFoundError):
                mock_email_verification_service.send_verification_email(
                    user_service=mock_user_service, user_email="nonexistent@example.com"
                )

    def test_send_verification_email_expiry_is_relative_to_request_time(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_user: User,
    ) -> None:
        """Test that the stored expiry is measured from the request, not from process start."""
        # Arrange: Pretend the process has been up far longer than the configured window
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = None

        request_time = datetime.now(UTC) + timedelta(days=30)

        # Act: Send a verification email at that later point in time
        with patch.object(mock_user_service, "get_user_by_email", return_value=test_user):
            with patch("app.services.email_verification.EmailOutboxService"):
                with patch("app.services.email_verification.generate_email_verification_email"):
                    with patch("app.services.email_verification.datetime") as mock_datetime:
                        mock_datetime.now.return_value = request_time

                        mock_email_verification_service.send_verification_email(
                            user_service=mock_user_service, user_email=test_user.email
                        )

        # Assert: The row expires a full window after the request, not after the import
        email_verification = mock_email_verification_service.session.add.call_args[0][0]
        expected = request_time + timedelta(hours=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS)
        assert email_verification.expires_at == expected


class TestSendEmailChangeVerification:
    """Tests for the send_email_change_verification method."""

    def test_send_email_change_verification_writes_a_pending_change(
        self,
        mock_email_verification_service: EmailVerificationService,
        test_user: User,
    ) -> None:
        """Test the row keeps the current address and the one being asked for apart."""
        # Arrange: The user holds no other pending verification
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = None

        # Act
        with patch("app.services.email_verification.EmailOutboxService"):
            result = mock_email_verification_service.send_email_change_verification(
                user=test_user, new_email="moving-to@example.com"
            )

        # Assert
        assert isinstance(result, Message)
        email_verification = mock_email_verification_service.session.add.call_args[0][0]
        assert email_verification.email == test_user.email
        assert email_verification.new_email == "moving-to@example.com"
        assert email_verification.status == EmailVerificationStatus.PENDING

    def test_send_email_change_verification_addresses_the_token_to_the_new_address(
        self,
        mock_email_verification_service: EmailVerificationService,
        test_user: User,
    ) -> None:
        """Test the address being proven is the one the link is sent to."""
        # Arrange
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = None

        # Act
        with patch("app.services.email_verification.EmailOutboxService") as mock_outbox:
            mock_email_verification_service.send_email_change_verification(
                user=test_user, new_email="moving-to@example.com"
            )

        # Assert: The token names the new address, and the mail goes there
        # rather than to the address the account still holds
        email_verification = mock_email_verification_service.session.add.call_args[0][0]
        decoded = jwt.decode(
            email_verification.token, settings.SECRET_KEY, algorithms=[ALGORITHM], audience=JWT.AUDIENCE
        )
        assert decoded["sub"] == "moving-to@example.com"
        assert mock_outbox.for_session.return_value.deliver_or_queue.call_args.kwargs["email_to"] == (
            "moving-to@example.com"
        )

    def test_send_email_change_verification_retires_an_earlier_pending_verification(
        self,
        mock_email_verification_service: EmailVerificationService,
        test_user: User,
        test_email_verification: EmailVerification,
    ) -> None:
        """Test a fresh request leaves no earlier verification redeemable."""
        # Arrange: The user already has a pending verification
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = test_email_verification
        mock_email_verification_service.session.get.return_value = test_email_verification

        # Act
        with patch("app.services.email_verification.EmailOutboxService"):
            mock_email_verification_service.send_email_change_verification(
                user=test_user, new_email="moving-to@example.com"
            )

        # Assert
        assert test_email_verification.status == EmailVerificationStatus.EXPIRED


class TestResendVerificationEmail:
    """Tests for the resend_verification_email method."""

    def test_resend_verification_email_success(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_inactive_user: User,
        test_email_verification: EmailVerification,
    ) -> None:
        """Test resending verification email for an inactive user with pending verification."""
        # Arrange
        mock_email_verification_service.session.exec = MagicMock()

        # First call returns pending verification for check, second returns None for send
        mock_email_verification_service.session.exec.return_value.first.side_effect = [
            test_email_verification,
            None,
        ]

        # Act
        with patch.object(mock_user_service, "get_user_by_email", return_value=test_inactive_user):
            result = mock_email_verification_service.resend_verification_email(
                user_service=mock_user_service, email=test_inactive_user.email
            )

        # Assert
        assert isinstance(result, Message)
        assert "If an account exists" in result.message

    def test_resend_verification_email_user_not_found(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
    ) -> None:
        """Test resending verification email when user doesn't exist."""
        # Act
        with patch.object(mock_user_service, "get_user_by_email", return_value=None):
            result = mock_email_verification_service.resend_verification_email(
                user_service=mock_user_service, email="nonexistent@example.com"
            )

        # Assert
        assert isinstance(result, Message)
        assert "If an account exists" in result.message

    def test_resend_verification_email_user_is_active(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_user: User,
    ) -> None:
        """Test resending verification email for an active user."""
        # Act
        with patch.object(mock_user_service, "get_user_by_email", return_value=test_user):
            result = mock_email_verification_service.resend_verification_email(
                user_service=mock_user_service, email=test_user.email
            )

        # Assert
        assert isinstance(result, Message)
        assert "If an account exists" in result.message

    def test_resend_verification_email_no_pending_verification(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_inactive_user: User,
    ) -> None:
        """Test resending verification email for inactive user without pending verification."""
        # Arrange
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = None

        # Act
        with patch.object(mock_user_service, "get_user_by_email", return_value=test_inactive_user):
            result = mock_email_verification_service.resend_verification_email(
                user_service=mock_user_service, email=test_inactive_user.email
            )

        # Assert
        assert isinstance(result, Message)
        assert "If an account exists" in result.message

    def test_resend_verification_email_exception_handling(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_inactive_user: User,
        test_email_verification: EmailVerification,
    ) -> None:
        """Test that exceptions during resend are silently caught."""
        # Arrange
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = test_email_verification

        # Mock send_verification_email to raise an exception
        with patch.object(mock_user_service, "get_user_by_email", return_value=test_inactive_user):
            with patch.object(
                mock_email_verification_service,
                "send_verification_email",
                side_effect=Exception("Email service down"),
            ):
                # Act
                result = mock_email_verification_service.resend_verification_email(
                    user_service=mock_user_service, email=test_inactive_user.email
                )

        # Assert - Should return success message even though exception occurred
        assert isinstance(result, Message)
        assert "If an account exists" in result.message


class TestAResendIsNotAWayBackToActive:
    """Tests that a resend never turns a pending change of address into an activation."""

    def test_an_account_with_only_a_pending_change_is_not_resent_anything(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_inactive_user: User,
        pending_email_change: EmailVerification,
    ) -> None:
        """A disabled account must not be able to mail itself an activation."""
        # Arrange: the only thing pending for this account is a change of address
        repository = mock_email_verification_service.email_verification_repository
        repository.get_pending_activation_by_user_id = MagicMock(return_value=None)
        repository.get_pending_change_by_user_id = MagicMock(return_value=pending_email_change)

        # Act
        with patch.object(mock_user_service, "get_user_by_email", return_value=test_inactive_user):
            with patch.object(mock_email_verification_service, "send_verification_email") as mock_send:
                result = mock_email_verification_service.resend_verification_email(
                    user_service=mock_user_service, email=test_inactive_user.email
                )

        # Assert: nothing was issued, and the answer still gives no account away
        mock_send.assert_not_called()
        assert pending_email_change.status == EmailVerificationStatus.PENDING
        assert "If an account exists" in result.message

    def test_issuing_an_activation_leaves_a_pending_change_standing(
        self,
        mock_email_verification_service: EmailVerificationService,
        test_user: User,
        pending_email_change: EmailVerification,
    ) -> None:
        """Confirming the address an account holds is not a withdrawal of the change it asked for."""
        # Arrange
        repository = mock_email_verification_service.email_verification_repository
        repository.get_pending_activation_by_user_id = MagicMock(return_value=None)
        repository.get_pending_change_by_user_id = MagicMock(return_value=pending_email_change)

        # Act
        with patch("app.services.email_verification.EmailOutboxService"):
            with patch("app.services.email_verification.generate_email_verification_email"):
                mock_email_verification_service._issue_verification(user=test_user, address=test_user.email)

        # Assert
        assert pending_email_change.status == EmailVerificationStatus.PENDING
        repository.get_pending_activation_by_user_id.assert_called_once_with(test_user.id)
        repository.get_pending_change_by_user_id.assert_not_called()

    def test_issuing_a_change_expires_the_change_it_replaces(
        self,
        mock_email_verification_service: EmailVerificationService,
        test_user: User,
        test_email_verification: EmailVerification,
        pending_email_change: EmailVerification,
    ) -> None:
        """Only one address may be waiting to be proved, and it is the one last asked for."""
        # Arrange
        repository = mock_email_verification_service.email_verification_repository
        repository.get_pending_activation_by_user_id = MagicMock(return_value=test_email_verification)
        repository.get_pending_change_by_user_id = MagicMock(return_value=pending_email_change)
        mock_email_verification_service.session.get.return_value = pending_email_change

        # Act
        with patch("app.services.email_verification.EmailOutboxService"):
            with patch("app.services.email_verification.generate_email_verification_email"):
                mock_email_verification_service._issue_verification(
                    user=test_user, address="elsewhere@example.com", new_email="elsewhere@example.com"
                )

        # Assert: the earlier change is spent, the activation the account may still need is not
        assert pending_email_change.status == EmailVerificationStatus.EXPIRED
        assert test_email_verification.status == EmailVerificationStatus.PENDING
        repository.get_pending_change_by_user_id.assert_called_once_with(test_user.id)
        repository.get_pending_activation_by_user_id.assert_not_called()


class TestVerifyEmail:
    """Tests for the verify_email method."""

    def test_verify_email_success(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_user: User,
        test_email_verification: EmailVerification,
    ) -> None:
        """Test successfully verifying an email."""
        # Arrange
        token = create_email_verification_token(subject=test_user.email)
        test_email_verification.token = token

        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = test_email_verification
        mock_email_verification_service.session.get.return_value = test_email_verification

        # Act
        with patch.object(mock_user_service.user_repository, "get_by_id", return_value=test_user):
            result = mock_email_verification_service.verify_email(user_service=mock_user_service, token=token)

        # Assert
        assert isinstance(result, Message)
        assert "Email verified successfully" in result.message
        assert test_user.is_active is True

    def test_verify_email_claims_the_invites_sent_to_the_address(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_user: User,
        test_email_verification: EmailVerification,
    ) -> None:
        """Proving the mailbox is what makes an invitation to it redeemable."""
        # Arrange
        token = create_email_verification_token(subject=test_user.email)
        test_email_verification.token = token
        claimer = MagicMock()

        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = test_email_verification
        mock_email_verification_service.session.get.return_value = test_email_verification

        # Act
        with patch.object(mock_user_service.user_repository, "get_by_id", return_value=test_user):
            mock_email_verification_service.verify_email(
                user_service=mock_user_service, token=token, invite_claimer=claimer
            )

        # Assert
        claimer.claim_invites_for_verified_email.assert_called_once_with(user=test_user)

    def test_verify_email_claims_no_invites_when_the_token_is_rejected(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_user: User,
        test_email_verification: EmailVerification,
    ) -> None:
        """Nothing was proved, so nothing may be handed over."""
        # Arrange: the account no longer holds the address the token names.
        token = create_email_verification_token(subject=test_user.email)
        test_email_verification.token = token
        test_user.email = "moved-on@example.com"
        claimer = MagicMock()

        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = test_email_verification
        mock_email_verification_service.session.get.return_value = test_email_verification

        # Act & Assert
        with patch.object(mock_user_service.user_repository, "get_by_id", return_value=test_user):
            with pytest.raises(EmailVerificationTokenNotValidError):
                mock_email_verification_service.verify_email(
                    user_service=mock_user_service, token=token, invite_claimer=claimer
                )

        claimer.claim_invites_for_verified_email.assert_not_called()

    def test_verify_email_resolves_the_target_from_the_verification_row(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_user: User,
        another_test_user: User,
        test_email_verification: EmailVerification,
    ) -> None:
        """Test the verification activates the account it was issued for, not the address holder."""
        # Arrange: The verification was issued for test_user, who has since
        # released the address; another_test_user holds it now.
        token = create_email_verification_token(subject=test_user.email)
        test_email_verification.token = token
        another_test_user.email = test_user.email
        another_test_user.is_active = False
        test_user.email = "moved-on@example.com"

        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = test_email_verification
        mock_email_verification_service.session.get.return_value = test_email_verification

        # Act & Assert: The token no longer matches the address the account
        # holds, so it activates neither account.
        with patch.object(mock_user_service.user_repository, "get_by_id", return_value=test_user) as get_by_id:
            with pytest.raises(EmailVerificationTokenNotValidError):
                mock_email_verification_service.verify_email(user_service=mock_user_service, token=token)

        get_by_id.assert_called_once_with(test_email_verification.user_id)
        assert another_test_user.is_active is False
        assert test_email_verification.status == EmailVerificationStatus.PENDING

    def test_verify_email_invalid_token(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
    ) -> None:
        """Test verifying email with an invalid token."""
        # Arrange
        invalid_token = "invalid.token.here"

        # Act & Assert
        with pytest.raises(EmailVerificationTokenNotValidError):
            mock_email_verification_service.verify_email(user_service=mock_user_service, token=invalid_token)

    def test_verify_email_verification_not_found(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_user: User,
    ) -> None:
        """Test verifying email when verification record doesn't exist."""
        # Arrange
        token = create_email_verification_token(subject=test_user.email)

        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = None

        # Act & Assert
        with pytest.raises(EmailVerificationNotFoundError):
            mock_email_verification_service.verify_email(user_service=mock_user_service, token=token)

    def test_verify_email_already_verified(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_user: User,
        verified_email_verification: EmailVerification,
    ) -> None:
        """Test verifying email that has already been verified."""
        # Arrange
        token = create_email_verification_token(subject=test_user.email)
        verified_email_verification.token = token

        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = verified_email_verification

        # Act & Assert
        with pytest.raises(EmailVerificationUsedError):
            mock_email_verification_service.verify_email(user_service=mock_user_service, token=token)

    def test_verify_email_expired_status(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_user: User,
        expired_email_verification: EmailVerification,
    ) -> None:
        """Test verifying email with expired status."""
        # Arrange
        token = create_email_verification_token(subject=test_user.email)
        expired_email_verification.token = token

        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = expired_email_verification

        # Act & Assert
        with pytest.raises(EmailVerificationExpiredError):
            mock_email_verification_service.verify_email(user_service=mock_user_service, token=token)

    def test_verify_email_expired_time(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_user: User,
        test_email_verification: EmailVerification,
    ) -> None:
        """Test verifying email when the expiration time has passed."""
        # Arrange
        token = create_email_verification_token(subject=test_user.email)
        test_email_verification.token = token
        test_email_verification.expires_at = datetime.now(UTC) - timedelta(hours=1)
        test_email_verification.status = EmailVerificationStatus.PENDING

        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = test_email_verification
        mock_email_verification_service.session.get.return_value = test_email_verification

        # Act & Assert
        with pytest.raises(EmailVerificationExpiredError):
            mock_email_verification_service.verify_email(user_service=mock_user_service, token=token)

    def test_verify_email_user_not_found(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_user: User,
        test_email_verification: EmailVerification,
    ) -> None:
        """Test verifying email when user doesn't exist."""
        # Arrange
        token = create_email_verification_token(subject=test_user.email)
        test_email_verification.token = token

        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = test_email_verification
        mock_email_verification_service.session.get.return_value = test_email_verification

        # Act & Assert
        with patch.object(mock_user_service.user_repository, "get_by_id", return_value=None):
            with pytest.raises(UserNotFoundError):
                mock_email_verification_service.verify_email(user_service=mock_user_service, token=token)


class TestVerifyEmailAddressChange:
    """Tests for redeeming a verification that stands for a change of address."""

    @pytest.fixture
    def change_email_verification(self, test_user: User) -> EmailVerification:
        """Create a pending change of address for the test user.

        Args:
            test_user: The test user.

        Returns:
            A pending verification of an address the user asked to move to.
        """
        verification = EmailVerification(
            email=test_user.email,
            new_email="moving-to@example.com",
            user_id=test_user.id,
            status=EmailVerificationStatus.PENDING,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
            token=create_email_verification_token(subject="moving-to@example.com"),
        )
        verification.id = uuid.UUID("77777777-7777-7777-7777-777777777777")
        return verification

    def test_verify_email_moves_the_account_to_the_verified_address(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_user: User,
        change_email_verification: EmailVerification,
    ) -> None:
        """Test the address the token proves is the one the account ends up with."""
        # Arrange: Nothing else holds the address being moved to
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = change_email_verification
        mock_email_verification_service.session.get.return_value = change_email_verification

        # Act
        with patch.object(mock_user_service.user_repository, "get_by_id", return_value=test_user):
            with patch.object(mock_user_service, "get_user_by_email", return_value=None):
                result = mock_email_verification_service.verify_email(
                    user_service=mock_user_service, token=change_email_verification.token
                )

        # Assert
        assert isinstance(result, Message)
        assert "updated" in result.message
        assert test_user.email == "moving-to@example.com"
        assert change_email_verification.status == EmailVerificationStatus.VERIFIED

    def test_verify_email_change_leaves_the_account_status_alone(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_user: User,
        change_email_verification: EmailVerification,
    ) -> None:
        """Test a change of address does not activate an account that is not active."""
        # Arrange: The account is not active, and a change of address says
        # nothing about why it was deactivated
        test_user.is_active = False
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = change_email_verification
        mock_email_verification_service.session.get.return_value = change_email_verification

        # Act
        with patch.object(mock_user_service.user_repository, "get_by_id", return_value=test_user):
            with patch.object(mock_user_service, "get_user_by_email", return_value=None):
                mock_email_verification_service.verify_email(
                    user_service=mock_user_service, token=change_email_verification.token
                )

        # Assert
        assert test_user.is_active is False

    def test_verify_email_change_rejects_a_token_for_another_address(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_user: User,
        change_email_verification: EmailVerification,
    ) -> None:
        """Test the row's pending address is the only one its token can prove."""
        # Arrange: The row names one address, the token another
        change_email_verification.new_email = "somewhere-else@example.com"
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = change_email_verification
        mock_email_verification_service.session.get.return_value = change_email_verification

        # Act & Assert
        with patch.object(mock_user_service.user_repository, "get_by_id", return_value=test_user):
            with pytest.raises(EmailVerificationTokenNotValidError):
                mock_email_verification_service.verify_email(
                    user_service=mock_user_service, token=change_email_verification.token
                )

        assert test_user.email != "somewhere-else@example.com"
        assert change_email_verification.status == EmailVerificationStatus.PENDING

    def test_verify_email_change_rejects_a_token_the_account_has_moved_past(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_user: User,
        change_email_verification: EmailVerification,
    ) -> None:
        """Test a change asked for from an address the account no longer holds is not redeemable."""
        # Arrange: The account was moved elsewhere after this change was asked for
        test_user.email = "already-moved@example.com"
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = change_email_verification
        mock_email_verification_service.session.get.return_value = change_email_verification

        # Act & Assert
        with patch.object(mock_user_service.user_repository, "get_by_id", return_value=test_user):
            with pytest.raises(EmailVerificationTokenNotValidError):
                mock_email_verification_service.verify_email(
                    user_service=mock_user_service, token=change_email_verification.token
                )

        assert test_user.email == "already-moved@example.com"

    def test_verify_email_change_rejects_an_address_taken_in_the_meantime(
        self,
        mock_email_verification_service: EmailVerificationService,
        mock_user_service: UserService,
        test_user: User,
        another_test_user: User,
        change_email_verification: EmailVerification,
    ) -> None:
        """Test an address registered between the request and the redemption is not taken over."""
        # Arrange: Another account signed up with the address in the meantime
        another_test_user.email = "moving-to@example.com"
        mock_email_verification_service.session.exec = MagicMock()
        mock_email_verification_service.session.exec.return_value.first.return_value = change_email_verification
        mock_email_verification_service.session.get.return_value = change_email_verification

        # Act & Assert
        with patch.object(mock_user_service.user_repository, "get_by_id", return_value=test_user):
            with patch.object(mock_user_service, "get_user_by_email", return_value=another_test_user):
                with pytest.raises(UserExistsError):
                    mock_email_verification_service.verify_email(
                        user_service=mock_user_service, token=change_email_verification.token
                    )

        assert change_email_verification.status == EmailVerificationStatus.PENDING
