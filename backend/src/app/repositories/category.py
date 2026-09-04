import uuid
from collections.abc import Sequence

from sqlmodel import Session, col, func, select

from app.models import Category, CategoryKind
from app.repositories.base import HouseholdScopedRepository


class CategoryRepository(HouseholdScopedRepository[Category]):
    """Repository for Category database operations."""

    def __init__(self, session: Session) -> None:
        """Initialize the category repository.

        Args:
            session: The database session.
        """
        super().__init__(session, Category)

    def list_for_household(
        self,
        household_id: uuid.UUID,
        include_archived: bool = False,
        kind: CategoryKind | None = None,
        parent_id: uuid.UUID | None = None,
        roots_only: bool = False,
    ) -> Sequence[Category]:
        """List the categories of a household.

        Args:
            household_id: The ID of the household.
            include_archived: Whether to include archived categories.
            kind: An optional kind to filter on.
            parent_id: An optional parent to filter on.
            roots_only: Whether to return only top level categories.

        Returns:
            The categories, ordered by sort order and then name.
        """
        statement = select(Category).where(Category.household_id == household_id)

        if not include_archived:
            statement = statement.where(col(Category.archived_at).is_(None))

        if kind is not None:
            statement = statement.where(Category.kind == kind)

        if parent_id is not None:
            statement = statement.where(Category.parent_id == parent_id)
        elif roots_only:
            statement = statement.where(col(Category.parent_id).is_(None))

        statement = statement.order_by(col(Category.sort_order), col(Category.name))

        return self.session.exec(statement).all()

    def get_many_for_household(self, category_ids: Sequence[uuid.UUID], household_id: uuid.UUID) -> Sequence[Category]:
        """Get several categories of a household in one query.

        Used where a request references many categories at once, so validating
        them does not turn into one query per ID.

        Args:
            category_ids: The IDs to look up.
            household_id: The ID of the household that must own them.

        Returns:
            The categories that exist and belong to the household.
        """
        if not category_ids:
            return []

        statement = select(Category).where(Category.household_id == household_id, col(Category.id).in_(category_ids))
        return self.session.exec(statement).all()

    def get_by_name(self, household_id: uuid.UUID, name: str, parent_id: uuid.UUID | None) -> Category | None:
        """Get a category by its name within its parent.

        Args:
            household_id: The ID of the household.
            name: The category name.
            parent_id: The parent, or None for a top level category.

        Returns:
            The category if one exists with that name, None otherwise.
        """
        statement = select(Category).where(Category.household_id == household_id, Category.name == name)

        if parent_id is None:
            statement = statement.where(col(Category.parent_id).is_(None))
        else:
            statement = statement.where(Category.parent_id == parent_id)

        return self.session.exec(statement).first()

    def count_children(self, category_id: uuid.UUID, household_id: uuid.UUID) -> int:
        """Count the subcategories of a category.

        Args:
            category_id: The ID of the parent category.
            household_id: The ID of the household.

        Returns:
            The number of subcategories.
        """
        statement = (
            select(func.count())
            .select_from(Category)
            .where(Category.household_id == household_id, Category.parent_id == category_id)
        )
        return self.session.exec(statement).one()
