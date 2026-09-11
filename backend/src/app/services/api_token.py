import datetime
import uuid
from typing import NamedTuple

from sqlmodel import Session

from app.core.security import (
    generate_api_token,
    hash_api_token_secret,
    split_api_token,
    verify_api_token_secret,
)
from app.exceptions import (
    ApiTokenLimitError,
    ApiTokenNotFoundError,
    ApiTokenReadOnlyError,
    InvalidApiTokenError,
)
from app.models import (
    MAX_ACTIVE_TOKENS_PER_USER,
    ApiToken,
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenPublic,
    ApiTokenScope,
    ApiTokensPublic,
    ApiTokenStatus,
    Message,
    User,
)
from app.repositories.api_token import ApiTokenRepository
from app.repositories.user import UserRepository

# How stale last_used_at is allowed to get. Writing it on every call would turn
# each read a machine client makes into a write, and the value is only ever
# read by a person deciding whether a token is still in use.
LAST_USED_WRITE_INTERVAL = datetime.timedelta(minutes=5)

# The request methods a read scoped token may make. Everything else changes
# something, whatever the route happens to be called.
#
# This is the method, not the effect. A handful of reads do write: asking for
# the transactions or a report materialises any recurring occurrence that has
# fallen due, which is a row added to the ledger. A read token can therefore
# still cause that, and it is the one exception to "reads nothing changes".
# The rows would have appeared on the owner's next visit anyway, so what a
# token holder gains is the timing and nothing else.
SAFE_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class ResolvedApiToken(NamedTuple):
    """A token that checked out, together with the user it acts as."""

    token: ApiToken
    user: User


class ApiTokenService:
    """Provide services for API token management."""

    def __init__(
        self,
        session: Session,
        api_token_repository: ApiTokenRepository,
        user_repository: UserRepository,
    ) -> None:
        """Initialize the API token service.

        Args:
            session: The database session.
            api_token_repository: The API token repository instance.
            user_repository: The user repository instance.
        """
        self.session = session
        self.api_token_repository = api_token_repository
        self.user_repository = user_repository

    def create_token(self, *, user: User, token_create: ApiTokenCreate) -> ApiTokenCreated:
        """Mint an API token for a user.

        Args:
            user: The user the token will act as.
            token_create: The name, scope and lifetime asked for.

        Returns:
            The new token, together with the secret. This is the only time the
            secret is ever returned.

        Raises:
            ApiTokenLimitError: If the user already holds as many active tokens
                as they may.
        """
        now = datetime.datetime.now(datetime.UTC)
        if self.api_token_repository.count_active_for_user(user.id, now=now) >= MAX_ACTIVE_TOKENS_PER_USER:
            raise ApiTokenLimitError(MAX_ACTIVE_TOKENS_PER_USER) from None

        credential, token_id, secret_hash = generate_api_token()

        expires_at = None
        if token_create.expires_in_days is not None:
            expires_at = now + datetime.timedelta(days=token_create.expires_in_days)

        api_token = ApiToken(
            name=token_create.name,
            scope=token_create.scope,
            status=ApiTokenStatus.ACTIVE,
            expires_at=expires_at,
            token_id=token_id,
            secret_hash=secret_hash,
            user_id=user.id,
        )
        self.api_token_repository.save(api_token)
        self.session.commit()
        self.session.refresh(api_token)

        return ApiTokenCreated(token=ApiTokenPublic.model_validate(api_token), secret=credential)

    def list_tokens(self, *, user: User, include_revoked: bool = False) -> ApiTokensPublic:
        """List the API tokens of a user.

        Args:
            user: The user whose tokens to list.
            include_revoked: Whether revoked tokens are listed as well.

        Returns:
            The tokens, without any secret.
        """
        tokens = self.api_token_repository.list_for_user(user.id, include_revoked=include_revoked)
        data = [ApiTokenPublic.model_validate(token) for token in tokens]
        return ApiTokensPublic(data=data, count=len(data))

    def revoke_token(self, *, user: User, token_id: uuid.UUID) -> Message:
        """Revoke one of a user's API tokens.

        Args:
            user: The user who owns the token.
            token_id: The ID of the token to revoke.

        Returns:
            A message confirming the revocation.

        Raises:
            ApiTokenNotFoundError: If the user has no such token. A token
                belonging to somebody else is reported the same way, so the API
                does not say which IDs exist.
        """
        api_token = self.api_token_repository.get_for_user(token_id, user.id)
        if api_token is None:
            raise ApiTokenNotFoundError from None

        self.api_token_repository.revoke(api_token)
        self.session.commit()

        return Message(message="API token revoked.")

    def authenticate(self, *, credential: str) -> User:
        """Resolve the user behind an API token.

        Every way of failing raises the same exception with the same message.
        An unknown token, a wrong secret, a revoked one, an expired one and an
        inactive owner are indistinguishable from outside, so the endpoint
        cannot be used to learn which tokens exist or what state one is in.

        Args:
            credential: The string presented as a bearer token.

        Returns:
            The user the token acts as.

        Raises:
            InvalidApiTokenError: If the token does not check out, for any reason.
        """
        return self._resolve(credential).user

    def authenticate_request(self, *, credential: str, method: str) -> User:
        """Resolve the user behind an API token, for a request of a given method.

        The scope is checked here rather than route by route, so a route added
        later is covered without being told that scopes exist.

        Args:
            credential: The string presented as a bearer token.
            method: The HTTP method of the request being authorized.

        Returns:
            The user the token acts as.

        Raises:
            InvalidApiTokenError: If the token does not check out.
            ApiTokenReadOnlyError: If a read scoped token is making a request
                that would change something.
        """
        resolved = self._resolve(credential)

        if resolved.token.scope is ApiTokenScope.READ and method.upper() not in SAFE_HTTP_METHODS:
            raise ApiTokenReadOnlyError from None

        return resolved.user

    def _resolve(self, credential: str) -> ResolvedApiToken:
        """Check a credential and return the token and its user.

        Args:
            credential: The string presented as a bearer token.

        Returns:
            The token row and the user it acts as.

        Raises:
            InvalidApiTokenError: If the token does not check out, for any reason.
        """
        parts = split_api_token(credential)
        if parts is None:
            raise InvalidApiTokenError from None

        token_id, secret = parts

        api_token = self.api_token_repository.get_by_token_id(token_id)
        if api_token is None:
            # Hash anyway, so an unknown lookup id costs what a wrong secret
            # costs and the response time says nothing.
            hash_api_token_secret(secret)
            raise InvalidApiTokenError from None

        if not verify_api_token_secret(secret, api_token.secret_hash):
            raise InvalidApiTokenError from None

        if api_token.status is not ApiTokenStatus.ACTIVE:
            raise InvalidApiTokenError from None

        now = datetime.datetime.now(datetime.UTC)
        if api_token.expires_at is not None and api_token.expires_at <= now:
            raise InvalidApiTokenError from None

        user = self.user_repository.get_by_id(api_token.user_id)
        if user is None or not user.is_active:
            raise InvalidApiTokenError from None

        self._touch(api_token, now)

        return ResolvedApiToken(token=api_token, user=user)

    def _touch(self, api_token: ApiToken, now: datetime.datetime) -> None:
        """Record that a token was used, but not on every single request.

        Args:
            api_token: The token that was used.
            now: The moment to record.
        """
        last_used_at = api_token.last_used_at
        if last_used_at is not None and now - last_used_at < LAST_USED_WRITE_INTERVAL:
            return

        self.api_token_repository.touch_last_used(api_token, now)
        self.session.commit()
