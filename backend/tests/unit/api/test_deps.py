import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.dependencies.utils import get_dependant
from pydantic import ValidationError

from app.api.deps import (
    get_api_token_service,
    get_current_active_superuser,
    get_current_user,
    get_household_context,
    get_household_owner,
    get_password_reset_service,
    get_session_user,
    get_source_address,
    get_user_service,
)
from app.core.config import settings
from app.exceptions import (
    ApiTokenNotPermittedError,
    ApiTokenReadOnlyError,
    HouseholdMembershipNotFoundError,
    HouseholdRoleRequiredError,
    InvalidApiTokenError,
    UserNotAuthorizedError,
)
from app.exceptions.password_exceptions import InvalidCredentialsError
from app.models import ApiToken, ApiTokenScope, HouseholdContext, HouseholdRole, User
from app.repositories import ApiTokenRepository, PasswordResetRepository, UserRepository
from app.services import ApiTokenService, PasswordResetService, UserService


def get_request(method: str = "GET") -> MagicMock:
    """Build a stand-in request whose method is all the dependency reads."""
    request = MagicMock()
    request.method = method
    request.state = SimpleNamespace()
    return request


class TestGetUserService:
    """Test cases for get_user_service dependency."""

    def test_get_user_service_returns_service(
        self, mock_db_session: MagicMock, mock_user_repository: UserRepository
    ) -> None:
        """Test that get_user_service returns a UserService instance."""
        # Act: Get user service with mock database session and repository
        result = get_user_service(mock_db_session, mock_user_repository)

        # Assert: Verify service is correct type and has correct session
        assert isinstance(result, UserService)
        assert result.session == mock_db_session
        assert result.user_repository == mock_user_repository


class TestGetPasswordResetService:
    """Test cases for get_password_reset_service dependency."""

    def test_get_password_reset_service_returns_service(
        self, mock_db_session: MagicMock, mock_password_reset_repository: PasswordResetRepository
    ) -> None:
        """Test that get_password_reset_service returns a PasswordResetService instance."""
        # Act: Get password reset service with mock database session and repository
        result = get_password_reset_service(mock_db_session, mock_password_reset_repository)

        # Assert: Verify service is correct type and has correct session
        assert isinstance(result, PasswordResetService)
        assert result.session == mock_db_session
        assert result.password_reset_repository == mock_password_reset_repository


class TestGetCurrentUser:
    """Test cases for get_current_user dependency."""

    def test_get_current_user_with_valid_token(
        self,
        mock_user_service: UserService,
        mock_api_token_service: ApiTokenService,
        user_token: str,
        test_user: User,
    ) -> None:
        """Test get_current_user with a valid token."""
        # Arrange: Mock user service to return test user
        mock_user_service.get_authenticated_user = MagicMock(return_value=test_user)

        # Act: Get current user with valid token
        result = get_current_user(get_request(), mock_user_service, mock_api_token_service, user_token)

        # Assert: Verify correct user is returned and service was called
        assert result == test_user
        mock_user_service.get_authenticated_user.assert_called_once()

    def test_get_current_user_with_malformed_token(
        self, mock_user_service: UserService, mock_api_token_service: ApiTokenService
    ) -> None:
        """Test get_current_user with a malformed token."""
        # Arrange: Set up malformed token
        malformed_token = "not-a-jwt-token"

        # Act & Assert: Verify InvalidCredentialsError is raised
        with pytest.raises(InvalidCredentialsError):
            get_current_user(get_request(), mock_user_service, mock_api_token_service, malformed_token)

    @patch("app.api.deps.TokenPayload")
    @patch("app.api.deps.decode_token")
    def test_get_current_user_with_validation_error(
        self,
        mock_jwt_decode: MagicMock,
        mock_token_payload: MagicMock,
        mock_user_service: UserService,
        mock_api_token_service: ApiTokenService,
    ) -> None:
        """Test get_current_user when token payload fails validation."""
        # Arrange: Mock decode_token to return a valid payload and TokenPayload to raise ValidationError
        mock_jwt_decode.decode_token = {"sub": "some-id"}
        mock_token_payload.side_effect = ValidationError.from_exception_data(
            title="TokenPayload",
            line_errors=[
                {
                    "type": "missing",
                    "loc": ("sub",),
                    "input": {},
                }
            ],
        )

        # Act & Assert: Verify InvalidCredentialsError is raised for validation failure
        with pytest.raises(InvalidCredentialsError):
            get_current_user(get_request(), mock_user_service, mock_api_token_service, "some.token.here")

    def test_get_current_user_with_expired_token(
        self,
        mock_user_service: UserService,
        mock_api_token_service: ApiTokenService,
        expired_user_token: str,
    ) -> None:
        """Test get_current_user with an expired JWT token."""
        # Act & Assert: Verify InvalidCredentialsError is raised for expired token
        with pytest.raises(InvalidCredentialsError):
            get_current_user(get_request(), mock_user_service, mock_api_token_service, expired_user_token)


class TestGetCurrentActiveSuperuser:
    """Test cases for get_current_active_superuser dependency."""

    def test_get_current_active_superuser_with_superuser(self, test_superuser: User) -> None:
        """Test get_current_active_superuser with a valid superuser."""
        # Act: Get current active superuser with valid superuser
        result = get_current_active_superuser(test_superuser)

        # Assert: Verify superuser is returned and has correct privileges
        assert result == test_superuser
        assert result.is_superuser is True

    def test_get_current_active_superuser_with_regular_user(self, test_user: User) -> None:
        """Test get_current_active_superuser with a regular user raises error."""
        # Act & Assert: Verify UserNotAuthorizedError is raised for regular user
        with pytest.raises(UserNotAuthorizedError):
            get_current_active_superuser(test_user)

    def test_the_superuser_guard_requires_a_session(self) -> None:
        """Test that an API token cannot reach the routes behind this guard.

        They create users, set any user's password and delete accounts, so a
        token here could mint a second superuser it knows the password of.
        Asserted on the dependency rather than on the body, because that is
        where the restriction lives and where it would be lost.
        """
        dependency = get_dependant(path="/", call=get_current_active_superuser)
        chain = [sub.call for sub in dependency.dependencies]

        assert get_session_user in chain


class TestGetHouseholdContext:
    """Tests for the get_household_context dependency."""

    def test_returns_the_context_from_the_service(self, test_user: User) -> None:
        """Test that the dependency delegates to the household service."""
        # Arrange: A service that returns a context
        context = HouseholdContext(
            user=test_user,
            household_id=uuid.uuid4(),
            membership_id=uuid.uuid4(),
            role=HouseholdRole.OWNER,
        )
        household_service = MagicMock()
        household_service.get_context.return_value = context

        # Act: Resolve the dependency
        result = get_household_context(current_user=test_user, household_service=household_service)

        # Assert: The context comes from the service, keyed on the current user
        assert result is context
        household_service.get_context.assert_called_once_with(user=test_user)

    def test_propagates_a_missing_membership(self, test_user: User) -> None:
        """Test that a user with no household is reported, not silently scoped."""
        # Arrange: A service that has no membership for the user
        household_service = MagicMock()
        household_service.get_context.side_effect = HouseholdMembershipNotFoundError

        # Act & Assert: The error reaches the caller
        with pytest.raises(HouseholdMembershipNotFoundError):
            get_household_context(current_user=test_user, household_service=household_service)


class TestGetHouseholdOwner:
    """Tests for the get_household_owner dependency."""

    def test_allows_an_owner(self, test_user: User) -> None:
        """Test that an owner passes the check unchanged."""
        # Arrange: An owner context
        context = HouseholdContext(
            user=test_user,
            household_id=uuid.uuid4(),
            membership_id=uuid.uuid4(),
            role=HouseholdRole.OWNER,
        )

        # Act: Resolve the dependency
        result = get_household_owner(household=context)

        # Assert: The same context is returned
        assert result is context

    def test_rejects_a_member(self, test_user: User) -> None:
        """Test that a plain member cannot pass the owner check."""
        # Arrange: A member context
        context = HouseholdContext(
            user=test_user,
            household_id=uuid.uuid4(),
            membership_id=uuid.uuid4(),
            role=HouseholdRole.MEMBER,
        )

        # Act & Assert: The check refuses the request
        with pytest.raises(HouseholdRoleRequiredError):
            get_household_owner(household=context)


class TestGetApiTokenService:
    """Test cases for the get_api_token_service dependency."""

    def test_returns_a_service(
        self,
        mock_db_session: MagicMock,
        mock_api_token_repository: ApiTokenRepository,
        mock_user_repository: UserRepository,
    ) -> None:
        """Test that get_api_token_service returns an ApiTokenService instance."""
        result = get_api_token_service(mock_db_session, mock_api_token_repository, mock_user_repository)

        assert isinstance(result, ApiTokenService)
        assert result.session == mock_db_session
        assert result.api_token_repository == mock_api_token_repository
        assert result.user_repository == mock_user_repository


class TestGetCurrentUserWithApiToken:
    """Test cases for resolving an API token through get_current_user."""

    def test_an_api_token_goes_to_the_api_token_service(
        self,
        mock_user_service: UserService,
        mock_api_token_service: ApiTokenService,
        api_token_credential: str,
        test_user: User,
    ) -> None:
        """Test that a credential carrying the prefix never reaches the JWT path."""
        mock_api_token_service.authenticate_request = MagicMock(return_value=test_user)
        mock_user_service.get_authenticated_user = MagicMock()

        result = get_current_user(get_request(), mock_user_service, mock_api_token_service, api_token_credential)

        assert result == test_user
        mock_user_service.get_authenticated_user.assert_not_called()

    def test_a_session_token_never_reaches_the_api_token_service(
        self,
        mock_user_service: UserService,
        mock_api_token_service: ApiTokenService,
        user_token: str,
        test_user: User,
    ) -> None:
        """Test that a JWT is resolved the way it always was."""
        mock_user_service.get_authenticated_user = MagicMock(return_value=test_user)
        mock_api_token_service.authenticate_request = MagicMock()

        result = get_current_user(get_request(), mock_user_service, mock_api_token_service, user_token)

        assert result == test_user
        mock_api_token_service.authenticate_request.assert_not_called()

    def test_the_request_method_is_passed_on(
        self,
        mock_user_service: UserService,
        mock_api_token_service: ApiTokenService,
        api_token_credential: str,
        test_user: User,
    ) -> None:
        """Test that the scope check is given the method it needs."""
        mock_api_token_service.authenticate_request = MagicMock(return_value=test_user)

        get_current_user(get_request("POST"), mock_user_service, mock_api_token_service, api_token_credential)

        mock_api_token_service.authenticate_request.assert_called_once_with(
            credential=api_token_credential, method="POST"
        )

    def test_a_read_token_cannot_reach_a_write_route(
        self,
        mock_user_service: UserService,
        mock_api_token_service: ApiTokenService,
        api_token_credential: str,
        test_api_token: ApiToken,
        test_user: User,
    ) -> None:
        """Test that the scope is enforced where the credential is resolved."""
        mock_api_token_service.api_token_repository = MagicMock()
        mock_api_token_service.api_token_repository.get_by_token_id.return_value = test_api_token
        mock_api_token_service.user_repository = MagicMock()
        mock_api_token_service.user_repository.get_by_id.return_value = test_user

        with pytest.raises(ApiTokenReadOnlyError):
            get_current_user(get_request("POST"), mock_user_service, mock_api_token_service, api_token_credential)

    def test_a_read_write_token_can(
        self,
        mock_user_service: UserService,
        mock_api_token_service: ApiTokenService,
        api_token_credential: str,
        test_api_token: ApiToken,
        test_user: User,
    ) -> None:
        """Test that a read write token is not stopped by the scope check."""
        test_api_token.scope = ApiTokenScope.READ_WRITE
        mock_api_token_service.api_token_repository = MagicMock()
        mock_api_token_service.api_token_repository.get_by_token_id.return_value = test_api_token
        mock_api_token_service.user_repository = MagicMock()
        mock_api_token_service.user_repository.get_by_id.return_value = test_user

        result = get_current_user(get_request("POST"), mock_user_service, mock_api_token_service, api_token_credential)

        assert result == test_user

    def test_an_unknown_api_token_is_refused(
        self,
        mock_user_service: UserService,
        mock_api_token_service: ApiTokenService,
        api_token_credential: str,
    ) -> None:
        """Test that a credential no token matches does not authenticate."""
        mock_api_token_service.api_token_repository = MagicMock()
        mock_api_token_service.api_token_repository.get_by_token_id.return_value = None

        with pytest.raises(InvalidApiTokenError):
            get_current_user(get_request(), mock_user_service, mock_api_token_service, api_token_credential)


class TestGetSessionUser:
    """Test cases for the get_session_user dependency."""

    def test_a_session_passes_through(self, test_user: User) -> None:
        """Test that a JWT authenticated request is allowed."""
        request = get_request()
        request.state.api_token_authenticated = False

        assert get_session_user(request, test_user) == test_user

    def test_an_api_token_is_refused(self, test_user: User) -> None:
        """Test that an API token cannot reach an operation reserved for a session."""
        request = get_request()
        request.state.api_token_authenticated = True

        with pytest.raises(ApiTokenNotPermittedError):
            get_session_user(request, test_user)

    def test_an_unmarked_request_is_treated_as_a_session(self, test_user: User) -> None:
        """Test the default, which is what a test overriding get_current_user gets."""
        request = MagicMock()
        request.state = SimpleNamespace()

        assert get_session_user(request, test_user) == test_user


class TestGetSourceAddress:
    """Tests for the address a request is counted against."""

    def build_request(self, *, peer: str | None, forwarded_for: str | None = None) -> MagicMock:
        """Build a stand-in request with a peer and, if given, a forwarding header.

        Args:
            peer: The address of the connection's other end, or None when the
                server does not know it.
            forwarded_for: What X-Forwarded-For carries, if anything.

        Returns:
            A request the dependency can read.
        """
        request = MagicMock()
        request.client = SimpleNamespace(host=peer) if peer is not None else None
        request.headers = {"x-forwarded-for": forwarded_for} if forwarded_for is not None else {}
        return request

    def test_the_peer_is_the_source_by_default(self) -> None:
        """Nothing is in front of the app, so the connection is what there is to go on."""
        # Arrange: A request straight from a client
        request = self.build_request(peer="203.0.113.7")

        # Act: Work out where it came from
        source = get_source_address(request)

        # Assert: Verify the peer is used
        assert source == "203.0.113.7"

    def test_a_forwarding_header_is_ignored_unless_a_proxy_is_counted(self) -> None:
        """A client can send the header itself, which would be a budget per request."""
        # Arrange: A request that claims to have been forwarded
        request = self.build_request(peer="203.0.113.7", forwarded_for="198.51.100.1")

        # Act: Work out where it came from, with no proxy configured
        with patch.object(settings, "TRUSTED_PROXY_HOPS", 0):
            source = get_source_address(request)

        # Assert: Verify the header was not believed
        assert source == "203.0.113.7"

    def test_one_hop_reads_the_entry_that_proxy_wrote(self) -> None:
        """Behind a proxy the peer is the proxy, which would be one budget for everybody."""
        # Arrange: A request the proxy appended the client it saw to
        request = self.build_request(peer="10.0.0.1", forwarded_for="192.0.2.9, 198.51.100.1")

        # Act: Work out where it came from, with one proxy in front
        with patch.object(settings, "TRUSTED_PROXY_HOPS", 1):
            source = get_source_address(request)

        # Assert: Verify the entry the proxy wrote is used, not the one the client made up
        assert source == "198.51.100.1"

    def test_two_hops_look_past_the_second_proxy(self) -> None:
        """A platform edge in front of the app's own proxy writes an entry of its own."""
        # Arrange: A client, as the edge recorded it, with the edge appended by the proxy
        request = self.build_request(peer="10.0.0.1", forwarded_for="198.51.100.1, 100.64.0.5")

        # Act: Work out where it came from, with two proxies in front
        with patch.object(settings, "TRUSTED_PROXY_HOPS", 2):
            source = get_source_address(request)

        # Assert: Verify the client is used rather than either proxy
        assert source == "198.51.100.1"

    def test_a_header_shorter_than_the_hops_falls_back_to_its_oldest_entry(self) -> None:
        """The proxies the setting describes did not write this, so it is not read as if they had."""
        # Arrange: A single entry where two hops were configured
        request = self.build_request(peer="10.0.0.1", forwarded_for="198.51.100.1")

        # Act: Work out where it came from
        with patch.object(settings, "TRUSTED_PROXY_HOPS", 2):
            source = get_source_address(request)

        # Assert: Verify the oldest entry is used rather than nothing at all
        assert source == "198.51.100.1"

    def test_a_request_with_no_peer_has_no_source(self) -> None:
        """An address that cannot be worked out is absent rather than made up."""
        # Arrange: A request with no client, as a test transport can leave one
        request = self.build_request(peer=None)

        # Act: Work out where it came from
        source = get_source_address(request)

        # Assert: Verify nothing is invented
        assert source is None
