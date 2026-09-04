from collections.abc import Generator
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.exceptions import (
    EmailVerificationExpiredError,
    EmailVerificationNotFoundError,
    EmailVerificationTokenNotValidError,
    EmailVerificationUsedError,
)
from app.main import app
from app.models import Message
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
        def override_get_db() -> Generator[MagicMock, None, None]:
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
        def override_get_db() -> Generator[MagicMock, None, None]:
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
        def override_get_db() -> Generator[MagicMock, None, None]:
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
        def override_get_db() -> Generator[MagicMock, None, None]:
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


class TestVerifyEmail:
    """Tests for the verify_email endpoint (POST /email-verification/verify)."""

    def test_verify_email_success(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test successfully verifying email with valid token."""
        # Arrange: Set up database dependency override and mock service method
        def override_get_db() -> Generator[MagicMock, None, None]:
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
        def override_get_db() -> Generator[MagicMock, None, None]:
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
        def override_get_db() -> Generator[MagicMock, None, None]:
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
        def override_get_db() -> Generator[MagicMock, None, None]:
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
        def override_get_db() -> Generator[MagicMock, None, None]:
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
        def override_get_db() -> Generator[MagicMock, None, None]:
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
