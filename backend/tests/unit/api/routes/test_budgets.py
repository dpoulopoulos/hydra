import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_budget_service, get_current_user, get_db, get_household_context
from app.exceptions import (
    BudgetCategoryKindError,
    BudgetExistsError,
    BudgetNotFoundError,
    BudgetOverlapError,
    CategoryNotFoundError,
)
from app.main import app
from app.models import BudgetPublic, BudgetsPublic, HouseholdContext, Message, User
from app.models.fields import MAX_AMOUNT_MINOR

BUDGET_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")
CATEGORY_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


def make_public(limit_minor: int = 40_000, month: str = "2026-03") -> BudgetPublic:
    """Build a budget response payload."""
    return BudgetPublic(
        id=BUDGET_ID,
        household_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        category_id=CATEGORY_ID,
        month=month,
        limit_minor=limit_minor,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def wire(
    mock_db_session: MagicMock, test_user: User, household_context: HouseholdContext
) -> Generator[MagicMock]:
    """Override the database, the current user, the household scope and the service.

    Yields:
        A mock budget service the test can program.
    """
    service = MagicMock()

    def override_get_db() -> Generator[MagicMock]:
        yield mock_db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_household_context] = lambda: household_context
    app.dependency_overrides[get_budget_service] = lambda: service

    yield service

    app.dependency_overrides.clear()


class TestCreateBudget:
    """Tests for POST /budgets/."""

    def test_sets_a_limit(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.create_budget.return_value = make_public()

        response = client.post(
            "/api/v1/budgets/",
            headers=auth_headers,
            json={"category_id": str(CATEGORY_ID), "month": "2026-03", "limit_minor": 40000},
        )

        assert response.status_code == 200
        assert response.json()["month"] == "2026-03"

    def test_rejects_a_month_that_is_not_a_month(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/api/v1/budgets/",
            headers=auth_headers,
            json={"category_id": str(CATEGORY_ID), "month": "2026-13", "limit_minor": 1},
        )

        assert response.status_code == 422

    def test_rejects_a_full_date(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        """Storage keeps only the month, so a day would be silently dropped."""
        response = client.post(
            "/api/v1/budgets/",
            headers=auth_headers,
            json={"category_id": str(CATEGORY_ID), "month": "2026-03-04", "limit_minor": 1},
        )

        assert response.status_code == 422

    def test_rejects_a_limit_beyond_the_cap(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        """Beyond the cap the value is one the column cannot hold: a 422, not a 500."""
        response = client.post(
            "/api/v1/budgets/",
            headers=auth_headers,
            json={
                "category_id": str(CATEGORY_ID),
                "month": "2026-03",
                "limit_minor": MAX_AMOUNT_MINOR + 1,
            },
        )

        assert response.status_code == 422

    def test_reports_an_overlap_as_a_conflict(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.create_budget.side_effect = BudgetOverlapError(
            parent_name="Food & Drink", child_name="Groceries"
        )

        response = client.post(
            "/api/v1/budgets/",
            headers=auth_headers,
            json={"category_id": str(CATEGORY_ID), "month": "2026-03", "limit_minor": 1},
        )

        assert response.status_code == 409
        assert "count the same spending twice" in response.json()["detail"]

    def test_reports_an_income_category_as_a_bad_request(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.create_budget.side_effect = BudgetCategoryKindError(name="Salary")

        response = client.post(
            "/api/v1/budgets/",
            headers=auth_headers,
            json={"category_id": str(CATEGORY_ID), "month": "2026-03", "limit_minor": 1},
        )

        assert response.status_code == 400

    def test_a_category_from_another_household_is_not_found(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.create_budget.side_effect = CategoryNotFoundError

        response = client.post(
            "/api/v1/budgets/",
            headers=auth_headers,
            json={"category_id": str(uuid.uuid4()), "month": "2026-03", "limit_minor": 1},
        )

        assert response.status_code == 404


class TestListBudgets:
    """Tests for GET /budgets/."""

    def test_returns_the_budgets_for_a_month(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.list_budgets.return_value = BudgetsPublic(
            data=[make_public()], count=1, total_limit_minor=40_000
        )

        response = client.get("/api/v1/budgets/", headers=auth_headers, params={"month": "2026-03"})

        assert response.status_code == 200
        assert response.json()["total_limit_minor"] == 40000

    def test_requires_a_month(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/api/v1/budgets/", headers=auth_headers)

        assert response.status_code == 422

    def test_rejects_a_month_that_is_not_a_month(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/api/v1/budgets/", headers=auth_headers, params={"month": "March"})

        assert response.status_code == 422


class TestBulkUpsertBudgets:
    """Tests for PUT /budgets/bulk."""

    def test_sets_a_whole_month_in_one_request(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.bulk_upsert.return_value = BudgetsPublic(
            data=[make_public()], count=1, total_limit_minor=40_000
        )

        response = client.put(
            "/api/v1/budgets/bulk",
            headers=auth_headers,
            json={
                "month": "2026-03",
                "entries": [
                    {"category_id": str(CATEGORY_ID), "limit_minor": 40000},
                    {"category_id": str(uuid.uuid4()), "limit_minor": 15000},
                ],
            },
        )

        assert response.status_code == 200
        assert len(wire.bulk_upsert.call_args.kwargs["bulk"].entries) == 2

    def test_bulk_is_not_parsed_as_a_budget_id(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        """The literal "bulk" path must win over the {budget_id} path."""
        wire.bulk_upsert.return_value = BudgetsPublic(data=[], count=0)

        response = client.put(
            "/api/v1/budgets/bulk", headers=auth_headers, json={"month": "2026-03", "entries": []}
        )

        assert response.status_code != 422
        wire.get_budget.assert_not_called()

    def test_an_empty_set_clears_the_month(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.bulk_upsert.return_value = BudgetsPublic(data=[], count=0)

        response = client.put(
            "/api/v1/budgets/bulk", headers=auth_headers, json={"month": "2026-03", "entries": []}
        )

        assert response.status_code == 200
        assert response.json()["count"] == 0


class TestCopyBudgets:
    """Tests for POST /budgets/copy."""

    def test_copies_a_month_forward(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.copy_month.return_value = BudgetsPublic(
            data=[make_public(month="2026-04")], count=1, total_limit_minor=40_000
        )

        response = client.post(
            "/api/v1/budgets/copy",
            headers=auth_headers,
            json={"from_month": "2026-03", "to_month": "2026-04"},
        )

        assert response.status_code == 200
        assert response.json()["data"][0]["month"] == "2026-04"

    def test_defaults_to_not_overwriting(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.copy_month.return_value = BudgetsPublic(data=[], count=0)

        client.post(
            "/api/v1/budgets/copy",
            headers=auth_headers,
            json={"from_month": "2026-03", "to_month": "2026-04"},
        )

        assert wire.copy_month.call_args.kwargs["copy_request"].overwrite is False

    def test_reports_an_occupied_target_month_as_a_conflict(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.copy_month.side_effect = BudgetExistsError(identifier="2026-04")

        response = client.post(
            "/api/v1/budgets/copy",
            headers=auth_headers,
            json={"from_month": "2026-03", "to_month": "2026-04"},
        )

        assert response.status_code == 409


class TestGetBudget:
    """Tests for GET /budgets/{budget_id}."""

    def test_returns_the_budget(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.get_budget.return_value = make_public()

        response = client.get(f"/api/v1/budgets/{BUDGET_ID}", headers=auth_headers)

        assert response.status_code == 200

    def test_a_budget_from_another_household_is_not_found(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        """A foreign ID reads as 404, never 403, so the API does not leak which IDs exist."""
        wire.get_budget.side_effect = BudgetNotFoundError

        response = client.get(f"/api/v1/budgets/{uuid.uuid4()}", headers=auth_headers)

        assert response.status_code == 404


class TestUpdateBudget:
    """Tests for PATCH /budgets/{budget_id}."""

    def test_changes_the_limit(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.update_budget.return_value = make_public(limit_minor=50_000)

        response = client.patch(
            f"/api/v1/budgets/{BUDGET_ID}", headers=auth_headers, json={"limit_minor": 50000}
        )

        assert response.status_code == 200
        assert wire.update_budget.call_args.kwargs["budget_update"].limit_minor == 50000

    def test_rejects_a_negative_limit(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.patch(
            f"/api/v1/budgets/{BUDGET_ID}", headers=auth_headers, json={"limit_minor": -1}
        )

        assert response.status_code == 422


    def test_rejects_a_limit_beyond_the_cap(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.patch(
            f"/api/v1/budgets/{BUDGET_ID}",
            headers=auth_headers,
            json={"limit_minor": MAX_AMOUNT_MINOR + 1},
        )

        assert response.status_code == 422


class TestDeleteBudget:
    """Tests for DELETE /budgets/{budget_id}."""

    def test_removes_the_budget(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.delete_budget.return_value = Message(message="Budget removed.")

        response = client.delete(f"/api/v1/budgets/{BUDGET_ID}", headers=auth_headers)

        assert response.status_code == 200
