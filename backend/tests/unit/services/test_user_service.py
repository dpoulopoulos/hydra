import logging
import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.core.config import settings
from app.core.security import dummy_password_hash
from app.exceptions import (
    DeleteSuperUserError,
    InvalidEmailOrPasswordError,
    PasswordIsWrongError,
    PasswordUnmodifiedError,
    UserExistsError,
    UserNotActiveError,
    UserNotAuthorizedError,
    UserNotFoundError,
)
from app.models import (
    Message,
    PasswordUpdate,
    Token,
    TokenPayload,
    User,
    UserCreate,
    UserPublic,
    UserRegister,
    UserUpdate,
    UserUpdateMe,
)
from app.services import EmailVerificationService, PasswordResetService, UserService


class TestAuthenticate:
    """Tests for the authenticate method."""

    def test_authenticate_success(
        self, mock_user_service: UserService, test_user: User, user_token: str
    ) -> None:
        """Test successful user authentication."""
        # Arrange: Mock database query to return test user
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = test_user

        # Act: Authenticate with valid credentials
        with patch("app.services.user.verify_password", return_value=True):
            with patch("app.services.user.create_access_token") as mock_create_token:
                mock_create_token.return_value = user_token
                result = mock_user_service.authenticate(
                    email=test_user.email, password="testpassword123"
                )

        # Assert: Verify token was created with correct user ID and expiry
        assert isinstance(result, Token)
        assert result.access_token == user_token

        call_args = mock_create_token.call_args
        assert call_args[0][0] == test_user.id

        mock_create_token.assert_called_once()

    def test_authenticate_user_not_found(
        self, mock_user_service: UserService
    ) -> None:
        """Test authentication when user does not exist."""
        # Arrange: Mock database query to return None (user not found)
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = None

        # Act & Assert: Verify the failure does not name the email as the reason
        with pytest.raises(InvalidEmailOrPasswordError):
            mock_user_service.authenticate(
                email="nonexistent@example.com", password="password123"
            )

    def test_authenticate_wrong_password(
        self, mock_user_service: UserService, test_user: User
    ) -> None:
        """Test authentication with incorrect password."""
        # Arrange: Mock database query and password verification to fail
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = test_user

        # Act & Assert: Verify the failure does not name the password as the reason
        with patch("app.services.user.verify_password", return_value=False):
            with pytest.raises(InvalidEmailOrPasswordError):
                mock_user_service.authenticate(
                    email=test_user.email, password="wrongpassword"
                )

    def test_authenticate_hashes_a_password_even_when_the_email_is_unknown(
        self, mock_user_service: UserService
    ) -> None:
        """Test that an unknown address still pays for a password check.

        Hashing is deliberately slow, so returning without it would make an unregistered address answer
        measurably sooner and give the same answer the status code no longer does.
        """
        # Arrange: Mock database query to return None (user not found)
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = None

        # Act: Authenticate an unregistered address
        with patch("app.services.user.verify_password", return_value=False) as mock_verify_password:
            with pytest.raises(InvalidEmailOrPasswordError):
                mock_user_service.authenticate(
                    email="nonexistent@example.com", password="junkpassword123"
                )

        # Assert: Verify the password was checked against the dummy hash
        mock_verify_password.assert_called_once_with("junkpassword123", dummy_password_hash())

    def test_authenticate_reports_unknown_email_and_wrong_password_alike(
        self, mock_user_service: UserService, test_user: User
    ) -> None:
        """Test that neither credential failure says which of the two it was.

        The caller turns this message into the response body, so a difference here is a way of asking
        whether an address has an account.
        """
        # Arrange: Mock database query to return no user, then the test user
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = None

        # Act: Authenticate an unregistered address, then a registered one with a wrong password
        with pytest.raises(InvalidEmailOrPasswordError) as unknown_email:
            mock_user_service.authenticate(
                email="nonexistent@example.com", password="junkpassword123"
            )

        mock_user_service.session.exec.return_value.first.return_value = test_user

        with patch("app.services.user.verify_password", return_value=False):
            with pytest.raises(InvalidEmailOrPasswordError) as wrong_password:
                mock_user_service.authenticate(
                    email=test_user.email, password="junkpassword123"
                )

        # Assert: Both failures carry the same message
        assert unknown_email.value.message == wrong_password.value.message

    def test_authenticate_inactive_user(
        self, mock_user_service: UserService, test_inactive_user: User
    ) -> None:
        """Test authentication with inactive user."""
        # Arrange: Mock database query to return inactive user
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = (
            test_inactive_user
        )

        # Act & Assert: Verify UserNotActiveError is raised for inactive user
        with patch("app.services.user.verify_password", return_value=True):
            with pytest.raises(UserNotActiveError):
                mock_user_service.authenticate(
                    email=test_inactive_user.email, password="password123"
                )

    def test_authenticate_inactive_user_with_pending_verification(
        self, mock_user_service: UserService, test_inactive_user: User, mock_email_verification_service
    ) -> None:
        """Test authentication with inactive user with pending email verification."""
        # Arrange: Mock database query to return inactive user
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = (
            test_inactive_user
        )

        # Mock email verification service with pending verification
        mock_pending_verification = MagicMock()
        mock_email_verification_service.get_pending_verification_by_user_id = MagicMock(
            return_value=mock_pending_verification
        )

        # Act & Assert: Verify UserNotActiveError is raised with is_verified=False
        with patch("app.services.user.verify_password", return_value=True):
            with pytest.raises(UserNotActiveError) as exc_info:
                mock_user_service.authenticate(
                    email=test_inactive_user.email,
                    password="password123",
                    email_verification_service=mock_email_verification_service,
                )
            # Verify is_verified is False when pending verification exists
            assert exc_info.value.is_verified is False

    def test_authenticate_inactive_user_without_pending_verification(
        self, mock_user_service: UserService, test_inactive_user: User, mock_email_verification_service
    ) -> None:
        """Test authentication with inactive user without pending email verification."""
        # Arrange: Mock database query to return inactive user
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = (
            test_inactive_user
        )

        # Mock email verification service with no pending verification
        mock_email_verification_service.get_pending_verification_by_user_id = MagicMock(
            return_value=None
        )

        # Act & Assert: Verify UserNotActiveError is raised with is_verified=True
        with patch("app.services.user.verify_password", return_value=True):
            with pytest.raises(UserNotActiveError) as exc_info:
                mock_user_service.authenticate(
                    email=test_inactive_user.email,
                    password="password123",
                    email_verification_service=mock_email_verification_service,
                )
            # Verify is_verified is True when no pending verification exists
            assert exc_info.value.is_verified is True


class TestCreateUser:
    """Tests for the create_user method."""

    def test_create_user_success(
        self, mock_user_service: UserService, test_user: User
    ) -> None:
        """Test successful user creation."""
        # Arrange: Mock database operations and user data
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = None
        mock_user_service.session.add = MagicMock()
        mock_user_service.session.commit = MagicMock()
        mock_user_service.session.refresh = MagicMock()

        user_create = UserCreate(
            email="newuser@example.com",
            password="password123",
            full_name="New User",
        )

        # Act: Create new user with password hashing
        with patch("app.services.user.get_password_hash") as mock_hash:
            mock_hash.return_value = "hashed_password"
            result = mock_user_service.create_user(user_create=user_create, category_service=MagicMock())

        # Assert: Verify user was created and database operations were called
        assert isinstance(result, UserPublic)
        mock_user_service.session.add.assert_called_once()
        mock_user_service.session.commit.assert_called_once()
        mock_user_service.session.refresh.assert_called_once()

    def test_create_user_survives_a_failed_welcome_email(
        self, mock_user_service: UserService, monkeypatch, caplog
    ) -> None:
        """Test that a welcome email that cannot be delivered is only logged."""
        # Arrange: Mock database operations and turn mail on
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = None
        mock_user_service.session.add = MagicMock()
        mock_user_service.session.commit = MagicMock()
        mock_user_service.session.refresh = MagicMock()

        monkeypatch.setattr(settings, "EMAIL_PROVIDER", "resend")
        monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test_key")
        monkeypatch.setattr(settings, "EMAILS_FROM_EMAIL", "from@example.com")

        user_create = UserCreate(
            email="newuser@example.com",
            password="password123",
            full_name="New User",
        )

        # Act: Create the user while the provider is unreachable
        with patch("app.utils.email_utils.send_email", side_effect=httpx.ConnectTimeout("timed out")):
            with caplog.at_level(logging.ERROR, logger="app.utils.email_utils"):
                result = mock_user_service.create_user(user_create=user_create, category_service=MagicMock())

        # Assert: Verify the account is returned and the failure is on record
        assert isinstance(result, UserPublic)
        mock_user_service.session.commit.assert_called_once()
        assert "newuser@example.com" in caplog.text
        assert "ConnectTimeout" in caplog.text

    def test_create_user_with_user_register(
        self, mock_user_service: UserService
    ) -> None:
        """Test user creation with UserRegister model."""
        # Arrange: Mock database operations and UserRegister data
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = None
        mock_user_service.session.add = MagicMock()
        mock_user_service.session.commit = MagicMock()
        mock_user_service.session.refresh = MagicMock()

        user_register = UserRegister(
            email="newuser@example.com",
            password="password123",
            full_name="New User",
        )

        # Act: Create user using UserRegister model
        with patch("app.services.user.get_password_hash") as mock_hash:
            mock_hash.return_value = "hashed_password"
            result = mock_user_service.create_user(user_create=user_register, category_service=MagicMock())

        # Assert: Verify user was created and database operations were called
        assert isinstance(result, UserPublic)
        mock_user_service.session.add.assert_called_once()
        mock_user_service.session.commit.assert_called_once()
        mock_user_service.session.refresh.assert_called_once()

    def test_create_user_already_exists(
        self, mock_user_service: UserService, test_user: User
    ) -> None:
        """Test creating user when email already exists."""
        # Arrange: Mock database query to return existing user
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = test_user

        user_create = UserCreate(
            email=test_user.email,
            password="password123",
            full_name="Test User",
        )

        # Act & Assert: Verify UserExistsError is raised
        with pytest.raises(UserExistsError):
            mock_user_service.create_user(user_create=user_create, category_service=MagicMock())


class TestGetAuthenticatedUser:
    """Tests for the get_authenticated_user method."""

    def test_get_authenticated_user_success(
        self, mock_user_service: UserService, test_user: User
    ) -> None:
        """Test successful retrieval of authenticated user."""
        # Arrange: Mock repository to return active user
        mock_user_service.user_repository.get_by_id = MagicMock(return_value=test_user)
        token_data = TokenPayload(sub=str(test_user.id))

        # Act: Get authenticated user from token
        result = mock_user_service.get_authenticated_user(token_data=token_data)

        # Assert: Verify correct user was returned
        assert result == test_user
        mock_user_service.user_repository.get_by_id.assert_called_once_with(test_user.id)

    def test_get_authenticated_user_not_found(
        self, mock_user_service: UserService
    ) -> None:
        """Test getting authenticated user when user not found."""
        # Arrange: Mock repository to return None (user not found)
        mock_user_service.user_repository.get_by_id = MagicMock(return_value=None)
        token_data = TokenPayload(sub=str(uuid.uuid4()))

        # Act & Assert: Verify UserNotFoundError is raised
        with pytest.raises(UserNotFoundError):
            mock_user_service.get_authenticated_user(token_data=token_data)

    def test_get_authenticated_user_inactive(
        self, mock_user_service: UserService, test_inactive_user: User
    ) -> None:
        """Test getting authenticated user when user is inactive."""
        # Arrange: Mock repository to return inactive user
        mock_user_service.user_repository.get_by_id = MagicMock(return_value=test_inactive_user)
        token_data = TokenPayload(sub=str(test_inactive_user.id))

        # Act & Assert: Verify UserNotActiveError is raised
        with pytest.raises(UserNotActiveError):
            mock_user_service.get_authenticated_user(token_data=token_data)

    def test_get_authenticated_user_no_subject(
        self, mock_user_service: UserService
    ) -> None:
        """Test getting authenticated user when token has no subject."""
        # Arrange: Create token data with None subject
        token_data = TokenPayload(sub=None)

        # Act & Assert: Verify UserNotFoundError is raised
        with pytest.raises(UserNotFoundError):
            mock_user_service.get_authenticated_user(token_data=token_data)


class TestGetUserByEmail:
    """Tests for the get_user_by_email method."""

    def test_get_user_by_email_success(
        self, mock_user_service: UserService, test_user: User
    ) -> None:
        """Test successfully getting user by email."""
        # Arrange: Mock database query to return user
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = test_user

        # Act: Get user by email
        result = mock_user_service.get_user_by_email(email=test_user.email)

        # Assert: Verify correct user was returned
        assert result == test_user
        mock_user_service.session.exec.assert_called_once()

    def test_get_user_by_email_not_found(
        self, mock_user_service: UserService
    ) -> None:
        """Test getting user by email when user does not exist."""
        # Arrange: Mock database query to return None
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = None

        # Act: Attempt to get non-existent user by email
        result = mock_user_service.get_user_by_email(email="nonexistent@example.com")

        # Assert: Verify None was returned
        assert result is None
        mock_user_service.session.exec.assert_called_once()


class TestGetUserById:
    """Tests for the get_user_by_id method."""

    def test_get_user_by_id_own_user(
        self, mock_user_service: UserService, test_user: User
    ) -> None:
        """Test getting own user by ID."""
        # Arrange: Mock database to return user
        mock_user_service.session.get = MagicMock(return_value=test_user)

        # Act: Get own user by ID
        result = mock_user_service.get_user_by_id(
            current_user=test_user, user_id=test_user.id
        )

        # Assert: Verify correct user was returned
        assert result == UserPublic.model_validate(test_user)
        mock_user_service.session.get.assert_called_once()

    def test_get_user_by_id_as_superuser(
        self,
        mock_user_service: UserService,
        test_superuser: User,
        test_user: User,
    ) -> None:
        """Test superuser getting another user by ID."""
        # Arrange: Mock database to return target user
        mock_user_service.session.get = MagicMock(return_value=test_user)

        # Act: Get another user by ID as superuser
        result = mock_user_service.get_user_by_id(
            current_user=test_superuser, user_id=test_user.id
        )

        # Assert: Verify correct user was returned
        assert result == UserPublic.model_validate(test_user)
        mock_user_service.session.get.assert_called_once()

    def test_get_user_by_id_not_found(
        self, mock_user_service: UserService, test_user: User
    ) -> None:
        """Test getting user by ID when user not found."""
        # Arrange: Mock database to return None (user not found)
        mock_user_service.session.get = MagicMock(return_value=None)
        nonexistent_id = uuid.UUID("99999999-9999-9999-9999-999999999999")

        # Act & Assert: Verify UserNotFoundError is raised
        with pytest.raises(UserNotFoundError):
            mock_user_service.get_user_by_id(
                current_user=test_user, user_id=nonexistent_id
            )

    def test_get_user_by_id_not_authorized(
        self,
        mock_user_service: UserService,
        test_user: User,
        another_test_user: User,
    ) -> None:
        """Test regular user trying to get another user by ID."""
        # Arrange: Mock database to return another user
        mock_user_service.session.get = MagicMock(return_value=another_test_user)

        # Act & Assert: Verify UserNotAuthorizedError is raised
        with pytest.raises(UserNotAuthorizedError):
            mock_user_service.get_user_by_id(
                current_user=test_user, user_id=another_test_user.id
            )


class TestGetUsers:
    """Tests for the get_users method."""

    def test_get_users_success(
        self,
        mock_user_service: UserService,
        test_user: User,
        another_test_user: User,
    ) -> None:
        """Test successfully getting list of users."""
        # Arrange: Mock database queries for count and user list
        users = [UserPublic.model_validate(test_user), UserPublic.model_validate(another_test_user)]
        mock_user_service.session.exec = MagicMock()
        mock_exec = mock_user_service.session.exec

        # Mock count query
        mock_exec.return_value.one.return_value = 2
        # Mock users query
        mock_exec.return_value.all.return_value = users

        # Act: Get users with pagination
        result_users_public = mock_user_service.get_users(skip=0, limit=100)
        result_users = result_users_public.data
        result_count = result_users_public.count

        # Assert: Verify users and count are returned correctly
        assert result_users == users
        assert result_count == 2
        mock_user_service.session.exec.assert_called()

    def test_get_users_with_pagination(
        self, mock_user_service: UserService, test_user: User
    ) -> None:
        """Test getting users with pagination."""
        # Arrange: Mock database queries with pagination parameters
        mock_user_service.session.exec = MagicMock()
        mock_exec = mock_user_service.session.exec

        # Mock count query
        mock_exec.return_value.one.return_value = 10
        # Mock users query
        mock_exec.return_value.all.return_value = [test_user]

        # Act: Get users with skip and limit
        result_users_public = mock_user_service.get_users(skip=5, limit=5)
        result_users = result_users_public.data
        result_count = result_users_public.count

        # Assert: Verify paginated results are correct
        assert len(result_users) == 1
        assert result_count == 10
        mock_user_service.session.exec.assert_called()


class TestUpdateUserMe:
    """Tests for the update_user_me method."""

    def test_update_user_me_success(
        self,
        mock_user_service: UserService,
        test_user: User,
        mock_password_reset_service: PasswordResetService,
        mock_email_verification_service: EmailVerificationService,
    ) -> None:
        """Test successfully updating current user."""
        # Arrange: Mock database operations and update data
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = None
        mock_user_service.session.add = MagicMock()
        mock_user_service.session.commit = MagicMock()
        mock_user_service.session.refresh = MagicMock()

        user_update = UserUpdateMe(full_name="Updated Name")

        # Act: Update current user's information
        result = mock_user_service.update_user_me(
            current_user=test_user,
            user_update=user_update,
            password_reset_service=mock_password_reset_service,
            email_verification_service=mock_email_verification_service,
        )

        # Assert: Verify user was updated successfully
        assert isinstance(result, UserPublic)
        assert result.full_name == user_update.full_name
        mock_user_service.session.add.assert_called_once()
        mock_user_service.session.commit.assert_called_once()
        mock_user_service.session.refresh.assert_called_once()

    def test_update_user_me_email_change(
        self,
        mock_user_service: UserService,
        test_user: User,
        mock_password_reset_service: PasswordResetService,
        mock_email_verification_service: EmailVerificationService,
    ) -> None:
        """Test updating current user's email."""
        # Arrange: Mock database operations and new email
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = None
        mock_user_service.session.add = MagicMock()
        mock_user_service.session.commit = MagicMock()
        mock_user_service.session.refresh = MagicMock()
        mock_password_reset_service.invalidate_pending_for_user = MagicMock()
        mock_email_verification_service.invalidate_pending_for_user = MagicMock()

        user_update = UserUpdateMe(email="newemail@example.com")

        # Act: Update current user's email
        result = mock_user_service.update_user_me(
            current_user=test_user,
            user_update=user_update,
            password_reset_service=mock_password_reset_service,
            email_verification_service=mock_email_verification_service,
        )

        # Assert: Verify email was updated successfully
        assert isinstance(result, UserPublic)
        assert result.email == user_update.email
        mock_user_service.session.add.assert_called_once()
        mock_user_service.session.commit.assert_called_once()
        mock_user_service.session.refresh.assert_called_once()

    def test_update_user_me_email_exists(
        self,
        mock_user_service: UserService,
        test_user: User,
        another_test_user: User,
        mock_password_reset_service: PasswordResetService,
        mock_email_verification_service: EmailVerificationService,
    ) -> None:
        """Test updating email to one that already exists."""
        # Arrange: Mock database query to return existing user with email
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = (
            another_test_user
        )

        user_update = UserUpdateMe(email=another_test_user.email)

        # Act & Assert: Verify UserExistsError is raised
        with pytest.raises(UserExistsError):
            mock_user_service.update_user_me(
                current_user=test_user,
                user_update=user_update,
                password_reset_service=mock_password_reset_service,
                email_verification_service=mock_email_verification_service,
            )

    def test_update_user_me_email_change_retires_pending_email_flows(
        self,
        mock_user_service: UserService,
        test_user: User,
        mock_password_reset_service: PasswordResetService,
        mock_email_verification_service: EmailVerificationService,
    ) -> None:
        """Test a change of address retires the tokens issued for the old one."""
        # Arrange: Nothing else holds the new address
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = None
        mock_password_reset_service.invalidate_pending_for_user = MagicMock()
        mock_email_verification_service.invalidate_pending_for_user = MagicMock()

        user_update = UserUpdateMe(email="newemail@example.com")

        # Act
        mock_user_service.update_user_me(
            current_user=test_user,
            user_update=user_update,
            password_reset_service=mock_password_reset_service,
            email_verification_service=mock_email_verification_service,
        )

        # Assert: A reset or verification issued for the old address is no
        # longer redeemable
        mock_password_reset_service.invalidate_pending_for_user.assert_called_once_with(
            user_id=test_user.id
        )
        mock_email_verification_service.invalidate_pending_for_user.assert_called_once_with(
            user_id=test_user.id
        )

    def test_update_user_me_keeps_pending_email_flows_on_an_unchanged_address(
        self,
        mock_user_service: UserService,
        test_user: User,
        mock_password_reset_service: PasswordResetService,
        mock_email_verification_service: EmailVerificationService,
    ) -> None:
        """Test resubmitting the same address leaves its pending tokens alone."""
        # Arrange: The update carries the address the user already holds
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = test_user
        mock_password_reset_service.invalidate_pending_for_user = MagicMock()
        mock_email_verification_service.invalidate_pending_for_user = MagicMock()

        user_update = UserUpdateMe(email=test_user.email)

        # Act
        mock_user_service.update_user_me(
            current_user=test_user,
            user_update=user_update,
            password_reset_service=mock_password_reset_service,
            email_verification_service=mock_email_verification_service,
        )

        # Assert
        mock_password_reset_service.invalidate_pending_for_user.assert_not_called()
        mock_email_verification_service.invalidate_pending_for_user.assert_not_called()


class TestUpdateUser:
    """Tests for the update_user method."""

    def test_update_user_success(
        self,
        mock_user_service: UserService,
        test_user: User,
    ) -> None:
        """Test successfully updating a user."""
        # Arrange: Mock database operations and update data
        mock_user_service.session.get = MagicMock(return_value=test_user)
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = None
        mock_user_service.session.add = MagicMock()
        mock_user_service.session.commit = MagicMock()
        mock_user_service.session.refresh = MagicMock()

        user_update = UserUpdate(full_name="Updated Name")

        # Act: Update user's full name
        result = mock_user_service.update_user(
            user_id=test_user.id, user_update=user_update
        )

        # Assert: Verify user was updated successfully
        assert isinstance(result, UserPublic)
        assert result.full_name == user_update.full_name
        mock_user_service.session.add.assert_called_once()
        mock_user_service.session.commit.assert_called_once()
        mock_user_service.session.refresh.assert_called_once()

    def test_update_user_with_password(
        self, mock_user_service: UserService, test_user: User
    ) -> None:
        """Test updating user with new password."""
        # Arrange: Mock database operations and password update
        mock_user_service.session.get = MagicMock(return_value=test_user)
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = None
        mock_user_service.session.add = MagicMock()
        mock_user_service.session.commit = MagicMock()
        mock_user_service.session.refresh = MagicMock()

        user_update = UserUpdate(password="newpassword123")

        # Act: Update user with new hashed password
        with patch("app.services.user.get_password_hash") as mock_hash:
            hashed_password = "new_hashed_password"
            mock_hash.return_value = hashed_password
            result = mock_user_service.update_user(
                user_id=test_user.id, user_update=user_update
            )

        # Assert: Verify password was hashed and updated
        assert isinstance(result, UserPublic)
        mock_hash.assert_called_once_with("newpassword123")
        mock_user_service.session.add.assert_called_once()
        mock_user_service.session.commit.assert_called_once()
        mock_user_service.session.refresh.assert_called_once()

    def test_update_user_not_found(self, mock_user_service: UserService) -> None:
        """Test updating user when user not found."""
        # Arrange: Mock database to return None (user not found)
        mock_user_service.session.get = MagicMock(return_value=None)
        nonexistent_id = uuid.UUID("99999999-9999-9999-9999-999999999999")
        user_update = UserUpdate(full_name="Updated Name")

        # Act & Assert: Verify UserNotFoundError is raised
        with pytest.raises(UserNotFoundError):
            mock_user_service.update_user(
                user_id=nonexistent_id, user_update=user_update
            )

    def test_update_user_email_exists(
        self,
        mock_user_service: UserService,
        test_user: User,
        another_test_user: User,
    ) -> None:
        """Test updating user email to one that already exists."""
        # Arrange: Mock database to return existing user with email
        mock_user_service.session.get = MagicMock(return_value=test_user)
        mock_user_service.session.exec = MagicMock()
        mock_user_service.session.exec.return_value.first.return_value = (
            another_test_user
        )

        user_update = UserUpdate(email=another_test_user.email)

        # Act & Assert: Verify UserExistsError is raised
        with pytest.raises(UserExistsError):
            mock_user_service.update_user(
                user_id=test_user.id, user_update=user_update
            )


class TestUpdatePassword:
    """Tests for the update_password method."""

    def test_update_password_success(
        self, mock_user_service: UserService, test_user: User
    ) -> None:
        """Test successfully updating password."""
        # Arrange: Mock database operations and password data
        mock_user_service.session.add = MagicMock()
        mock_user_service.session.commit = MagicMock()

        password_update = PasswordUpdate(
            current_password="testpassword123", new_password="newpassword456"
        )

        # Act: Update password with verification and hashing
        with patch("app.services.user.verify_password", return_value=True):
            with patch("app.services.user.get_password_hash") as mock_hash:
                hashed_password = "new_hashed_password"
                mock_hash.return_value = hashed_password
                result = mock_user_service.update_password(
                    user=test_user, password_update=password_update
                )

        # Assert: Verify password was updated successfully
        assert isinstance(result, Message)
        assert result.message == "Password updated successfully."
        mock_user_service.session.add.assert_called_once()
        mock_user_service.session.commit.assert_called_once()

    def test_update_password_wrong_current(
        self, mock_user_service: UserService, test_user: User
    ) -> None:
        """Test updating password with wrong current password."""
        # Arrange: Set up password update with wrong current password
        password_update = PasswordUpdate(
            current_password="wrongpassword", new_password="newpassword456"
        )

        # Act & Assert: Verify PasswordIsWrongError is raised
        with patch("app.services.user.verify_password", return_value=False):
            with pytest.raises(PasswordIsWrongError):
                mock_user_service.update_password(
                    user=test_user, password_update=password_update
                )

    def test_update_password_same_as_current(
        self, mock_user_service: UserService, test_user: User
    ) -> None:
        """Test updating password to same as current."""
        # Arrange: Set up password update with same password
        password_update = PasswordUpdate(
            current_password="testpassword123", new_password="testpassword123"
        )

        # Act & Assert: Verify PasswordUnmodifiedError is raised
        with patch("app.services.user.verify_password", return_value=True):
            with pytest.raises(PasswordUnmodifiedError):
                mock_user_service.update_password(
                    user=test_user, password_update=password_update
                )


class TestDeleteUserMe:
    """Tests for the delete_user_me method."""

    def test_delete_user_me_success(
        self, mock_user_service: UserService, test_user: User
    ) -> None:
        """Test successfully deleting current user."""
        # Arrange: Mock database delete operations
        mock_user_service.session.delete = MagicMock()
        mock_user_service.session.commit = MagicMock()

        # Act: Delete current user
        result = mock_user_service.delete_user_me(user=test_user)

        # Assert: Verify user was deleted successfully
        assert isinstance(result, Message)
        assert result.message == "User deleted successfully."
        mock_user_service.session.delete.assert_called_once_with(test_user)
        mock_user_service.session.commit.assert_called_once()

    def test_delete_user_me_releases_the_household(
        self, mock_user_service: UserService, test_user: User
    ) -> None:
        """Their household would otherwise be left behind with its ledger."""
        # Arrange: Mock database delete operations and a household service
        mock_user_service.session.delete = MagicMock()
        mock_user_service.session.commit = MagicMock()
        household_service = MagicMock()

        # Act: Delete current user
        mock_user_service.delete_user_me(user=test_user, household_service=household_service)

        # Assert: Verify the household was released before the user went
        household_service.release_for_user.assert_called_once_with(user=test_user)
        mock_user_service.session.commit.assert_called_once()

    def test_delete_user_me_superuser_keeps_the_household(
        self, mock_user_service: UserService, test_superuser: User
    ) -> None:
        """The account survives the refusal, so its household must too."""
        # Arrange: Provide a household service that must not be used
        household_service = MagicMock()

        # Act & Assert: Verify the household is untouched when the delete is refused
        with pytest.raises(DeleteSuperUserError):
            mock_user_service.delete_user_me(user=test_superuser, household_service=household_service)

        household_service.release_for_user.assert_not_called()

    def test_delete_user_me_superuser(
        self, mock_user_service: UserService, test_superuser: User
    ) -> None:
        """Test superuser trying to delete their own account."""
        # Act & Assert: Verify DeleteSuperUserError is raised for superuser
        with pytest.raises(DeleteSuperUserError):
            mock_user_service.delete_user_me(user=test_superuser)


class TestDeleteUser:
    """Tests for the delete_user method."""

    def test_delete_user_success(
        self,
        mock_user_service: UserService,
        test_superuser: User,
        test_user: User,
    ) -> None:
        """Test successfully deleting a user."""
        # Arrange: Mock database operations for user deletion
        mock_user_service.session.get = MagicMock(return_value=test_user)
        mock_user_service.session.delete = MagicMock()
        mock_user_service.session.commit = MagicMock()

        # Act: Delete user as superuser
        result = mock_user_service.delete_user(
            user_id=test_user.id
        )

        # Assert: Verify user was deleted successfully
        assert isinstance(result, Message)
        assert result.message == "User deleted successfully"
        mock_user_service.session.delete.assert_called_once_with(test_user)
        mock_user_service.session.commit.assert_called_once()

    def test_delete_user_releases_the_household(
        self,
        mock_user_service: UserService,
        test_user: User,
    ) -> None:
        """A superuser deleting somebody must not strand their data either."""
        # Arrange: Mock database operations and a household service
        mock_user_service.session.get = MagicMock(return_value=test_user)
        mock_user_service.session.delete = MagicMock()
        mock_user_service.session.commit = MagicMock()
        household_service = MagicMock()

        # Act: Delete the user as a superuser
        mock_user_service.delete_user(user_id=test_user.id, household_service=household_service)

        # Assert: Verify the household went with them
        household_service.release_for_user.assert_called_once_with(user=test_user)
        mock_user_service.session.commit.assert_called_once()

    def test_delete_user_not_found(
        self, mock_user_service: UserService, test_superuser: User
    ) -> None:
        """Test deleting user when user not found."""
        # Arrange: Mock database to return None (user not found)
        mock_user_service.session.get = MagicMock(return_value=None)
        nonexistent_id = uuid.UUID("99999999-9999-9999-9999-999999999999")

        # Act & Assert: Verify UserNotFoundError is raised
        with pytest.raises(UserNotFoundError):
            mock_user_service.delete_user(
                user_id=nonexistent_id
            )

    def test_delete_superuser_self(
        self, mock_user_service: UserService, test_superuser: User
    ) -> None:
        """Test user trying to delete their own account."""
        # Arrange: Mock database to return superuser
        mock_user_service.session.get = MagicMock(return_value=test_superuser)

        # Act & Assert: Verify DeleteSuperUserError is raised when superuser tries to delete self
        with pytest.raises(DeleteSuperUserError):
            mock_user_service.delete_user(
                user_id=test_superuser.id
            )
