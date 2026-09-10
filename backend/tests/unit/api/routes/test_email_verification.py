from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.exceptions import (
    EmailVerificationExpiredError,
    EmailVerificationNotFoundError,
    EmailVerificationTokenNotValidError,
    EmailVerificationUsedError,
)
from app.main import app
from app.models import Message, PendingEmailChange, User
from app.services import EmailVerificationService


class TestResendVerificationEmail:
    """Tests for the resend_verification_email endpoint (POST /email-verification/send)."""

    def test_resend_verification_email_success(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test successfully sending a verification email."""

        # Arrange: Set up database dependency override and mock service method
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        expected_message = Message(
            message=(
                "If an account exists with this email and requires verification, "
                "you will receive verification instructions."
            )
        )

        try:
            with patch.object(
                EmailVerificationService,
                "resend_verification_email",
                return_value=expected_message,
            ):
                # Act: Post email verification request
                response = client.post(
                    "/api/v1/email-verification/send",
                    json={"email": "test@example.com"},
                )

                # Assert: Verify successful response
                data = response.json()

                assert response.status_code == 200
                assert data["message"] == (
                    "If an account exists with this email and requires verification, "
                    "you will receive verification instructions."
                )
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_resend_verification_email_nonexistent_user(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test sending verification email for non-existent user (should still succeed for security)."""

        # Arrange: Set up database dependency override and mock service method
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        # The service returns success even for non-existent users (anti-enumeration)
        expected_message = Message(
            message=(
                "If an account exists with this email and requires verification, "
                "you will receive verification instructions."
            )
        )

        try:
            with patch.object(
                EmailVerificationService,
                "resend_verification_email",
                return_value=expected_message,
            ):
                # Act: Post email verification request for non-existent user
                response = client.post(
                    "/api/v1/email-verification/send",
                    json={"email": "nonexistent@example.com"},
                )

                # Assert: Verify successful response (no user enumeration)
                data = response.json()

                assert response.status_code == 200
                assert data["message"] == (
                    "If an account exists with this email and requires verification, "
                    "you will receive verification instructions."
                )
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_resend_verification_email_invalid_email(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test sending verification email with invalid email format."""

        # Arrange: Set up database dependency override
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            # Act: Post invalid email
            response = client.post(
                "/api/v1/email-verification/send",
                json={"email": "not-an-email"},
            )

            # Assert: Verify 422 validation error
            assert response.status_code == 422
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_resend_verification_email_missing_email(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test sending verification email without email field."""

        # Arrange: Set up database dependency override
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            # Act: Post without email
            response = client.post(
                "/api/v1/email-verification/send",
                json={},
            )

            # Assert: Verify 422 validation error
            assert response.status_code == 422
        finally:
            # Cleanup
            app.dependency_overrides.clear()


class TestSendVerificationEmailMe:
    """Tests for the send_verification_email_me endpoint (POST /email-verification/me/send)."""

    def test_send_verification_email_me_success(
        self,
        client: TestClient,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test that an active account can ask for a confirmation of the address it holds."""

        # Arrange: Set up dependency overrides with an authenticated user
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        try:
            with patch.object(
                EmailVerificationService,
                "send_verification_email",
                return_value=Message(message="Verification email sent successfully."),
            ) as send:
                # Act: Ask for a confirmation of the caller's own address
                response = client.post("/api/v1/email-verification/me/send")

                # Assert: The caller's own address is the one confirmed, never one it names
                assert response.status_code == 200
                assert response.json()["message"] == "Verification email sent successfully."
                assert send.call_args.kwargs["user_email"] == test_user.email
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_send_verification_email_me_requires_authentication(self, client: TestClient) -> None:
        """Test that the endpoint refuses a caller with no token."""
        # Act: Ask for a confirmation without signing in
        response = client.post("/api/v1/email-verification/me/send")

        # Assert: Verify 401 unauthorized response
        assert response.status_code == 401


class TestGetPendingEmailChangeMe:
    """Tests for the get_pending_email_change_me endpoint (GET /email-verification/me/email-change)."""

    def test_get_pending_email_change_me_reports_the_address_waited_on(
        self,
        client: TestClient,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test the screen can find out which address a change is waiting on."""

        # Arrange: Set up dependency overrides with an authenticated user
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        pending = PendingEmailChange(
            new_email="moving-to@example.com",
            expires_at=datetime(2026, 1, 2, tzinfo=UTC),
        )

        try:
            with patch.object(
                EmailVerificationService,
                "get_pending_email_change",
                return_value=pending,
            ) as get_pending:
                # Act: Ask what the caller's own account is waiting on
                response = client.get("/api/v1/email-verification/me/email-change")

                # Assert: The answer is about the caller, never an account it names
                assert response.status_code == 200
                assert response.json()["new_email"] == "moving-to@example.com"
                assert get_pending.call_args.kwargs["user"] == test_user
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_get_pending_email_change_me_without_anything_pending(
        self,
        client: TestClient,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test an account with nothing outstanding is answered, not refused."""

        # Arrange: Set up dependency overrides with an authenticated user
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        try:
            with patch.object(EmailVerificationService, "get_pending_email_change", return_value=None):
                # Act: Ask what the caller's own account is waiting on
                response = client.get("/api/v1/email-verification/me/email-change")

                # Assert: Nothing pending is an ordinary answer
                assert response.status_code == 200
                assert response.json() is None
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_get_pending_email_change_me_requires_authentication(self, client: TestClient) -> None:
        """Test that the endpoint refuses a caller with no token."""
        # Act: Ask without signing in
        response = client.get("/api/v1/email-verification/me/email-change")

        # Assert: Verify 401 unauthorized response
        assert response.status_code == 401


class TestCancelPendingEmailChangeMe:
    """Tests for the cancel_pending_email_change_me endpoint (DELETE /email-verification/me/email-change)."""

    def test_cancel_pending_email_change_me_calls_the_change_off(
        self,
        client: TestClient,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test the screen can call off a change the account is waiting on."""

        # Arrange: Set up dependency overrides with an authenticated user
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        try:
            with patch.object(
                EmailVerificationService,
                "cancel_pending_email_change",
                return_value=Message(message="Email change cancelled."),
            ) as cancel:
                # Act: Call off the change on the caller's own account
                response = client.delete("/api/v1/email-verification/me/email-change")

                # Assert: The change called off is the caller's, never one it names
                assert response.status_code == 200
                assert response.json()["message"] == "Email change cancelled."
                assert cancel.call_args.kwargs["user"] == test_user
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_cancel_pending_email_change_me_without_anything_pending(
        self,
        client: TestClient,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test there is nothing to call off when no change is outstanding."""

        # Arrange: Set up dependency overrides with an authenticated user
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        try:
            with patch.object(
                EmailVerificationService,
                "cancel_pending_email_change",
                side_effect=EmailVerificationNotFoundError(),
            ):
                # Act: Call off a change that is not there
                response = client.delete("/api/v1/email-verification/me/email-change")

                # Assert: Verify 404 not found response
                assert response.status_code == 404
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_cancel_pending_email_change_me_requires_authentication(self, client: TestClient) -> None:
        """Test that the endpoint refuses a caller with no token."""
        # Act: Call off a change without signing in
        response = client.delete("/api/v1/email-verification/me/email-change")

        # Assert: Verify 401 unauthorized response
        assert response.status_code == 401


class TestVerifyEmail:
    """Tests for the verify_email endpoint (POST /email-verification/verify)."""

    def test_verify_email_success(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test successfully verifying email with valid token."""

        # Arrange: Set up database dependency override and mock service method
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        expected_message = Message(message="Email verified successfully. Your account is now active.")

        try:
            with patch.object(
                EmailVerificationService,
                "verify_email",
                return_value=expected_message,
            ):
                # Act: Post verification token
                response = client.post(
                    "/api/v1/email-verification/verify",
                    json={"token": "valid-token-123"},
                )

                # Assert: Verify successful verification
                data = response.json()

                assert response.status_code == 200
                assert data["message"] == "Email verified successfully. Your account is now active."
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_verify_email_not_found(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test verifying email with non-existent token."""

        # Arrange: Set up database dependency override and mock EmailVerificationNotFoundError
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            with patch.object(
                EmailVerificationService,
                "verify_email",
                side_effect=EmailVerificationNotFoundError,
            ):
                # Act: Post non-existent token
                response = client.post(
                    "/api/v1/email-verification/verify",
                    json={"token": "nonexistent-token"},
                )

                # Assert: Verify 404 not found response
                data = response.json()

                assert response.status_code == 404
                assert data["detail"] == "Email verification not found."
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_verify_email_expired(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test verifying email with expired token."""

        # Arrange: Set up database dependency override and mock EmailVerificationExpiredError
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            with patch.object(
                EmailVerificationService,
                "verify_email",
                side_effect=EmailVerificationExpiredError,
            ):
                # Act: Post expired token
                response = client.post(
                    "/api/v1/email-verification/verify",
                    json={"token": "expired-token"},
                )

                # Assert: Verify 400 bad request response
                data = response.json()

                assert response.status_code == 400
                assert data["detail"] == "The email verification has expired."
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_verify_email_already_used(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test verifying email with already used token."""

        # Arrange: Set up database dependency override and mock EmailVerificationUsedError
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            with patch.object(
                EmailVerificationService,
                "verify_email",
                side_effect=EmailVerificationUsedError,
            ):
                # Act: Post already used token
                response = client.post(
                    "/api/v1/email-verification/verify",
                    json={"token": "used-token"},
                )

                # Assert: Verify 400 bad request response
                data = response.json()

                assert response.status_code == 400
                assert data["detail"] == "The email verification has already been used."
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_verify_email_invalid_token(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test verifying email with invalid token format."""

        # Arrange: Set up database dependency override and mock EmailVerificationTokenNotValidError
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            with patch.object(
                EmailVerificationService,
                "verify_email",
                side_effect=EmailVerificationTokenNotValidError,
            ):
                # Act: Post invalid token
                response = client.post(
                    "/api/v1/email-verification/verify",
                    json={"token": "invalid-token"},
                )

                # Assert: Verify 400 bad request response
                data = response.json()

                assert response.status_code == 400
                assert data["detail"] == "The email verification token is not valid."
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_verify_email_missing_token(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test verifying email without token field."""

        # Arrange: Set up database dependency override
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            # Act: Post without token
            response = client.post(
                "/api/v1/email-verification/verify",
                json={},
            )

            # Assert: Verify 422 validation error
            assert response.status_code == 422
        finally:
            # Cleanup
            app.dependency_overrides.clear()
