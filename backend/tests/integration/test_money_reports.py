"""The money arithmetic that lives in SQL, against a ledger with known totals.

The sign convention, the expense/income filtering, the transfer exclusion and
the COALESCE roll-up of a subcategory into its parent are all in the queries
themselves, so against a mocked session they are asserted only against the
values the mock was told to return. A wrong sign or a wrong join gives wrong
money and a green suite.

Every figure below is hand computed from the ledger the fixture seeds, so a
change to any of those queries has to be reconciled with a number a person
wrote down rather than with the query's own output.
"""

import dataclasses
import datetime

import pytest
from sqlmodel import Session

from app.models import (
    Account,
    BudgetCreate,
    Category,
    CategoryDepth,
    CategoryKind,
    HouseholdContext,
    Transaction,
    TransactionKind,
)
from app.services import BudgetService, ReportService
from tests.integration.conftest import make_account, make_category

MONTH = "2024-03"

# What the seeded ledger adds up to. Spelled out here rather than recomputed in
# the assertions, which would only restate the query being tested.
RENT_MINOR = 30_000
HOME_DIRECT_MINOR = 12_000
GROCERIES_MINOR = 8_000
UNCATEGORIZED_MINOR = 5_000
SALARY_MINOR = 200_000
TRANSFER_MINOR = 25_000
FEBRUARY_MINOR = 9_999

HOME_TOTAL_MINOR = RENT_MINOR + HOME_DIRECT_MINOR
MARCH_EXPENSE_MINOR = HOME_TOTAL_MINOR + GROCERIES_MINOR + UNCATEGORIZED_MINOR

CURRENT_OPENING_MINOR = 100_000
SAVINGS_OPENING_MINOR = 50_000


@dataclasses.dataclass
class Ledger:
    """The seeded rows, so a test can name the ones it asserts about."""

    current: Account
    savings: Account
    home: Category
    rent: Category
    groceries: Category
    salary: Category


@pytest.fixture
def ledger(db_session: Session, household_a: HouseholdContext) -> Ledger:
    """Seed a month of spending, income and one transfer.

    March 2024 holds two expenses under the Home branch, one under Groceries,
    one with no category at all, a salary and a transfer between the two
    accounts. February holds one further expense, which every March figure has
    to leave out.

    Args:
        db_session: The database session.
        household_a: The household to seed.

    Returns:
        The accounts and categories the rows point at.
    """
    household_id = household_a.household_id
    current = make_account(
        db_session, household_id=household_id, name="Current", opening_balance_minor=CURRENT_OPENING_MINOR
    )
    savings = make_account(
        db_session, household_id=household_id, name="Savings", opening_balance_minor=SAVINGS_OPENING_MINOR
    )
    home = make_category(db_session, household_id=household_id, name="Home")
    rent = make_category(db_session, household_id=household_id, name="Rent", parent_id=home.id)
    groceries = make_category(db_session, household_id=household_id, name="Groceries")
    salary = make_category(db_session, household_id=household_id, name="Salary", kind=CategoryKind.INCOME)

    rows = [
        Transaction(
            household_id=household_id,
            account_id=current.id,
            category_id=rent.id,
            kind=TransactionKind.EXPENSE,
            amount_minor=RENT_MINOR,
            occurred_on=datetime.date(2024, 3, 1),
        ),
        Transaction(
            household_id=household_id,
            account_id=current.id,
            category_id=home.id,
            kind=TransactionKind.EXPENSE,
            amount_minor=HOME_DIRECT_MINOR,
            occurred_on=datetime.date(2024, 3, 10),
        ),
        Transaction(
            household_id=household_id,
            account_id=current.id,
            category_id=groceries.id,
            kind=TransactionKind.EXPENSE,
            amount_minor=GROCERIES_MINOR,
            occurred_on=datetime.date(2024, 3, 12),
        ),
        Transaction(
            household_id=household_id,
            account_id=current.id,
            kind=TransactionKind.EXPENSE,
            amount_minor=UNCATEGORIZED_MINOR,
            occurred_on=datetime.date(2024, 3, 20),
        ),
        Transaction(
            household_id=household_id,
            account_id=current.id,
            category_id=salary.id,
            kind=TransactionKind.INCOME,
            amount_minor=SALARY_MINOR,
            occurred_on=datetime.date(2024, 3, 25),
        ),
        Transaction(
            household_id=household_id,
            account_id=current.id,
            counter_account_id=savings.id,
            kind=TransactionKind.TRANSFER,
            amount_minor=TRANSFER_MINOR,
            occurred_on=datetime.date(2024, 3, 28),
        ),
        Transaction(
            household_id=household_id,
            account_id=current.id,
            category_id=groceries.id,
            kind=TransactionKind.EXPENSE,
            amount_minor=FEBRUARY_MINOR,
            occurred_on=datetime.date(2024, 2, 15),
        ),
    ]
    db_session.add_all(rows)
    db_session.flush()

    return Ledger(current=current, savings=savings, home=home, rent=rent, groceries=groceries, salary=salary)


class TestSpendByCategory:
    """The grouping, the roll-up and what the period excludes."""

    def test_a_subcategory_rolls_up_into_its_parent(
        self, report_service: ReportService, household_a: HouseholdContext, ledger: Ledger
    ) -> None:
        """The COALESCE in the GROUP BY collapses Rent into Home."""
        report = report_service.spend_by_category(household=household_a, month=MONTH, depth=CategoryDepth.PARENT)

        by_name = {slice_.category_name: slice_.amount_minor for slice_ in report.slices}
        assert by_name == {
            "Home": HOME_TOTAL_MINOR,
            "Groceries": GROCERIES_MINOR,
            "Uncategorized": UNCATEGORIZED_MINOR,
        }
        assert report.total_minor == MARCH_EXPENSE_MINOR

    def test_leaf_depth_keeps_the_subcategory_apart(
        self, report_service: ReportService, household_a: HouseholdContext, ledger: Ledger
    ) -> None:
        """Without the roll-up, spending sits on the category it was filed under."""
        report = report_service.spend_by_category(household=household_a, month=MONTH, depth=CategoryDepth.LEAF)

        by_name = {slice_.category_name: slice_.amount_minor for slice_ in report.slices}
        assert by_name == {
            "Rent": RENT_MINOR,
            "Home": HOME_DIRECT_MINOR,
            "Groceries": GROCERIES_MINOR,
            "Uncategorized": UNCATEGORIZED_MINOR,
        }
        assert report.total_minor == MARCH_EXPENSE_MINOR

    def test_the_largest_slice_comes_first_and_shares_sum_to_one(
        self, report_service: ReportService, household_a: HouseholdContext, ledger: Ledger
    ) -> None:
        """The order is the ORDER BY, and the shares are the totals divided by the total."""
        report = report_service.spend_by_category(household=household_a, month=MONTH, depth=CategoryDepth.PARENT)

        assert [slice_.category_name for slice_ in report.slices] == ["Home", "Groceries", "Uncategorized"]
        assert report.slices[0].share == round(HOME_TOTAL_MINOR / MARCH_EXPENSE_MINOR, 4)
        assert sum(slice_.amount_minor for slice_ in report.slices) == MARCH_EXPENSE_MINOR

    def test_income_is_reported_separately_from_spending(
        self, report_service: ReportService, household_a: HouseholdContext, ledger: Ledger
    ) -> None:
        """The kind filter is the whole difference between the two breakdowns."""
        report = report_service.spend_by_category(
            household=household_a, month=MONTH, kind=TransactionKind.INCOME, depth=CategoryDepth.PARENT
        )

        assert [(slice_.category_name, slice_.amount_minor) for slice_ in report.slices] == [("Salary", SALARY_MINOR)]

    def test_the_transfer_is_in_no_breakdown(
        self, report_service: ReportService, household_a: HouseholdContext, ledger: Ledger
    ) -> None:
        """A transfer is neither spending nor income, so neither total can include it."""
        expenses = report_service.spend_by_category(household=household_a, month=MONTH)
        income = report_service.spend_by_category(household=household_a, month=MONTH, kind=TransactionKind.INCOME)

        assert expenses.total_minor == MARCH_EXPENSE_MINOR
        assert income.total_minor == SALARY_MINOR

    def test_february_is_outside_the_march_period(
        self, report_service: ReportService, household_a: HouseholdContext, ledger: Ledger
    ) -> None:
        """The date range is inclusive of the month and of nothing else."""
        february = report_service.spend_by_category(household=household_a, month="2024-02")

        assert february.total_minor == FEBRUARY_MINOR

    def test_another_household_sees_none_of_it(
        self, report_service: ReportService, household_b: HouseholdContext, ledger: Ledger
    ) -> None:
        """The household condition is in the WHERE clause of every aggregate."""
        report = report_service.spend_by_category(household=household_b, month=MONTH)

        assert report.slices == []
        assert report.total_minor == 0


class TestIncomeExpense:
    """Money in against money out, month by month."""

    def test_a_month_nets_income_against_expenses(
        self, report_service: ReportService, household_a: HouseholdContext, ledger: Ledger
    ) -> None:
        """The transfer moves money without changing either side."""
        report = report_service.income_expense(household=household_a, month_from=MONTH, month_to=MONTH)

        assert report.total_income_minor == SALARY_MINOR
        assert report.total_expense_minor == MARCH_EXPENSE_MINOR
        assert report.total_net_minor == SALARY_MINOR - MARCH_EXPENSE_MINOR

    def test_each_month_of_a_range_is_reported_on_its_own(
        self, report_service: ReportService, household_a: HouseholdContext, ledger: Ledger
    ) -> None:
        """February holds one expense and no income, March holds the rest."""
        report = report_service.income_expense(household=household_a, month_from="2024-02", month_to=MONTH)

        assert [(month.income_minor, month.expense_minor) for month in report.months] == [
            (0, FEBRUARY_MINOR),
            (SALARY_MINOR, MARCH_EXPENSE_MINOR),
        ]


class TestBudgetProgress:
    """Limits against the spending they cover."""

    @pytest.fixture
    def budgets(self, budget_service: BudgetService, household_a: HouseholdContext, ledger: Ledger) -> None:
        """Set a limit on the Home branch and a smaller one on Groceries.

        Args:
            budget_service: The budget service.
            household_a: The household to budget for.
            ledger: The seeded ledger.
        """
        budget_service.create_budget(
            household=household_a,
            budget_create=BudgetCreate(category_id=ledger.home.id, month=MONTH, limit_minor=50_000),
        )
        budget_service.create_budget(
            household=household_a,
            budget_create=BudgetCreate(category_id=ledger.groceries.id, month=MONTH, limit_minor=5_000),
        )

    def test_a_limit_on_a_parent_covers_its_subcategories(
        self, report_service: ReportService, household_a: HouseholdContext, budgets: None
    ) -> None:
        """The Home limit is measured against Home plus Rent."""
        report = report_service.budget_progress(household=household_a, month=MONTH)

        home = next(row for row in report.rows if row.category_name == "Home")
        assert home.spent_minor == HOME_TOTAL_MINOR
        assert home.remaining_minor == 50_000 - HOME_TOTAL_MINOR
        assert home.covers_subcategories is True
        assert home.is_over_budget is False

    def test_spending_past_a_limit_is_over_budget(
        self, report_service: ReportService, household_a: HouseholdContext, budgets: None
    ) -> None:
        """Groceries is the smaller limit and the larger spend."""
        report = report_service.budget_progress(household=household_a, month=MONTH)

        groceries = next(row for row in report.rows if row.category_name == "Groceries")
        assert groceries.spent_minor == GROCERIES_MINOR
        assert groceries.remaining_minor == 5_000 - GROCERIES_MINOR
        assert groceries.is_over_budget is True

    def test_spending_with_no_limit_is_reported_apart(
        self, report_service: ReportService, household_a: HouseholdContext, budgets: None
    ) -> None:
        """Every unit of spending is attributed once, or to nothing at all."""
        report = report_service.budget_progress(household=household_a, month=MONTH)

        assert report.total_limit_minor == 55_000
        assert report.total_spent_minor == HOME_TOTAL_MINOR + GROCERIES_MINOR
        assert report.unbudgeted_spend_minor == UNCATEGORIZED_MINOR


class TestMonthSummary:
    """The dashboard's own endpoint, over the same ledger."""

    def test_the_summary_totals_the_month(
        self, report_service: ReportService, household_a: HouseholdContext, ledger: Ledger
    ) -> None:
        """Income, expenses and their net, with the transfer in none of them."""
        summary = report_service.month_summary(household=household_a, month=MONTH)

        assert summary.income_minor == SALARY_MINOR
        assert summary.expense_minor == MARCH_EXPENSE_MINOR
        assert summary.net_minor == SALARY_MINOR - MARCH_EXPENSE_MINOR

    def test_the_summary_counts_every_row_of_the_month(
        self, report_service: ReportService, household_a: HouseholdContext, ledger: Ledger
    ) -> None:
        """The count is of the ledger, so the transfer is a row like any other."""
        summary = report_service.month_summary(household=household_a, month=MONTH)

        assert summary.transaction_count == 6

    def test_net_worth_is_the_sum_of_the_computed_balances(
        self, report_service: ReportService, household_a: HouseholdContext, ledger: Ledger
    ) -> None:
        """The two legs of the transfer cancel, so it cannot move net worth."""
        opening = CURRENT_OPENING_MINOR + SAVINGS_OPENING_MINOR
        spent = MARCH_EXPENSE_MINOR + FEBRUARY_MINOR

        summary = report_service.month_summary(household=household_a, month=MONTH)

        assert summary.net_worth_minor == opening + SALARY_MINOR - spent

    def test_the_top_categories_are_the_rolled_up_ones(
        self, report_service: ReportService, household_a: HouseholdContext, ledger: Ledger
    ) -> None:
        """The dashboard shows branches, not the leaves under them."""
        summary = report_service.month_summary(household=household_a, month=MONTH)

        assert [(slice_.category_name, slice_.amount_minor) for slice_ in summary.top_categories] == [
            ("Home", HOME_TOTAL_MINOR),
            ("Groceries", GROCERIES_MINOR),
            ("Uncategorized", UNCATEGORIZED_MINOR),
        ]

    def test_another_household_gets_its_own_empty_summary(
        self, report_service: ReportService, household_b: HouseholdContext, ledger: Ledger
    ) -> None:
        """None of the figures reach across the household boundary."""
        summary = report_service.month_summary(household=household_b, month=MONTH)

        assert (summary.income_minor, summary.expense_minor, summary.net_worth_minor) == (0, 0, 0)
        assert summary.transaction_count == 0
