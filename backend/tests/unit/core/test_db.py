from unittest.mock import MagicMock

from app.core.config import settings
from app.core.db import init_db
from app.models import User, UserCreate
from app.services import CategoryService, HouseholdService, UserService


class TestInitDb:
    """Test the init_db function."""

    def test_init_db_with_existing_superuser(
        self,
        mock_user_service: UserService,
        mock_household_service: HouseholdService,
        mock_category_service: CategoryService,
        test_superuser: User,
    ):
        """Test that init_db does not create a superuser when one already exists."""
        # Arrange: Mock the service to return an existing superuser
        mock_user_service.get_user_by_email = MagicMock(return_value=test_superuser)
        mock_user_service.create_user = MagicMock()
        mock_household_service.ensure_every_user_has_a_household = MagicMock(return_value=0)
        mock_household_service.ensure_every_household_has_an_owner = MagicMock(return_value=0)

        # Act: Call init_db
        init_db(
            user_service=mock_user_service,
            household_service=mock_household_service,
            category_service=mock_category_service,
        )

        # Assert: Verify get_user_by_email was called with the correct email
        mock_user_service.get_user_by_email.assert_called_once_with(
            email=settings.FIRST_SUPERUSER
        )

        # Assert: Verify create_user was NOT called since superuser exists
        mock_user_service.create_user.assert_not_called()

    def test_init_db_creates_superuser_when_none_exists(
        self,
        mock_user_service: UserService,
        mock_household_service: HouseholdService,
        mock_category_service: CategoryService,
        test_superuser: User,
    ):
        """Test that init_db creates a superuser when none exists."""
        # Arrange: Mock the service to return None (no existing superuser)
        mock_user_service.get_user_by_email = MagicMock(return_value=None)
        mock_user_service.create_user = MagicMock(return_value=test_superuser)
        mock_household_service.ensure_every_user_has_a_household = MagicMock(return_value=0)
        mock_household_service.ensure_every_household_has_an_owner = MagicMock(return_value=0)

        # Act: Call init_db
        init_db(
            user_service=mock_user_service,
            household_service=mock_household_service,
            category_service=mock_category_service,
        )

        # Assert: Verify get_user_by_email was called with the correct email
        mock_user_service.get_user_by_email.assert_called_once_with(
            email=settings.FIRST_SUPERUSER
        )

        # Assert: Verify create_user was called with the correct parameters
        mock_user_service.create_user.assert_called_once()

        # Get the actual UserCreate object passed to create_user
        call_args = mock_user_service.create_user.call_args
        user_create_arg = call_args.kwargs["user_create"]

        # Verify the UserCreate object has the correct values
        assert isinstance(user_create_arg, UserCreate)
        assert user_create_arg.email == settings.FIRST_SUPERUSER
        assert user_create_arg.password == settings.FIRST_SUPERUSER_PASSWORD
        assert user_create_arg.is_superuser is True

    def test_init_db_provisions_missing_households(
        self,
        mock_user_service: UserService,
        mock_household_service: HouseholdService,
        mock_category_service: CategoryService,
        test_superuser: User,
    ):
        """Test that init_db repairs users that have no household."""
        # Arrange: A superuser already exists, but some accounts have no household
        mock_user_service.get_user_by_email = MagicMock(return_value=test_superuser)
        mock_user_service.create_user = MagicMock()
        mock_household_service.ensure_every_user_has_a_household = MagicMock(return_value=2)
        mock_household_service.ensure_every_household_has_an_owner = MagicMock(return_value=0)

        # Act: Call init_db
        init_db(
            user_service=mock_user_service,
            household_service=mock_household_service,
            category_service=mock_category_service,
        )

        # Assert: Verify the repair ran
        mock_household_service.ensure_every_user_has_a_household.assert_called_once_with(
            category_service=mock_category_service
        )

    def test_init_db_passes_the_household_service_to_create_user(
        self,
        mock_user_service: UserService,
        mock_household_service: HouseholdService,
        mock_category_service: CategoryService,
        test_superuser: User,
    ):
        """Test that a newly created superuser gets a household in the same transaction."""
        # Arrange: Mock the service to return None (no existing superuser)
        mock_user_service.get_user_by_email = MagicMock(return_value=None)
        mock_user_service.create_user = MagicMock(return_value=test_superuser)
        mock_household_service.ensure_every_user_has_a_household = MagicMock(return_value=0)
        mock_household_service.ensure_every_household_has_an_owner = MagicMock(return_value=0)

        # Act: Call init_db
        init_db(
            user_service=mock_user_service,
            household_service=mock_household_service,
            category_service=mock_category_service,
        )

        # Assert: Verify both collaborators were handed to create_user, so the
        # user, their household and its categories share one transaction
        kwargs = mock_user_service.create_user.call_args.kwargs
        assert kwargs["household_service"] is mock_household_service
        assert kwargs["category_service"] is mock_category_service

    def test_init_db_repairs_households_left_without_an_owner(
        self,
        mock_user_service: UserService,
        mock_household_service: HouseholdService,
        mock_category_service: CategoryService,
        test_superuser: User,
    ):
        """Test that init_db gives an owner back to the households that lost theirs."""
        # Arrange: A superuser already exists, but a household has no owner left
        mock_user_service.get_user_by_email = MagicMock(return_value=test_superuser)
        mock_user_service.create_user = MagicMock()
        mock_household_service.ensure_every_user_has_a_household = MagicMock(return_value=0)
        mock_household_service.ensure_every_household_has_an_owner = MagicMock(return_value=1)

        # Act: Call init_db
        init_db(
            user_service=mock_user_service,
            household_service=mock_household_service,
            category_service=mock_category_service,
        )

        # Assert: Verify the repair ran
        mock_household_service.ensure_every_household_has_an_owner.assert_called_once_with()
