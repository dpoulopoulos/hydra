import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db, get_goal_service, get_household_context
from app.exceptions import (
    GoalAccountLockedError,
    GoalAccountNotSavingsError,
    GoalExistsError,
    GoalNotFoundError,
)
from app.main import app
from app.models import GoalHistory, GoalMonth, GoalPublic, GoalsPublic, HouseholdContext, Message, User

GOAL_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")
ACCOUNT_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")


def make_public(saved_minor: int = 0) -> GoalPublic:
    """Build a goal response payload."""
    return GoalPublic(
        id=GOAL_ID,
        household_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        account_id=ACCOUNT_ID,
        account_name="Savings",
        currency_code="EUR",
        name="New car",
        target_minor=2_000_000,
        saved_minor=saved_minor,
        peak_saved_minor=saved_minor,
        remaining_minor=2_000_000 - saved_minor,
        progress=saved_minor / 2_000_000,
        average_monthly_minor=0,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def wire(mock_db_session: MagicMock, test_user: User, household_context: HouseholdContext) -> Generator[MagicMock]:
    """Override the database, the current user, the household scope and the service.

    Yields:
        A mock goal service the test can program.
    """
    service = MagicMock()

    def override_get_db() -> Generator[MagicMock]:
        yield mock_db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_household_context] = lambda: household_context
    app.dependency_overrides[get_goal_service] = lambda: service

    yield service

    app.dependency_overrides.clear()


class TestCreateGoal:
    """Tests for POST /goals/."""

    def test_creates_a_goal(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        wire.create_goal.return_value = make_public()

        response = client.post(
            "/api/v1/goals/",
            headers=auth_headers,
            json={"name": "New car", "account_id": str(ACCOUNT_ID), "target_minor": 2_000_000},
        )

        assert response.status_code == 200
        assert response.json()["name"] == "New car"

    def test_rejects_an_empty_name(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        response = client.post(
            "/api/v1/goals/",
            headers=auth_headers,
            json={"name": "", "account_id": str(ACCOUNT_ID), "target_minor": 1},
        )

        assert response.status_code == 422

    def test_maps_a_taken_name_to_409(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        wire.create_goal.side_effect = GoalExistsError(identifier="New car")

        response = client.post(
            "/api/v1/goals/",
            headers=auth_headers,
            json={"name": "New car", "account_id": str(ACCOUNT_ID), "target_minor": 1},
        )

        assert response.status_code == 409

    def test_maps_a_non_savings_account_to_400(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.create_goal.side_effect = GoalAccountNotSavingsError(name="Everyday")

        response = client.post(
            "/api/v1/goals/",
            headers=auth_headers,
            json={"name": "Car", "account_id": str(ACCOUNT_ID), "target_minor": 1},
        )

        assert response.status_code == 400


class TestListGoals:
    """Tests for GET /goals/."""

    def test_lists_goals(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        wire.list_goals.return_value = GoalsPublic(data=[make_public(500)], count=1, accounts=[])

        response = client.get("/api/v1/goals/", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["data"][0]["saved_minor"] == 500


class TestGetGoal:
    """Tests for GET /goals/{goal_id}."""

    def test_maps_an_unknown_goal_to_404(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.get_goal.side_effect = GoalNotFoundError()

        response = client.get(f"/api/v1/goals/{GOAL_ID}", headers=auth_headers)

        assert response.status_code == 404


class TestGoalHistory:
    """Tests for GET /goals/{goal_id}/history."""

    def test_returns_the_months(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        wire.history.return_value = GoalHistory(
            goal_id=GOAL_ID,
            month_from="2026-01",
            month_to="2026-01",
            months=[GoalMonth(month="2026-01", saved_in_minor=5, saved_out_minor=0, net_minor=5, cumulative_minor=5)],
        )

        response = client.get(
            f"/api/v1/goals/{GOAL_ID}/history",
            headers=auth_headers,
            params={"month_from": "2026-01", "month_to": "2026-01"},
        )

        assert response.status_code == 200
        assert response.json()["months"][0]["net_minor"] == 5

    def test_rejects_a_month_that_is_not_a_month(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.get(f"/api/v1/goals/{GOAL_ID}/history", headers=auth_headers, params={"month_to": "2026-13"})

        assert response.status_code == 422


class TestUpdateGoal:
    """Tests for PATCH /goals/{goal_id}."""

    def test_maps_a_locked_account_to_409(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.update_goal.side_effect = GoalAccountLockedError()

        response = client.patch(
            f"/api/v1/goals/{GOAL_ID}", headers=auth_headers, json={"account_id": str(uuid.uuid4())}
        )

        assert response.status_code == 409


class TestDeleteGoal:
    """Tests for DELETE /goals/{goal_id}."""

    def test_deletes_a_goal(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        wire.delete_goal.return_value = Message(message="Goal deleted.")

        response = client.delete(f"/api/v1/goals/{GOAL_ID}", headers=auth_headers)

        assert response.status_code == 200
