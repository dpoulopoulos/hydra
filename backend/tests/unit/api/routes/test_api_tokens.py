import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_api_token_service, get_current_user, get_db, get_session_user
from app.exceptions import ApiTokenLimitError, ApiTokenNotFoundError, ApiTokenNotPermittedError
from app.main import app
from app.models import (
    ApiTokenCreated,
    ApiTokenPublic,
    ApiTokenScope,
    ApiTokensPublic,
    ApiTokenStatus,
    Message,
    User,
)

TOKEN_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
SECRET = "hyd_0123456789abcdef_aSecretNobodyElseWillEverSee"


def make_public(name: str = "Claude") -> ApiTokenPublic:
    """Build an API token response payload."""
    return ApiTokenPublic(
        id=TOKEN_ID,
        name=name,
        scope=ApiTokenScope.READ,
        status=ApiTokenStatus.ACTIVE,
        expires_at=None,
        token_id="0123456789abcdef",
        last_used_at=None,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def wire(mock_db_session: MagicMock, test_user: User) -> Generator[MagicMock]:
    """Override the database, the signed-in user and the service.

    Yields:
        A mock API token service the test can program.
    """
    service = MagicMock()

    def override_get_db() -> Generator[MagicMock]:
        yield mock_db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_session_user] = lambda: test_user
    app.dependency_overrides[get_api_token_service] = lambda: service

    yield service

    app.dependency_overrides.clear()


class TestCreateApiToken:
    """Tests for POST /api-tokens/."""

    def test_mints_a_token(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        wire.create_token.return_value = ApiTokenCreated(token=make_public(), secret=SECRET)

        response = client.post("/api/v1/api-tokens/", headers=auth_headers, json={"name": "Claude"})

        assert response.status_code == 200
        assert response.json()["secret"] == SECRET

    def test_the_secret_is_in_this_response_and_no_other(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.create_token.return_value = ApiTokenCreated(token=make_public(), secret=SECRET)
        wire.list_tokens.return_value = ApiTokensPublic(data=[make_public()], count=1)

        created = client.post("/api/v1/api-tokens/", headers=auth_headers, json={"name": "Claude"})
        listed = client.get("/api/v1/api-tokens/", headers=auth_headers)

        assert SECRET in created.text
        assert SECRET not in listed.text

    def test_refuses_a_nameless_token(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        response = client.post("/api/v1/api-tokens/", headers=auth_headers, json={"name": ""})

        assert response.status_code == 422

    def test_refuses_a_lifetime_nobody_meant(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/api/v1/api-tokens/", headers=auth_headers, json={"name": "Claude", "expires_in_days": 100_000}
        )

        assert response.status_code == 422

    def test_reports_the_limit_as_a_conflict(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.create_token.side_effect = ApiTokenLimitError(10)

        response = client.post("/api/v1/api-tokens/", headers=auth_headers, json={"name": "Claude"})

        assert response.status_code == 409


class TestListApiTokens:
    """Tests for GET /api-tokens/."""

    def test_lists_the_tokens(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        wire.list_tokens.return_value = ApiTokensPublic(data=[make_public()], count=1)

        response = client.get("/api/v1/api-tokens/", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["count"] == 1

    def test_revoked_tokens_are_left_out_unless_asked_for(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.list_tokens.return_value = ApiTokensPublic(data=[], count=0)

        client.get("/api/v1/api-tokens/?include_revoked=true", headers=auth_headers)

        assert wire.list_tokens.call_args.kwargs["include_revoked"] is True


class TestRevokeApiToken:
    """Tests for DELETE /api-tokens/{token_id}."""

    def test_revokes_a_token(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        wire.revoke_token.return_value = Message(message="API token revoked.")

        response = client.delete(f"/api/v1/api-tokens/{TOKEN_ID}", headers=auth_headers)

        assert response.status_code == 200

    def test_a_token_that_is_not_yours_is_a_404(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.revoke_token.side_effect = ApiTokenNotFoundError

        response = client.delete(f"/api/v1/api-tokens/{uuid.uuid4()}", headers=auth_headers)

        assert response.status_code == 404


class TestApiTokensCannotManageApiTokens:
    """Tests that a machine credential cannot mint or revoke one."""

    @pytest.fixture
    def wire_with_api_token(self, mock_db_session: MagicMock, test_user: User) -> Generator[MagicMock]:
        """Override everything except the session requirement, which must bite.

        Yields:
            A mock API token service the test can program.
        """
        service = MagicMock()

        def override_get_db() -> Generator[MagicMock]:
            yield mock_db_session

        def refuse() -> User:
            raise ApiTokenNotPermittedError

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: test_user
        app.dependency_overrides[get_session_user] = refuse
        app.dependency_overrides[get_api_token_service] = lambda: service

        yield service

        app.dependency_overrides.clear()

    def test_minting_needs_a_session(
        self, client: TestClient, wire_with_api_token: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.post("/api/v1/api-tokens/", headers=auth_headers, json={"name": "Claude"})

        assert response.status_code == 403

    def test_revoking_needs_a_session(
        self, client: TestClient, wire_with_api_token: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.delete(f"/api/v1/api-tokens/{TOKEN_ID}", headers=auth_headers)

        assert response.status_code == 403

    def test_listing_does_not(
        self, client: TestClient, wire_with_api_token: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire_with_api_token.list_tokens.return_value = ApiTokensPublic(data=[], count=0)

        response = client.get("/api/v1/api-tokens/", headers=auth_headers)

        assert response.status_code == 200
