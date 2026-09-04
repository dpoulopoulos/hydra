import uuid
from collections.abc import Generator
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import (
    get_current_user,
    get_db,
    get_household_context,
    get_recurring_rule_service,
)
from app.exceptions import InvalidRecurrenceError, RecurringRuleNotFoundError
from app.main import app
from app.models import (
    HouseholdContext,
    Message,
    RecurrenceFrequency,
    RecurringRulePublic,
    RecurringRulesPublic,
    RecurringRunResult,
    TransactionKind,
    UpcomingOccurrence,
    UpcomingOccurrencesPublic,
    User,
)
from app.models.fields import MAX_AMOUNT_MINOR
from app.models.recurring_rule import MAX_RECURRENCE_INTERVAL

RULE_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")
ACCOUNT_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")


def make_public(
    amount_minor: int = 120_000, next_occurrence_on: date | None = date(2026, 4, 1)
) -> RecurringRulePublic:
    """Build a recurring rule response payload."""
    return RecurringRulePublic(
        id=RULE_ID,
        household_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        name="Rent",
        frequency=RecurrenceFrequency.MONTHLY,
        interval=1,
        day_of_month=1,
        start_date=date(2026, 1, 1),
        kind=TransactionKind.EXPENSE,
        amount_minor=amount_minor,
        account_id=ACCOUNT_ID,
        next_occurrence_on=next_occurrence_on,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def wire(
    mock_db_session: MagicMock, test_user: User, household_context: HouseholdContext
) -> Generator[MagicMock]:
    """Override the database, the current user, the household scope and the service.

    Yields:
        A mock recurring rule service the test can program.
    """
    service = MagicMock()

    def override_get_db() -> Generator[MagicMock]:
        yield mock_db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_household_context] = lambda: household_context
    app.dependency_overrides[get_recurring_rule_service] = lambda: service

    yield service

    app.dependency_overrides.clear()


class TestCreateRecurringRule:
    """Tests for POST /recurring-rules/."""

    def test_creates_a_rule(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.create_rule.return_value = make_public()

        response = client.post(
            "/api/v1/recurring-rules/",
            headers=auth_headers,
            json={
                "name": "Rent",
                "frequency": "monthly",
                "day_of_month": 1,
                "start_date": "2026-01-01",
                "amount_minor": 120000,
                "account_id": str(ACCOUNT_ID),
            },
        )

        assert response.status_code == 200
        assert response.json()["next_occurrence_on"] == "2026-04-01"

    def test_rejects_a_zero_amount(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/api/v1/recurring-rules/",
            headers=auth_headers,
            json={
                "name": "Rent",
                "start_date": "2026-01-01",
                "amount_minor": 0,
                "account_id": str(ACCOUNT_ID),
            },
        )

        assert response.status_code == 422

    def test_rejects_an_amount_beyond_the_cap(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        """Beyond the cap the value is one the column cannot hold: a 422, not a 500."""
        response = client.post(
            "/api/v1/recurring-rules/",
            headers=auth_headers,
            json={
                "name": "Rent",
                "start_date": "2026-01-01",
                "amount_minor": MAX_AMOUNT_MINOR + 1,
                "account_id": str(ACCOUNT_ID),
            },
        )

        assert response.status_code == 422

    def test_rejects_a_day_beyond_the_calendar(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/api/v1/recurring-rules/",
            headers=auth_headers,
            json={
                "name": "Rent",
                "day_of_month": 32,
                "start_date": "2026-01-01",
                "amount_minor": 1,
                "account_id": str(ACCOUNT_ID),
            },
        )

        assert response.status_code == 422

    def test_rejects_a_zero_interval(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/api/v1/recurring-rules/",
            headers=auth_headers,
            json={
                "name": "Rent",
                "interval": 0,
                "start_date": "2026-01-01",
                "amount_minor": 1,
                "account_id": str(ACCOUNT_ID),
            },
        )

        assert response.status_code == 422

    def test_rejects_an_interval_beyond_the_cap(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        """A fat-fingered interval would push the schedule past the last date there is."""
        response = client.post(
            "/api/v1/recurring-rules/",
            headers=auth_headers,
            json={
                "name": "Rent",
                "interval": MAX_RECURRENCE_INTERVAL + 1,
                "start_date": "2026-01-01",
                "amount_minor": 1,
                "account_id": str(ACCOUNT_ID),
            },
        )

        assert response.status_code == 422

    def test_reports_an_impossible_schedule_as_a_bad_request(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.create_rule.side_effect = InvalidRecurrenceError("A rule cannot end before it starts.")

        response = client.post(
            "/api/v1/recurring-rules/",
            headers=auth_headers,
            json={
                "name": "Rent",
                "start_date": "2026-06-01",
                "end_date": "2026-01-01",
                "amount_minor": 1,
                "account_id": str(ACCOUNT_ID),
            },
        )

        assert response.status_code == 400


class TestListRecurringRules:
    """Tests for GET /recurring-rules/."""

    def test_returns_the_rules(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.list_rules.return_value = RecurringRulesPublic(data=[make_public()], count=1)

        response = client.get("/api/v1/recurring-rules/", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["count"] == 1

    def test_can_filter_to_paused_rules(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.list_rules.return_value = RecurringRulesPublic(data=[], count=0)

        client.get("/api/v1/recurring-rules/", headers=auth_headers, params={"is_active": "false"})

        assert wire.list_rules.call_args.kwargs["is_active"] is False


class TestListUpcoming:
    """Tests for GET /recurring-rules/upcoming."""

    def test_returns_the_projection(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.list_upcoming.return_value = UpcomingOccurrencesPublic(
            data=[
                UpcomingOccurrence(
                    rule_id=RULE_ID,
                    name="Rent",
                    kind=TransactionKind.EXPENSE,
                    amount_minor=120_000,
                    occurs_on=date(2026, 4, 1),
                    account_id=ACCOUNT_ID,
                )
            ],
            count=1,
            total_minor=120_000,
        )

        response = client.get("/api/v1/recurring-rules/upcoming", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["total_minor"] == 120000

    def test_upcoming_is_not_parsed_as_a_rule_id(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        """The literal "upcoming" path must win over the {rule_id} path."""
        wire.list_upcoming.return_value = UpcomingOccurrencesPublic(data=[], count=0)

        response = client.get("/api/v1/recurring-rules/upcoming", headers=auth_headers)

        assert response.status_code != 422
        wire.get_rule.assert_not_called()


class TestRunRecurringRules:
    """Tests for POST /recurring-rules/run."""

    def test_records_what_has_fallen_due(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.materialize_due.return_value = RecurringRunResult(
            created_count=3, skipped_count=0, rules_advanced=1
        )

        response = client.post("/api/v1/recurring-rules/run", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["created_count"] == 3

    def test_run_is_not_parsed_as_a_rule_id(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.materialize_due.return_value = RecurringRunResult(
            created_count=0, skipped_count=0, rules_advanced=0
        )

        response = client.post("/api/v1/recurring-rules/run", headers=auth_headers)

        assert response.status_code != 422


class TestGetRecurringRule:
    """Tests for GET /recurring-rules/{rule_id}."""

    def test_returns_the_rule(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.get_rule.return_value = make_public()

        response = client.get(f"/api/v1/recurring-rules/{RULE_ID}", headers=auth_headers)

        assert response.status_code == 200

    def test_a_rule_from_another_household_is_not_found(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        """A foreign ID reads as 404, never 403, so the API does not leak which IDs exist."""
        wire.get_rule.side_effect = RecurringRuleNotFoundError

        response = client.get(f"/api/v1/recurring-rules/{uuid.uuid4()}", headers=auth_headers)

        assert response.status_code == 404


class TestUpdateRecurringRule:
    """Tests for PATCH /recurring-rules/{rule_id}."""

    def test_changes_the_amount(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.update_rule.return_value = make_public(amount_minor=130_000)

        response = client.patch(
            f"/api/v1/recurring-rules/{RULE_ID}", headers=auth_headers, json={"amount_minor": 130000}
        )

        assert response.status_code == 200
        assert wire.update_rule.call_args.kwargs["rule_update"].amount_minor == 130000

    def test_pauses_the_rule(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.update_rule.return_value = make_public()

        client.patch(
            f"/api/v1/recurring-rules/{RULE_ID}", headers=auth_headers, json={"is_active": False}
        )

        assert wire.update_rule.call_args.kwargs["rule_update"].is_active is False


    def test_rejects_an_interval_beyond_the_cap(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.patch(
            f"/api/v1/recurring-rules/{RULE_ID}",
            headers=auth_headers,
            json={"interval": MAX_RECURRENCE_INTERVAL + 1},
        )

        assert response.status_code == 422


class TestDeleteRecurringRule:
    """Tests for DELETE /recurring-rules/{rule_id}."""

    def test_deletes_the_rule(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.delete_rule.return_value = Message(
            message="Recurring rule deleted. The transactions it created are kept."
        )

        response = client.delete(f"/api/v1/recurring-rules/{RULE_ID}", headers=auth_headers)

        assert response.status_code == 200
        assert "kept" in response.json()["message"]
