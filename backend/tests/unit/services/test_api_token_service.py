import datetime
import uuid
from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from app.core.security import API_TOKEN_PREFIX, hash_api_token_secret
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
    ApiTokenScope,
    ApiTokenStatus,
    User,
)
from app.services.api_token import LAST_USED_WRITE_INTERVAL, ApiTokenService


@pytest.fixture
def service(mock_api_token_service: ApiTokenService) -> ApiTokenService:
    """Give the service mock repositories a test can program."""
    mock_api_token_service.api_token_repository = MagicMock()
    mock_api_token_service.user_repository = MagicMock()
    return mock_api_token_service


def keeping(saved: list[ApiToken]) -> Callable[[ApiToken], ApiToken]:
    """Stand in for the repository's save, keeping what it was handed.

    The row is what the assertions are about: a token is only ever returned
    with its secret once, so what was written is the only place left to look
    for what was written.

    Args:
        saved: The list to record each saved row in.

    Returns:
        A side effect that records the row and hands it back.
    """

    def save(token: ApiToken) -> ApiToken:
        saved.append(token)
        return token

    return save


class TestCreateToken:
    """Tests for minting a token."""

    def test_returns_a_credential_that_resolves_to_the_stored_token(
        self, service: ApiTokenService, test_user: User
    ) -> None:
        service.api_token_repository.count_active_for_user.return_value = 0
        saved: list[ApiToken] = []
        service.api_token_repository.save.side_effect = keeping(saved)

        created = service.create_token(user=test_user, token_create=ApiTokenCreate(name="Claude"))

        token_id, _, secret = created.secret.removeprefix(API_TOKEN_PREFIX).partition("_")
        assert saved[0].token_id == token_id
        assert saved[0].secret_hash == hash_api_token_secret(secret)

    def test_the_secret_itself_is_never_stored(self, service: ApiTokenService, test_user: User) -> None:
        service.api_token_repository.count_active_for_user.return_value = 0
        saved: list[ApiToken] = []
        service.api_token_repository.save.side_effect = keeping(saved)

        created = service.create_token(user=test_user, token_create=ApiTokenCreate(name="Claude"))

        _, _, secret = created.secret.removeprefix(API_TOKEN_PREFIX).partition("_")
        assert secret not in saved[0].model_dump_json()

    def test_an_expiry_becomes_a_moment_in_the_future(self, service: ApiTokenService, test_user: User) -> None:
        service.api_token_repository.count_active_for_user.return_value = 0
        service.api_token_repository.save.side_effect = lambda token: token

        created = service.create_token(user=test_user, token_create=ApiTokenCreate(name="Claude", expires_in_days=30))

        assert created.token.expires_at is not None
        assert created.token.expires_at > datetime.datetime.now(datetime.UTC)

    def test_no_expiry_asked_for_means_no_expiry(self, service: ApiTokenService, test_user: User) -> None:
        service.api_token_repository.count_active_for_user.return_value = 0
        service.api_token_repository.save.side_effect = lambda token: token

        created = service.create_token(user=test_user, token_create=ApiTokenCreate(name="Claude", expires_in_days=None))

        assert created.token.expires_at is None

    def test_refuses_once_the_user_holds_as_many_as_they_may(self, service: ApiTokenService, test_user: User) -> None:
        service.api_token_repository.count_active_for_user.return_value = MAX_ACTIVE_TOKENS_PER_USER

        with pytest.raises(ApiTokenLimitError):
            service.create_token(user=test_user, token_create=ApiTokenCreate(name="Claude"))

    def test_the_limit_is_measured_against_now(self, service: ApiTokenService, test_user: User) -> None:
        # The count has to leave out the rows that have expired, or ten
        # short-lived tokens lock a user out of minting an eleventh forever.
        service.api_token_repository.count_active_for_user.return_value = 0

        before = datetime.datetime.now(datetime.UTC)
        service.create_token(user=test_user, token_create=ApiTokenCreate(name="Claude"))
        after = datetime.datetime.now(datetime.UTC)

        _, kwargs = service.api_token_repository.count_active_for_user.call_args
        assert before <= kwargs["now"] <= after


class TestRevokeToken:
    """Tests for revoking a token."""

    def test_revokes_a_token_of_the_user(
        self, service: ApiTokenService, test_user: User, test_api_token: ApiToken
    ) -> None:
        service.api_token_repository.get_for_user.return_value = test_api_token

        service.revoke_token(user=test_user, token_id=test_api_token.id)

        service.api_token_repository.revoke.assert_called_once_with(test_api_token)

    def test_somebody_elses_token_is_reported_as_missing(self, service: ApiTokenService, test_user: User) -> None:
        # The repository scopes the lookup to the user, so a token belonging to
        # somebody else comes back as nothing. A 404 rather than a 403 is what
        # stops the endpoint saying which token IDs exist.
        service.api_token_repository.get_for_user.return_value = None

        with pytest.raises(ApiTokenNotFoundError):
            service.revoke_token(user=test_user, token_id=uuid.uuid4())


class TestAuthenticate:
    """Tests for resolving the user behind a credential."""

    def test_resolves_the_user(
        self,
        service: ApiTokenService,
        test_user: User,
        test_api_token: ApiToken,
        api_token_credential: str,
    ) -> None:
        service.api_token_repository.get_by_token_id.return_value = test_api_token
        service.user_repository.get_by_id.return_value = test_user

        assert service.authenticate(credential=api_token_credential) is test_user

    @pytest.mark.parametrize(
        "credential",
        ["", "not-a-token", "eyJhbGciOiJIUzI1NiJ9.e30.sig", "hyd_nosecret"],
    )
    def test_refuses_a_credential_of_the_wrong_shape(self, service: ApiTokenService, credential: str) -> None:
        with pytest.raises(InvalidApiTokenError):
            service.authenticate(credential=credential)

    def test_refuses_an_unknown_lookup_id(self, service: ApiTokenService, api_token_credential: str) -> None:
        service.api_token_repository.get_by_token_id.return_value = None

        with pytest.raises(InvalidApiTokenError):
            service.authenticate(credential=api_token_credential)

    def test_refuses_a_wrong_secret(self, service: ApiTokenService, test_user: User, test_api_token: ApiToken) -> None:
        service.api_token_repository.get_by_token_id.return_value = test_api_token
        service.user_repository.get_by_id.return_value = test_user

        with pytest.raises(InvalidApiTokenError):
            service.authenticate(credential=f"{API_TOKEN_PREFIX}{test_api_token.token_id}_wrong")

    def test_refuses_a_revoked_token(
        self,
        service: ApiTokenService,
        test_user: User,
        test_api_token: ApiToken,
        api_token_credential: str,
    ) -> None:
        test_api_token.status = ApiTokenStatus.REVOKED
        service.api_token_repository.get_by_token_id.return_value = test_api_token
        service.user_repository.get_by_id.return_value = test_user

        with pytest.raises(InvalidApiTokenError):
            service.authenticate(credential=api_token_credential)

    def test_refuses_an_expired_token(
        self,
        service: ApiTokenService,
        test_user: User,
        test_api_token: ApiToken,
        api_token_credential: str,
    ) -> None:
        test_api_token.expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)
        service.api_token_repository.get_by_token_id.return_value = test_api_token
        service.user_repository.get_by_id.return_value = test_user

        with pytest.raises(InvalidApiTokenError):
            service.authenticate(credential=api_token_credential)

    def test_refuses_a_token_whose_user_is_gone(
        self, service: ApiTokenService, test_api_token: ApiToken, api_token_credential: str
    ) -> None:
        service.api_token_repository.get_by_token_id.return_value = test_api_token
        service.user_repository.get_by_id.return_value = None

        with pytest.raises(InvalidApiTokenError):
            service.authenticate(credential=api_token_credential)

    def test_refuses_a_token_whose_user_is_inactive(
        self,
        service: ApiTokenService,
        test_inactive_user: User,
        test_api_token: ApiToken,
        api_token_credential: str,
    ) -> None:
        service.api_token_repository.get_by_token_id.return_value = test_api_token
        service.user_repository.get_by_id.return_value = test_inactive_user

        with pytest.raises(InvalidApiTokenError):
            service.authenticate(credential=api_token_credential)

    def test_every_refusal_says_the_same_thing(
        self, service: ApiTokenService, test_api_token: ApiToken, api_token_credential: str
    ) -> None:
        # Unknown, wrong, revoked, expired and inactive must be told apart by
        # nobody outside, or the endpoint becomes a way to ask which tokens
        # exist and what state they are in.
        messages = set()

        service.api_token_repository.get_by_token_id.return_value = None
        for credential in ("nonsense", api_token_credential):
            with pytest.raises(InvalidApiTokenError) as caught:
                service.authenticate(credential=credential)
            messages.add(caught.value.message)

        service.api_token_repository.get_by_token_id.return_value = test_api_token
        service.user_repository.get_by_id.return_value = None
        with pytest.raises(InvalidApiTokenError) as caught:
            service.authenticate(credential=api_token_credential)
        messages.add(caught.value.message)

        assert len(messages) == 1


class TestLastUsed:
    """Tests for recording that a token was used."""

    def test_records_the_first_use(
        self,
        service: ApiTokenService,
        test_user: User,
        test_api_token: ApiToken,
        api_token_credential: str,
    ) -> None:
        service.api_token_repository.get_by_token_id.return_value = test_api_token
        service.user_repository.get_by_id.return_value = test_user

        service.authenticate(credential=api_token_credential)

        service.api_token_repository.touch_last_used.assert_called_once()

    def test_does_not_write_again_straight_away(
        self,
        service: ApiTokenService,
        test_user: User,
        test_api_token: ApiToken,
        api_token_credential: str,
    ) -> None:
        # Otherwise every read a machine client makes becomes a write.
        test_api_token.last_used_at = datetime.datetime.now(datetime.UTC)
        service.api_token_repository.get_by_token_id.return_value = test_api_token
        service.user_repository.get_by_id.return_value = test_user

        service.authenticate(credential=api_token_credential)

        service.api_token_repository.touch_last_used.assert_not_called()

    def test_writes_again_once_the_value_is_stale(
        self,
        service: ApiTokenService,
        test_user: User,
        test_api_token: ApiToken,
        api_token_credential: str,
    ) -> None:
        test_api_token.last_used_at = (
            datetime.datetime.now(datetime.UTC) - LAST_USED_WRITE_INTERVAL - datetime.timedelta(seconds=1)
        )
        service.api_token_repository.get_by_token_id.return_value = test_api_token
        service.user_repository.get_by_id.return_value = test_user

        service.authenticate(credential=api_token_credential)

        service.api_token_repository.touch_last_used.assert_called_once()


class TestScope:
    """Tests for what a token's scope lets it do."""

    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "get"])
    def test_a_read_token_may_make_a_safe_request(
        self,
        service: ApiTokenService,
        test_user: User,
        test_api_token: ApiToken,
        api_token_credential: str,
        method: str,
    ) -> None:
        service.api_token_repository.get_by_token_id.return_value = test_api_token
        service.user_repository.get_by_id.return_value = test_user

        assert service.authenticate_request(credential=api_token_credential, method=method) is test_user

    @pytest.mark.parametrize("method", ["POST", "PATCH", "PUT", "DELETE"])
    def test_a_read_token_may_not_change_anything(
        self,
        service: ApiTokenService,
        test_user: User,
        test_api_token: ApiToken,
        api_token_credential: str,
        method: str,
    ) -> None:
        service.api_token_repository.get_by_token_id.return_value = test_api_token
        service.user_repository.get_by_id.return_value = test_user

        with pytest.raises(ApiTokenReadOnlyError):
            service.authenticate_request(credential=api_token_credential, method=method)

    @pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
    def test_a_read_write_token_may_do_either(
        self,
        service: ApiTokenService,
        test_user: User,
        test_api_token: ApiToken,
        api_token_credential: str,
        method: str,
    ) -> None:
        test_api_token.scope = ApiTokenScope.READ_WRITE
        service.api_token_repository.get_by_token_id.return_value = test_api_token
        service.user_repository.get_by_id.return_value = test_user

        assert service.authenticate_request(credential=api_token_credential, method=method) is test_user


class TestListTokens:
    """Tests for listing a user's tokens."""

    def test_never_returns_a_secret(self, service: ApiTokenService, test_user: User, test_api_token: ApiToken) -> None:
        service.api_token_repository.list_for_user.return_value = [test_api_token]

        listed = service.list_tokens(user=test_user)

        assert listed.count == 1
        assert test_api_token.secret_hash not in listed.model_dump_json()
