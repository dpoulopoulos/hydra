import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlmodel import Session

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
    CategoriesPublic,
    Category,
    CategoryCreate,
    CategoryKind,
    CategoryPublic,
    CategoryTreeNode,
    CategoryTreePublic,
    CategoryUpdate,
    HouseholdContext,
    Message,
)
from app.repositories.budget import BudgetRepository
from app.repositories.category import CategoryRepository
from app.repositories.recurring_rule import RecurringRuleRepository
from app.repositories.transaction import TransactionRepository


class CategoryService:
    """Provide services for category management."""

    def __init__(
        self,
        session: Session,
        category_repository: CategoryRepository,
        transaction_repository: TransactionRepository,
        budget_repository: BudgetRepository,
        recurring_rule_repository: RecurringRuleRepository,
    ) -> None:
        """Initialize the category service.

        Args:
            session: The database session.
            category_repository: The category repository instance.
            transaction_repository: The transaction repository instance.
            budget_repository: The budget repository instance.
            recurring_rule_repository: The recurring rule repository instance.
        """
        self.session = session
        self.category_repository = category_repository
        self.transaction_repository = transaction_repository
        self.budget_repository = budget_repository
        self.recurring_rule_repository = recurring_rule_repository

    def seed_defaults(self, household_id: uuid.UUID) -> None:
        """Create the default categories of a household, without committing.

        The caller owns the transaction, so a household is never observable
        without its categories.

        Args:
            household_id: The ID of the household to seed.
        """
        for sort_order, default in enumerate(DEFAULT_CATEGORIES):
            kind = CategoryKind.INCOME if default.is_income else CategoryKind.EXPENSE
            parent = Category(
                household_id=household_id,
                name=default.name,
                kind=kind,
                icon=default.icon,
                sort_order=sort_order,
                is_system=default.is_system,
            )
            self.category_repository.add(parent)

            for child_order, child_name in enumerate(default.children):
                self.category_repository.add(
                    Category(
                        household_id=household_id,
                        name=child_name,
                        kind=kind,
                        parent_id=parent.id,
                        sort_order=child_order,
                        is_system=default.is_system,
                    )
                )

        # One flush for the whole tree. IDs are generated client side, so the
        # children do not need their parents to be flushed first.
        self.category_repository.flush()

    def create_category(self, household: HouseholdContext, category_create: CategoryCreate) -> CategoryPublic:
        """Create a category or subcategory.

        Args:
            household: The household context.
            category_create: The category to create.

        Returns:
            The created category.

        Raises:
            CategoryNotFoundError: If the parent does not exist in the household.
            CategoryDepthExceededError: If the parent is itself a subcategory.
            CategoryKindMismatchError: If the kind differs from the parent's.
            CategoryExistsError: If a sibling already has that name.
        """
        kind = category_create.kind

        if category_create.parent_id is not None:
            parent = self._require_category(household=household, category_id=category_create.parent_id)

            if parent.parent_id is not None:
                raise CategoryDepthExceededError from None

            if parent.kind is not kind:
                raise CategoryKindMismatchError from None

        self._require_name_is_free(household=household, name=category_create.name, parent_id=category_create.parent_id)

        category = Category.model_validate(category_create, update={"household_id": household.household_id})
        self.category_repository.save(category)
        self.session.commit()

        return CategoryPublic.model_validate(category)

    def list_categories(
        self,
        household: HouseholdContext,
        include_archived: bool = False,
        kind: CategoryKind | None = None,
        parent_id: uuid.UUID | None = None,
    ) -> CategoriesPublic:
        """List the categories of the household as a flat list.

        Args:
            household: The household context.
            include_archived: Whether to include archived categories.
            kind: An optional kind to filter on.
            parent_id: An optional parent to filter on.

        Returns:
            The categories.
        """
        categories = self.category_repository.list_for_household(
            household_id=household.household_id,
            include_archived=include_archived,
            kind=kind,
            parent_id=parent_id,
        )
        data = [CategoryPublic.model_validate(category) for category in categories]

        return CategoriesPublic(data=data, count=len(data))

    def get_category_tree(
        self, household: HouseholdContext, include_archived: bool = False, kind: CategoryKind | None = None
    ) -> CategoryTreePublic:
        """Get the categories of the household as a two level tree.

        Args:
            household: The household context.
            include_archived: Whether to include archived categories.
            kind: An optional kind to filter on.

        Returns:
            The top level categories, each with its subcategories.
        """
        categories = self.category_repository.list_for_household(
            household_id=household.household_id, include_archived=include_archived, kind=kind
        )

        return CategoryTreePublic(data=self._build_tree(categories), count=len(categories))

    def get_category(self, household: HouseholdContext, category_id: uuid.UUID) -> CategoryPublic:
        """Get one category of the household.

        Args:
            household: The household context.
            category_id: The ID of the category.

        Returns:
            The category.

        Raises:
            CategoryNotFoundError: If the category does not exist in the household.
        """
        return CategoryPublic.model_validate(self._require_category(household=household, category_id=category_id))

    def update_category(
        self, household: HouseholdContext, category_id: uuid.UUID, category_update: CategoryUpdate
    ) -> CategoryPublic:
        """Rename, re-parent, archive or restore a category.

        Archiving is a branch operation: archiving a top level category also
        archives its subcategories, and restoring it puts back exactly the
        subcategories that cascade archived. A subcategory that was archived on
        its own is left alone in both directions, since retiring it was a
        separate decision.

        Args:
            household: The household context.
            category_id: The ID of the category to update.
            category_update: The fields to update.

        Returns:
            The updated category.

        Raises:
            CategoryNotFoundError: If the category or the new parent does not exist in the household.
            SystemCategoryError: If the category is built in.
            CategorySelfParentError: If the category would become its own parent.
            CategoryDepthExceededError: If the change would make the tree deeper than two levels.
            CategoryKindMismatchError: If the new parent has a different kind.
            CategoryExistsError: If a sibling already has the new name.
        """
        category = self._require_category(household=household, category_id=category_id)

        if category.is_system:
            raise SystemCategoryError from None

        fields = category_update.model_dump(exclude_unset=True)
        is_archived = fields.pop("is_archived", None)

        if "parent_id" in fields:
            self._check_reparent(household=household, category=category, parent_id=fields["parent_id"])

        name = fields.get("name", category.name)
        parent_id = fields.get("parent_id", category.parent_id)

        if name != category.name or parent_id != category.parent_id:
            self._require_name_is_free(household=household, name=name, parent_id=parent_id, ignore_id=category.id)

        category.sqlmodel_update(fields)

        if is_archived is not None:
            category.archived_at = datetime.now(UTC) if is_archived else None
            # A category being archived in its own right, or coming back, is no
            # longer whatever a past cascade left behind.
            category.archived_with_parent = False

        self.category_repository.save(category)

        # Archiving a parent archives the whole branch. Leaving a subcategory
        # selectable under an archived parent would let new spending land in a
        # category the user believes they have retired. Restoring the parent
        # undoes exactly that, so the operation is invertible and the user is
        # not left with a top level category that has nothing under it.
        if is_archived is not None and category.parent_id is None:
            if is_archived:
                self._archive_children(household=household, category=category)
            else:
                self._restore_children(household=household, category=category)

        self.session.commit()

        return CategoryPublic.model_validate(category)

    def delete_category(self, household: HouseholdContext, category_id: uuid.UUID) -> Message:
        """Delete a category that nothing references.

        Args:
            household: The household context.
            category_id: The ID of the category to delete.

        Returns:
            A confirmation message.

        Raises:
            CategoryNotFoundError: If the category does not exist in the household.
            SystemCategoryError: If the category is built in.
            CategoryInUseError: If a subcategory, transaction, budget or recurring rule still
                references the category.
        """
        category = self._require_category(household=household, category_id=category_id)

        if category.is_system:
            raise SystemCategoryError from None

        self._require_nothing_references(household=household, category=category)

        self.category_repository.delete(category)
        self.session.commit()

        return Message(message="Category deleted.")

    def _require_nothing_references(self, household: HouseholdContext, category: Category) -> None:
        """Check that a category can be deleted without breaking a reference to it.

        Every foreign key onto category is RESTRICT, so an unchecked delete
        fails in the database at commit time and surfaces as a 500. Ask for
        each reference up front instead, in the order the user is likeliest to
        be able to act on, so the refusal can say what is holding the category.

        Args:
            household: The household context.
            category: The category about to be deleted.

        Raises:
            CategoryInUseError: If anything still references the category.
        """
        household_id = household.household_id

        if self.category_repository.count_children(category_id=category.id, household_id=household_id):
            raise CategoryInUseError(name=category.name, reason="has subcategories") from None

        if self.transaction_repository.count_for_category(category_id=category.id, household_id=household_id):
            raise CategoryInUseError(name=category.name, reason="has transactions filed under it") from None

        if self.budget_repository.count_for_category(category_id=category.id, household_id=household_id):
            raise CategoryInUseError(name=category.name, reason="has a budget set on it") from None

        if self.recurring_rule_repository.count_for_category(category_id=category.id, household_id=household_id):
            raise CategoryInUseError(name=category.name, reason="has recurring rules filed under it") from None

    def _build_tree(self, categories: Sequence[Category]) -> list[CategoryTreeNode]:
        """Assemble a flat list of categories into a two level tree.

        Done in Python from a single query rather than one query per level.

        Args:
            categories: The categories of the household, already ordered.

        Returns:
            The top level categories, each with its subcategories.
        """
        nodes = {
            category.id: CategoryTreeNode.model_validate(category, update={"children": []})
            for category in categories
            if category.parent_id is None
        }

        for category in categories:
            if category.parent_id is not None and category.parent_id in nodes:
                nodes[category.parent_id].children.append(CategoryPublic.model_validate(category))

        return list(nodes.values())

    def _archive_children(self, household: HouseholdContext, category: Category) -> None:
        """Archive every subcategory that is not already archived on its own.

        A child that was archived before the cascade keeps its own date: its
        retirement was a separate decision, and restoring the parent must not
        undo it. Marking only the children this cascade took down records which
        ones that is, which is what makes the restore possible.

        Args:
            household: The household context.
            category: The parent category being archived.
        """
        children = self.category_repository.list_for_household(
            household_id=household.household_id, include_archived=True, parent_id=category.id
        )

        for child in children:
            if child.archived_at is None:
                child.archived_at = category.archived_at
                child.archived_with_parent = True
                self.category_repository.add(child)

        self.category_repository.flush()

    def _restore_children(self, household: HouseholdContext, category: Category) -> None:
        """Restore the subcategories that were archived along with a category.

        Args:
            household: The household context.
            category: The parent category being restored.
        """
        children = self.category_repository.list_for_household(
            household_id=household.household_id, include_archived=True, parent_id=category.id
        )

        for child in children:
            if child.archived_with_parent:
                child.archived_at = None
                child.archived_with_parent = False
                self.category_repository.add(child)

        self.category_repository.flush()

    def _check_reparent(self, household: HouseholdContext, category: Category, parent_id: uuid.UUID | None) -> None:
        """Check that a category may be moved under a new parent.

        Args:
            household: The household context.
            category: The category being moved.
            parent_id: The new parent, or None to move it to the top level.

        Raises:
            CategorySelfParentError: If the category would become its own parent.
            CategoryNotFoundError: If the new parent does not exist in the household.
            CategoryDepthExceededError: If the move would make the tree deeper than
                two levels, either because the new parent is itself a subcategory
                or because the category has subcategories of its own.
            CategoryKindMismatchError: If the new parent has a different kind.
        """
        if parent_id is None:
            return

        if parent_id == category.id:
            raise CategorySelfParentError from None

        parent = self._require_category(household=household, category_id=parent_id)

        if parent.parent_id is not None:
            raise CategoryDepthExceededError from None

        if parent.kind is not category.kind:
            raise CategoryKindMismatchError from None

        if self.category_repository.count_children(category_id=category.id, household_id=household.household_id):
            raise CategoryDepthExceededError from None

    def _require_name_is_free(
        self,
        household: HouseholdContext,
        name: str,
        parent_id: uuid.UUID | None,
        ignore_id: uuid.UUID | None = None,
    ) -> None:
        """Check that no sibling already uses a name.

        Args:
            household: The household context.
            name: The name to check.
            parent_id: The parent the name would sit under.
            ignore_id: A category to ignore, so renaming to its own name is not a conflict.

        Raises:
            CategoryExistsError: If a sibling already has that name.
        """
        existing = self.category_repository.get_by_name(
            household_id=household.household_id, name=name, parent_id=parent_id
        )

        if existing and existing.id != ignore_id:
            raise CategoryExistsError(name=name) from None

    def _require_category(self, household: HouseholdContext, category_id: uuid.UUID) -> Category:
        """Load a category of the household.

        Args:
            household: The household context.
            category_id: The ID of the category.

        Returns:
            The category.

        Raises:
            CategoryNotFoundError: If the category does not exist in the household.
        """
        category = self.category_repository.get_for_household(
            entity_id=category_id, household_id=household.household_id
        )

        if not category:
            raise CategoryNotFoundError from None

        return category
