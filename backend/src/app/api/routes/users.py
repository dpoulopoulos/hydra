import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, EmailVerificationServiceDep, UserServiceDep, get_current_active_superuser
from app.exceptions import (
    DeleteSuperUserError,
    PasswordUnmodifiedError,
    ServiceError,
    UserExistsError,
    UserNotAuthorizedError,
    UserNotFoundError,
)
from app.exceptions.password_exceptions import InvalidCredentialsError, PasswordIsWrongError
from app.models import (
    Message,
    PasswordUpdate,
    UserCreate,
    UserPublic,
    UserRegister,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
)

router = APIRouter(prefix="/users", tags=["users"])


def user_exception_mappings() -> dict[type[ServiceError], int]:
    """Map service exceptions to appropriate HTTP status codes.

    Returns:
        A dictionary mapping exception types to HTTP status codes.
    """
    return {
        UserExistsError: status.HTTP_409_CONFLICT,
        UserNotAuthorizedError: status.HTTP_403_FORBIDDEN,
        InvalidCredentialsError: status.HTTP_401_UNAUTHORIZED,
        PasswordIsWrongError: status.HTTP_401_UNAUTHORIZED,
        UserNotFoundError: status.HTTP_404_NOT_FOUND,
        PasswordUnmodifiedError: status.HTTP_400_BAD_REQUEST,
        DeleteSuperUserError: status.HTTP_400_BAD_REQUEST,
    }


@router.post("/", dependencies=[Depends(get_current_active_superuser)], response_model=UserPublic)
def create_user(*, user_service: UserServiceDep, user_in: UserCreate) -> UserPublic:
    """Create a new user.

    Args:
        user_service: The user service dependency.
        user_in: The user creation payload.

    Returns:
        The newly created user.

    Raises:
        HTTPException: If a user with this email already exists (409),
            the user is not authorized to perform this action (403),
            the user's token is invalid (401), or the authenticated
            user is not found in the database (404).
    """
    return user_service.create_user(user_create=user_in)


@router.post("/signup", response_model=UserPublic)
def register_user(
    *,
    user_service: UserServiceDep,
    email_verification_service: EmailVerificationServiceDep,
    user_in: UserRegister,
) -> UserPublic:
    """Register a new user.

    This endpoint allows users to register without being authenticated.
    The user will be created with is_active=False and must verify their email
    before they can log in.

    Args:
        user_service: The user service dependency.
        email_verification_service: The email verification service dependency.
        user_in: The user registration data.

    Returns:
        The newly created user.

    Raises:
        HTTPException: If a user with the same email already exists (409).
    """
    user = user_service.create_user(user_create=user_in)
    email_verification_service.send_verification_email(user_service=user_service, user_email=user.email)
    return user


@router.get("/me", response_model=UserPublic)
def get_user_me(current_user: CurrentUser) -> UserPublic:
    """Get the current user's information.

    Args:
        current_user: The current authenticated user.

    Returns:
        The current user's public information.

    Raises:
        HTTPException: If the user's token is invalid (401), the user is not found (404), or the user is inactive (403).
    """
    return UserPublic.model_validate(current_user)


@router.get("/{user_id}", response_model=UserPublic)
def get_user_by_id(*, user_service: UserServiceDep, current_user: CurrentUser, user_id: uuid.UUID) -> UserPublic:
    """Get a specific user by their ID.

    A user can retrieve their own information. Superusers can retrieve any
    user's information.

    Args:
        user_service: The user service dependency.
        current_user: The current authenticated user.
        user_id: The ID of the user to retrieve.

    Returns:
        The user's public information.

    Raises:
        HTTPException: If the user does not have sufficient privileges (403), the user is not found (404),
            or the token is invalid (401).
    """
    return user_service.get_user_by_id(current_user=current_user, user_id=user_id)


@router.get(
    "/",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UsersPublic,
)
def get_users(*, user_service: UserServiceDep, skip: int = 0, limit: int = 100) -> UsersPublic:
    """Get registered users.

    Args:
        user_service: The user service dependency.
        skip (int): The number of users to skip.
        limit (int): The maximum number of users to return.

    Returns:
        A list of users.

    Raises:
        HTTPException: If the user is not authorized (403), has an invalid token (401), or is not found (404).
    """
    return user_service.get_users(skip=skip, limit=limit)


@router.patch("/me", response_model=UserPublic)
def update_user_me(*, user_service: UserServiceDep, user_in: UserUpdateMe, current_user: CurrentUser) -> UserPublic:
    """Update the current user's information.

    Args:
        user_service: The user service dependency.
        user_in: The user data to update.
        current_user: The current authenticated user.

    Returns:
        The updated user information.

    Raises:
        HTTPException: If a user with the same email already exists (409), the user's token is invalid (401),
            the user is not found (404), or the user is inactive (403).
    """
    return user_service.update_user_me(current_user=current_user, user_update=user_in)


@router.patch(
    "/{user_id}",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UserPublic,
)
def update_user(
    *,
    user_service: UserServiceDep,
    user_id: uuid.UUID,
    user_in: UserUpdate,
) -> UserPublic:
    """Update a user's information.

    This endpoint is only accessible to superusers.

    Args:
        user_service: The user service dependency.
        user_id: The ID of the user to update.
        user_in: The user data to update.

    Returns:
        The updated user information.

    Raises:
        HTTPException: If the user is not found (404), the new email already exists (409),
            the current user is not authorized (403), or the token is invalid (401).
    """
    return user_service.update_user(user_id=user_id, user_update=user_in)


@router.patch("/me/password", response_model=Message)
def update_password_me(
    *,
    user_service: UserServiceDep,
    password_in: PasswordUpdate,
    current_user: CurrentUser,
) -> Message:
    """Update the current user's password.

    Args:
        user_service: The user service dependency.
        password_in: The current and new password.
        current_user: The current authenticated user.

    Returns:
        A message indicating that the password was updated successfully.

    Raises:
        HTTPException: If the current password is incorrect (401),
            the new password is the same as the current one (400),
            the user is not found (404), or the user is inactive (403).
    """
    return user_service.update_password(user=current_user, password_update=password_in)


@router.delete("/me", response_model=Message)
def delete_user_me(*, user_service: UserServiceDep, current_user: CurrentUser) -> Message:
    """Delete the current user.

    Args:
        user_service: The user service dependency.
        current_user: The current authenticated user.

    Returns:
        A message indicating that the user was deleted successfully.

    Raises:
        HTTPException: If a superuser tries to delete their own account (400), the token is invalid (401),
            the user is not found (404), or the user is inactive (403).
    """
    return user_service.delete_user_me(user=current_user)


@router.delete("/{user_id}", dependencies=[Depends(get_current_active_superuser)])
def delete_user(*, user_service: UserServiceDep, user_id: uuid.UUID) -> Message:
    """Delete a user.

    This endpoint is only accessible to superusers.

    Args:
        user_service: The user service dependency.
        user_id: The ID of the user to delete.

    Returns:
        A message indicating that the user was deleted successfully.

    Raises:
        HTTPException: If the user to delete is not found (404), trying to delete any superuser account (400),
            the current user is not authorized (403), or the token is invalid (401).
    """
    return user_service.delete_user(user_id=user_id)
