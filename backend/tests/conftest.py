import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.main import app
from app.core.security import ALGORITHM, create_access_token, get_password_hash
from app.models import HouseholdContext, HouseholdRole, User
from app.repositories import (
    AccountRepository,
    BudgetRepository,
    CategoryRepository,
    EmailVerificationRepository,
    HouseholdInviteRepository,
    HouseholdMemberRepository,
    HouseholdRepository,
    PasswordResetRepository,
    RecurringRuleRepository,
    ReportRepository,
    TransactionRepository,
    UserRepository,
)
from app.services import (
    AccountService,
    BudgetService,
    CategoryService,
    EmailVerificationService,
    HouseholdService,
    PasswordResetService,
    RecurringRuleService,
    ReportService,
    TransactionService,
    UserService,
)


@pytest.fixture
def mock_db_session() -> MagicMock:
    """Create a mock database session.

    Returns:
        A mock database session.
    """
    return MagicMock(spec=Session)


@pytest.fixture
def test_user() -> User:
    """Create a test user.

    Returns:
        A test user instance.
    """
    user = User(
        email="test@example.com",
        full_name="Test User",
        hashed_password=get_password_hash("testpassword123"),
        is_active=True,
        is_superuser=False,
    )
    # Override the generated ID for consistent testing
    user.id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    return user


@pytest.fixture
def test_superuser() -> User:
    """Create a test superuser.

    Returns:
        A test superuser instance.
    """
    user = User(
        email="admin@example.com",
        full_name="Admin User",
        hashed_password=get_password_hash("adminpassword123"),
        is_active=True,
        is_superuser=True,
    )
    # Override the generated ID for consistent testing
    user.id = uuid.UUID("87654321-4321-8765-4321-876543218765")
    return user


@pytest.fixture
def test_inactive_user() -> User:
    """Create an inactive test user.

    Returns:
        An inactive test user instance.
    """
    user = User(
        email="inactive@example.com",
        full_name="Inactive User",
        hashed_password=get_password_hash("inactivepassword123"),
        is_active=False,
        is_superuser=False,
    )
    # Override the generated ID for consistent testing
    user.id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    return user


@pytest.fixture
def another_test_user() -> User:
    """Create another test user for multi-user scenarios.

    Returns:
        Another test user instance.
    """
    user = User(
        email="another@example.com",
        full_name="Another User",
        hashed_password=get_password_hash("anotherpassword123"),
        is_active=True,
        is_superuser=False,
    )
    # Override the generated ID for consistent testing
    user.id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    return user


@pytest.fixture
def mock_user_repository(mock_db_session: MagicMock) -> UserRepository:
    """Create a UserRepository instance with a mocked session.

    Args:
        mock_db_session: The mock database session.

    Returns:
        A UserRepository instance with a mocked session.
    """
    return UserRepository(session=mock_db_session)


@pytest.fixture
def mock_user_service(mock_db_session: MagicMock, mock_user_repository: UserRepository) -> UserService:
    """Create a UserService instance with a mocked session and repository.

    Args:
        mock_db_session: The mock database session.
        mock_user_repository: The mock user repository.

    Returns:
        A UserService instance with a mocked session and repository.
    """
    return UserService(session=mock_db_session, user_repository=mock_user_repository)


@pytest.fixture
def mock_email_verification_repository(mock_db_session: MagicMock) -> EmailVerificationRepository:
    """Create an EmailVerificationRepository instance with a mocked session.

    Args:
        mock_db_session: The mock database session.

    Returns:
        An EmailVerificationRepository instance with a mocked session.
    """
    return EmailVerificationRepository(session=mock_db_session)


@pytest.fixture
def mock_email_verification_service(
    mock_db_session: MagicMock, mock_email_verification_repository: EmailVerificationRepository
) -> EmailVerificationService:
    """Create an EmailVerificationService instance with a mocked session and repository.

    Args:
        mock_db_session: The mock database session.
        mock_email_verification_repository: The mock email verification repository.

    Returns:
        An EmailVerificationService instance with a mocked session and repository.
    """
    return EmailVerificationService(
        session=mock_db_session, email_verification_repository=mock_email_verification_repository
    )


@pytest.fixture
def user_token(test_user: User) -> str:
    """Create a valid JWT token for the test user.

    Args:
        test_user: The test user to create a token for.

    Returns:
        A valid JWT access token.
    """
    return create_access_token(test_user.id)


@pytest.fixture
def mock_password_reset_repository(mock_db_session: MagicMock) -> PasswordResetRepository:
    """Create a PasswordResetRepository instance with a mocked session.

    Args:
        mock_db_session: The mock database session.

    Returns:
        A PasswordResetRepository instance with a mocked session.
    """
    return PasswordResetRepository(session=mock_db_session)


@pytest.fixture
def mock_password_reset_service(
    mock_db_session: MagicMock, mock_password_reset_repository: PasswordResetRepository
) -> PasswordResetService:
    """Create a PasswordResetService instance with a mocked session and repository.

    Args:
        mock_db_session: The mock database session.
        mock_password_reset_repository: The mock password reset repository.

    Returns:
        A PasswordResetService instance with a mocked session and repository.
    """
    return PasswordResetService(session=mock_db_session, password_reset_repository=mock_password_reset_repository)


@pytest.fixture
def expired_user_token(test_user: User) -> str:
    """Create an expired JWT token for the test user.

    Args:
        test_user: The test user to create a token for.

    Returns:
        An expired JWT access token.
    """
    # Create a token that expired 1 hour ago
    delta = timedelta(hours=-1)
    now = datetime.now(UTC)
    expires = now + delta
    exp = expires.timestamp()
    encoded_jwt = jwt.encode(
        {"exp": exp, "nbf": now, "sub": str(test_user.id), "type": "session"},
        settings.SECRET_KEY,
        algorithm=ALGORITHM,
    )
    return encoded_jwt


@pytest.fixture
def superuser_token(test_superuser: User) -> str:
    """Create a valid JWT token for the test superuser.

    Args:
        test_superuser: The test superuser to create a token for.

    Returns:
        A valid JWT access token.
    """
    return create_access_token(test_superuser.id)


@pytest.fixture
def inactive_user_token(test_inactive_user: User) -> str:
    """Create a valid JWT token for the inactive test user.

    Args:
        test_inactive_user: The inactive test user to create a token for.

    Returns:
        A valid JWT access token.
    """
    return create_access_token(test_inactive_user.id)


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Create a test client for the FastAPI application.

    Yields:
        A FastAPI test client.
    """
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers(user_token: str) -> dict[str, str]:
    """Create authorization headers with a valid user token.

    Args:
        user_token: The JWT token for authentication.

    Returns:
        A dictionary containing authorization headers.
    """
    return {"Authorization": f"Bearer {user_token}"}


@pytest.fixture
def superuser_auth_headers(superuser_token: str) -> dict[str, str]:
    """Create authorization headers with a valid superuser token.

    Args:
        superuser_token: The JWT token for superuser authentication.

    Returns:
        A dictionary containing authorization headers.
    """
    return {"Authorization": f"Bearer {superuser_token}"}


@pytest.fixture
def inactive_user_auth_headers(inactive_user_token: str) -> dict[str, str]:
    """Create authorization headers with an inactive user token.

    Args:
        inactive_user_token: The JWT token for inactive user authentication.

    Returns:
        A dictionary containing authorization headers.
    """
    return {"Authorization": f"Bearer {inactive_user_token}"}


@pytest.fixture
def base_settings_env(monkeypatch):
    """Set up common environment variables for Settings tests.

    This fixture provides secure default values for all required settings.
    Individual tests can override specific values as needed.

    Args:
        monkeypatch: pytest monkeypatch fixture.
    """
    monkeypatch.setenv("PROJECT_NAME", "Test Project")
    monkeypatch.setenv("PROJECT_ID", "test-project")
    monkeypatch.setenv("POSTGRES_SERVER", "localhost")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_USER", "test_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secure_password")
    monkeypatch.setenv("POSTGRES_DB", "test_db")
    monkeypatch.setenv("FIRST_SUPERUSER", "admin@example.com")
    monkeypatch.setenv("FIRST_SUPERUSER_PASSWORD", "secure_password")
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("SECRET_KEY", "secure_secret_key")


@pytest.fixture
def mock_household_repository(mock_db_session: MagicMock) -> HouseholdRepository:
    """Create a HouseholdRepository instance with a mocked session.

    Args:
        mock_db_session: The mock database session.

    Returns:
        A HouseholdRepository instance with a mocked session.
    """
    return HouseholdRepository(session=mock_db_session)


@pytest.fixture
def mock_household_member_repository(mock_db_session: MagicMock) -> HouseholdMemberRepository:
    """Create a HouseholdMemberRepository instance with a mocked session.

    Args:
        mock_db_session: The mock database session.

    Returns:
        A HouseholdMemberRepository instance with a mocked session.
    """
    return HouseholdMemberRepository(session=mock_db_session)


@pytest.fixture
def mock_household_invite_repository(mock_db_session: MagicMock) -> HouseholdInviteRepository:
    """Create a HouseholdInviteRepository instance with a mocked session.

    Args:
        mock_db_session: The mock database session.

    Returns:
        A HouseholdInviteRepository instance with a mocked session.
    """
    return HouseholdInviteRepository(session=mock_db_session)


@pytest.fixture
def mock_household_service(
    mock_db_session: MagicMock,
    mock_household_repository: HouseholdRepository,
    mock_household_member_repository: HouseholdMemberRepository,
    mock_household_invite_repository: HouseholdInviteRepository,
) -> HouseholdService:
    """Create a HouseholdService instance with a mocked session.

    Args:
        mock_db_session: The mock database session.
        mock_household_repository: The household repository instance.
        mock_household_member_repository: The household member repository instance.
        mock_household_invite_repository: The household invite repository instance.

    Returns:
        A HouseholdService instance with a mocked session.
    """
    return HouseholdService(
        session=mock_db_session,
        household_repository=mock_household_repository,
        household_member_repository=mock_household_member_repository,
        household_invite_repository=mock_household_invite_repository,
    )


@pytest.fixture
def mock_category_repository(mock_db_session: MagicMock) -> CategoryRepository:
    """Create a CategoryRepository instance with a mocked session.

    Args:
        mock_db_session: The mock database session.

    Returns:
        A CategoryRepository instance with a mocked session.
    """
    return CategoryRepository(session=mock_db_session)


@pytest.fixture
def mock_category_service(
    mock_db_session: MagicMock,
    mock_category_repository: CategoryRepository,
    mock_transaction_repository: TransactionRepository,
    mock_budget_repository: BudgetRepository,
    mock_recurring_rule_repository: RecurringRuleRepository,
) -> CategoryService:
    """Create a CategoryService instance with a mocked session.

    Args:
        mock_db_session: The mock database session.
        mock_category_repository: The category repository instance.
        mock_transaction_repository: The transaction repository instance.
        mock_budget_repository: The budget repository instance.
        mock_recurring_rule_repository: The recurring rule repository instance.

    Returns:
        A CategoryService instance with a mocked session.
    """
    return CategoryService(
        session=mock_db_session,
        category_repository=mock_category_repository,
        transaction_repository=mock_transaction_repository,
        budget_repository=mock_budget_repository,
        recurring_rule_repository=mock_recurring_rule_repository,
    )


@pytest.fixture
def household_context(test_user: User) -> HouseholdContext:
    """Build an owner household context for the test user.

    Args:
        test_user: The test user.

    Returns:
        A household context in which the user owns the household.
    """
    return HouseholdContext(
        user=test_user,
        household_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        membership_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        role=HouseholdRole.OWNER,
    )


@pytest.fixture
def mock_account_repository(mock_db_session: MagicMock) -> AccountRepository:
    """Create an AccountRepository instance with a mocked session.

    Args:
        mock_db_session: The mock database session.

    Returns:
        An AccountRepository instance with a mocked session.
    """
    return AccountRepository(session=mock_db_session)


@pytest.fixture
def mock_account_service(
    mock_db_session: MagicMock,
    mock_account_repository: AccountRepository,
    mock_household_repository: HouseholdRepository,
    mock_transaction_repository: TransactionRepository,
    mock_recurring_rule_repository: RecurringRuleRepository,
) -> AccountService:
    """Create an AccountService instance with a mocked session.

    Args:
        mock_db_session: The mock database session.
        mock_account_repository: The account repository instance.
        mock_household_repository: The household repository instance.
        mock_transaction_repository: The transaction repository instance.
        mock_recurring_rule_repository: The recurring rule repository instance.

    Returns:
        An AccountService instance with a mocked session.
    """
    return AccountService(
        session=mock_db_session,
        account_repository=mock_account_repository,
        household_repository=mock_household_repository,
        transaction_repository=mock_transaction_repository,
        recurring_rule_repository=mock_recurring_rule_repository,
    )


@pytest.fixture
def mock_transaction_repository(mock_db_session: MagicMock) -> TransactionRepository:
    """Create a TransactionRepository instance with a mocked session.

    Args:
        mock_db_session: The mock database session.

    Returns:
        A TransactionRepository instance with a mocked session.
    """
    return TransactionRepository(session=mock_db_session)


@pytest.fixture
def mock_transaction_service(
    mock_db_session: MagicMock,
    mock_transaction_repository: TransactionRepository,
    mock_account_repository: AccountRepository,
    mock_category_repository: CategoryRepository,
) -> TransactionService:
    """Create a TransactionService instance with a mocked session.

    Args:
        mock_db_session: The mock database session.
        mock_transaction_repository: The transaction repository instance.
        mock_account_repository: The account repository instance.
        mock_category_repository: The category repository instance.

    Returns:
        A TransactionService instance with a mocked session.
    """
    return TransactionService(
        session=mock_db_session,
        transaction_repository=mock_transaction_repository,
        account_repository=mock_account_repository,
        category_repository=mock_category_repository,
    )


@pytest.fixture
def mock_budget_repository(mock_db_session: MagicMock) -> BudgetRepository:
    """Create a BudgetRepository instance with a mocked session.

    Args:
        mock_db_session: The mock database session.

    Returns:
        A BudgetRepository instance with a mocked session.
    """
    return BudgetRepository(session=mock_db_session)


@pytest.fixture
def mock_budget_service(
    mock_db_session: MagicMock,
    mock_budget_repository: BudgetRepository,
    mock_category_repository: CategoryRepository,
) -> BudgetService:
    """Create a BudgetService instance with a mocked session.

    Args:
        mock_db_session: The mock database session.
        mock_budget_repository: The budget repository instance.
        mock_category_repository: The category repository instance.

    Returns:
        A BudgetService instance with a mocked session.
    """
    return BudgetService(
        session=mock_db_session,
        budget_repository=mock_budget_repository,
        category_repository=mock_category_repository,
    )


@pytest.fixture
def mock_report_repository(mock_db_session: MagicMock) -> ReportRepository:
    """Create a ReportRepository instance with a mocked session.

    Args:
        mock_db_session: The mock database session.

    Returns:
        A ReportRepository instance with a mocked session.
    """
    return ReportRepository(session=mock_db_session)


@pytest.fixture
def mock_report_service(
    mock_db_session: MagicMock,
    mock_report_repository: ReportRepository,
    mock_household_repository: HouseholdRepository,
    mock_category_repository: CategoryRepository,
    mock_budget_repository: BudgetRepository,
    mock_account_repository: AccountRepository,
) -> ReportService:
    """Create a ReportService instance with a mocked session.

    Args:
        mock_db_session: The mock database session.
        mock_report_repository: The report repository instance.
        mock_household_repository: The household repository instance.
        mock_category_repository: The category repository instance.
        mock_budget_repository: The budget repository instance.
        mock_account_repository: The account repository instance.

    Returns:
        A ReportService instance with a mocked session.
    """
    return ReportService(
        session=mock_db_session,
        report_repository=mock_report_repository,
        household_repository=mock_household_repository,
        category_repository=mock_category_repository,
        budget_repository=mock_budget_repository,
        account_repository=mock_account_repository,
    )


@pytest.fixture
def mock_recurring_rule_repository(mock_db_session: MagicMock) -> RecurringRuleRepository:
    """Create a RecurringRuleRepository instance with a mocked session.

    Args:
        mock_db_session: The mock database session.

    Returns:
        A RecurringRuleRepository instance with a mocked session.
    """
    return RecurringRuleRepository(session=mock_db_session)


@pytest.fixture
def mock_recurring_rule_service(
    mock_db_session: MagicMock,
    mock_recurring_rule_repository: RecurringRuleRepository,
    mock_transaction_repository: TransactionRepository,
    mock_account_repository: AccountRepository,
    mock_category_repository: CategoryRepository,
) -> RecurringRuleService:
    """Create a RecurringRuleService instance with a mocked session.

    Args:
        mock_db_session: The mock database session.
        mock_recurring_rule_repository: The recurring rule repository instance.
        mock_transaction_repository: The transaction repository instance.
        mock_account_repository: The account repository instance.
        mock_category_repository: The category repository instance.

    Returns:
        A RecurringRuleService instance with a mocked session.
    """
    return RecurringRuleService(
        session=mock_db_session,
        recurring_rule_repository=mock_recurring_rule_repository,
        transaction_repository=mock_transaction_repository,
        account_repository=mock_account_repository,
        category_repository=mock_category_repository,
    )
