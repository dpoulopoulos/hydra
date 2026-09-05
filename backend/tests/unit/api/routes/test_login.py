from collections.abc import Generator
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.exceptions import UserNotActiveError
from app.exceptions.password_exceptions import InvalidEmailOrPasswordError
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
        def override_get_db() -> Generator[MagicMock]:
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

    def test_login_unknown_email(
        self,
        client: TestClient,
        mock_db_session: MagicMock,
    ) -> None:
        """Test login with non-existent user email."""
        # Arrange: Set up database dependency override and mock InvalidEmailOrPasswordError
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            with patch.object(UserService, "authenticate", side_effect=InvalidEmailOrPasswordError):
                # Act: Post login with non-existent user email
                response = client.post(
                    "/api/v1/login/access-token",
                    data={
                        "username": "nonexistent@example.com",
                        "password": "password123",
                    },
                )

                # Assert: Verify the address is not reported as unregistered
                data = response.json()

                assert response.status_code == 401
                assert data["detail"] == "Incorrect email or password."
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_login_does_not_disclose_registered_addresses(
        self,
        client: TestClient,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test that an unknown address and a wrong password answer identically.

        The status code and the body are both compared: either one differing would let anyone read off
        which addresses have an account here, one request per address.
        """
        # Arrange: Set up database dependency override
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            # Act: Post the same junk password against an unregistered and a registered address
            with patch.object(UserService, "get_user_by_email", return_value=None):
                unknown = client.post(
                    "/api/v1/login/access-token",
                    data={"username": "nonexistent@example.com", "password": "junkpassword123"},
                )

            with patch.object(UserService, "get_user_by_email", return_value=test_user):
                registered = client.post(
                    "/api/v1/login/access-token",
                    data={"username": test_user.email, "password": "junkpassword123"},
                )

            # Assert: Both answers are the same 401, byte for byte
            assert unknown.status_code == 401
            assert unknown.status_code == registered.status_code
            assert unknown.content == registered.content
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
        # Arrange: Set up database dependency override and mock InvalidEmailOrPasswordError
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            with patch.object(UserService, "authenticate", side_effect=InvalidEmailOrPasswordError):
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
                assert data["detail"] == "Incorrect email or password."
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
        def override_get_db() -> Generator[MagicMock]:
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
        def override_get_db() -> Generator[MagicMock]:
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
        def override_get_db() -> Generator[MagicMock]:
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
        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            with patch.object(
                UserService, "authenticate", side_effect=InvalidEmailOrPasswordError
            ) as mock_authenticate:
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
