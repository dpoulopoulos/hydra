import uuid
from collections.abc import Generator
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db, get_household_context, get_transaction_service
from app.exceptions import (
    AccountArchivedError,
    CategoryNotFoundError,
    SameAccountTransferError,
    TransactionNotFoundError,
    TransferShapeError,
)
from app.main import app
from app.models import (
    HouseholdContext,
    Message,
    TransactionKind,
    TransactionPublic,
    TransactionsPublic,
    TransactionSort,
    User,
)
from app.models.fields import MAX_AMOUNT_MINOR

TRANSACTION_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
ACCOUNT_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")


def make_public(
    kind: TransactionKind = TransactionKind.EXPENSE,
    amount_minor: int = 4250,
    counter_account_id: uuid.UUID | None = None,
) -> TransactionPublic:
    """Build a transaction response payload."""
    return TransactionPublic(
        id=TRANSACTION_ID,
        household_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        kind=kind,
        amount_minor=amount_minor,
        occurred_on=date(2026, 3, 4),
        account_id=ACCOUNT_ID,
        counter_account_id=counter_account_id,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def wire(
    mock_db_session: MagicMock, test_user: User, household_context: HouseholdContext
) -> Generator[MagicMock]:
    """Override the database, the current user, the household scope and the service.

    Yields:
        A mock transaction service the test can program.
    """
    service = MagicMock()

    def override_get_db() -> Generator[MagicMock]:
        yield mock_db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_household_context] = lambda: household_context
    app.dependency_overrides[get_transaction_service] = lambda: service

    yield service

    app.dependency_overrides.clear()


class TestCreateTransaction:
    """Tests for POST /transactions/."""

    def test_records_an_expense(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.create_transaction.return_value = make_public()

        response = client.post(
            "/api/v1/transactions/",
            headers=auth_headers,
            json={
                "kind": "expense",
                "amount_minor": 4250,
                "occurred_on": "2026-03-04",
                "account_id": str(ACCOUNT_ID),
            },
        )

        assert response.status_code == 200
        assert response.json()["amount_minor"] == 4250

    def test_records_a_transfer(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        """A transfer is an ordinary transaction, so it needs no separate endpoint."""
        destination = uuid.uuid4()
        wire.create_transaction.return_value = make_public(
            kind=TransactionKind.TRANSFER, amount_minor=20_000, counter_account_id=destination
        )

        response = client.post(
            "/api/v1/transactions/",
            headers=auth_headers,
            json={
                "kind": "transfer",
                "amount_minor": 20000,
                "occurred_on": "2026-03-05",
                "account_id": str(ACCOUNT_ID),
                "counter_account_id": str(destination),
            },
        )

        assert response.status_code == 200
        assert response.json()["counter_account_id"] == str(destination)

    def test_rejects_a_zero_amount(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/api/v1/transactions/",
            headers=auth_headers,
            json={
                "kind": "expense",
                "amount_minor": 0,
                "occurred_on": "2026-03-04",
                "account_id": str(ACCOUNT_ID),
            },
        )

        assert response.status_code == 422

    def test_rejects_a_negative_amount(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        """The sign lives in the kind, so a negative magnitude is meaningless."""
        response = client.post(
            "/api/v1/transactions/",
            headers=auth_headers,
            json={
                "kind": "expense",
                "amount_minor": -4250,
                "occurred_on": "2026-03-04",
                "account_id": str(ACCOUNT_ID),
            },
        )

        assert response.status_code == 422

    def test_rejects_an_amount_beyond_the_cap(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        """Beyond the cap the value is one the column cannot hold: a 422, not a 500."""
        response = client.post(
            "/api/v1/transactions/",
            headers=auth_headers,
            json={
                "kind": "expense",
                "amount_minor": MAX_AMOUNT_MINOR + 1,
                "occurred_on": "2026-03-04",
                "account_id": str(ACCOUNT_ID),
            },
        )

        assert response.status_code == 422

    def test_reports_a_bad_transfer_shape_as_a_bad_request(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.create_transaction.side_effect = TransferShapeError("A transfer needs a destination account.")

        response = client.post(
            "/api/v1/transactions/",
            headers=auth_headers,
            json={
                "kind": "transfer",
                "amount_minor": 100,
                "occurred_on": "2026-03-04",
                "account_id": str(ACCOUNT_ID),
            },
        )

        assert response.status_code == 400

    def test_reports_a_self_transfer_as_a_bad_request(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.create_transaction.side_effect = SameAccountTransferError

        response = client.post(
            "/api/v1/transactions/",
            headers=auth_headers,
            json={
                "kind": "transfer",
                "amount_minor": 100,
                "occurred_on": "2026-03-04",
                "account_id": str(ACCOUNT_ID),
                "counter_account_id": str(ACCOUNT_ID),
            },
        )

        assert response.status_code == 400

    def test_reports_an_archived_account_as_a_bad_request(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.create_transaction.side_effect = AccountArchivedError(name="Old card")

        response = client.post(
            "/api/v1/transactions/",
            headers=auth_headers,
            json={
                "kind": "expense",
                "amount_minor": 100,
                "occurred_on": "2026-03-04",
                "account_id": str(ACCOUNT_ID),
            },
        )

        assert response.status_code == 400


class TestListTransactions:
    """Tests for GET /transactions/."""

    def test_returns_the_transactions(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.list_transactions.return_value = TransactionsPublic(data=[make_public()], count=1)

        response = client.get("/api/v1/transactions/", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["count"] == 1

    def test_does_not_record_recurring_transactions(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        """Writing here would leave the reports on the same screen out of date."""
        wire.list_transactions.return_value = TransactionsPublic(data=[], count=0)

        response = client.get("/api/v1/transactions/", headers=auth_headers)

        assert response.status_code == 200
        assert "recurring_rule_service" not in wire.list_transactions.call_args.kwargs

    def test_passes_the_filters_through(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.list_transactions.return_value = TransactionsPublic(data=[], count=0)
        category_id = uuid.uuid4()

        response = client.get(
            "/api/v1/transactions/",
            headers=auth_headers,
            params={
                "date_from": "2026-03-01",
                "date_to": "2026-03-31",
                "account_id": str(ACCOUNT_ID),
                "category_id": str(category_id),
                "include_subcategories": "false",
                "kind": "expense",
                "min_amount_minor": 100,
                "max_amount_minor": 50000,
                "q": "market",
                "skip": 10,
                "limit": 25,
                "sort": "amount",
            },
        )

        assert response.status_code == 200
        filters = wire.list_transactions.call_args.kwargs["filters"]
        assert filters.date_from == date(2026, 3, 1)
        assert filters.date_to == date(2026, 3, 31)
        assert filters.account_id == ACCOUNT_ID
        assert filters.category_id == category_id
        assert filters.include_subcategories is False
        assert filters.kind is TransactionKind.EXPENSE
        assert filters.min_amount_minor == 100
        assert filters.max_amount_minor == 50000
        assert filters.q == "market"
        assert filters.skip == 10
        assert filters.limit == 25
        assert filters.sort is TransactionSort.AMOUNT_ASC

    def test_rejects_a_mistyped_filter(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        """A silently dropped filter would return more data than the caller asked for."""
        response = client.get(
            "/api/v1/transactions/", headers=auth_headers, params={"catgory_id": str(uuid.uuid4())}
        )

        assert response.status_code == 422
        wire.list_transactions.assert_not_called()

    def test_caps_the_page_size(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/api/v1/transactions/", headers=auth_headers, params={"limit": 5000})

        assert response.status_code == 422

    def test_caps_an_amount_filter(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.get(
            "/api/v1/transactions/",
            headers=auth_headers,
            params={"min_amount_minor": MAX_AMOUNT_MINOR + 1},
        )

        assert response.status_code == 422

    def test_defaults_to_newest_first(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.list_transactions.return_value = TransactionsPublic(data=[], count=0)

        client.get("/api/v1/transactions/", headers=auth_headers)

        assert wire.list_transactions.call_args.kwargs["filters"].sort is TransactionSort.DATE_DESC

    def test_a_category_filter_from_another_household_is_not_found(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.list_transactions.side_effect = CategoryNotFoundError

        response = client.get(
            "/api/v1/transactions/", headers=auth_headers, params={"category_id": str(uuid.uuid4())}
        )

        assert response.status_code == 404


class TestGetTransaction:
    """Tests for GET /transactions/{transaction_id}."""

    def test_returns_the_transaction(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.get_transaction.return_value = make_public()

        response = client.get(f"/api/v1/transactions/{TRANSACTION_ID}", headers=auth_headers)

        assert response.status_code == 200

    def test_a_transaction_from_another_household_is_not_found(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        """A foreign ID reads as 404, never 403, so the API does not leak which IDs exist."""
        wire.get_transaction.side_effect = TransactionNotFoundError

        response = client.get(f"/api/v1/transactions/{uuid.uuid4()}", headers=auth_headers)

        assert response.status_code == 404


class TestUpdateTransaction:
    """Tests for PATCH /transactions/{transaction_id}."""

    def test_updates_the_transaction(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.update_transaction.return_value = make_public(amount_minor=5000)

        response = client.patch(
            f"/api/v1/transactions/{TRANSACTION_ID}", headers=auth_headers, json={"amount_minor": 5000}
        )

        assert response.status_code == 200
        assert wire.update_transaction.call_args.kwargs["transaction_update"].amount_minor == 5000

    def test_rejects_a_zero_amount(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.patch(
            f"/api/v1/transactions/{TRANSACTION_ID}", headers=auth_headers, json={"amount_minor": 0}
        )

        assert response.status_code == 422


    def test_rejects_an_amount_beyond_the_cap(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.patch(
            f"/api/v1/transactions/{TRANSACTION_ID}",
            headers=auth_headers,
            json={"amount_minor": MAX_AMOUNT_MINOR + 1},
        )

        assert response.status_code == 422


class TestDeleteTransaction:
    """Tests for DELETE /transactions/{transaction_id}."""

    def test_deletes_the_transaction(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.delete_transaction.return_value = Message(message="Transaction deleted.")

        response = client.delete(f"/api/v1/transactions/{TRANSACTION_ID}", headers=auth_headers)

        assert response.status_code == 200

    def test_a_transaction_from_another_household_is_not_found(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.delete_transaction.side_effect = TransactionNotFoundError

        response = client.delete(f"/api/v1/transactions/{uuid.uuid4()}", headers=auth_headers)

        assert response.status_code == 404
