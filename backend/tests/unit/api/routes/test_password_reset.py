from collections.abc import Generator
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.exceptions import (
    PasswordResetExpiredError,
    PasswordResetNotFoundError,
    PasswordResetTokenNotValidError,
    PasswordResetUsedError,
)
from app.main import app
from app.models import Message
from app.models.fields import BCRYPT_MAX_PASSWORD_BYTES
from app.services import PasswordResetService


class TestRequestPasswordReset:
    """Tests for the request_password_reset endpoint (POST /password-reset/request)."""

    def test_request_password_reset_success(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test successfully requesting a password reset."""

        # Arrange: Set up database dependency override and mock service method
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        expected_message = Message(
            message="If an account exists with this email, you will receive password reset instructions."
        )

        try:
            with patch.object(
                PasswordResetService,
                "request_password_reset",
                return_value=expected_message,
            ):
                # Act: Post password reset request
                response = client.post(
                    "/api/v1/password-reset/request",
                    json={"email": "test@example.com"},
                )

                # Assert: Verify successful response
                data = response.json()

                assert response.status_code == 200
                assert data["message"] == (
                    "If an account exists with this email, you will receive password reset instructions."
                )
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_request_password_reset_nonexistent_user(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test requesting password reset for non-existent user (should still succeed for security)."""

        # Arrange: Set up database dependency override and mock service method
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        # The service returns success even for non-existent users (anti-enumeration)
        expected_message = Message(
            message="If an account exists with this email, you will receive password reset instructions."
        )

        try:
            with patch.object(
                PasswordResetService,
                "request_password_reset",
                return_value=expected_message,
            ):
                # Act: Post password reset request for non-existent user
                response = client.post(
                    "/api/v1/password-reset/request",
                    json={"email": "nonexistent@example.com"},
                )

                # Assert: Verify successful response (no user enumeration)
                data = response.json()

                assert response.status_code == 200
                assert data["message"] == (
                    "If an account exists with this email, you will receive password reset instructions."
                )
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_request_password_reset_invalid_email(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test requesting password reset with invalid email format."""

        # Arrange: Set up database dependency override
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            # Act: Post invalid email
            response = client.post(
                "/api/v1/password-reset/request",
                json={"email": "not-an-email"},
            )

            # Assert: Verify 422 validation error
            assert response.status_code == 422
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_request_password_reset_missing_email(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test requesting password reset without email field."""

        # Arrange: Set up database dependency override
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            # Act: Post without email
            response = client.post(
                "/api/v1/password-reset/request",
                json={},
            )

            # Assert: Verify 422 validation error
            assert response.status_code == 422
        finally:
            # Cleanup
            app.dependency_overrides.clear()


class TestVerifyPasswordResetToken:
    """Tests for the verify_password_reset_token endpoint (POST /password-reset/verify)."""

    def test_verify_token_success(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test successfully verifying a password reset token."""

        # Arrange: Set up database dependency override and mock service method
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        expected_message = Message(message="Token is valid.")

        try:
            with patch.object(
                PasswordResetService,
                "verify_token",
                return_value=expected_message,
            ):
                # Act: Post verification token
                response = client.post(
                    "/api/v1/password-reset/verify",
                    json={"token": "valid-token-123"},
                )

                # Assert: Verify successful verification
                data = response.json()

                assert response.status_code == 200
                assert data["message"] == "Token is valid."
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_verify_token_not_found(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test verifying password reset token that doesn't exist."""

        # Arrange: Set up database dependency override and mock PasswordResetNotFoundError
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            with patch.object(
                PasswordResetService,
                "verify_token",
                side_effect=PasswordResetNotFoundError,
            ):
                # Act: Post non-existent token
                response = client.post(
                    "/api/v1/password-reset/verify",
                    json={"token": "nonexistent-token"},
                )

                # Assert: Verify 404 not found response
                data = response.json()

                assert response.status_code == 404
                assert data["detail"] == "Password reset request not found."
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_verify_token_expired(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test verifying expired password reset token."""

        # Arrange: Set up database dependency override and mock PasswordResetExpiredError
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            with patch.object(
                PasswordResetService,
                "verify_token",
                side_effect=PasswordResetExpiredError,
            ):
                # Act: Post expired token
                response = client.post(
                    "/api/v1/password-reset/verify",
                    json={"token": "expired-token"},
                )

                # Assert: Verify 400 bad request response
                data = response.json()

                assert response.status_code == 400
                assert data["detail"] == "The password reset has expired."
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_verify_token_already_used(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test verifying password reset token that was already used."""

        # Arrange: Set up database dependency override and mock PasswordResetUsedError
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            with patch.object(
                PasswordResetService,
                "verify_token",
                side_effect=PasswordResetUsedError,
            ):
                # Act: Post already used token
                response = client.post(
                    "/api/v1/password-reset/verify",
                    json={"token": "used-token"},
                )

                # Assert: Verify 400 bad request response
                data = response.json()

                assert response.status_code == 400
                assert data["detail"] == "The password reset has already been used."
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_verify_token_invalid(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test verifying invalid password reset token."""

        # Arrange: Set up database dependency override and mock PasswordResetTokenNotValidError
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            with patch.object(
                PasswordResetService,
                "verify_token",
                side_effect=PasswordResetTokenNotValidError,
            ):
                # Act: Post invalid token
                response = client.post(
                    "/api/v1/password-reset/verify",
                    json={"token": "invalid-token"},
                )

                # Assert: Verify 400 bad request response
                data = response.json()

                assert response.status_code == 400
                assert data["detail"] == "The password reset token is not valid."
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_verify_token_missing_token(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test verifying password reset without token field."""

        # Arrange: Set up database dependency override
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            # Act: Post without token
            response = client.post(
                "/api/v1/password-reset/verify",
                json={},
            )

            # Assert: Verify 422 validation error
            assert response.status_code == 422
        finally:
            # Cleanup
            app.dependency_overrides.clear()


class TestConfirmPasswordReset:
    """Tests for the confirm_password_reset endpoint (POST /password-reset/confirm)."""

    def test_confirm_password_reset_success(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test successfully confirming a password reset."""

        # Arrange: Set up database dependency override and mock service method
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        expected_message = Message(message="Password reset successfully.")

        try:
            with patch.object(
                PasswordResetService,
                "reset_password",
                return_value=expected_message,
            ):
                # Act: Post password reset confirmation
                response = client.post(
                    "/api/v1/password-reset/confirm",
                    json={"token": "valid-token-123", "new_password": "newpassword123"},
                )

                # Assert: Verify successful password reset
                data = response.json()

                assert response.status_code == 200
                assert data["message"] == "Password reset successfully."
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_confirm_password_reset_not_found(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test confirming password reset with non-existent token."""

        # Arrange: Set up database dependency override and mock PasswordResetNotFoundError
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            with patch.object(
                PasswordResetService,
                "reset_password",
                side_effect=PasswordResetNotFoundError,
            ):
                # Act: Post non-existent token
                response = client.post(
                    "/api/v1/password-reset/confirm",
                    json={"token": "nonexistent-token", "new_password": "newpassword123"},
                )

                # Assert: Verify 404 not found response
                data = response.json()

                assert response.status_code == 404
                assert data["detail"] == "Password reset request not found."
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_confirm_password_reset_expired(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test confirming password reset with expired token."""

        # Arrange: Set up database dependency override and mock PasswordResetExpiredError
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            with patch.object(
                PasswordResetService,
                "reset_password",
                side_effect=PasswordResetExpiredError,
            ):
                # Act: Post expired token
                response = client.post(
                    "/api/v1/password-reset/confirm",
                    json={"token": "expired-token", "new_password": "newpassword123"},
                )

                # Assert: Verify 400 bad request response
                data = response.json()

                assert response.status_code == 400
                assert data["detail"] == "The password reset has expired."
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_confirm_password_reset_already_used(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test confirming password reset with already used token."""

        # Arrange: Set up database dependency override and mock PasswordResetUsedError
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            with patch.object(
                PasswordResetService,
                "reset_password",
                side_effect=PasswordResetUsedError,
            ):
                # Act: Post already used token
                response = client.post(
                    "/api/v1/password-reset/confirm",
                    json={"token": "used-token", "new_password": "newpassword123"},
                )

                # Assert: Verify 400 bad request response
                data = response.json()

                assert response.status_code == 400
                assert data["detail"] == "The password reset has already been used."
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_confirm_password_reset_invalid_token(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test confirming password reset with invalid token."""

        # Arrange: Set up database dependency override and mock PasswordResetTokenNotValidError
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            with patch.object(
                PasswordResetService,
                "reset_password",
                side_effect=PasswordResetTokenNotValidError,
            ):
                # Act: Post invalid token
                response = client.post(
                    "/api/v1/password-reset/confirm",
                    json={"token": "invalid-token", "new_password": "newpassword123"},
                )

                # Assert: Verify 400 bad request response
                data = response.json()

                assert response.status_code == 400
                assert data["detail"] == "The password reset token is not valid."
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_confirm_password_reset_missing_token(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test confirming password reset without token field."""

        # Arrange: Set up database dependency override
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            # Act: Post without token
            response = client.post(
                "/api/v1/password-reset/confirm",
                json={"new_password": "newpassword123"},
            )

            # Assert: Verify 422 validation error
            assert response.status_code == 422
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_confirm_password_reset_missing_password(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test confirming password reset without new_password field."""

        # Arrange: Set up database dependency override
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            # Act: Post without new_password
            response = client.post(
                "/api/v1/password-reset/confirm",
                json={"token": "valid-token-123"},
            )

            # Assert: Verify 422 validation error
            assert response.status_code == 422
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_confirm_password_reset_short_password(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test confirming password reset with password that's too short."""

        # Arrange: Set up database dependency override
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            # Act: Post with password that's too short (less than 8 characters)
            response = client.post(
                "/api/v1/password-reset/confirm",
                json={"token": "valid-token-123", "new_password": "short"},
            )

            # Assert: Verify 422 validation error
            assert response.status_code == 422
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_confirm_password_reset_long_password(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test confirming password reset with password that's too long."""

        # Arrange: Set up database dependency override
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            # Act: Post with a password longer than bcrypt is able to hash
            response = client.post(
                "/api/v1/password-reset/confirm",
                json={"token": "valid-token-123", "new_password": "a" * (BCRYPT_MAX_PASSWORD_BYTES + 1)},
            )

            # Assert: Verify 422 validation error
            assert response.status_code == 422
        finally:
            # Cleanup
            app.dependency_overrides.clear()
