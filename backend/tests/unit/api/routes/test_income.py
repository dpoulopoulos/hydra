import uuid
from collections.abc import Generator
from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db, get_household_context, get_income_service
from app.exceptions import (
    IncomeClientInUseError,
    IncomeClientNotFoundError,
    IncomeClientNotOwnedError,
    IncomeSessionNotFoundError,
)
from app.main import app
from app.models import (
    ForecastBasis,
    HouseholdContext,
    IncomeClientPublic,
    IncomeClientsPublic,
    IncomeForecast,
    IncomeMonth,
    IncomeSessionPublic,
    IncomeSessionsPublic,
    IncomeSessionStatus,
    IncomeSummary,
    Message,
    PaymentStatus,
    User,
)

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def a_client() -> IncomeClientPublic:
    """Build a client response, name still encrypted."""
    return IncomeClientPublic(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        owner_user_id=uuid.uuid4(),
        name_ct="Z0FBQUFBQm5jaXBoZXJ0ZXh0",
        default_rate_minor=50_00,
        cadence_interval=1,
        cadence_weekdays=[],
        default_account_id=uuid.uuid4(),
        created_at=date(2026, 1, 1),
    )


def a_session(
    status: IncomeSessionStatus = IncomeSessionStatus.ATTENDED,
    payment_status: PaymentStatus = PaymentStatus.PENDING,
) -> IncomeSessionPublic:
    """Build a session response."""
    return IncomeSessionPublic(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        client_id=uuid.uuid4(),
        occurs_on=date(2026, 9, 8),
        fee_minor=50_00,
        status=status,
        payment_status=payment_status,
        created_at=date(2026, 1, 1),
    )


@pytest.fixture
def wire(mock_db_session: MagicMock, test_user: User, household_context: HouseholdContext) -> Generator[MagicMock]:
    """Override the database, the current user, the household scope and the service.

    Yields:
        A mock income service the test can program.
    """
    service = MagicMock()

    def override_get_db() -> Generator[MagicMock]:
        yield mock_db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_household_context] = lambda: household_context
    app.dependency_overrides[get_income_service] = lambda: service

    yield service

    app.dependency_overrides.clear()


class TestClients:
    """Tests for the client endpoints."""

    def test_clients_are_listed(self, client: TestClient, auth_headers: dict[str, str], wire: MagicMock) -> None:
        wire.list_clients.return_value = IncomeClientsPublic(data=[a_client()], count=1)

        response = client.get("/api/v1/income/clients", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["count"] == 1

    def test_a_listed_client_still_has_an_encrypted_name(
        self, client: TestClient, auth_headers: dict[str, str], wire: MagicMock
    ) -> None:
        """The API is a post box for the name. It never decrypts anything."""
        wire.list_clients.return_value = IncomeClientsPublic(data=[a_client()], count=1)

        body = client.get("/api/v1/income/clients", headers=auth_headers).json()

        assert body["data"][0]["name_ct"] == "Z0FBQUFBQm5jaXBoZXJ0ZXh0"
        assert "name" not in body["data"][0]

    def test_a_text_search_is_refused_rather_than_ignored(
        self, client: TestClient, auth_headers: dict[str, str], wire: MagicMock
    ) -> None:
        """Names are ciphertext here, so a search could only ever mislead."""
        response = client.get("/api/v1/income/clients", headers=auth_headers, params={"q": "anna"})

        assert response.status_code == 422

    def test_an_unknown_client_is_a_404(
        self, client: TestClient, auth_headers: dict[str, str], wire: MagicMock
    ) -> None:
        wire.get_client.side_effect = IncomeClientNotFoundError

        response = client.get(f"/api/v1/income/clients/{uuid.uuid4()}", headers=auth_headers)

        assert response.status_code == 404

    def test_another_members_client_is_a_403_not_a_404(
        self, client: TestClient, auth_headers: dict[str, str], wire: MagicMock
    ) -> None:
        """The row is visible to the whole household. Only the name is private."""
        wire.update_client.side_effect = IncomeClientNotOwnedError

        response = client.patch(
            f"/api/v1/income/clients/{uuid.uuid4()}", headers=auth_headers, json={"default_rate_minor": 100}
        )

        assert response.status_code == 403

    def test_a_client_with_sessions_is_a_409(
        self, client: TestClient, auth_headers: dict[str, str], wire: MagicMock
    ) -> None:
        wire.delete_client.side_effect = IncomeClientInUseError

        response = client.delete(f"/api/v1/income/clients/{uuid.uuid4()}", headers=auth_headers)

        assert response.status_code == 409


class TestSessions:
    """Tests for the session endpoints."""

    def test_sessions_are_listed_with_their_totals(
        self, client: TestClient, auth_headers: dict[str, str], wire: MagicMock
    ) -> None:
        wire.list_sessions.return_value = IncomeSessionsPublic(
            data=[a_session()], count=1, earned_total_minor=50_00, outstanding_total_minor=50_00
        )

        body = client.get("/api/v1/income/sessions", headers=auth_headers).json()

        assert body["earned_total_minor"] == 50_00
        assert body["outstanding_total_minor"] == 50_00

    def test_the_debtors_list_is_one_filter(
        self, client: TestClient, auth_headers: dict[str, str], wire: MagicMock
    ) -> None:
        wire.list_sessions.return_value = IncomeSessionsPublic(data=[], count=0)

        response = client.get("/api/v1/income/sessions", headers=auth_headers, params={"payment_status": "pending"})

        assert response.status_code == 200
        assert wire.list_sessions.call_args.kwargs["filters"].payment_status is PaymentStatus.PENDING

    def test_a_mistyped_month_is_a_422(self, client: TestClient, auth_headers: dict[str, str], wire: MagicMock) -> None:
        response = client.get("/api/v1/income/sessions", headers=auth_headers, params={"month": "2026-13"})

        assert response.status_code == 422

    def test_an_unknown_filter_is_a_422(
        self, client: TestClient, auth_headers: dict[str, str], wire: MagicMock
    ) -> None:
        """A silently dropped filter returns more data than was asked for."""
        response = client.get("/api/v1/income/sessions", headers=auth_headers, params={"stauts": "attended"})

        assert response.status_code == 422

    def test_an_unknown_session_is_a_404(
        self, client: TestClient, auth_headers: dict[str, str], wire: MagicMock
    ) -> None:
        wire.update_session.side_effect = IncomeSessionNotFoundError

        response = client.patch(
            f"/api/v1/income/sessions/{uuid.uuid4()}", headers=auth_headers, json={"payment_status": "paid"}
        )

        assert response.status_code == 404


class TestSummaryAndForecast:
    """Tests for the reporting endpoints."""

    def test_the_summary_reports_earned_and_received_apart(
        self, client: TestClient, auth_headers: dict[str, str], wire: MagicMock
    ) -> None:
        wire.get_summary.return_value = IncomeSummary(
            month="2026-09",
            currency_code="EUR",
            earned_minor=1_000_00,
            received_minor=800_00,
            outstanding_minor=200_00,
            total_outstanding_minor=350_00,
            attended_count=20,
            unpaid_count=3,
            scheduled_minor=0,
            scheduled_count=0,
            missed_count=1,
            cancelled_count=0,
            active_client_count=6,
        )

        body = client.get("/api/v1/income/summary", headers=auth_headers, params={"month": "2026-09"}).json()

        assert body["earned_minor"] == 1_000_00
        assert body["received_minor"] == 800_00
        assert body["total_outstanding_minor"] == 350_00

    def test_the_forecast_carries_its_band_and_its_basis(
        self, client: TestClient, auth_headers: dict[str, str], wire: MagicMock
    ) -> None:
        wire.get_forecast.return_value = IncomeForecast(
            month="2026-10",
            currency_code="EUR",
            likely_minor=1_966_00,
            low_minor=1_663_00,
            high_minor=2_269_00,
            basis=ForecastBasis.HISTORY,
            months_used=6,
            booked_minor=400_00,
            booked_session_count=8,
            earned_so_far_minor=0,
            expected_from_diary_minor=360_00,
            diary_realisation_rate=0.9,
            clients=[],
            history=[
                IncomeMonth(
                    month="2026-09",
                    earned_minor=2_050_00,
                    received_minor=2_050_00,
                    outstanding_minor=0,
                    attended_count=41,
                    missed_count=1,
                    cancelled_count=0,
                    unpaid_count=0,
                    client_count=9,
                )
            ],
        )

        body = client.get("/api/v1/income/forecast", headers=auth_headers).json()

        assert body["low_minor"] < body["likely_minor"] < body["high_minor"]
        assert body["basis"] == "history"
        assert body["months_used"] == 6

    def test_the_current_month_can_be_estimated_too(
        self, client: TestClient, auth_headers: dict[str, str], wire: MagicMock
    ) -> None:
        """The month in progress is the one people actually ask about."""
        wire.get_forecast.return_value = IncomeForecast(
            month="2026-09",
            currency_code="EUR",
            likely_minor=1_500_00,
            low_minor=1_500_00,
            high_minor=1_800_00,
            basis=ForecastBasis.HISTORY,
            months_used=6,
            history=[],
            booked_minor=300_00,
            booked_session_count=6,
            earned_so_far_minor=1_200_00,
            expected_from_diary_minor=270_00,
            diary_realisation_rate=0.9,
            clients=[],
        )

        body = client.get("/api/v1/income/forecast", headers=auth_headers, params={"month": "2026-09"}).json()

        # Work already done is a floor. The diary is not: it is discounted for
        # the appointments that will not happen, and only informs the estimate.
        assert body["low_minor"] >= body["earned_so_far_minor"]
        assert body["expected_from_diary_minor"] < body["booked_minor"]

    def test_the_forecast_says_how_much_of_the_roster_it_covers(
        self, client: TestClient, auth_headers: dict[str, str], wire: MagicMock
    ) -> None:
        """A practice larger than the capped read has to be told the estimate is partial."""
        wire.get_forecast.return_value = IncomeForecast(
            month="2026-10",
            currency_code="EUR",
            likely_minor=1_966_00,
            low_minor=1_663_00,
            high_minor=2_269_00,
            basis=ForecastBasis.HISTORY,
            months_used=6,
            history=[],
            booked_minor=400_00,
            booked_session_count=8,
            earned_so_far_minor=0,
            expected_from_diary_minor=360_00,
            active_client_count=260,
            priced_client_count=200,
            clients=[],
        )

        body = client.get("/api/v1/income/forecast", headers=auth_headers).json()

        assert body["priced_client_count"] == 200
        assert body["active_client_count"] == 260

    def test_too_much_history_is_refused(
        self, client: TestClient, auth_headers: dict[str, str], wire: MagicMock
    ) -> None:
        response = client.get("/api/v1/income/forecast", headers=auth_headers, params={"months": 99})

        assert response.status_code == 422


class TestVaultReset:
    """Tests for the destructive reset."""

    def test_a_reset_without_confirmation_does_nothing(
        self, client: TestClient, auth_headers: dict[str, str], wire: MagicMock
    ) -> None:
        """Losing every client name should take more than one stray request."""
        response = client.delete("/api/v1/income/vault", headers=auth_headers)

        assert response.status_code == 200
        wire.reset_vault.assert_not_called()

    def test_a_confirmed_reset_goes_through(
        self, client: TestClient, auth_headers: dict[str, str], wire: MagicMock
    ) -> None:
        wire.reset_vault.return_value = Message(message="done")

        client.delete("/api/v1/income/vault", headers=auth_headers, params={"confirm": True})

        wire.reset_vault.assert_called_once()
