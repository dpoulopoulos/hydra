import uuid
from datetime import date
from unittest.mock import MagicMock

import pytest

from app.exceptions import (
    BudgetCategoryKindError,
    BudgetExistsError,
    BudgetNotFoundError,
    BudgetOverlapError,
    CategoryNotFoundError,
    DuplicateBudgetCategoryError,
)
from app.models import (
    Budget,
    BudgetBulkUpsert,
    BudgetCopyRequest,
    BudgetCreate,
    BudgetEntry,
    BudgetUpdate,
    Category,
    CategoryKind,
    HouseholdContext,
    Message,
)
from app.services import BudgetService

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def make_category(
    name: str = "Food & Drink",
    kind: CategoryKind = CategoryKind.EXPENSE,
    parent_id: uuid.UUID | None = None,
) -> Category:
    """Build a category row for the tests."""
    return Category(household_id=HOUSEHOLD_ID, name=name, kind=kind, parent_id=parent_id)


def make_budget(
    category_id: uuid.UUID | None = None,
    limit_minor: int = 40_000,
    period_month: date = date(2026, 3, 1),
) -> Budget:
    """Build a budget row for the tests."""
    return Budget(
        household_id=HOUSEHOLD_ID,
        category_id=category_id or uuid.uuid4(),
        period_month=period_month,
        limit_minor=limit_minor,
    )


class TestCreateBudget:
    """Tests for create_budget."""

    def test_sets_a_limit(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        category = make_category()
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.first.side_effect = [category, None]
        mock_budget_service.session.exec.return_value.all.return_value = []

        result = mock_budget_service.create_budget(
            household=household_context,
            budget_create=BudgetCreate(category_id=category.id, month="2026-03", limit_minor=40_000),
        )

        assert result.limit_minor == 40_000
        assert result.month == "2026-03"
        mock_budget_service.session.commit.assert_called_once()

    def test_pins_the_month_to_its_first_day(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        category = make_category()
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.first.side_effect = [category, None]
        mock_budget_service.session.exec.return_value.all.return_value = []

        mock_budget_service.create_budget(
            household=household_context,
            budget_create=BudgetCreate(category_id=category.id, month="2026-03", limit_minor=1),
        )

        assert mock_budget_service.session.add.call_args.args[0].period_month == date(2026, 3, 1)

    def test_rejects_a_month_that_is_not_a_month(self) -> None:
        with pytest.raises(ValueError):
            BudgetCreate(category_id=uuid.uuid4(), month="2026-13", limit_minor=1)

    def test_rejects_a_full_date(self) -> None:
        """Storage keeps only the month, so a day would be silently dropped."""
        with pytest.raises(ValueError):
            BudgetCreate(category_id=uuid.uuid4(), month="2026-03-04", limit_minor=1)

    def test_rejects_a_negative_limit(self) -> None:
        with pytest.raises(ValueError):
            BudgetCreate(category_id=uuid.uuid4(), month="2026-03", limit_minor=-1)

    def test_allows_a_zero_limit(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        """A limit of nothing is a real choice: spend nothing here this month."""
        category = make_category()
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.first.side_effect = [category, None]
        mock_budget_service.session.exec.return_value.all.return_value = []

        result = mock_budget_service.create_budget(
            household=household_context,
            budget_create=BudgetCreate(category_id=category.id, month="2026-03", limit_minor=0),
        )

        assert result.limit_minor == 0

    def test_rejects_an_income_category(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        """A budget is a spending limit, so budgeting Salary is meaningless."""
        category = make_category(name="Salary", kind=CategoryKind.INCOME)
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.first.return_value = category

        with pytest.raises(BudgetCategoryKindError):
            mock_budget_service.create_budget(
                household=household_context,
                budget_create=BudgetCreate(category_id=category.id, month="2026-03", limit_minor=1),
            )

    def test_rejects_a_category_from_another_household(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.first.return_value = None

        with pytest.raises(CategoryNotFoundError):
            mock_budget_service.create_budget(
                household=household_context,
                budget_create=BudgetCreate(category_id=uuid.uuid4(), month="2026-03", limit_minor=1),
            )

    def test_rejects_a_second_limit_for_the_same_category_and_month(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        category = make_category()
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.first.side_effect = [
            category,
            make_budget(category_id=category.id),
        ]

        with pytest.raises(BudgetExistsError):
            mock_budget_service.create_budget(
                household=household_context,
                budget_create=BudgetCreate(category_id=category.id, month="2026-03", limit_minor=1),
            )

    def test_rejects_budgeting_a_child_when_its_parent_is_budgeted(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        """The parent limit already covers this spending, so both would double count it."""
        parent = make_category(name="Food & Drink")
        child = make_category(name="Groceries", parent_id=parent.id)
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.first.side_effect = [child, None, parent]
        mock_budget_service.session.exec.return_value.all.return_value = [
            make_budget(category_id=parent.id)
        ]

        with pytest.raises(BudgetOverlapError) as caught:
            mock_budget_service.create_budget(
                household=household_context,
                budget_create=BudgetCreate(category_id=child.id, month="2026-03", limit_minor=1),
            )

        assert caught.value.parent_name == "Food & Drink"
        assert caught.value.child_name == "Groceries"

    def test_rejects_budgeting_a_parent_when_a_child_is_budgeted(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        parent = make_category(name="Food & Drink")
        child = make_category(name="Groceries", parent_id=parent.id)
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.first.side_effect = [parent, None, child]
        mock_budget_service.session.exec.return_value.all.side_effect = [
            [child],
            [make_budget(category_id=child.id)],
        ]

        with pytest.raises(BudgetOverlapError) as caught:
            mock_budget_service.create_budget(
                household=household_context,
                budget_create=BudgetCreate(category_id=parent.id, month="2026-03", limit_minor=1),
            )

        assert caught.value.parent_name == "Food & Drink"
        assert caught.value.child_name == "Groceries"


class TestListBudgets:
    """Tests for list_budgets."""

    def test_returns_the_budgets_and_the_total(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.all.return_value = [
            make_budget(limit_minor=40_000),
            make_budget(limit_minor=15_000),
        ]

        result = mock_budget_service.list_budgets(household=household_context, month="2026-03")

        assert result.count == 2
        assert result.total_limit_minor == 55_000
        assert {budget.month for budget in result.data} == {"2026-03"}


class TestGetBudget:
    """Tests for get_budget."""

    def test_returns_the_budget(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        budget = make_budget()
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.first.return_value = budget

        assert mock_budget_service.get_budget(household=household_context, budget_id=budget.id).id == budget.id

    def test_a_budget_from_another_household_is_not_found(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.first.return_value = None

        with pytest.raises(BudgetNotFoundError):
            mock_budget_service.get_budget(household=household_context, budget_id=uuid.uuid4())


class TestUpdateBudget:
    """Tests for update_budget."""

    def test_changes_the_limit(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        budget = make_budget()
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.first.return_value = budget

        result = mock_budget_service.update_budget(
            household=household_context, budget_id=budget.id, budget_update=BudgetUpdate(limit_minor=50_000)
        )

        assert result.limit_minor == 50_000

    def test_the_category_and_month_cannot_be_changed(self) -> None:
        """They identify the budget, so changing either is setting a different one."""
        assert "category_id" not in BudgetUpdate.model_fields
        assert "month" not in BudgetUpdate.model_fields


class TestDeleteBudget:
    """Tests for delete_budget."""

    def test_removes_the_budget(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        budget = make_budget()
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.first.return_value = budget

        result = mock_budget_service.delete_budget(household=household_context, budget_id=budget.id)

        assert isinstance(result, Message)
        mock_budget_service.session.delete.assert_called_once_with(budget)


class TestBulkUpsert:
    """Tests for bulk_upsert."""

    def test_sets_a_whole_month_at_once(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        food = make_category(name="Food & Drink")
        transport = make_category(name="Transport")
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.all.side_effect = [
            [food, transport],
            [],
            [make_budget(category_id=food.id, limit_minor=40_000)],
        ]

        result = mock_budget_service.bulk_upsert(
            household=household_context,
            bulk=BudgetBulkUpsert(
                month="2026-03",
                entries=[
                    BudgetEntry(category_id=food.id, limit_minor=40_000),
                    BudgetEntry(category_id=transport.id, limit_minor=15_000),
                ],
            ),
        )

        assert mock_budget_service.session.add.call_count == 2
        assert result.count == 1

    def test_updates_a_limit_that_is_already_set(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        food = make_category(name="Food & Drink")
        existing = make_budget(category_id=food.id, limit_minor=40_000)
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.all.side_effect = [[food], [existing], [existing]]

        mock_budget_service.bulk_upsert(
            household=household_context,
            bulk=BudgetBulkUpsert(
                month="2026-03", entries=[BudgetEntry(category_id=food.id, limit_minor=45_000)]
            ),
        )

        assert existing.limit_minor == 45_000
        mock_budget_service.session.delete.assert_not_called()

    def test_removes_a_limit_left_out_of_the_set(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        """The set is the whole month, so an omission means "no longer budgeted"."""
        food = make_category(name="Food & Drink")
        dropped = make_budget(limit_minor=15_000)
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.all.side_effect = [[food], [dropped], []]

        mock_budget_service.bulk_upsert(
            household=household_context,
            bulk=BudgetBulkUpsert(
                month="2026-03", entries=[BudgetEntry(category_id=food.id, limit_minor=40_000)]
            ),
        )

        mock_budget_service.session.delete.assert_called_once_with(dropped)

    def test_rejects_the_same_category_twice(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        category_id = uuid.uuid4()

        with pytest.raises(DuplicateBudgetCategoryError):
            mock_budget_service.bulk_upsert(
                household=household_context,
                bulk=BudgetBulkUpsert(
                    month="2026-03",
                    entries=[
                        BudgetEntry(category_id=category_id, limit_minor=1),
                        BudgetEntry(category_id=category_id, limit_minor=2),
                    ],
                ),
            )

    def test_validates_every_category_in_one_query(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        """Otherwise a month of budgets would validate one query at a time."""
        food = make_category(name="Food & Drink")
        transport = make_category(name="Transport")
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.all.side_effect = [
            [food, transport],
            [],
            [],
        ]

        mock_budget_service.bulk_upsert(
            household=household_context,
            bulk=BudgetBulkUpsert(
                month="2026-03",
                entries=[
                    BudgetEntry(category_id=food.id, limit_minor=1),
                    BudgetEntry(category_id=transport.id, limit_minor=2),
                ],
            ),
        )

        statements = [str(call.args[0]) for call in mock_budget_service.session.exec.call_args_list]
        assert sum("category.id IN" in statement for statement in statements) == 1

    def test_rejects_a_category_from_another_household(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.all.return_value = []

        with pytest.raises(CategoryNotFoundError):
            mock_budget_service.bulk_upsert(
                household=household_context,
                bulk=BudgetBulkUpsert(
                    month="2026-03", entries=[BudgetEntry(category_id=uuid.uuid4(), limit_minor=1)]
                ),
            )

    def test_rejects_a_set_containing_a_parent_and_its_child(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        parent = make_category(name="Food & Drink")
        child = make_category(name="Groceries", parent_id=parent.id)
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.all.return_value = [parent, child]

        with pytest.raises(BudgetOverlapError):
            mock_budget_service.bulk_upsert(
                household=household_context,
                bulk=BudgetBulkUpsert(
                    month="2026-03",
                    entries=[
                        BudgetEntry(category_id=parent.id, limit_minor=1),
                        BudgetEntry(category_id=child.id, limit_minor=2),
                    ],
                ),
            )


class TestCopyMonth:
    """Tests for copy_month."""

    def test_copies_the_limits_forward(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        source = [make_budget(limit_minor=40_000), make_budget(limit_minor=15_000)]
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.all.side_effect = [source, [], []]

        mock_budget_service.copy_month(
            household=household_context,
            copy_request=BudgetCopyRequest(from_month="2026-03", to_month="2026-04"),
        )

        added = [call.args[0] for call in mock_budget_service.session.add.call_args_list]
        assert len(added) == 2
        assert all(budget.period_month == date(2026, 4, 1) for budget in added)
        assert {budget.limit_minor for budget in added} == {40_000, 15_000}

    def test_refuses_to_overwrite_by_default(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.all.side_effect = [
            [make_budget()],
            [make_budget()],
        ]

        with pytest.raises(BudgetExistsError):
            mock_budget_service.copy_month(
                household=household_context,
                copy_request=BudgetCopyRequest(from_month="2026-03", to_month="2026-04"),
            )

    def test_overwrites_when_asked(
        self, mock_budget_service: BudgetService, household_context: HouseholdContext
    ) -> None:
        category_id = uuid.uuid4()
        source = make_budget(category_id=category_id, limit_minor=45_000)
        target = make_budget(category_id=category_id, limit_minor=40_000, period_month=date(2026, 4, 1))
        mock_budget_service.session.exec = MagicMock()
        mock_budget_service.session.exec.return_value.all.side_effect = [[source], [target], [target]]

        mock_budget_service.copy_month(
            household=household_context,
            copy_request=BudgetCopyRequest(from_month="2026-03", to_month="2026-04", overwrite=True),
        )

        assert target.limit_minor == 45_000
