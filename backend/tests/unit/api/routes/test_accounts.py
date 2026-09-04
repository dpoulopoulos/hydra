import uuid
from collections.abc import Generator
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_account_service, get_current_user, get_db, get_household_context
from app.exceptions import AccountExistsError, AccountInUseError, AccountNotFoundError
from app.main import app
from app.models import (
    AccountPublic,
    AccountsPublic,
    AccountType,
    HouseholdContext,
    Message,
    User,
)
from app.models.fields import MAX_AMOUNT_MINOR

ACCOUNT_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")


def make_public(
    name: str = "Current",
    account_type: AccountType = AccountType.CURRENT,
    balance_minor: int = 100_000,
) -> AccountPublic:
    """Build an account response payload."""
    return AccountPublic(
        id=ACCOUNT_ID,
        household_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        name=name,
        type=account_type,
        currency_code="EUR",
        opening_balance_minor=balance_minor,
        opening_balance_date=date(2026, 1, 1),
        current_balance_minor=balance_minor,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def wire(
    mock_db_session: MagicMock, test_user: User, household_context: HouseholdContext
) -> Generator[MagicMock]:
    """Override the database, the current user, the household scope and the service.

    Yields:
        A mock account service the test can program.
    """
    service = MagicMock()

    def override_get_db() -> Generator[MagicMock]:
        yield mock_db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_household_context] = lambda: household_context
    app.dependency_overrides[get_account_service] = lambda: service

    yield service

    app.dependency_overrides.clear()


class TestCreateAccount:
    """Tests for POST /accounts/."""

    def test_creates_an_account(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.create_account.return_value = make_public()

        response = client.post(
            "/api/v1/accounts/",
            headers=auth_headers,
            json={
                "name": "Current",
                "type": "current",
                "opening_balance_minor": 100000,
                "opening_balance_date": "2026-01-01",
            },
        )

        assert response.status_code == 200
        assert response.json()["current_balance_minor"] == 100000

    def test_requires_an_opening_balance_date(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/api/v1/accounts/", headers=auth_headers, json={"name": "Cash", "type": "cash"}
        )

        assert response.status_code == 422

    def test_rejects_an_unknown_type(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        """"checking" is the US term and is deliberately not accepted."""
        response = client.post(
            "/api/v1/accounts/",
            headers=auth_headers,
            json={"name": "Cash", "type": "checking", "opening_balance_date": "2026-01-01"},
        )

        assert response.status_code == 422

    @pytest.mark.parametrize(
        "opening_balance_minor", [MAX_AMOUNT_MINOR + 1, -MAX_AMOUNT_MINOR - 1]
    )
    def test_rejects_an_opening_balance_beyond_the_cap(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        opening_balance_minor: int,
    ) -> None:
        """A credit card starts overdrawn, so the balance is bounded both ways."""
        response = client.post(
            "/api/v1/accounts/",
            headers=auth_headers,
            json={
                "name": "Current",
                "type": "current",
                "opening_balance_minor": opening_balance_minor,
                "opening_balance_date": "2026-01-01",
            },
        )

        assert response.status_code == 422

    def test_reports_a_duplicate_name_as_a_conflict(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.create_account.side_effect = AccountExistsError(name="Current")

        response = client.post(
            "/api/v1/accounts/",
            headers=auth_headers,
            json={"name": "Current", "type": "current", "opening_balance_date": "2026-01-01"},
        )

        assert response.status_code == 409


class TestListAccounts:
    """Tests for GET /accounts/."""

    def test_returns_the_accounts_and_the_total(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.list_accounts.return_value = AccountsPublic(
            data=[make_public()], count=1, total_balance_minor=100_000
        )

        response = client.get("/api/v1/accounts/", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["total_balance_minor"] == 100000

    def test_passes_the_filters_through(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.list_accounts.return_value = AccountsPublic(data=[], count=0)

        response = client.get(
            "/api/v1/accounts/",
            headers=auth_headers,
            params={"include_archived": "true", "type": "savings", "skip": 5, "limit": 10},
        )

        assert response.status_code == 200
        kwargs = wire.list_accounts.call_args.kwargs
        assert kwargs["include_archived"] is True
        assert kwargs["account_type"] is AccountType.SAVINGS
        assert kwargs["skip"] == 5
        assert kwargs["limit"] == 10

    def test_caps_the_page_size(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/api/v1/accounts/", headers=auth_headers, params={"limit": 5000})

        assert response.status_code == 422


class TestGetAccount:
    """Tests for GET /accounts/{account_id}."""

    def test_returns_the_account(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.get_account.return_value = make_public()

        response = client.get(f"/api/v1/accounts/{ACCOUNT_ID}", headers=auth_headers)

        assert response.status_code == 200

    def test_an_account_from_another_household_is_not_found(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        """A foreign ID reads as 404, never 403, so the API does not leak which IDs exist."""
        wire.get_account.side_effect = AccountNotFoundError

        response = client.get(f"/api/v1/accounts/{uuid.uuid4()}", headers=auth_headers)

        assert response.status_code == 404


class TestUpdateAccount:
    """Tests for PATCH /accounts/{account_id}."""

    def test_renames_the_account(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.update_account.return_value = make_public(name="Main")

        response = client.patch(
            f"/api/v1/accounts/{ACCOUNT_ID}", headers=auth_headers, json={"name": "Main"}
        )

        assert response.status_code == 200
        assert wire.update_account.call_args.kwargs["account_update"].name == "Main"

    def test_ignores_an_attempt_to_change_the_opening_balance(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        """The field is not on the update schema, so it cannot rewrite history."""
        wire.update_account.return_value = make_public()

        response = client.patch(
            f"/api/v1/accounts/{ACCOUNT_ID}",
            headers=auth_headers,
            json={"opening_balance_minor": 999999},
        )

        assert response.status_code == 200
        assert wire.update_account.call_args.kwargs["account_update"].model_dump(exclude_unset=True) == {}


class TestDeleteAccount:
    """Tests for DELETE /accounts/{account_id}."""

    def test_deletes_the_account(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.delete_account.return_value = Message(message="Account deleted.")

        response = client.delete(f"/api/v1/accounts/{ACCOUNT_ID}", headers=auth_headers)

        assert response.status_code == 200

    def test_reports_an_account_with_history_as_a_conflict(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.delete_account.side_effect = AccountInUseError(name="Current")

        response = client.delete(f"/api/v1/accounts/{ACCOUNT_ID}", headers=auth_headers)

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "still has transactions" in detail
        assert "Archive it instead" in detail
        # The message must not claim the account "already exists", which is what the
        # generic conflict wording would have said.
        assert "already exists" not in detail
