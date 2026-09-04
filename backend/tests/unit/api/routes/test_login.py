from collections.abc import Generator
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.exceptions import UserNotActiveError, UserNotFoundError
from app.exceptions.password_exceptions import InvalidCredentialsError
from app.main import app
from app.models import Token, User
from app.services import UserService


class TestLoginAccessToken:
    """Tests for the login_access_token endpoint (POST /login/access-token)."""

    def test_login_success(
        self,
        client: TestClient,
        test_user: User,
        user_token: str,
        mock_db_session: MagicMock,
    ) -> None:
        """Test successfully logging in with valid credentials."""
        # Arrange: Set up database dependency override and mock authentication
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        expected_token = Token(access_token=user_token, token_type="bearer")

        try:
            with patch.object(UserService, "authenticate", return_value=expected_token):
                # Act: Post login credentials
                response = client.post(
                    "/api/v1/login/access-token",
                    data={
                        "username": test_user.email,
                        "password": "testpassword123",
                    },
                )

                # Assert: Verify successful login response
                data = response.json()

                assert response.status_code == 200
                assert data["access_token"] == user_token
                assert data["token_type"] == "bearer"
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_login_user_not_found(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test login with non-existent user email."""
        # Arrange: Set up database dependency override and mock UserNotFoundError
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            with patch.object(UserService, "authenticate", side_effect=UserNotFoundError):
                # Act: Post login with non-existent user email
                response = client.post(
                    "/api/v1/login/access-token",
                    data={
                        "username": "nonexistent@example.com",
                        "password": "password123",
                    },
                )

                # Assert: Verify 404 error response
                data = response.json()

                assert response.status_code == 404
                assert data["detail"] == "User not found."
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_login_invalid_password(
        self,
        client: TestClient,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test login with incorrect password."""
        # Arrange: Set up database dependency override and mock InvalidCredentialsError
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            with patch.object(UserService, "authenticate", side_effect=InvalidCredentialsError):
                # Act: Post login with incorrect password
                response = client.post(
                    "/api/v1/login/access-token",
                    data={
                        "username": test_user.email,
                        "password": "wrongpassword",
                    },
                )

                # Assert: Verify 401 unauthorized response
                data = response.json()

                assert response.status_code == 401
                assert data["detail"] == "Could not validate credentials."
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_login_inactive_user(
        self,
        client: TestClient,
        test_inactive_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test login with inactive user account."""
        # Arrange: Set up database dependency override and mock UserNotActiveError
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            with patch.object(UserService, "authenticate", side_effect=UserNotActiveError(user=test_inactive_user)):
                # Act: Post login with inactive user credentials
                response = client.post(
                    "/api/v1/login/access-token",
                    data={
                        "username": test_inactive_user.email,
                        "password": "inactivepassword123",
                    },
                )

                # Assert: Verify 403 forbidden response
                data = response.json()

                assert response.status_code == 403
                assert data["detail"] == f"User with email {test_inactive_user.email} is not active."
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_login_missing_username(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test login with missing username field."""
        # Arrange: Set up database dependency override
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            # Act: Post login without username
            response = client.post(
                "/api/v1/login/access-token",
                data={
                    "password": "password123",
                },
            )

            # Assert: Verify 422 validation error
            assert response.status_code == 422  # Unprocessable Entity
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_login_missing_password(
        self,
        client: TestClient,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test login with missing password field."""
        # Arrange: Set up database dependency override
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            # Act: Post login without password
            response = client.post(
                "/api/v1/login/access-token",
                data={
                    "username": test_user.email,
                },
            )

            # Assert: Verify 422 validation error
            assert response.status_code == 422  # Unprocessable Entity
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_login_empty_credentials(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test login with empty username and password."""
        # Arrange: Set up database dependency override and fail if authentication is reached
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            with patch.object(UserService, "authenticate", side_effect=UserNotFoundError) as mock_authenticate:
                # Act: Post login with empty credentials
                response = client.post(
                    "/api/v1/login/access-token",
                    data={
                        "username": "",
                        "password": "",
                    },
                )

                # Assert: Verify empty form values are rejected as missing before
                # the request reaches the service, rather than being looked up
                assert response.status_code == 422
                mock_authenticate.assert_not_called()
        finally:
            # Cleanup
            app.dependency_overrides.clear()
