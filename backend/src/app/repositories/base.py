from uuid import UUID

from sqlmodel import Session, SQLModel


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

    def refresh(self, entity: T) -> None:
        """Refresh entity from database.

        Reloads the entity's state from the database, discarding any
        uncommitted changes.

        Args:
            entity: The entity to refresh.
        """
        self.session.refresh(entity)
