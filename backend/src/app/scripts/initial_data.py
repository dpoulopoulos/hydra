from sqlmodel import Session

from app.core.db import engine, init_db
from app.logging import get_logger
from app.repositories import UserRepository
from app.services import UserService

logger = get_logger(__name__)


def init() -> None:
    """Initialize the database."""
    with Session(engine) as session:
        user_repository = UserRepository(session=session)
        user_service = UserService(session=session, user_repository=user_repository)
        init_db(user_service=user_service)


def main() -> None:
    """Create initial data."""
    logger.info("Creating initial data")
    init()
    logger.info("Initial data created")


if __name__ == "__main__":
    main()
