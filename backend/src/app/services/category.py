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
from app.repositories.category import CategoryRepository


class CategoryService:
    """Provide services for category management."""

    def __init__(self, session: Session, category_repository: CategoryRepository) -> None:
        """Initialize the category service.

        Args:
            session: The database session.
            category_repository: The category repository instance.
        """
        self.session = session
        self.category_repository = category_repository

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

        self.category_repository.save(category)

        # Archiving a parent archives the whole branch. Leaving a subcategory
        # selectable under an archived parent would let new spending land in a
        # category the user believes they have retired.
        if is_archived and category.parent_id is None:
            self._archive_children(household=household, category=category)

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
            CategoryInUseError: If the category still has subcategories.
        """
        category = self._require_category(household=household, category_id=category_id)

        if category.is_system:
            raise SystemCategoryError from None

        if self.category_repository.count_children(category_id=category.id, household_id=household.household_id):
            raise CategoryInUseError(name=category.name) from None

        self.category_repository.delete(category)
        self.session.commit()

        return Message(message="Category deleted.")

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
        """Archive every subcategory of a category.

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
