from sqlmodel import create_engine

from app.core.config import settings
from app.models.user import UserCreate
from app.services import UserService

engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))


def init_db(user_service: UserService) -> None:
    """Initialize the database.

    Ensure that a first superuser is created if one does not already exist in the database.
    This function is typically called on application startup to set up initial data.

    Args:
        user_service: The user service. This service is used to query the database for an
            existing superuser and to create a new superuser if necessary.
    """
    user = user_service.get_user_by_email(email=settings.FIRST_SUPERUSER)

    if not user:
        user_in = UserCreate(
            email=settings.FIRST_SUPERUSER,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            is_superuser=True,
        )
        user_service.create_user(user_create=user_in)
