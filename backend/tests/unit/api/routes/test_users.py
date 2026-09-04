import uuid
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_active_superuser, get_current_user, get_db
from app.exceptions import (
    DeleteSuperUserError,
    PasswordUnmodifiedError,
    UserExistsError,
    UserNotAuthorizedError,
    UserNotFoundError,
)
from app.exceptions.password_exceptions import PasswordIsWrongError
from app.main import app
from app.models import Message, User, UserPublic, UsersPublic
from app.services import HouseholdService, UserService


class TestCreateUser:
    """Tests for the create_user endpoint (POST /users/)."""

    def test_create_user_success(
        self,
        client: TestClient,
        test_superuser: User,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test successfully creating a new user as a superuser."""
        # Arrange: Set up dependency overrides and mock user creation
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_superuser

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_current_active_superuser] = override_get_current_user

        try:
            with patch.object(UserService, "create_user", return_value=test_user):
                # Act: Post new user data as superuser
                response = client.post(
                    "/api/v1/users/",
                    json={
                        "email": test_user.email,
                        "password": "password123",
                        "full_name": test_user.full_name,
                    },
                )

                # Assert: Verify user was created successfully
                data = response.json()

                assert response.status_code == 200
                assert data["email"] == test_user.email
                assert data["full_name"] == test_user.full_name
                assert data["is_active"] is True
                assert data["is_superuser"] is False
                assert "hashed_password" not in data
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_create_user_already_exists(
        self,
        client: TestClient,
        test_superuser: User,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test creating a user with an email that already exists."""
        # Arrange: Set up dependency overrides and mock UserExistsError
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_superuser

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_current_active_superuser] = override_get_current_user

        try:
            with patch.object(UserService, "create_user", side_effect=UserExistsError(user=test_user)):
                # Act: Post user data with existing email
                response = client.post(
                    "/api/v1/users/",
                    json={"email": "test@example.com", "password": "password123", "full_name": "Test User"},
                )

                # Assert: Verify 409 conflict error response
                data = response.json()

                assert response.status_code == 409
                assert data["detail"] == f"Conflict: User with unique identifier '{test_user.email}' already exists."
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_create_user_not_superuser(
        self,
        client: TestClient,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test creating a user as a non-superuser (should fail)."""
        # Arrange: Set up dependency overrides with regular user that raises UserNotAuthorizedError
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_user

        def override_get_current_active_superuser() -> User:
            raise UserNotAuthorizedError(user=test_user)

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_current_active_superuser] = override_get_current_active_superuser

        try:
            # Act: Attempt to create user as non-superuser
            response = client.post(
                "/api/v1/users/",
                json={"email": "newuser@example.com", "password": "password123", "full_name": "New User"},
            )

            # Assert: Verify 403 forbidden response
            data = response.json()

            assert response.status_code == 403
            error_msg = f"User with email '{test_user.email}' doesn't have enough privileges to perform this action."
            assert data["detail"] == error_msg
        finally:
            # Cleanup
            app.dependency_overrides.clear()


class TestRegisterUser:
    """Tests for the register_user endpoint (POST /users/signup)."""

    def test_register_user_success(
        self,
        client: TestClient,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test successfully registering a new user."""
        # Arrange: Set up database dependency override and mock user creation
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            with (
                patch.object(UserService, "create_user", return_value=test_user),
                patch("app.services.email_verification.EmailVerificationService.send_verification_email"),
            ):
                # Act: Post signup data
                response = client.post(
                    "/api/v1/users/signup",
                    json={
                        "email": test_user.email,
                        "password": "password123",
                        "full_name": test_user.full_name,
                    },
                )

                # Assert: Verify user was registered successfully
                data = response.json()

                assert response.status_code == 200
                assert data["email"] == test_user.email
                assert data["full_name"] == test_user.full_name
                assert data["is_active"] is True
                assert data["is_superuser"] is False
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_register_user_already_exists(
        self,
        client: TestClient,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test registering with an email that already exists."""
        # Arrange: Set up database dependency override and mock UserExistsError
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        app.dependency_overrides[get_db] = override_get_db

        try:
            with patch.object(UserService, "create_user", side_effect=UserExistsError(user=test_user)):
                # Act: Post signup data with existing email
                response = client.post(
                    "/api/v1/users/signup",
                    json={
                        "email": "test@example.com",
                        "password": "password123",
                        "full_name": "Test User",
                    },
                )

                # Assert: Verify 409 conflict error response
                data = response.json()

                assert response.status_code == 409
                assert data["detail"] == f"Conflict: User with unique identifier '{test_user.email}' already exists."
        finally:
            # Cleanup
            app.dependency_overrides.clear()


class TestGetUserMe:
    """Tests for the get_user_me endpoint (GET /users/me)."""

    def test_get_user_me_success(
        self,
        client: TestClient,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test successfully retrieving current user information."""
        # Arrange: Set up dependency overrides with authenticated user
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        try:
            # Act: Get current user information
            response = client.get("/api/v1/users/me")

            # Assert: Verify user information is returned correctly
            data = response.json()

            assert response.status_code == 200
            assert data["email"] == test_user.email
            assert data["full_name"] == test_user.full_name
            assert data["id"] == str(test_user.id)
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_get_user_me_inactive_user(
        self,
        client: TestClient,
        test_inactive_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test retrieving user info with inactive user token."""
        # Arrange: Set up dependency overrides that raise UserNotAuthorizedError for inactive user
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            raise UserNotAuthorizedError(user=test_inactive_user)

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        try:
            # Act: Attempt to get current user information
            response = client.get("/api/v1/users/me")

            # Assert: Verify 403 forbidden response
            assert response.status_code == 403
        finally:
            # Cleanup
            app.dependency_overrides.clear()

    def test_get_user_me_no_token(self, client: TestClient) -> None:
        """Test retrieving user info without authentication token."""
        # Act: Attempt to get current user without authentication
        response = client.get("/api/v1/users/me")

        # Assert: Verify 401 unauthorized response
        assert response.status_code == 401


class TestGetUserById:
    """Tests for the get_user_by_id endpoint (GET /users/{user_id})."""

    def test_get_own_user_by_id(
        self,
        client: TestClient,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test retrieving own user information by ID."""
        # Arrange: Set up dependency overrides and mock get_user_by_id
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        try:
            with patch.object(UserService, "get_user_by_id", return_value=test_user):
                # Act: Get own user by ID
                response = client.get(f"/api/v1/users/{test_user.id}")

                # Assert: Verify user information is returned correctly
                data = response.json()

                assert response.status_code == 200
                assert data["email"] == test_user.email
                assert data["id"] == str(test_user.id)
        finally:
            app.dependency_overrides.clear()

    def test_get_another_user_by_id_as_superuser(
        self,
        client: TestClient,
        test_superuser: User,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test superuser retrieving another user's information."""
        # Arrange: Set up dependency overrides with superuser and mock get_user_by_id
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_superuser

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        try:
            with patch.object(UserService, "get_user_by_id", return_value=test_user):
                # Act: Get another user's information as superuser
                response = client.get(f"/api/v1/users/{test_user.id}")

                # Assert: Verify user information is returned correctly
                data = response.json()

                assert response.status_code == 200
                assert data["email"] == test_user.email
                assert data["id"] == str(test_user.id)
        finally:
            app.dependency_overrides.clear()

    def test_get_another_user_by_id_as_regular_user(
        self,
        client: TestClient,
        test_user: User,
        another_test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test regular user trying to retrieve another user's information (should fail)."""
        # Arrange: Set up dependency overrides and mock UserNotAuthorizedError
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        try:
            with patch.object(UserService, "get_user_by_id", side_effect=UserNotAuthorizedError(test_user)):
                # Act: Attempt to get another user's information as regular user
                response = client.get(f"/api/v1/users/{another_test_user.id}")

                # Assert: Verify 403 forbidden response
                assert response.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_get_user_by_id_not_found(
        self,
        client: TestClient,
        test_superuser: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test retrieving a non-existent user."""
        # Arrange: Set up dependency overrides and mock UserNotFoundError
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_superuser

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        try:
            with patch.object(UserService, "get_user_by_id", side_effect=UserNotFoundError):
                nonexistent_id = uuid.UUID("99999999-9999-9999-9999-999999999999")

                # Act: Attempt to get non-existent user
                response = client.get(f"/api/v1/users/{nonexistent_id}")

                # Assert: Verify 404 not found response
                assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()


class TestGetUsers:
    """Tests for the get_users endpoint (GET /users/)."""

    def test_get_users_success(
        self,
        client: TestClient,
        test_superuser: User,
        test_user: User,
        another_test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test successfully retrieving list of users as superuser."""
        # Arrange: Set up dependency overrides and mock get_users
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_superuser

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_current_active_superuser] = override_get_current_user

        try:
            users = UsersPublic(
                data=[
                    UserPublic.model_validate(test_superuser),
                    UserPublic.model_validate(test_user),
                    UserPublic.model_validate(another_test_user),
                ],
                count=3,
            )
            with patch.object(UserService, "get_users", return_value=users):
                # Act: Get list of all users as superuser
                response = client.get("/api/v1/users/")

                # Assert: Verify user list is returned correctly
                users = response.json()

                assert response.status_code == 200
                assert users["count"] == 3
                assert len(users["data"]) == 3
        finally:
            app.dependency_overrides.clear()

    def test_get_users_with_pagination(
        self,
        client: TestClient,
        test_superuser: User,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test retrieving users with pagination parameters."""
        # Arrange: Set up dependency overrides and mock get_users with pagination
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_superuser

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_current_active_superuser] = override_get_current_user

        try:
            users = UsersPublic(data=[UserPublic.model_validate(test_user)], count=10)
            with patch.object(UserService, "get_users", return_value=users):
                # Act: Get users with skip and limit parameters
                response = client.get("/api/v1/users/?skip=5&limit=5")

                # Assert: Verify paginated response is correct
                users = response.json()

                assert response.status_code == 200
                assert users["count"] == 10
                assert len(users["data"]) == 1
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.parametrize("query", ["?limit=-1", "?limit=0", "?limit=100000000", "?skip=-1"])
    def test_get_users_rejects_pagination_outside_the_range(
        self,
        client: TestClient,
        test_superuser: User,
        mock_db_session: MagicMock,
        query: str,
    ) -> None:
        """A negative limit reaches Postgres as a negative LIMIT: a 500 where a 422 belongs."""
        # Arrange: Set up dependency overrides for a superuser
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_superuser

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_current_active_superuser] = override_get_current_user

        try:
            with patch.object(UserService, "get_users") as get_users:
                # Act: Ask for a page outside the range the route allows
                response = client.get(f"/api/v1/users/{query}")

                # Assert: Verify the request was rejected before reaching the service
                assert response.status_code == 422
                get_users.assert_not_called()
        finally:
            app.dependency_overrides.clear()

    def test_get_users_not_superuser(
        self,
        client: TestClient,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test retrieving users as non-superuser (should fail)."""
        # Arrange: Set up dependency overrides with regular user that raises UserNotAuthorizedError
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_user

        def override_get_current_active_superuser() -> User:
            raise UserNotAuthorizedError(user=test_user)

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_current_active_superuser] = override_get_current_active_superuser

        try:
            # Act: Attempt to get users as non-superuser
            response = client.get("/api/v1/users/")

            # Assert: Verify 403 forbidden response
            assert response.status_code == 403
        finally:
            # Cleanup
            app.dependency_overrides.clear()


class TestUpdateUserMe:
    """Tests for the update_user_me endpoint (PATCH /users/me)."""

    def test_update_user_me_success(
        self,
        client: TestClient,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test successfully updating current user's information."""
        # Arrange: Set up dependency overrides and mock update_user_me
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_user

        updated_user = User(
            email=test_user.email,
            full_name="Updated Name",
            hashed_password=test_user.hashed_password,
            is_active=test_user.is_active,
            is_superuser=test_user.is_superuser,
        )
        updated_user.id = test_user.id

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        try:
            with patch.object(UserService, "update_user_me", return_value=updated_user):
                # Act: Update current user's full name
                response = client.patch(
                    "/api/v1/users/me",
                    json={"full_name": "Updated Name"},
                )

                # Assert: Verify user was updated successfully
                data = response.json()

                assert response.status_code == 200
                assert data["full_name"] == "Updated Name"
                assert data["email"] == test_user.email
        finally:
            app.dependency_overrides.clear()

    def test_update_user_me_email_exists(
        self,
        client: TestClient,
        test_user: User,
        another_test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test updating email to one that already exists."""
        # Arrange: Set up dependency overrides and mock UserExistsError
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        try:
            with patch.object(UserService, "update_user_me", side_effect=UserExistsError(user=another_test_user)):
                # Act: Attempt to update email to existing one
                response = client.patch(
                    "/api/v1/users/me",
                    json={"email": "another@example.com"},
                )

                # Assert: Verify 409 conflict response
                assert response.status_code == 409
        finally:
            app.dependency_overrides.clear()


class TestUpdateUser:
    """Tests for the update_user endpoint (PATCH /users/{user_id})."""

    def test_update_user_success(
        self,
        client: TestClient,
        test_superuser: User,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test superuser successfully updating a user."""
        # Arrange: Set up dependency overrides and mock update_user
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_superuser

        updated_user = User(
            email="newemail@example.com",
            full_name=test_user.full_name,
            hashed_password=test_user.hashed_password,
            is_active=test_user.is_active,
            is_superuser=test_user.is_superuser,
        )
        updated_user.id = test_user.id

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_current_active_superuser] = override_get_current_user

        try:
            with patch.object(UserService, "update_user", return_value=updated_user):
                # Act: Update user's email as superuser
                response = client.patch(
                    f"/api/v1/users/{test_user.id}",
                    json={"email": "newemail@example.com"},
                )

                # Assert: Verify user was updated successfully
                data = response.json()

                assert response.status_code == 200
                assert data["email"] == "newemail@example.com"
        finally:
            app.dependency_overrides.clear()

    def test_update_user_not_found(
        self,
        client: TestClient,
        test_superuser: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test updating a non-existent user."""
        # Arrange: Set up dependency overrides and mock UserNotFoundError
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_superuser

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_current_active_superuser] = override_get_current_user

        try:
            with patch.object(UserService, "update_user", side_effect=UserNotFoundError):
                nonexistent_id = uuid.UUID("99999999-9999-9999-9999-999999999999")

                # Act: Attempt to update non-existent user
                response = client.patch(
                    f"/api/v1/users/{nonexistent_id}",
                    json={"email": "newemail@example.com"},
                )

                # Assert: Verify 404 not found response
                assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_update_user_not_superuser(
        self,
        client: TestClient,
        test_user: User,
        another_test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test regular user trying to update another user (should fail)."""
        # Arrange: Set up dependency overrides with regular user that raises UserNotAuthorizedError
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_user

        def override_get_current_active_superuser() -> User:
            raise UserNotAuthorizedError(user=test_user)

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_current_active_superuser] = override_get_current_active_superuser

        try:
            # Act: Attempt to update another user as non-superuser
            response = client.patch(
                f"/api/v1/users/{another_test_user.id}",
                json={"email": "newemail@example.com"},
            )

            # Assert: Verify 403 forbidden response
            assert response.status_code == 403
        finally:
            # Cleanup
            app.dependency_overrides.clear()


class TestUpdatePasswordMe:
    """Tests for the update_password_me endpoint (PATCH /users/me/password)."""

    def test_update_password_success(
        self,
        client: TestClient,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test successfully updating password."""
        # Arrange: Set up dependency overrides and mock update_password
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        try:
            success_message = Message(message="Password updated successfully.")
            with patch.object(UserService, "update_password", return_value=success_message):
                # Act: Update password with valid current and new password
                response = client.patch(
                    "/api/v1/users/me/password",
                    json={"current_password": "testpassword123", "new_password": "newpassword456"},
                )

                # Assert: Verify password was updated successfully
                data = response.json()

                assert response.status_code == 200
                assert data["message"] == "Password updated successfully."
        finally:
            app.dependency_overrides.clear()

    def test_update_password_incorrect_current(
        self,
        client: TestClient,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test updating password with incorrect current password."""
        # Arrange: Set up dependency overrides and mock PasswordIsWrongError
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        try:
            with patch.object(UserService, "update_password", side_effect=PasswordIsWrongError):
                # Act: Attempt to update password with wrong current password
                response = client.patch(
                    "/api/v1/users/me/password",
                    json={"current_password": "wrongpassword", "new_password": "newpassword456"},
                )

                # Assert: Verify 401 unauthorized response
                assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()

    def test_update_password_same_as_current(
        self,
        client: TestClient,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test updating password to the same as current password."""
        # Arrange: Set up dependency overrides and mock PasswordUnmodifiedError
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        try:
            with patch.object(UserService, "update_password", side_effect=PasswordUnmodifiedError):
                # Act: Attempt to update password to same as current
                response = client.patch(
                    "/api/v1/users/me/password",
                    json={"current_password": "testpassword123", "new_password": "testpassword123"},
                )

                # Assert: Verify 400 bad request response
                assert response.status_code == 400
        finally:
            app.dependency_overrides.clear()


class TestDeleteUserMe:
    """Tests for the delete_user_me endpoint (DELETE /users/me)."""

    def test_delete_user_me_success(
        self,
        client: TestClient,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test successfully deleting current user."""
        # Arrange: Set up dependency overrides and mock delete_user_me
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        try:
            success_message = Message(message="User deleted successfully.")
            with patch.object(UserService, "delete_user_me", return_value=success_message):
                # Act: Delete current user
                response = client.delete("/api/v1/users/me")

                # Assert: Verify user was deleted successfully
                data = response.json()

                assert response.status_code == 200
                assert data["message"] == "User deleted successfully."
        finally:
            app.dependency_overrides.clear()

    def test_delete_user_me_hands_over_the_household_service(
        self,
        client: TestClient,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Without it the user's household would be left behind."""
        # Arrange: Set up dependency overrides and mock delete_user_me
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        try:
            success_message = Message(message="User deleted successfully.")
            with patch.object(UserService, "delete_user_me", return_value=success_message) as delete_user_me:
                # Act: Delete current user
                response = client.delete("/api/v1/users/me")

                # Assert: Verify the household service reached the service call
                assert response.status_code == 200
                assert isinstance(delete_user_me.call_args.kwargs["household_service"], HouseholdService)
        finally:
            app.dependency_overrides.clear()

    def test_delete_user_me_superuser(
        self,
        client: TestClient,
        test_superuser: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test superuser trying to delete their own account (should fail)."""
        # Arrange: Set up dependency overrides and mock DeleteSuperUserError
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_superuser

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        try:
            with patch.object(UserService, "delete_user_me", side_effect=DeleteSuperUserError):
                # Act: Attempt to delete own account as superuser
                response = client.delete("/api/v1/users/me")

                # Assert: Verify 400 bad request response
                assert response.status_code == 400
        finally:
            app.dependency_overrides.clear()


class TestDeleteUser:
    """Tests for the delete_user endpoint (DELETE /users/{user_id})."""

    def test_delete_user_success(
        self,
        client: TestClient,
        test_superuser: User,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test superuser successfully deleting another user."""
        # Arrange: Set up dependency overrides and mock delete_user
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_superuser

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_current_active_superuser] = override_get_current_user

        try:
            success_message = Message(message="User deleted successfully")
            with patch.object(UserService, "delete_user", return_value=success_message):
                # Act: Delete user as superuser
                response = client.delete(f"/api/v1/users/{test_user.id}")

                # Assert: Verify user was deleted successfully
                data = response.json()

                assert response.status_code == 200
                assert data["message"] == "User deleted successfully"
        finally:
            app.dependency_overrides.clear()

    def test_delete_user_hands_over_the_household_service(
        self,
        client: TestClient,
        test_superuser: User,
        test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """A superuser deleting somebody must not leave their household either."""
        # Arrange: Set up dependency overrides and mock delete_user
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_superuser

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_current_active_superuser] = override_get_current_user

        try:
            success_message = Message(message="User deleted successfully")
            with patch.object(UserService, "delete_user", return_value=success_message) as delete_user:
                # Act: Delete the user as a superuser
                response = client.delete(f"/api/v1/users/{test_user.id}")

                # Assert: Verify the household service reached the service call
                assert response.status_code == 200
                assert isinstance(delete_user.call_args.kwargs["household_service"], HouseholdService)
        finally:
            app.dependency_overrides.clear()

    def test_delete_user_not_found(
        self,
        client: TestClient,
        test_superuser: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test deleting a non-existent user."""
        # Arrange: Set up dependency overrides and mock UserNotFoundError
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_superuser

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_current_active_superuser] = override_get_current_user

        try:
            with patch.object(UserService, "delete_user", side_effect=UserNotFoundError):
                nonexistent_id = uuid.UUID("99999999-9999-9999-9999-999999999999")

                # Act: Attempt to delete non-existent user
                response = client.delete(f"/api/v1/users/{nonexistent_id}")

                # Assert: Verify 404 not found response
                assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_delete_user_self_as_superuser(
        self,
        client: TestClient,
        test_superuser: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test superuser trying to delete their own account (should fail)."""
        # Arrange: Set up dependency overrides and mock DeleteSuperUserError
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_superuser

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_current_active_superuser] = override_get_current_user

        try:
            with patch.object(UserService, "delete_user", side_effect=DeleteSuperUserError):
                # Act: Attempt to delete own account as superuser
                response = client.delete(f"/api/v1/users/{test_superuser.id}")

                # Assert: Verify 400 bad request response
                assert response.status_code == 400
        finally:
            app.dependency_overrides.clear()

    def test_delete_user_not_superuser(
        self,
        client: TestClient,
        test_user: User,
        another_test_user: User,
        mock_db_session: MagicMock,
    ) -> None:
        """Test regular user trying to delete another user (should fail)."""
        # Arrange: Set up dependency overrides with regular user that raises UserNotAuthorizedError
        def override_get_db() -> Generator[MagicMock, None, None]:
            yield mock_db_session

        def override_get_current_user() -> User:
            return test_user

        def override_get_current_active_superuser() -> User:
            raise UserNotAuthorizedError(user=test_user)

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_current_active_superuser] = override_get_current_active_superuser

        try:
            # Act: Attempt to delete another user as non-superuser
            response = client.delete(f"/api/v1/users/{another_test_user.id}")

            # Assert: Verify 403 forbidden response
            assert response.status_code == 403
        finally:
            # Cleanup
            app.dependency_overrides.clear()
