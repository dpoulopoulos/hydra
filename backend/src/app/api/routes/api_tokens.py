import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import ApiTokenServiceDep, CurrentUser, SessionUser
from app.exceptions import (
    ApiTokenLimitError,
    ApiTokenNotFoundError,
    ApiTokenNotPermittedError,
    ApiTokenReadOnlyError,
    InvalidApiTokenError,
    ServiceError,
)
from app.models import ApiTokenCreate, ApiTokenCreated, ApiTokensPublic, Message

router = APIRouter(prefix="/api-tokens", tags=["api-tokens"])


def api_token_exception_mappings() -> dict[type[ServiceError], int]:
    """Map service exceptions to appropriate HTTP status codes.

    Returns:
        A dictionary mapping exception types to HTTP status codes.
    """
    return {
        ApiTokenNotFoundError: status.HTTP_404_NOT_FOUND,
        InvalidApiTokenError: status.HTTP_401_UNAUTHORIZED,
        ApiTokenReadOnlyError: status.HTTP_403_FORBIDDEN,
        ApiTokenNotPermittedError: status.HTTP_403_FORBIDDEN,
        ApiTokenLimitError: status.HTTP_409_CONFLICT,
    }


@router.post("/", response_model=ApiTokenCreated)
def create_api_token(
    *, api_token_service: ApiTokenServiceDep, current_user: SessionUser, token_in: ApiTokenCreate
) -> ApiTokenCreated:
    """Mint an API token, for a machine client such as an MCP server.

    The secret is in this response and in no other. It is not stored, so it
    cannot be shown again.

    Requires a signed-in session: a token may not mint another token, or a
    leaked one could replace itself for as long as it liked.

    Args:
        api_token_service: The API token service dependency.
        current_user: The signed-in user.
        token_in: The name, scope and lifetime asked for.

    Returns:
        The new token, together with its secret.

    Raises:
        HTTPException: If the user already holds as many active tokens as they
            may (409), or the request was authenticated with an API token (403).
    """
    return api_token_service.create_token(user=current_user, token_create=token_in)


@router.get("/", response_model=ApiTokensPublic)
def list_api_tokens(
    *,
    api_token_service: ApiTokenServiceDep,
    current_user: CurrentUser,
    include_revoked: bool = Query(default=False),
) -> ApiTokensPublic:
    """List your API tokens.

    Secrets are never included: only a hash of each is kept.

    Args:
        api_token_service: The API token service dependency.
        current_user: The current user.
        include_revoked: Whether revoked tokens are listed as well.

    Returns:
        The tokens.
    """
    return api_token_service.list_tokens(user=current_user, include_revoked=include_revoked)


@router.delete("/{token_id}", response_model=Message)
def revoke_api_token(
    *, api_token_service: ApiTokenServiceDep, current_user: SessionUser, token_id: uuid.UUID
) -> Message:
    """Revoke an API token.

    The row is kept and marked revoked, so when the token was last used is not
    lost with it.

    Args:
        api_token_service: The API token service dependency.
        current_user: The signed-in user.
        token_id: The ID of the token to revoke.

    Returns:
        A message confirming the revocation.

    Raises:
        HTTPException: If you have no such token (404), or the request was
            authenticated with an API token (403).
    """
    return api_token_service.revoke_token(user=current_user, token_id=token_id)
