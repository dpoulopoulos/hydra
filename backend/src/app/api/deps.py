from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.core.security import TokenType, decode_token
from app.exceptions import UserNotAuthorizedError
from app.exceptions.password_exceptions import InvalidCredentialsError
from app.models import TokenPayload, User
from app.repositories import (
    EmailVerificationRepository,
    PasswordResetRepository,
    UserRepository,
)
from app.services import EmailVerificationService, PasswordResetService, UserService

reusable_oauth2 = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/login/access-token")


def get_db() -> Generator[Session]:
    """Get a database session.

    Yields:
        A database session.
    """
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]


def get_user_repository(session: SessionDep) -> UserRepository:
    """Get a user repository instance.

    Args:
        session: The database session.

    Returns:
        A user repository instance.
    """
    return UserRepository(session=session)


UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]


def get_password_reset_repository(session: SessionDep) -> PasswordResetRepository:
    """Get a password reset repository instance.

    Args:
        session: The database session.

    Returns:
        A password reset repository instance.
    """
    return PasswordResetRepository(session=session)


PasswordResetRepositoryDep = Annotated[PasswordResetRepository, Depends(get_password_reset_repository)]


def get_email_verification_repository(session: SessionDep) -> EmailVerificationRepository:
    """Get an email verification repository instance.

    Args:
        session: The database session.

    Returns:
        An email verification repository instance.
    """
    return EmailVerificationRepository(session=session)


EmailVerificationRepositoryDep = Annotated[EmailVerificationRepository, Depends(get_email_verification_repository)]


def get_user_service(session: SessionDep, user_repository: UserRepositoryDep) -> UserService:
    """Get a user service instance.

    Args:
        session: The database session.
        user_repository: The user repository instance.

    Returns:
        A user service instance.
    """
    return UserService(session=session, user_repository=user_repository)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]


def get_password_reset_service(
    session: SessionDep, password_reset_repository: PasswordResetRepositoryDep
) -> PasswordResetService:
    """Get a password reset service instance.

    Args:
        session: The database session.
        password_reset_repository: The password reset repository instance.

    Returns:
        A password reset service instance.
    """
    return PasswordResetService(session=session, password_reset_repository=password_reset_repository)


PasswordResetServiceDep = Annotated[PasswordResetService, Depends(get_password_reset_service)]


def get_email_verification_service(
    session: SessionDep, email_verification_repository: EmailVerificationRepositoryDep
) -> EmailVerificationService:
    """Get an email verification service instance.

    Args:
        session: The database session.
        email_verification_repository: The email verification repository instance.

    Returns:
        An email verification service instance.
    """
    return EmailVerificationService(session=session, email_verification_repository=email_verification_repository)


EmailVerificationServiceDep = Annotated[EmailVerificationService, Depends(get_email_verification_service)]


TokenDep = Annotated[str, Depends(reusable_oauth2)]


def get_current_user(user_service: UserServiceDep, token: TokenDep) -> User:
    """Get the current authenticated user.

    Args:
        user_service: The user service instance.
        token: The OAuth2 bearer token.

    Returns:
        The authenticated user.

    Raises:
        InvalidCredentialsError: If the token is invalid or expired.
        UserNotFoundError: If the user associated with the token is not found.
        UserNotAuthorizedError: If the user is inactive.
    """
    try:
        payload = decode_token(token, expected_type=TokenType.SESSION)
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError) as exc:
        raise InvalidCredentialsError from exc

    return user_service.get_authenticated_user(token_data=token_data)


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_active_superuser(current_user: CurrentUser) -> User:
    """Get the current active superuser.

    Args:
        current_user: The current user.

    Returns:
        The current active superuser.

    Raises:
        UserNotAuthorizedError: If the user is not a superuser.
    """
    if not current_user.is_superuser:
        raise UserNotAuthorizedError(current_user)

    return current_user
