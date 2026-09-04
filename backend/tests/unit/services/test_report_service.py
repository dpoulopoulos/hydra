import uuid
from datetime import date
from unittest.mock import MagicMock

import pytest

from app.exceptions import CategoryNotFoundError, InvalidDateRangeError, ReportRangeTooLargeError
from app.models import (
    Category,
    CategoryDepth,
    Household,
    HouseholdContext,
    TimeGranularity,
    TransactionKind,
)
from app.repositories.rows import CategorySpendRow, MonthlyFlowRow, TimeBucketRow
from app.services import ReportService

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def household() -> Household:
    house = Household(name="Test household", currency_code="EUR")
    house.id = HOUSEHOLD_ID
    return house


def spend_row(
    name: str = "Food & Drink",
    amount_minor: int = 40_000,
    count: int = 3,
    category_id: uuid.UUID | None = None,
) -> CategorySpendRow:
    """Build a grouped spend row."""
    return CategorySpendRow(
        category_id=category_id or uuid.uuid4(),
        category_name=name,
        parent_id=None,
        parent_name=None,
        color=None,
        amount_minor=amount_minor,
        transaction_count=count,
    )


class TestSpendByCategory:
    """Tests for spend_by_category."""

    def test_returns_slices_with_shares(
        self,
        mock_report_service: ReportService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        mock_report_service.session.execute = MagicMock()
        mock_report_service.session.execute.return_value.all.return_value = [
            spend_row(name="Food & Drink", amount_minor=75_000),
            spend_row(name="Transport", amount_minor=25_000),
        ]
        mock_report_service.session.get = MagicMock(return_value=household)

        result = mock_report_service.spend_by_category(household=household_context, month="2026-03")

        assert result.total_minor == 100_000
        assert [slice_.share for slice_ in result.slices] == [0.75, 0.25]
        assert result.period.currency_code == "EUR"

    def test_covers_the_whole_month(
        self,
        mock_report_service: ReportService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        """March has 31 days, so the period must end on the 31st."""
        mock_report_service.session.execute = MagicMock()
        mock_report_service.session.execute.return_value.all.return_value = []
        mock_report_service.session.get = MagicMock(return_value=household)

        result = mock_report_service.spend_by_category(household=household_context, month="2026-03")

        assert result.period.date_from == date(2026, 3, 1)
        assert result.period.date_to == date(2026, 3, 31)

    def test_handles_a_short_month(
        self,
        mock_report_service: ReportService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        mock_report_service.session.execute = MagicMock()
        mock_report_service.session.execute.return_value.all.return_value = []
        mock_report_service.session.get = MagicMock(return_value=household)

        result = mock_report_service.spend_by_category(household=household_context, month="2026-02")

        assert result.period.date_to == date(2026, 2, 28)

    def test_handles_december(
        self,
        mock_report_service: ReportService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        """The next month rolls the year over, so the range must not collapse."""
        mock_report_service.session.execute = MagicMock()
        mock_report_service.session.execute.return_value.all.return_value = []
        mock_report_service.session.get = MagicMock(return_value=household)

        result = mock_report_service.spend_by_category(household=household_context, month="2026-12")

        assert result.period.date_to == date(2026, 12, 31)

    def test_a_month_with_no_spending_has_no_shares(
        self,
        mock_report_service: ReportService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        """A zero total must not divide by zero."""
        mock_report_service.session.execute = MagicMock()
        mock_report_service.session.execute.return_value.all.return_value = []
        mock_report_service.session.get = MagicMock(return_value=household)

        result = mock_report_service.spend_by_category(household=household_context, month="2026-03")

        assert result.total_minor == 0
        assert result.slices == []

    def test_labels_spending_with_no_category(
        self,
        mock_report_service: ReportService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        mock_report_service.session.execute = MagicMock()
        mock_report_service.session.execute.return_value.all.return_value = [
            CategorySpendRow(None, None, None, None, None, 1_000, 1)
        ]
        mock_report_service.session.get = MagicMock(return_value=household)

        result = mock_report_service.spend_by_category(household=household_context, month="2026-03")

        assert result.slices[0].category_name == "Uncategorized"

    def test_defaults_to_expenses_rolled_up_to_the_parent(
        self,
        mock_report_service: ReportService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        mock_report_service.session.execute = MagicMock()
        mock_report_service.session.execute.return_value.all.return_value = []
        mock_report_service.session.get = MagicMock(return_value=household)

        result = mock_report_service.spend_by_category(household=household_context, month="2026-03")

        assert result.kind is TransactionKind.EXPENSE
        assert result.depth is CategoryDepth.PARENT


class TestSpendOverTime:
    """Tests for spend_over_time."""

    def test_fills_empty_days_with_zero(
        self,
        mock_report_service: ReportService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        """A chart that leaves days out implies a gap in time that is not there."""
        mock_report_service.session.execute = MagicMock()
        mock_report_service.session.execute.return_value.all.return_value = [
            TimeBucketRow(bucket=date(2026, 3, 1), amount_minor=1_000, transaction_count=1),
            TimeBucketRow(bucket=date(2026, 3, 4), amount_minor=2_000, transaction_count=2),
        ]
        mock_report_service.session.get = MagicMock(return_value=household)

        result = mock_report_service.spend_over_time(
            household=household_context, date_from=date(2026, 3, 1), date_to=date(2026, 3, 5)
        )

        assert [point.bucket.day for point in result.points] == [1, 2, 3, 4, 5]
        assert [point.amount_minor for point in result.points] == [1_000, 0, 0, 2_000, 0]

    def test_averages_over_active_buckets_only(
        self,
        mock_report_service: ReportService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        """Otherwise a quiet stretch would drag the average down and mislead."""
        mock_report_service.session.execute = MagicMock()
        mock_report_service.session.execute.return_value.all.return_value = [
            TimeBucketRow(bucket=date(2026, 3, 1), amount_minor=1_000, transaction_count=1),
            TimeBucketRow(bucket=date(2026, 3, 4), amount_minor=3_000, transaction_count=1),
        ]
        mock_report_service.session.get = MagicMock(return_value=household)

        result = mock_report_service.spend_over_time(
            household=household_context, date_from=date(2026, 3, 1), date_to=date(2026, 3, 31)
        )

        assert result.total_minor == 4_000
        assert result.average_minor == 2_000

    def test_fills_empty_months_with_zero(
        self,
        mock_report_service: ReportService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        mock_report_service.session.execute = MagicMock()
        mock_report_service.session.execute.return_value.all.return_value = [
            TimeBucketRow(bucket=date(2026, 1, 1), amount_minor=1_000, transaction_count=1)
        ]
        mock_report_service.session.get = MagicMock(return_value=household)

        result = mock_report_service.spend_over_time(
            household=household_context,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 3, 31),
            granularity=TimeGranularity.MONTH,
        )

        assert [point.bucket for point in result.points] == [
            date(2026, 1, 1),
            date(2026, 2, 1),
            date(2026, 3, 1),
        ]
        assert [point.amount_minor for point in result.points] == [1_000, 0, 0]

    def test_a_single_day_range_gives_one_point(
        self,
        mock_report_service: ReportService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        mock_report_service.session.execute = MagicMock()
        mock_report_service.session.execute.return_value.all.return_value = []
        mock_report_service.session.get = MagicMock(return_value=household)

        result = mock_report_service.spend_over_time(
            household=household_context, date_from=date(2026, 3, 4), date_to=date(2026, 3, 4)
        )

        assert len(result.points) == 1

    def test_rejects_a_backwards_range(
        self, mock_report_service: ReportService, household_context: HouseholdContext
    ) -> None:
        with pytest.raises(InvalidDateRangeError):
            mock_report_service.spend_over_time(
                household=household_context, date_from=date(2026, 3, 31), date_to=date(2026, 3, 1)
            )

    def test_rejects_too_many_daily_buckets(
        self, mock_report_service: ReportService, household_context: HouseholdContext
    ) -> None:
        with pytest.raises(ReportRangeTooLargeError):
            mock_report_service.spend_over_time(
                household=household_context, date_from=date(2020, 1, 1), date_to=date(2026, 1, 1)
            )

    def test_allows_a_long_range_of_months(
        self,
        mock_report_service: ReportService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        """The bucket count is what matters, and months are far fewer than days."""
        mock_report_service.session.execute = MagicMock()
        mock_report_service.session.execute.return_value.all.return_value = []
        mock_report_service.session.get = MagicMock(return_value=household)

        result = mock_report_service.spend_over_time(
            household=household_context,
            date_from=date(2020, 1, 1),
            date_to=date(2026, 1, 31),
            granularity=TimeGranularity.MONTH,
        )

        assert len(result.points) == 73

    def test_a_parent_category_filter_includes_its_subcategories(
        self,
        mock_report_service: ReportService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        parent = Category(household_id=HOUSEHOLD_ID, name="Food & Drink")
        child = Category(household_id=HOUSEHOLD_ID, name="Groceries", parent_id=parent.id)
        mock_report_service.session.exec = MagicMock()
        mock_report_service.session.exec.return_value.first.return_value = parent
        mock_report_service.session.exec.return_value.all.return_value = [child]
        mock_report_service.session.execute = MagicMock()
        mock_report_service.session.execute.return_value.all.return_value = []
        mock_report_service.session.get = MagicMock(return_value=household)

        mock_report_service.spend_over_time(
            household=household_context,
            date_from=date(2026, 3, 1),
            date_to=date(2026, 3, 31),
            category_id=parent.id,
        )

        statement = str(mock_report_service.session.execute.call_args.args[0])
        assert "category_id IN" in statement

    def test_a_category_from_another_household_is_not_found(
        self, mock_report_service: ReportService, household_context: HouseholdContext
    ) -> None:
        mock_report_service.session.exec = MagicMock()
        mock_report_service.session.exec.return_value.first.return_value = None

        with pytest.raises(CategoryNotFoundError):
            mock_report_service.spend_over_time(
                household=household_context,
                date_from=date(2026, 3, 1),
                date_to=date(2026, 3, 31),
                category_id=uuid.uuid4(),
            )


class TestIncomeExpense:
    """Tests for income_expense."""

    def test_pivots_kinds_into_columns(
        self,
        mock_report_service: ReportService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        mock_report_service.session.execute = MagicMock()
        mock_report_service.session.execute.return_value.all.return_value = [
            MonthlyFlowRow(date(2026, 3, 1), TransactionKind.INCOME, 250_000),
            MonthlyFlowRow(date(2026, 3, 1), TransactionKind.EXPENSE, 100_000),
        ]
        mock_report_service.session.get = MagicMock(return_value=household)

        result = mock_report_service.income_expense(
            household=household_context, month_from="2026-03", month_to="2026-03"
        )

        assert result.months[0].income_minor == 250_000
        assert result.months[0].expense_minor == 100_000
        assert result.months[0].net_minor == 150_000
        assert result.months[0].savings_rate == 0.6

    def test_accumulates_the_savings_trend(
        self,
        mock_report_service: ReportService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        mock_report_service.session.execute = MagicMock()
        mock_report_service.session.execute.return_value.all.return_value = [
            MonthlyFlowRow(date(2026, 1, 1), TransactionKind.INCOME, 100),
            MonthlyFlowRow(date(2026, 2, 1), TransactionKind.INCOME, 200),
            MonthlyFlowRow(date(2026, 3, 1), TransactionKind.EXPENSE, 50),
        ]
        mock_report_service.session.get = MagicMock(return_value=household)

        result = mock_report_service.income_expense(
            household=household_context, month_from="2026-01", month_to="2026-03"
        )

        assert [month.net_minor for month in result.months] == [100, 200, -50]
        assert [month.cumulative_net_minor for month in result.months] == [100, 300, 250]
        assert result.total_net_minor == 250

    def test_fills_months_with_no_activity(
        self,
        mock_report_service: ReportService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        mock_report_service.session.execute = MagicMock()
        mock_report_service.session.execute.return_value.all.return_value = []
        mock_report_service.session.get = MagicMock(return_value=household)

        result = mock_report_service.income_expense(
            household=household_context, month_from="2026-11", month_to="2027-02"
        )

        assert [month.month for month in result.months] == [
            "2026-11",
            "2026-12",
            "2027-01",
            "2027-02",
        ]

    def test_a_month_with_no_income_has_no_savings_rate(
        self,
        mock_report_service: ReportService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        """Reporting 0% would suggest income that was all spent."""
        mock_report_service.session.execute = MagicMock()
        mock_report_service.session.execute.return_value.all.return_value = [
            MonthlyFlowRow(date(2026, 3, 1), TransactionKind.EXPENSE, 100)
        ]
        mock_report_service.session.get = MagicMock(return_value=household)

        result = mock_report_service.income_expense(
            household=household_context, month_from="2026-03", month_to="2026-03"
        )

        assert result.months[0].savings_rate is None
        assert result.average_savings_rate is None

    def test_rejects_a_backwards_range(
        self, mock_report_service: ReportService, household_context: HouseholdContext
    ) -> None:
        with pytest.raises(InvalidDateRangeError):
            mock_report_service.income_expense(
                household=household_context, month_from="2026-06", month_to="2026-01"
            )

    def test_rejects_too_many_months(
        self, mock_report_service: ReportService, household_context: HouseholdContext
    ) -> None:
        with pytest.raises(ReportRangeTooLargeError):
            mock_report_service.income_expense(
                household=household_context, month_from="2000-01", month_to="2026-01"
            )
