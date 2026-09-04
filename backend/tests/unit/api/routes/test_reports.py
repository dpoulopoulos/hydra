import uuid
from collections.abc import Generator
from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db, get_household_context, get_report_service
from app.exceptions import CategoryNotFoundError, InvalidDateRangeError, ReportRangeTooLargeError
from app.main import app
from app.models import (
    CategoryDepth,
    CategorySpendSlice,
    HouseholdContext,
    IncomeExpenseReport,
    MonthlyFlow,
    ReportPeriod,
    SpendByCategoryReport,
    SpendOverTimeReport,
    TimeGranularity,
    TimeSeriesPoint,
    TransactionKind,
    User,
)


def period() -> ReportPeriod:
    """Build a report period."""
    return ReportPeriod(date_from=date(2026, 3, 1), date_to=date(2026, 3, 31), currency_code="EUR")


@pytest.fixture
def wire(
    mock_db_session: MagicMock, test_user: User, household_context: HouseholdContext
) -> Generator[MagicMock]:
    """Override the database, the current user, the household scope and the service.

    Yields:
        A mock report service the test can program.
    """
    service = MagicMock()

    def override_get_db() -> Generator[MagicMock]:
        yield mock_db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_household_context] = lambda: household_context
    app.dependency_overrides[get_report_service] = lambda: service

    yield service

    app.dependency_overrides.clear()


class TestSpendByCategory:
    """Tests for GET /reports/spend-by-category."""

    def test_returns_the_slices(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.spend_by_category.return_value = SpendByCategoryReport(
            period=period(),
            kind=TransactionKind.EXPENSE,
            depth=CategoryDepth.PARENT,
            total_minor=20_000,
            slices=[
                CategorySpendSlice(
                    category_id=uuid.uuid4(),
                    category_name="Food & Drink",
                    amount_minor=10_000,
                    transaction_count=3,
                    share=0.5,
                )
            ],
        )

        response = client.get(
            "/api/v1/reports/spend-by-category", headers=auth_headers, params={"month": "2026-03"}
        )

        assert response.status_code == 200
        assert response.json()["slices"][0]["share"] == 0.5

    def test_requires_a_month(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/api/v1/reports/spend-by-category", headers=auth_headers)

        assert response.status_code == 422

    def test_rejects_a_month_that_is_not_a_month(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.get(
            "/api/v1/reports/spend-by-category", headers=auth_headers, params={"month": "2026-13"}
        )

        assert response.status_code == 422

    def test_defaults_to_expenses_rolled_up_to_parents(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.spend_by_category.return_value = SpendByCategoryReport(
            period=period(),
            kind=TransactionKind.EXPENSE,
            depth=CategoryDepth.PARENT,
            total_minor=0,
            slices=[],
        )

        client.get(
            "/api/v1/reports/spend-by-category", headers=auth_headers, params={"month": "2026-03"}
        )

        kwargs = wire.spend_by_category.call_args.kwargs
        assert kwargs["kind"] is TransactionKind.EXPENSE
        assert kwargs["depth"] is CategoryDepth.PARENT

    def test_can_report_per_subcategory(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.spend_by_category.return_value = SpendByCategoryReport(
            period=period(),
            kind=TransactionKind.EXPENSE,
            depth=CategoryDepth.LEAF,
            total_minor=0,
            slices=[],
        )

        client.get(
            "/api/v1/reports/spend-by-category",
            headers=auth_headers,
            params={"month": "2026-03", "depth": "leaf"},
        )

        assert wire.spend_by_category.call_args.kwargs["depth"] is CategoryDepth.LEAF


class TestSpendOverTime:
    """Tests for GET /reports/spend-over-time."""

    def test_returns_the_points(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.spend_over_time.return_value = SpendOverTimeReport(
            period=period(),
            granularity=TimeGranularity.DAY,
            kind=TransactionKind.EXPENSE,
            total_minor=1_000,
            average_minor=1_000,
            points=[TimeSeriesPoint(bucket=date(2026, 3, 1), amount_minor=1_000, transaction_count=1)],
        )

        response = client.get(
            "/api/v1/reports/spend-over-time",
            headers=auth_headers,
            params={"date_from": "2026-03-01", "date_to": "2026-03-31"},
        )

        assert response.status_code == 200
        assert response.json()["points"][0]["amount_minor"] == 1000

    def test_requires_both_bounds(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.get(
            "/api/v1/reports/spend-over-time", headers=auth_headers, params={"date_from": "2026-03-01"}
        )

        assert response.status_code == 422

    def test_reports_a_backwards_range_as_a_bad_request(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.spend_over_time.side_effect = InvalidDateRangeError

        response = client.get(
            "/api/v1/reports/spend-over-time",
            headers=auth_headers,
            params={"date_from": "2026-03-31", "date_to": "2026-03-01"},
        )

        assert response.status_code == 400

    def test_reports_too_large_a_range_as_unprocessable(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.spend_over_time.side_effect = ReportRangeTooLargeError(limit="two years of daily figures")

        response = client.get(
            "/api/v1/reports/spend-over-time",
            headers=auth_headers,
            params={"date_from": "2010-01-01", "date_to": "2026-01-01"},
        )

        assert response.status_code == 422

    def test_a_category_from_another_household_is_not_found(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.spend_over_time.side_effect = CategoryNotFoundError

        response = client.get(
            "/api/v1/reports/spend-over-time",
            headers=auth_headers,
            params={
                "date_from": "2026-03-01",
                "date_to": "2026-03-31",
                "category_id": str(uuid.uuid4()),
            },
        )

        assert response.status_code == 404

    def test_passes_the_filters_through(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.spend_over_time.return_value = SpendOverTimeReport(
            period=period(),
            granularity=TimeGranularity.MONTH,
            kind=TransactionKind.INCOME,
            total_minor=0,
            average_minor=0,
            points=[],
        )
        account_id = uuid.uuid4()

        client.get(
            "/api/v1/reports/spend-over-time",
            headers=auth_headers,
            params={
                "date_from": "2026-01-01",
                "date_to": "2026-03-31",
                "granularity": "month",
                "kind": "income",
                "account_id": str(account_id),
            },
        )

        kwargs = wire.spend_over_time.call_args.kwargs
        assert kwargs["granularity"] is TimeGranularity.MONTH
        assert kwargs["kind"] is TransactionKind.INCOME
        assert kwargs["account_id"] == account_id


class TestIncomeExpense:
    """Tests for GET /reports/income-expense."""

    def test_returns_the_months_with_the_running_net(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.income_expense.return_value = IncomeExpenseReport(
            period=period(),
            months=[
                MonthlyFlow(
                    month="2026-03",
                    income_minor=250_000,
                    expense_minor=100_000,
                    net_minor=150_000,
                    cumulative_net_minor=150_000,
                    savings_rate=0.6,
                )
            ],
            total_income_minor=250_000,
            total_expense_minor=100_000,
            total_net_minor=150_000,
            average_savings_rate=0.6,
        )

        response = client.get(
            "/api/v1/reports/income-expense",
            headers=auth_headers,
            params={"month_from": "2026-03", "month_to": "2026-03"},
        )

        assert response.status_code == 200
        assert response.json()["months"][0]["cumulative_net_minor"] == 150000

    def test_requires_both_months(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.get(
            "/api/v1/reports/income-expense", headers=auth_headers, params={"month_from": "2026-03"}
        )

        assert response.status_code == 422

    def test_reports_too_long_a_range_as_unprocessable(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.income_expense.side_effect = ReportRangeTooLargeError(
            limit="ten years of monthly figures"
        )

        response = client.get(
            "/api/v1/reports/income-expense",
            headers=auth_headers,
            params={"month_from": "2000-01", "month_to": "2026-01"},
        )

        assert response.status_code == 422
