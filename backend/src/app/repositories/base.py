from typing import Any, cast
from uuid import UUID

from sqlalchemy import Table
from sqlmodel import Session, SQLModel, func, select
from sqlmodel.sql.expression import SelectOfScalar


def table_of(model_class: type[SQLModel]) -> Table:
    """Get the mapped table of a SQLModel class.

    Args:
        model_class: A SQLModel class declared with ``table=True``.

    Returns:
        The SQLAlchemy table the model is mapped to.
    """
    # SQLModel does not declare __table__ on the class, but SQLAlchemy sets
    # it on every table=True model.
    return cast(Table, model_class.__table__)  # type: ignore[attr-defined]


class BaseRepository[T: SQLModel]:
    """Base repository for common database operations.

    This class provides generic CRUD operations for any SQLModel entity.
    Repositories only flush() changes, leaving commit() to the service layer
    to maintain transaction control.
    """

    def __init__(self, session: Session, model_class: type[T]) -> None:
        """Initialize the base repository.

        Args:
            session: The database session.
            model_class: The SQLModel class this repository manages.
        """
        self.session = session
        self.model_class = model_class

    def get_by_id(self, entity_id: UUID) -> T | None:
        """Get an entity by ID.

        Args:
            entity_id: The ID of the entity to retrieve.

        Returns:
            The entity if found, None otherwise.
        """
        return self.session.get(self.model_class, entity_id)

    def add(self, entity: T) -> None:
        """Add entity to session.

        Does NOT flush or commit - caller must explicitly flush/commit.

        Args:
            entity: The entity to add to the session.
        """
        self.session.add(entity)

    def save(self, entity: T) -> T:
        """Save an entity (create or update).

        Adds entity to session and flushes to get DB-generated values.
        Does NOT commit - caller must commit.

        Args:
            entity: The entity to save.

        Returns:
            The saved entity with DB-generated values.
        """
        self.add(entity)
        self.flush()
        self.refresh(entity)
        return entity

    def delete(self, entity: T) -> None:
        """Mark entity for deletion.

        Does NOT flush or commit - caller must explicitly flush/commit.

        Args:
            entity: The entity to delete.
        """
        self.session.delete(entity)

    def flush(self) -> None:
        """Flush changes to database without committing.

        This persists changes to the database and generates DB values
        (like auto-incremented IDs) without finalizing the transaction.
        """
        self.session.flush()

    def _paginate(self, statement: SelectOfScalar[T], skip: int, limit: int) -> SelectOfScalar[T]:
        """Cut a query down to one page of results.

        Shared so every listing spells a page the same way and a caller cannot
        get an offset applied without a limit, or the other way round.

        Args:
            statement: The ordered query to page over.
            skip: Number of records to skip.
            limit: Maximum number of records to return.

        Returns:
            The query, restricted to the page.
        """
        return statement.offset(skip).limit(limit)

    def refresh(self, entity: T) -> None:
        """Refresh entity from database.

        Reloads the entity's state from the database, discarding any
        uncommitted changes.

        Args:
            entity: The entity to refresh.
        """
        self.session.refresh(entity)


class HouseholdScopedRepository[T: SQLModel](BaseRepository[T]):
    """Base repository for entities owned by a household.

    Every read puts ``household_id`` in the ``WHERE`` clause, so a caller can
    never receive a row belonging to another household and services do not need
    to re-check ownership after fetching. Subclasses of this repository must use
    :meth:`get_for_household` rather than the inherited
    :meth:`BaseRepository.get_by_id`, which is unscoped.

    Columns are reached through ``__table__`` rather than the model class, so a
    model missing ``household_id`` fails loudly at construction instead of
    silently returning unscoped rows.
    """

    def __init__(self, session: Session, model_class: type[T]) -> None:
        """Initialize the household scoped repository.

        Args:
            session: The database session.
            model_class: The SQLModel class this repository manages. It must
                have an ``id`` and a ``household_id`` column.

        Raises:
            TypeError: If the model has no ``household_id`` column.
        """
        super().__init__(session, model_class)

        columns = table_of(model_class).c
        if "household_id" not in columns:
            raise TypeError(f"{model_class.__name__} has no household_id column and cannot be household scoped.")

        self.id_column = columns["id"]
        self.household_column = columns["household_id"]
        # Optional: only some household-owned models can be archived. Absence is
        # caught in _archived_conditions rather than here, so a model that has
        # no use for archiving is still allowed to be household scoped.
        self.archived_column = columns.get("archived_at")

    def get_for_household(self, entity_id: UUID, household_id: UUID) -> T | None:
        """Get an entity by ID within a household.

        Args:
            entity_id: The ID of the entity to retrieve.
            household_id: The ID of the household that must own the entity.

        Returns:
            The entity if it exists and belongs to the household, None otherwise.
        """
        statement = select(self.model_class).where(self.id_column == entity_id, self.household_column == household_id)
        return self.session.exec(statement).first()

    def _archived_conditions(self, include_archived: bool) -> list[Any]:
        """Build the WHERE clauses that keep archived rows out of a listing.

        Archiving is the same idea wherever it appears, so the predicate is
        written once here rather than in each repository that offers it.

        Args:
            include_archived: Whether archived rows should be included.

        Returns:
            The conditions to apply, empty when archived rows are wanted.

        Raises:
            TypeError: If the model has no ``archived_at`` column, which means
                the caller is asking a question the model cannot answer.
        """
        if self.archived_column is None:
            raise TypeError(f"{self.model_class.__name__} has no archived_at column and cannot be filtered on it.")

        return [] if include_archived else [self.archived_column.is_(None)]

    def exists_for_household(self, entity_id: UUID, household_id: UUID) -> bool:
        """Check whether an entity exists within a household.

        Args:
            entity_id: The ID of the entity to look for.
            household_id: The ID of the household that must own the entity.

        Returns:
            True if the entity exists and belongs to the household.
        """
        statement = select(self.id_column).where(self.id_column == entity_id, self.household_column == household_id)
        return self.session.exec(statement).first() is not None

    def count_for_household(self, household_id: UUID, *conditions: Any) -> int:
        """Count the entities owned by a household.

        Counting in SQL rather than by loading the rows, so a listing pays for
        its page and nothing more.

        Args:
            household_id: The ID of the household.
            conditions: Extra ``WHERE`` clauses, so a filtered listing can
                count exactly the rows it is about to page over.

        Returns:
            The number of matching entities the household owns.
        """
        statement = (
            select(func.count()).select_from(self.model_class).where(self.household_column == household_id, *conditions)
        )
        return self.session.exec(statement).one()
