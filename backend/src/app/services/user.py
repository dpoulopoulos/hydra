import uuid
from typing import TYPE_CHECKING, Any

from sqlmodel import Session

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash, verify_password
from app.exceptions import (
    DeleteSuperUserError,
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
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
)
from app.repositories.user import UserRepository
from app.utils import generate_new_account_email, send_email

if TYPE_CHECKING:
    from app.services.email_verification import EmailVerificationService
    from app.services.household import CategorySeeder, HouseholdService


class UserService:
    """Provide services for user management."""

    def __init__(self, session: Session, user_repository: UserRepository) -> None:
        """Initialize the user service.

        Args:
            session: The database session.
            user_repository: The user repository instance.
        """
        self.session = session
        self.user_repository = user_repository

    def authenticate(
        self, email: str, password: str, email_verification_service: "EmailVerificationService | None" = None
    ) -> Token:
        """Authenticate a user.

        Args:
            email: The user's email address.
            password: The user's password.
            email_verification_service: Optional email verification service to check verification status.

        Returns:
            A token for the authenticated user.

        Raises:
            UserNotFoundError: If a user with the given email does not exist.
            PasswordIsWrongError: If the given password does not match the stored password.
            UserNotActiveError: If the user is inactive.
        """
        user = self.get_user_by_email(email=email)

        if not user:
            raise UserNotFoundError

        if not verify_password(password, user.hashed_password):
            raise PasswordIsWrongError from None

        if not user.is_active:
            # Check if user has a pending email verification
            is_verified = True
            if email_verification_service:
                pending_verification = email_verification_service.get_pending_verification_by_user_id(user.id)
                is_verified = pending_verification is None

            raise UserNotActiveError(user=user, is_verified=is_verified) from None

        return Token(access_token=create_access_token(user.id))

    def create_user(
        self,
        user_create: UserCreate | UserRegister,
        household_service: "HouseholdService | None" = None,
        category_service: "CategorySeeder | None" = None,
    ) -> UserPublic:
        """Create a new user.

        Args:
            user_create: The user creation data.
            household_service: Optional household service. When given, a
                household is provisioned for the user in the same transaction,
                so a user is never observable without one.
            category_service: Optional category service, used to seed the
                default categories of the new household.

        Note:
            When the registration carries an invite token, the user joins the
            household that invited them instead of getting one of their own.

        Returns:
            The created user.

        Raises:
            UserExistsError: If a user with the same email already exists.
        """
        existing_user = self.get_user_by_email(email=user_create.email)
        if existing_user:
            raise UserExistsError(user=existing_user) from None

        extra_data: dict[str, Any] = {"hashed_password": get_password_hash(user_create.password)}

        # Set is_active=False for public signup (UserRegister), True for admin-created users (UserCreate)
        if isinstance(user_create, UserRegister):
            extra_data["is_active"] = False

        user = User.model_validate(user_create, update=extra_data)

        user = self.user_repository.save(user)

        if household_service:
            # Only a public registration can carry an invitation. A superuser
            # creating an account has no link to follow.
            invite_token = user_create.invite_token if isinstance(user_create, UserRegister) else None
            household_service.create_for_user(user=user, category_service=category_service, invite_token=invite_token)

        self.session.commit()

        # Only send welcome email for admin-created users who are immediately active
        # Public signup users will receive email verification instead
        if isinstance(user_create, UserCreate) and settings.emails_enabled:
            email_data = generate_new_account_email(username=user.email)
            send_email(
                email_to=user.email,
                subject=email_data.subject,
                html_content=email_data.html_content,
            )

        return UserPublic.model_validate(user)

    def get_authenticated_user(self, token_data: TokenPayload) -> User:
        """Get the authenticated user from a token.

        Args:
            token_data: The token payload.

        Returns:
            The authenticated user.

        Raises:
            UserNotFoundError: If the user is not found.
            UserNotAuthorizedError: If the user is not active.
        """
        user_id = uuid.UUID(token_data.sub) if token_data.sub else None
        if not user_id:
            raise UserNotFoundError from None
        user = self.user_repository.get_by_id(user_id)
        if not user:
            raise UserNotFoundError from None
        if not user.is_active:
            raise UserNotActiveError(user) from None

        return user

    def get_user_by_email(self, email: str) -> User | None:
        """Get a user by their email address.

        Args:
            email: The user's email address.

        Returns:
            The user if found, otherwise None.
        """
        return self.user_repository.get_by_email(email)

    def get_user_by_id(self, current_user: User, user_id: uuid.UUID) -> UserPublic:
        """Get a user by ID.

        Args:
            current_user: The current authenticated user.
            user_id: The ID of the user to get.

        Returns:
            The retrieved user.

        Raises:
            UserNotFoundError: If the user is not found.
            UserNotAuthorizedError: If the user is not a superuser and is trying to access another user's data.
        """
        user = self.user_repository.get_by_id(user_id)

        if not user:
            raise UserNotFoundError from None
        if user == current_user:
            return UserPublic.model_validate(user)
        if not current_user.is_superuser:
            raise UserNotAuthorizedError(current_user) from None

        return UserPublic.model_validate(user)

    def get_users(self, skip: int = 0, limit: int = 100) -> UsersPublic:
        """Get a sequence of registered users.

        Args:
            skip: The number of users to skip.
            limit: The maximum number of users to return.

        Returns:
            A tuple containing a sequence of users and the total number of users.
        """
        users, count = self.user_repository.get_all_paginated(skip=skip, limit=limit)
        return UsersPublic(data=[UserPublic.model_validate(user) for user in users], count=count)

    def update_user_me(self, current_user: User, user_update: UserUpdateMe) -> UserPublic:
        """Update the current user's information.

        Args:
            current_user: The current authenticated user.
            user_update: The user data to update.

        Returns:
            The updated user.

        Raises:
            UserExistsError: If a user with the same email already exists.
        """
        user_data = user_update.model_dump(exclude_unset=True)

        if user_update.email:
            existing_user = self.get_user_by_email(email=user_update.email)
            if existing_user and existing_user.id != current_user.id:
                raise UserExistsError(user=existing_user) from None

        current_user.sqlmodel_update(user_data)
        current_user = self.user_repository.save(current_user)
        self.session.commit()

        return UserPublic.model_validate(current_user)

    def update_user(self, user_id: uuid.UUID, user_update: UserUpdate) -> UserPublic:
        """Update a user's information.

        Args:
            user_id: The ID of the user to update.
            user_update: The user data to update.

        Returns:
            The updated user.

        Raises:
            UserNotFoundError: If the user is not found.
            UserExistsError: If a user with the same email already exists.
        """
        db_user = self.user_repository.get_by_id(user_id)

        if not db_user:
            raise UserNotFoundError from None
        if user_update.email:
            existing_user = self.get_user_by_email(email=user_update.email)
            if existing_user and existing_user.id != user_id:
                raise UserExistsError(user=existing_user) from None

        user_data = user_update.model_dump(exclude_unset=True)

        extra_data = {}
        if "password" in user_data:
            password = user_data["password"]
            hashed_password = get_password_hash(password)
            extra_data["hashed_password"] = hashed_password

        db_user.sqlmodel_update(user_data, update=extra_data)
        db_user = self.user_repository.save(db_user)
        self.session.commit()

        return UserPublic.model_validate(db_user)

    def update_password(self, user: User, password_update: PasswordUpdate) -> Message:
        """Update a user's password.

        Args:
            user: The user to update the password for.
            password_update: The password update data.

        Returns:
            A message indicating that the password was updated successfully.

        Raises:
            PasswordIsWrongError: If the current password is not correct.
            PasswordUnmodifiedError: If the new password is the same as the current password.
        """
        if not verify_password(password_update.current_password, user.hashed_password):
            raise PasswordIsWrongError from None
        if password_update.current_password == password_update.new_password:
            raise PasswordUnmodifiedError from None

        hashed_password = get_password_hash(password_update.new_password)
        user.hashed_password = hashed_password

        self.user_repository.save(user)
        self.session.commit()

        return Message(message="Password updated successfully.")

    def delete_user_me(self, user: User) -> Message:
        """Delete the current user.

        Args:
            user: The current authenticated user.

        Returns:
            A message indicating that the user was deleted successfully.

        Raises:
            DeleteSuperUserError: If a superuser tries to delete their own account.
        """
        if user.is_superuser:
            raise DeleteSuperUserError from None

        self.user_repository.delete(user)
        self.user_repository.flush()
        self.session.commit()

        return Message(message="User deleted successfully.")

    def delete_user(self, user_id: uuid.UUID) -> Message:
        """Delete a user.

        Args:
            user_id: The ID of the user to delete.

        Returns:
            A message indicating that the user was deleted successfully.

        Raises:
            UserNotFoundError: If the user is not found.
            DeleteSuperUserError: If trying to delete any superuser account.
        """
        user = self.user_repository.get_by_id(user_id)

        if not user:
            raise UserNotFoundError from None
        if user.is_superuser:
            raise DeleteSuperUserError from None

        self.user_repository.delete(user)
        self.user_repository.flush()
        self.session.commit()

        return Message(message="User deleted successfully")
