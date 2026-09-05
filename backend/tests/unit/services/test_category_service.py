import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.data import DEFAULT_CATEGORIES
from app.exceptions import (
    CategoryDepthExceededError,
    CategoryExistsError,
    CategoryInUseError,
    CategoryKindMismatchError,
    CategoryNotFoundError,
    CategorySelfParentError,
    SystemCategoryError,
)
from app.models import (
    Category,
    CategoryCreate,
    CategoryKind,
    CategoryUpdate,
    HouseholdContext,
    Message,
)
from app.services import CategoryService

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def make_category(
    name: str = "Food & Drink",
    parent_id: uuid.UUID | None = None,
    kind: CategoryKind = CategoryKind.EXPENSE,
    is_system: bool = False,
    archived: bool = False,
    archived_with_parent: bool = False,
) -> Category:
    """Build a category row for the tests."""
    category = Category(
        household_id=HOUSEHOLD_ID,
        name=name,
        kind=kind,
        parent_id=parent_id,
        is_system=is_system,
        archived_at=datetime.now(UTC) if archived else None,
        archived_with_parent=archived_with_parent,
    )
    return category


class TestSeedDefaults:
    """Tests for seed_defaults."""

    def test_creates_the_whole_tree(self, mock_category_service: CategoryService) -> None:
        mock_category_service.seed_defaults(household_id=HOUSEHOLD_ID)

        added = [call.args[0] for call in mock_category_service.session.add.call_args_list]
        expected = len(DEFAULT_CATEGORIES) + sum(len(default.children) for default in DEFAULT_CATEGORIES)
        assert len(added) == expected

    def test_does_not_commit(self, mock_category_service: CategoryService) -> None:
        """The caller owns the transaction, so a household is never seen without its categories."""
        mock_category_service.seed_defaults(household_id=HOUSEHOLD_ID)

        mock_category_service.session.commit.assert_not_called()
        mock_category_service.session.flush.assert_called_once()

    def test_children_point_at_their_parent(self, mock_category_service: CategoryService) -> None:
        mock_category_service.seed_defaults(household_id=HOUSEHOLD_ID)

        added = [call.args[0] for call in mock_category_service.session.add.call_args_list]
        parents = {category.id for category in added if category.parent_id is None}
        children = [category for category in added if category.parent_id is not None]

        assert children
        assert all(child.parent_id in parents for child in children)

    def test_the_income_branch_is_marked_as_income(self, mock_category_service: CategoryService) -> None:
        mock_category_service.seed_defaults(household_id=HOUSEHOLD_ID)

        added = [call.args[0] for call in mock_category_service.session.add.call_args_list]
        income = [category for category in added if category.kind is CategoryKind.INCOME]

        assert {category.name for category in income} >= {"Income", "Salary", "Bonus"}

    def test_the_fallback_branch_is_marked_as_system(self, mock_category_service: CategoryService) -> None:
        mock_category_service.seed_defaults(household_id=HOUSEHOLD_ID)

        added = [call.args[0] for call in mock_category_service.session.add.call_args_list]
        system = [category for category in added if category.is_system]

        assert {category.name for category in system} == {"Other", "Uncategorized"}

    def test_every_category_belongs_to_the_household(self, mock_category_service: CategoryService) -> None:
        mock_category_service.seed_defaults(household_id=HOUSEHOLD_ID)

        added = [call.args[0] for call in mock_category_service.session.add.call_args_list]
        assert all(category.household_id == HOUSEHOLD_ID for category in added)


class TestCreateCategory:
    """Tests for create_category."""

    def test_creates_a_top_level_category(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.return_value = None

        result = mock_category_service.create_category(
            household=household_context, category_create=CategoryCreate(name="Boats")
        )

        assert result.name == "Boats"
        assert result.household_id == household_context.household_id
        mock_category_service.session.commit.assert_called_once()

    def test_creates_a_subcategory(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        parent = make_category()
        mock_category_service.session.exec = MagicMock()
        # First call resolves the parent, second checks the name is free.
        mock_category_service.session.exec.return_value.first.side_effect = [parent, None]

        result = mock_category_service.create_category(
            household=household_context, category_create=CategoryCreate(name="Groceries", parent_id=parent.id)
        )

        assert result.parent_id == parent.id

    def test_rejects_a_missing_parent(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.return_value = None

        with pytest.raises(CategoryNotFoundError):
            mock_category_service.create_category(
                household=household_context,
                category_create=CategoryCreate(name="Groceries", parent_id=uuid.uuid4()),
            )

    def test_rejects_a_third_level(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        child = make_category(name="Groceries", parent_id=uuid.uuid4())
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.return_value = child

        with pytest.raises(CategoryDepthExceededError):
            mock_category_service.create_category(
                household=household_context,
                category_create=CategoryCreate(name="Apples", parent_id=child.id),
            )

    def test_rejects_a_kind_that_differs_from_the_parent(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        parent = make_category(name="Income", kind=CategoryKind.INCOME)
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.return_value = parent

        with pytest.raises(CategoryKindMismatchError):
            mock_category_service.create_category(
                household=household_context,
                category_create=CategoryCreate(
                    name="Groceries", parent_id=parent.id, kind=CategoryKind.EXPENSE
                ),
            )

    def test_rejects_a_duplicate_sibling_name(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.return_value = make_category()

        with pytest.raises(CategoryExistsError):
            mock_category_service.create_category(
                household=household_context, category_create=CategoryCreate(name="Food & Drink")
            )


class TestGetCategoryTree:
    """Tests for get_category_tree."""

    def test_nests_children_under_their_parent(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        parent = make_category()
        other = make_category(name="Transport")
        child = make_category(name="Groceries", parent_id=parent.id)
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.all.return_value = [parent, other, child]

        result = mock_category_service.get_category_tree(household=household_context)

        assert result.count == 3
        assert [node.name for node in result.data] == ["Food & Drink", "Transport"]
        assert [subcategory.name for subcategory in result.data[0].children] == ["Groceries"]
        assert result.data[1].children == []

    def test_drops_a_child_whose_parent_is_filtered_out(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        """A subcategory of an archived parent must not surface as a root."""
        child = make_category(name="Groceries", parent_id=uuid.uuid4())
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.all.return_value = [child]

        result = mock_category_service.get_category_tree(household=household_context)

        assert result.data == []


class TestGetCategory:
    """Tests for get_category."""

    def test_returns_the_category(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        category = make_category()
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.return_value = category

        assert mock_category_service.get_category(
            household=household_context, category_id=category.id
        ).id == category.id

    def test_a_category_from_another_household_is_not_found(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        """The repository scopes the query, so a foreign ID simply is not there."""
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.return_value = None

        with pytest.raises(CategoryNotFoundError):
            mock_category_service.get_category(household=household_context, category_id=uuid.uuid4())


class TestUpdateCategory:
    """Tests for update_category."""

    def test_renames_a_category(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        category = make_category()
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.side_effect = [category, None]

        result = mock_category_service.update_category(
            household=household_context, category_id=category.id, category_update=CategoryUpdate(name="Eating")
        )

        assert result.name == "Eating"
        mock_category_service.session.commit.assert_called_once()

    def test_archives_a_category(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        category = make_category(name="Groceries", parent_id=uuid.uuid4())
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.return_value = category

        result = mock_category_service.update_category(
            household=household_context,
            category_id=category.id,
            category_update=CategoryUpdate(is_archived=True),
        )

        assert result.archived_at is not None

    def test_restores_a_category(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        category = make_category(name="Groceries", parent_id=uuid.uuid4(), archived=True)
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.return_value = category

        result = mock_category_service.update_category(
            household=household_context,
            category_id=category.id,
            category_update=CategoryUpdate(is_archived=False),
        )

        assert result.archived_at is None

    def test_archiving_a_parent_archives_its_children(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        """Otherwise new spending could still land in a branch the user retired."""
        parent = make_category()
        child = make_category(name="Groceries", parent_id=parent.id)
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.return_value = parent
        mock_category_service.session.exec.return_value.all.return_value = [child]

        mock_category_service.update_category(
            household=household_context,
            category_id=parent.id,
            category_update=CategoryUpdate(is_archived=True),
        )

        assert child.archived_at == parent.archived_at

    def test_archiving_a_parent_marks_the_children_the_cascade_took_down(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        """The mark is what lets a later restore put back this branch and nothing else."""
        parent = make_category()
        child = make_category(name="Groceries", parent_id=parent.id)
        already_archived = make_category(name="Takeaway", parent_id=parent.id, archived=True)
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.return_value = parent
        mock_category_service.session.exec.return_value.all.return_value = [child, already_archived]

        mock_category_service.update_category(
            household=household_context,
            category_id=parent.id,
            category_update=CategoryUpdate(is_archived=True),
        )

        assert child.archived_with_parent is True
        assert already_archived.archived_with_parent is False

    def test_restoring_a_parent_restores_the_children_it_archived(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        """Otherwise the parent comes back with nothing under it and is close to unusable."""
        parent = make_category(archived=True)
        child = make_category(name="Groceries", parent_id=parent.id, archived=True, archived_with_parent=True)
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.return_value = parent
        mock_category_service.session.exec.return_value.all.return_value = [child]

        result = mock_category_service.update_category(
            household=household_context,
            category_id=parent.id,
            category_update=CategoryUpdate(is_archived=False),
        )

        assert result.archived_at is None
        assert child.archived_at is None
        assert child.archived_with_parent is False

    def test_restoring_a_parent_leaves_a_separately_archived_child_alone(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        """Retiring that child was its own decision, so restoring the parent must not undo it."""
        parent = make_category(archived=True)
        child = make_category(name="Takeaway", parent_id=parent.id, archived=True)
        archived_at = child.archived_at
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.return_value = parent
        mock_category_service.session.exec.return_value.all.return_value = [child]

        mock_category_service.update_category(
            household=household_context,
            category_id=parent.id,
            category_update=CategoryUpdate(is_archived=False),
        )

        assert child.archived_at == archived_at

    def test_restoring_a_subcategory_clears_its_cascade_mark(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        """A child brought back on its own must not be re-restored by the next cascade."""
        child = make_category(name="Groceries", parent_id=uuid.uuid4(), archived=True, archived_with_parent=True)
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.return_value = child

        mock_category_service.update_category(
            household=household_context,
            category_id=child.id,
            category_update=CategoryUpdate(is_archived=False),
        )

        assert child.archived_at is None
        assert child.archived_with_parent is False

    def test_refuses_to_change_a_system_category(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        category = make_category(name="Other", is_system=True)
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.return_value = category

        with pytest.raises(SystemCategoryError):
            mock_category_service.update_category(
                household=household_context,
                category_id=category.id,
                category_update=CategoryUpdate(name="Misc"),
            )

    def test_refuses_to_make_a_category_its_own_parent(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        category = make_category()
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.return_value = category

        with pytest.raises(CategorySelfParentError):
            mock_category_service.update_category(
                household=household_context,
                category_id=category.id,
                category_update=CategoryUpdate(parent_id=category.id),
            )

    def test_refuses_to_move_a_parent_under_another_parent(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        """A category with children cannot become a child itself: that is three levels."""
        category = make_category()
        new_parent = make_category(name="Transport")
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.side_effect = [category, new_parent]
        mock_category_service.session.exec.return_value.one.return_value = 2

        with pytest.raises(CategoryDepthExceededError):
            mock_category_service.update_category(
                household=household_context,
                category_id=category.id,
                category_update=CategoryUpdate(parent_id=new_parent.id),
            )


class TestDeleteCategory:
    """Tests for delete_category."""

    def test_deletes_an_unused_category(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        category = make_category(name="Groceries", parent_id=uuid.uuid4())
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.return_value = category
        mock_category_service.session.exec.return_value.one.return_value = 0

        result = mock_category_service.delete_category(
            household=household_context, category_id=category.id
        )

        assert isinstance(result, Message)
        mock_category_service.session.delete.assert_called_once_with(category)

    def test_refuses_to_delete_a_category_with_children(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        category = make_category()
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.return_value = category
        mock_category_service.session.exec.return_value.one.return_value = 3

        with pytest.raises(CategoryInUseError):
            mock_category_service.delete_category(household=household_context, category_id=category.id)

    def test_refuses_to_delete_a_system_category(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        category = make_category(name="Uncategorized", is_system=True, parent_id=uuid.uuid4())
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.return_value = category

        with pytest.raises(SystemCategoryError):
            mock_category_service.delete_category(household=household_context, category_id=category.id)

    @pytest.mark.parametrize(
        ("counts", "blocker"),
        [
            ([0, 1, 0, 0], "transactions"),
            ([0, 0, 1, 0], "budget"),
            ([0, 0, 0, 1], "recurring"),
        ],
        ids=["transactions", "budgets", "recurring rules"],
    )
    def test_refuses_to_delete_a_category_the_ledger_references(
        self,
        mock_category_service: CategoryService,
        household_context: HouseholdContext,
        counts: list[int],
        blocker: str,
    ) -> None:
        """The foreign keys onto category are RESTRICT, so an unchecked delete is a 500."""
        category = make_category(name="Coffee", parent_id=uuid.uuid4())
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.return_value = category
        mock_category_service.session.exec.return_value.one.side_effect = counts

        with pytest.raises(CategoryInUseError) as excinfo:
            mock_category_service.delete_category(household=household_context, category_id=category.id)

        assert blocker in str(excinfo.value)
        mock_category_service.session.delete.assert_not_called()

    def test_stops_at_the_first_blocker(
        self, mock_category_service: CategoryService, household_context: HouseholdContext
    ) -> None:
        """Subcategories are checked first, so the message names them and not the transactions below."""
        category = make_category(name="Coffee")
        mock_category_service.session.exec = MagicMock()
        mock_category_service.session.exec.return_value.first.return_value = category
        mock_category_service.session.exec.return_value.one.side_effect = [1, 4, 0, 0]

        with pytest.raises(CategoryInUseError) as excinfo:
            mock_category_service.delete_category(household=household_context, category_id=category.id)

        assert "subcategories" in str(excinfo.value)
