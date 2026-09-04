from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import EmailVerificationServiceDep, UserServiceDep
from app.exceptions import (
    ServiceError,
    UserNotActiveError,
)
from app.exceptions.password_exceptions import InvalidEmailOrPasswordError
from app.models import Token

router = APIRouter(tags=["login"])


def login_exception_mappings() -> dict[type[ServiceError], int]:
    """Map service exceptions to appropriate HTTP status codes.

    Returns:
        A dictionary mapping exception types to HTTP status codes.
    """
    return {
        InvalidEmailOrPasswordError: status.HTTP_401_UNAUTHORIZED,
        UserNotActiveError: status.HTTP_403_FORBIDDEN,
    }


@router.post("/login/access-token")
def login_access_token(
    user_service: UserServiceDep,
    email_verification_service: EmailVerificationServiceDep,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    """Get an access token for future requests.

    The obtained token could be used as a Bearer token in subsequent authenticated requests.

    Args:
        user_service: The user service dependency.
        email_verification_service: The email verification service dependency.
        form_data: The OAuth2 password request form data.

    Returns:
        A token containing the access token.

    Raises:
        HTTPException: If the credentials do not check out (401), or the user is inactive (403). The 401
            is deliberately the same whether or not the address is registered, so that the endpoint cannot
            be used to enumerate accounts. For 403, the error message will indicate if email verification
            is pending.
    """
    return user_service.authenticate(
        email=form_data.username, password=form_data.password, email_verification_service=email_verification_service
    )
