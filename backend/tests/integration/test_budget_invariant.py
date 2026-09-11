"""The budget invariant, re-checked through the report after every write path.

``ReportService.budget_progress`` attributes a parent category's whole branch
to that parent's limit. That is only sound because a month can never hold a
limit on both a parent and one of its subcategories, which the report states as
an assumption and ``BudgetService`` upholds from five separate write paths.

Against a mocked session each write path is only ever checked against the guard
it happens to call, and the report is only ever checked against figures a mock
was told to return, so nothing joins the two. Issue #10 is what that costs:
``copy_month`` wrote a month the report cannot represent, and the report
answered with double the real spending and a negative unbudgeted total.

Every test here runs one write path against a real database and then runs the
report over what it wrote. The invariant is asserted in the report's own terms,
so a guard that stops working is caught by the figure it was protecting rather
than by a restatement of the guard.
"""

import datetime
import uuid

import pytest
from sqlmodel import Session

from app.exceptions import BudgetExistsError, BudgetOverlapError
from app.models import (
    Budget,
    BudgetBulkUpsert,
    BudgetCopyRequest,
    BudgetCreate,
    BudgetEntry,
    BudgetUpdate,
    Category,
    HouseholdContext,
    Transaction,
    TransactionKind,
)
from app.models.fields import month_start
from app.repositories import BudgetRepository
from app.services import BudgetService, ReportService
from tests.integration.conftest import make_account, make_category

MONTH = "2024-03"
SOURCE_MONTH = "2024-02"

# What the seeded ledger spends, hand computed so the assertions are reconciled
# against a number a person wrote down rather than against the report's output.
RENT_MINOR = 30_000
UTILITIES_MINOR = 12_000
HOME_DIRECT_MINOR = 5_000
GROCERIES_MINOR = 8_000
TRAVEL_MINOR = 7_000

HOME_BRANCH_MINOR = RENT_MINOR + UTILITIES_MINOR + HOME_DIRECT_MINOR
MARCH_EXPENSE_MINOR = HOME_BRANCH_MINOR + GROCERIES_MINOR + TRAVEL_MINOR

FEBRUARY_RENT_MINOR = 20_000
FEBRUARY_GROCERIES_MINOR = 4_000
FEBRUARY_EXPENSE_MINOR = FEBRUARY_RENT_MINOR + FEBRUARY_GROCERIES_MINOR

LIMIT_MINOR = 50_000


class Tree:
    """The seeded categories, so a test can name the ones it budgets."""

    def __init__(self, home: Category, rent: Category, utilities: Category, groceries: Category, travel: Category):
        """Hold the categories of the seeded household.

        Args:
            home: The parent category the Rent and Utilities spending files under.
            rent: A subcategory of Home.
            utilities: The other subcategory of Home.
            groceries: A top level category with no subcategories.
            travel: A top level category the tests leave unbudgeted.
        """
        self.home = home
        self.rent = rent
        self.utilities = utilities
        self.groceries = groceries
        self.travel = travel


@pytest.fixture
def tree(db_session: Session, household_a: HouseholdContext) -> Tree:
    """Seed two months of spending across a two level category tree.

    March holds spending on both subcategories of Home, on Home itself, and on
    two top level categories. February holds a smaller ledger, so a month
    copied onto another is measured against spending of its own.

    Args:
        db_session: The database session.
        household_a: The household to seed.

    Returns:
        The categories the seeded rows point at.
    """
    household_id = household_a.household_id
    account = make_account(db_session, household_id=household_id, name="Current")

    home = make_category(db_session, household_id=household_id, name="Home")
    rent = make_category(db_session, household_id=household_id, name="Rent", parent_id=home.id)
    utilities = make_category(db_session, household_id=household_id, name="Utilities", parent_id=home.id)
    groceries = make_category(db_session, household_id=household_id, name="Groceries")
    travel = make_category(db_session, household_id=household_id, name="Travel")

    spending = [
        (rent.id, RENT_MINOR, datetime.date(2024, 3, 1)),
        (utilities.id, UTILITIES_MINOR, datetime.date(2024, 3, 4)),
        (home.id, HOME_DIRECT_MINOR, datetime.date(2024, 3, 9)),
        (groceries.id, GROCERIES_MINOR, datetime.date(2024, 3, 12)),
        (travel.id, TRAVEL_MINOR, datetime.date(2024, 3, 20)),
        (rent.id, FEBRUARY_RENT_MINOR, datetime.date(2024, 2, 1)),
        (groceries.id, FEBRUARY_GROCERIES_MINOR, datetime.date(2024, 2, 11)),
    ]
    db_session.add_all(
        Transaction(
            household_id=household_id,
            account_id=account.id,
            category_id=category_id,
            kind=TransactionKind.EXPENSE,
            amount_minor=amount_minor,
            occurred_on=occurred_on,
        )
        for category_id, amount_minor, occurred_on in spending
    )
    db_session.flush()

    return Tree(home=home, rent=rent, utilities=utilities, groceries=groceries, travel=travel)


def budgeted_names(budget_repository: BudgetRepository, household: HouseholdContext, month: str) -> set[str]:
    """Read back the names of the categories budgeted in a month.

    Args:
        budget_repository: The budget repository.
        household: The household context.
        month: The month, in "YYYY-MM" form.

    Returns:
        The name of every category holding a limit that month.
    """
    rows = budget_repository.list_with_categories(household_id=household.household_id, period_month=month_start(month))
    return {category.name for _, category in rows}


def assert_invariant_holds(
    report_service: ReportService,
    budget_repository: BudgetRepository,
    household: HouseholdContext,
    month: str,
    expense_total_minor: int,
) -> None:
    """Assert the month is one the budget report can represent.

    Three things have to hold together. No month may budget both a parent and
    one of its subcategories, because the parent's row already counts the
    child's spending. No unit of spending may be attributed twice, which shows
    up as a negative unbudgeted remainder. And what the report attributes plus
    what it leaves unbudgeted has to be the month's actual expenses, no more
    and no less.

    Args:
        report_service: The report service.
        budget_repository: The budget repository.
        household: The household context.
        month: The month, in "YYYY-MM" form.
        expense_total_minor: What the ledger actually spends that month.
    """
    rows = budget_repository.list_with_categories(household_id=household.household_id, period_month=month_start(month))
    budgeted_ids = {category.id for _, category in rows}
    overlapping = sorted(category.name for _, category in rows if category.parent_id in budgeted_ids)

    assert overlapping == [], f"{month} budgets a parent and its subcategory together: {overlapping}"

    report = report_service.budget_progress(household=household, month=month)

    assert report.unbudgeted_spend_minor >= 0
    assert report.total_spent_minor <= expense_total_minor
    assert report.total_spent_minor + report.unbudgeted_spend_minor == expense_total_minor


def budget_directly(session: Session, household: HouseholdContext, category_id: uuid.UUID, month: str) -> Budget:
    """Write a limit straight to the table, bypassing the service guards.

    A month written before the overlap check existed looks like this, and a
    copy of it must not spread what it holds.

    Args:
        session: The database session.
        household: The household context.
        category_id: The category to budget.
        month: The month, in "YYYY-MM" form.

    Returns:
        The stored budget.
    """
    budget = Budget(
        household_id=household.household_id,
        category_id=category_id,
        period_month=month_start(month),
        limit_minor=LIMIT_MINOR,
    )
    session.add(budget)
    session.flush()
    return budget


class TestCreateBudget:
    """One limit at a time, against the month the report reads back."""

    def test_a_month_budgeted_by_its_parents_attributes_every_expense(
        self,
        budget_service: BudgetService,
        report_service: ReportService,
        budget_repository: BudgetRepository,
        household_a: HouseholdContext,
        tree: Tree,
    ) -> None:
        """Budgeting every branch leaves nothing unbudgeted and nothing counted twice."""
        for category in (tree.home, tree.groceries, tree.travel):
            budget_service.create_budget(
                household=household_a,
                budget_create=BudgetCreate(category_id=category.id, month=MONTH, limit_minor=LIMIT_MINOR),
            )

        report = report_service.budget_progress(household=household_a, month=MONTH)

        assert report.total_spent_minor == MARCH_EXPENSE_MINOR
        assert report.unbudgeted_spend_minor == 0
        assert_invariant_holds(
            report_service, budget_repository, household_a, MONTH, expense_total_minor=MARCH_EXPENSE_MINOR
        )

    def test_a_subcategory_is_refused_once_its_parent_is_budgeted(
        self,
        budget_service: BudgetService,
        report_service: ReportService,
        budget_repository: BudgetRepository,
        household_a: HouseholdContext,
        tree: Tree,
    ) -> None:
        """The refused write leaves the month exactly as the report can read it."""
        budget_service.create_budget(
            household=household_a,
            budget_create=BudgetCreate(category_id=tree.home.id, month=MONTH, limit_minor=LIMIT_MINOR),
        )

        with pytest.raises(BudgetOverlapError):
            budget_service.create_budget(
                household=household_a,
                budget_create=BudgetCreate(category_id=tree.rent.id, month=MONTH, limit_minor=LIMIT_MINOR),
            )

        assert budgeted_names(budget_repository, household_a, MONTH) == {"Home"}
        assert_invariant_holds(
            report_service, budget_repository, household_a, MONTH, expense_total_minor=MARCH_EXPENSE_MINOR
        )

    def test_a_parent_is_refused_once_one_of_its_subcategories_is_budgeted(
        self,
        budget_service: BudgetService,
        report_service: ReportService,
        budget_repository: BudgetRepository,
        household_a: HouseholdContext,
        tree: Tree,
    ) -> None:
        """The check reads down the tree as well as up it."""
        budget_service.create_budget(
            household=household_a,
            budget_create=BudgetCreate(category_id=tree.utilities.id, month=MONTH, limit_minor=LIMIT_MINOR),
        )

        with pytest.raises(BudgetOverlapError):
            budget_service.create_budget(
                household=household_a,
                budget_create=BudgetCreate(category_id=tree.home.id, month=MONTH, limit_minor=LIMIT_MINOR),
            )

        assert budgeted_names(budget_repository, household_a, MONTH) == {"Utilities"}
        assert_invariant_holds(
            report_service, budget_repository, household_a, MONTH, expense_total_minor=MARCH_EXPENSE_MINOR
        )


class TestBulkUpsert:
    """A whole month saved at once, which is what the budgets screen sends."""

    def test_a_month_of_subcategory_limits_attributes_each_leaf_once(
        self,
        budget_service: BudgetService,
        report_service: ReportService,
        budget_repository: BudgetRepository,
        household_a: HouseholdContext,
        tree: Tree,
    ) -> None:
        """Limits on the leaves cover the leaves, and the parent's own spending is not theirs."""
        budget_service.bulk_upsert(
            household=household_a,
            bulk=BudgetBulkUpsert(
                month=MONTH,
                entries=[
                    BudgetEntry(category_id=tree.rent.id, limit_minor=LIMIT_MINOR),
                    BudgetEntry(category_id=tree.utilities.id, limit_minor=LIMIT_MINOR),
                    BudgetEntry(category_id=tree.groceries.id, limit_minor=LIMIT_MINOR),
                ],
            ),
        )

        report = report_service.budget_progress(household=household_a, month=MONTH)

        assert report.total_spent_minor == RENT_MINOR + UTILITIES_MINOR + GROCERIES_MINOR
        assert report.unbudgeted_spend_minor == HOME_DIRECT_MINOR + TRAVEL_MINOR
        assert_invariant_holds(
            report_service, budget_repository, household_a, MONTH, expense_total_minor=MARCH_EXPENSE_MINOR
        )

    def test_a_set_holding_a_parent_and_its_child_is_refused_whole(
        self,
        budget_service: BudgetService,
        report_service: ReportService,
        budget_repository: BudgetRepository,
        household_a: HouseholdContext,
        tree: Tree,
    ) -> None:
        """No entry of a rejected set is written, so the month keeps what it had."""
        budget_service.bulk_upsert(
            household=household_a,
            bulk=BudgetBulkUpsert(
                month=MONTH, entries=[BudgetEntry(category_id=tree.home.id, limit_minor=LIMIT_MINOR)]
            ),
        )

        with pytest.raises(BudgetOverlapError):
            budget_service.bulk_upsert(
                household=household_a,
                bulk=BudgetBulkUpsert(
                    month=MONTH,
                    entries=[
                        BudgetEntry(category_id=tree.home.id, limit_minor=LIMIT_MINOR),
                        BudgetEntry(category_id=tree.rent.id, limit_minor=LIMIT_MINOR),
                    ],
                ),
            )

        assert budgeted_names(budget_repository, household_a, MONTH) == {"Home"}
        assert_invariant_holds(
            report_service, budget_repository, household_a, MONTH, expense_total_minor=MARCH_EXPENSE_MINOR
        )

    def test_replacing_a_parent_limit_with_its_childrens_leaves_no_overlap(
        self,
        budget_service: BudgetService,
        report_service: ReportService,
        budget_repository: BudgetRepository,
        household_a: HouseholdContext,
        tree: Tree,
    ) -> None:
        """A category left out of the set loses its limit rather than surviving next to the new ones."""
        budget_service.bulk_upsert(
            household=household_a,
            bulk=BudgetBulkUpsert(
                month=MONTH, entries=[BudgetEntry(category_id=tree.home.id, limit_minor=LIMIT_MINOR)]
            ),
        )

        budget_service.bulk_upsert(
            household=household_a,
            bulk=BudgetBulkUpsert(
                month=MONTH,
                entries=[
                    BudgetEntry(category_id=tree.rent.id, limit_minor=LIMIT_MINOR),
                    BudgetEntry(category_id=tree.utilities.id, limit_minor=LIMIT_MINOR),
                ],
            ),
        )

        assert budgeted_names(budget_repository, household_a, MONTH) == {"Rent", "Utilities"}
        assert_invariant_holds(
            report_service, budget_repository, household_a, MONTH, expense_total_minor=MARCH_EXPENSE_MINOR
        )


class TestCopyMonth:
    """The path of issue #10: a month written from another month's limits."""

    def test_copying_a_parent_limit_over_subcategory_limits_replaces_them(
        self,
        budget_service: BudgetService,
        report_service: ReportService,
        budget_repository: BudgetRepository,
        household_a: HouseholdContext,
        tree: Tree,
    ) -> None:
        """This is issue #10: the target kept its children and the report counted Home twice."""
        budget_service.create_budget(
            household=household_a,
            budget_create=BudgetCreate(category_id=tree.home.id, month=SOURCE_MONTH, limit_minor=LIMIT_MINOR),
        )
        budget_service.bulk_upsert(
            household=household_a,
            bulk=BudgetBulkUpsert(
                month=MONTH,
                entries=[
                    BudgetEntry(category_id=tree.rent.id, limit_minor=LIMIT_MINOR),
                    BudgetEntry(category_id=tree.utilities.id, limit_minor=LIMIT_MINOR),
                ],
            ),
        )

        budget_service.copy_month(
            household=household_a,
            copy_request=BudgetCopyRequest(from_month=SOURCE_MONTH, to_month=MONTH, overwrite=True),
        )

        report = report_service.budget_progress(household=household_a, month=MONTH)

        assert budgeted_names(budget_repository, household_a, MONTH) == {"Home"}
        assert report.total_spent_minor == HOME_BRANCH_MINOR
        assert report.unbudgeted_spend_minor == GROCERIES_MINOR + TRAVEL_MINOR
        assert_invariant_holds(
            report_service, budget_repository, household_a, MONTH, expense_total_minor=MARCH_EXPENSE_MINOR
        )

    def test_copying_subcategory_limits_over_a_parent_limit_replaces_it(
        self,
        budget_service: BudgetService,
        report_service: ReportService,
        budget_repository: BudgetRepository,
        household_a: HouseholdContext,
        tree: Tree,
    ) -> None:
        """The same clash the other way round, which the overwrite has to resolve the same way."""
        budget_service.bulk_upsert(
            household=household_a,
            bulk=BudgetBulkUpsert(
                month=SOURCE_MONTH,
                entries=[
                    BudgetEntry(category_id=tree.rent.id, limit_minor=LIMIT_MINOR),
                    BudgetEntry(category_id=tree.utilities.id, limit_minor=LIMIT_MINOR),
                ],
            ),
        )
        budget_service.create_budget(
            household=household_a,
            budget_create=BudgetCreate(category_id=tree.home.id, month=MONTH, limit_minor=LIMIT_MINOR),
        )

        budget_service.copy_month(
            household=household_a,
            copy_request=BudgetCopyRequest(from_month=SOURCE_MONTH, to_month=MONTH, overwrite=True),
        )

        assert budgeted_names(budget_repository, household_a, MONTH) == {"Rent", "Utilities"}
        assert_invariant_holds(
            report_service, budget_repository, household_a, MONTH, expense_total_minor=MARCH_EXPENSE_MINOR
        )

    def test_a_source_month_that_overlaps_is_not_copied_anywhere(
        self,
        db_session: Session,
        budget_service: BudgetService,
        report_service: ReportService,
        budget_repository: BudgetRepository,
        household_a: HouseholdContext,
        tree: Tree,
    ) -> None:
        """A month predating the guard is unsound already; copying it must not make a second one."""
        budget_directly(db_session, household_a, category_id=tree.home.id, month=SOURCE_MONTH)
        budget_directly(db_session, household_a, category_id=tree.rent.id, month=SOURCE_MONTH)

        with pytest.raises(BudgetOverlapError):
            budget_service.copy_month(
                household=household_a,
                copy_request=BudgetCopyRequest(from_month=SOURCE_MONTH, to_month=MONTH, overwrite=True),
            )

        assert budgeted_names(budget_repository, household_a, MONTH) == set()
        assert_invariant_holds(
            report_service, budget_repository, household_a, MONTH, expense_total_minor=MARCH_EXPENSE_MINOR
        )

    def test_a_target_month_with_limits_is_left_alone_without_overwrite(
        self,
        budget_service: BudgetService,
        report_service: ReportService,
        budget_repository: BudgetRepository,
        household_a: HouseholdContext,
        tree: Tree,
    ) -> None:
        """Refusing rather than merging is what keeps the two months' limits from meeting."""
        budget_service.create_budget(
            household=household_a,
            budget_create=BudgetCreate(category_id=tree.home.id, month=SOURCE_MONTH, limit_minor=LIMIT_MINOR),
        )
        budget_service.create_budget(
            household=household_a,
            budget_create=BudgetCreate(category_id=tree.rent.id, month=MONTH, limit_minor=LIMIT_MINOR),
        )

        with pytest.raises(BudgetExistsError):
            budget_service.copy_month(
                household=household_a,
                copy_request=BudgetCopyRequest(from_month=SOURCE_MONTH, to_month=MONTH),
            )

        assert budgeted_names(budget_repository, household_a, MONTH) == {"Rent"}
        assert_invariant_holds(
            report_service, budget_repository, household_a, MONTH, expense_total_minor=MARCH_EXPENSE_MINOR
        )


class TestUpdateBudget:
    """Changing a limit, which moves no spending between rows."""

    def test_raising_a_limit_changes_the_remainder_and_nothing_else(
        self,
        budget_service: BudgetService,
        report_service: ReportService,
        budget_repository: BudgetRepository,
        household_a: HouseholdContext,
        tree: Tree,
    ) -> None:
        """The category and month are not changeable, so the attribution cannot move."""
        created = budget_service.create_budget(
            household=household_a,
            budget_create=BudgetCreate(category_id=tree.home.id, month=MONTH, limit_minor=LIMIT_MINOR),
        )

        budget_service.update_budget(
            household=household_a, budget_id=created.id, budget_update=BudgetUpdate(limit_minor=LIMIT_MINOR * 2)
        )

        report = report_service.budget_progress(household=household_a, month=MONTH)

        assert report.total_limit_minor == LIMIT_MINOR * 2
        assert report.total_spent_minor == HOME_BRANCH_MINOR
        assert_invariant_holds(
            report_service, budget_repository, household_a, MONTH, expense_total_minor=MARCH_EXPENSE_MINOR
        )


class TestDeleteBudget:
    """Removing a limit, which hands its spending back to the unbudgeted total."""

    def test_removing_a_parent_limit_returns_its_branch_to_the_unbudgeted_total(
        self,
        budget_service: BudgetService,
        report_service: ReportService,
        budget_repository: BudgetRepository,
        household_a: HouseholdContext,
        tree: Tree,
    ) -> None:
        """The spending the parent covered is unattributed, not lost and not counted twice."""
        created = budget_service.create_budget(
            household=household_a,
            budget_create=BudgetCreate(category_id=tree.home.id, month=MONTH, limit_minor=LIMIT_MINOR),
        )

        budget_service.delete_budget(household=household_a, budget_id=created.id)

        report = report_service.budget_progress(household=household_a, month=MONTH)

        assert report.rows == []
        assert report.total_spent_minor == 0
        assert report.unbudgeted_spend_minor == MARCH_EXPENSE_MINOR
        assert_invariant_holds(
            report_service, budget_repository, household_a, MONTH, expense_total_minor=MARCH_EXPENSE_MINOR
        )

    def test_the_source_month_of_a_copy_is_reported_on_its_own_spending(
        self,
        budget_service: BudgetService,
        report_service: ReportService,
        budget_repository: BudgetRepository,
        household_a: HouseholdContext,
        tree: Tree,
    ) -> None:
        """Copying limits forward leaves the month they came from untouched."""
        budget_service.create_budget(
            household=household_a,
            budget_create=BudgetCreate(category_id=tree.home.id, month=SOURCE_MONTH, limit_minor=LIMIT_MINOR),
        )

        budget_service.copy_month(
            household=household_a,
            copy_request=BudgetCopyRequest(from_month=SOURCE_MONTH, to_month=MONTH, overwrite=True),
        )

        assert_invariant_holds(
            report_service, budget_repository, household_a, SOURCE_MONTH, expense_total_minor=FEBRUARY_EXPENSE_MINOR
        )
        assert_invariant_holds(
            report_service, budget_repository, household_a, MONTH, expense_total_minor=MARCH_EXPENSE_MINOR
        )
