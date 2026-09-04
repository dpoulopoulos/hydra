from sqlmodel import create_engine

from app.core.config import settings
from app.logging import get_logger
from app.models.user import UserCreate
from app.services import HouseholdService, UserService

logger = get_logger(__name__)

engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))


def init_db(user_service: UserService, household_service: HouseholdService) -> None:
    """Initialize the database.

    Ensure that a first superuser is created if one does not already exist in the database.
    This function is typically called on application startup to set up initial data.

    Args:
        user_service: The user service. This service is used to query the database for an
            existing superuser and to create a new superuser if necessary.
        household_service: The household service. Every user needs a household to use the
            application, so this repairs any account that does not have one, including
            accounts that existed before households did.
    """
    user = user_service.get_user_by_email(email=settings.FIRST_SUPERUSER)

    if not user:
        user_in = UserCreate(
            email=settings.FIRST_SUPERUSER,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            is_superuser=True,
        )
        user_service.create_user(user_create=user_in, household_service=household_service)

    created = household_service.ensure_every_user_has_a_household()

    if created:
        logger.info("Provisioned %d household(s) for users that had none", created)
