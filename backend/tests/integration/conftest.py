"""Fixtures for the tests that run against a real Postgres.

The unit suite mocks the database session, so no SQL it builds is ever
executed. Everything that lives in SQL or in a database constraint --
household scoping, ``CHECK`` and ``RESTRICT`` constraints, the sign convention
of the money aggregations -- is therefore unverified by it. These tests fill
that gap by talking to a server.

The schema comes from ``SQLModel.metadata`` rather than from Alembic: the
migrations workflow already runs ``alembic check``, which fails when the models
and the migrations disagree, so creating from the metadata cannot drift from
what a migrated database looks like and costs one statement instead of a
revision walk.

Each test runs inside a transaction on its own connection, which is rolled back
afterwards. The services under test call ``commit()``; ``join_transaction_mode``
turns those into savepoint releases, so a test sees its own writes and still
leaves the database as it found it.

The one thing to keep in mind is the mirror image of that: a service
``rollback()`` releases the savepoint the other way and discards everything
written since the last commit, including rows the test itself seeded. A test
that exercises a path which rolls back should therefore commit its fixture data
first, or assert on what the rollback leaves behind rather than on the seed.
"""

import datetime
import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import Connection, Engine, create_engine, text
from sqlmodel import Session, SQLModel

from app.core.config import settings
from app.models import (
    Account,
    AccountType,
    Category,
    CategoryKind,
    Household,
    HouseholdContext,
    HouseholdMember,
    HouseholdRole,
    User,
)
from app.repositories import (
    AccountRepository,
    BudgetRepository,
    CategoryRepository,
    EmailVerificationRepository,
    HouseholdInviteRepository,
    HouseholdMemberRepository,
    HouseholdRepository,
    RecurringRuleRepository,
    ReportRepository,
    TransactionRepository,
    UserRepository,
)
from app.services import (
    AccountService,
    BudgetService,
    CategoryService,
    HouseholdService,
    LedgerReferenceResolver,
    RecurringRuleService,
    ReportService,
    TransactionService,
)

# The suite owns its database rather than the one the application uses, so
# running it cannot drop the rows of a local development stack.
TEST_DATABASE_SUFFIX = "_integration"


def _database_url(database: str) -> str:
    """Build a connection URL for a database on the configured server.

    Args:
        database: The name of the database to connect to.

    Returns:
        The URL of that database on the server the settings point at.
    """
    return str(settings.SQLALCHEMY_DATABASE_URI).rsplit("/", 1)[0] + f"/{database}"


@pytest.fixture(scope="session")
def engine() -> Generator[Engine]:
    """Create the test database and the schema in it.

    Yields:
        An engine bound to a database holding an empty, current schema.
    """
    database = f"{settings.POSTGRES_DB}{TEST_DATABASE_SUFFIX}"

    # CREATE DATABASE cannot run inside a transaction block, hence autocommit,
    # and it needs a connection to some other database to run from.
    admin = create_engine(_database_url("postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        exists = connection.execute(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": database}).first()
        if not exists:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
    admin.dispose()

    test_engine = create_engine(_database_url(database))
    SQLModel.metadata.drop_all(test_engine)
    SQLModel.metadata.create_all(test_engine)

    yield test_engine

    test_engine.dispose()


@pytest.fixture
def connection(engine: Engine) -> Generator[Connection]:
    """Open a connection whose transaction is rolled back after the test.

    Args:
        engine: The engine bound to the test database.

    Yields:
        A connection with an open transaction.
    """
    with engine.connect() as open_connection:
        transaction = open_connection.begin()
        yield open_connection
        transaction.rollback()


@pytest.fixture
def db_session(connection: Connection) -> Generator[Session]:
    """Create a session that the services can commit on without persisting.

    A service ``rollback()`` unwinds to the outer savepoint and takes the rows
    the test seeded with it, so seed through a commit when the path under test
    rolls back.

    Args:
        connection: The connection whose transaction wraps the test.

    Yields:
        A session bound to that connection.
    """
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        yield session


def make_household(session: Session, name: str, email: str) -> HouseholdContext:
    """Seed a household with one owner and return its context.

    Args:
        session: The database session.
        name: The name of the household.
        email: The email address of the owner to create.

    Returns:
        The context an owner of the new household would be given.
    """
    user = User(email=email, full_name=name, hashed_password="not-a-real-hash", is_active=True)
    household = Household(name=name)
    session.add(user)
    session.add(household)
    session.flush()

    membership = HouseholdMember(household_id=household.id, user_id=user.id, role=HouseholdRole.OWNER)
    session.add(membership)
    session.flush()

    return HouseholdContext(user=user, household_id=household.id, membership_id=membership.id, role=HouseholdRole.OWNER)


@pytest.fixture
def household_a(db_session: Session) -> HouseholdContext:
    """Seed the household the tests act as.

    Args:
        db_session: The database session.

    Returns:
        The context of a household owner.
    """
    return make_household(db_session, name="Household A", email="owner-a@example.com")


@pytest.fixture
def household_b(db_session: Session) -> HouseholdContext:
    """Seed the second household, whose rows must stay invisible to the first.

    Args:
        db_session: The database session.

    Returns:
        The context of the owner of another household.
    """
    return make_household(db_session, name="Household B", email="owner-b@example.com")


@pytest.fixture
def account_repository(db_session: Session) -> AccountRepository:
    """Build an account repository on the real session.

    Args:
        db_session: The database session.

    Returns:
        An account repository.
    """
    return AccountRepository(session=db_session)


@pytest.fixture
def budget_repository(db_session: Session) -> BudgetRepository:
    """Build a budget repository on the real session.

    Args:
        db_session: The database session.

    Returns:
        A budget repository.
    """
    return BudgetRepository(session=db_session)


@pytest.fixture
def category_repository(db_session: Session) -> CategoryRepository:
    """Build a category repository on the real session.

    Args:
        db_session: The database session.

    Returns:
        A category repository.
    """
    return CategoryRepository(session=db_session)


@pytest.fixture
def household_repository(db_session: Session) -> HouseholdRepository:
    """Build a household repository on the real session.

    Args:
        db_session: The database session.

    Returns:
        A household repository.
    """
    return HouseholdRepository(session=db_session)


@pytest.fixture
def recurring_rule_repository(db_session: Session) -> RecurringRuleRepository:
    """Build a recurring rule repository on the real session.

    Args:
        db_session: The database session.

    Returns:
        A recurring rule repository.
    """
    return RecurringRuleRepository(session=db_session)


@pytest.fixture
def transaction_repository(db_session: Session) -> TransactionRepository:
    """Build a transaction repository on the real session.

    Args:
        db_session: The database session.

    Returns:
        A transaction repository.
    """
    return TransactionRepository(session=db_session)


@pytest.fixture
def user_repository(db_session: Session) -> UserRepository:
    """Build a user repository on the real session.

    Args:
        db_session: The database session.

    Returns:
        A user repository.
    """
    return UserRepository(session=db_session)


@pytest.fixture
def email_verification_repository(db_session: Session) -> EmailVerificationRepository:
    """Build an email verification repository on the real session.

    Args:
        db_session: The database session.

    Returns:
        An email verification repository.
    """
    return EmailVerificationRepository(session=db_session)


@pytest.fixture
def account_service(
    db_session: Session, account_repository: AccountRepository, household_repository: HouseholdRepository
) -> AccountService:
    """Build an account service on the real session.

    Args:
        db_session: The database session.
        account_repository: The account repository.
        household_repository: The household repository.

    Returns:
        An account service.
    """
    return AccountService(
        session=db_session, account_repository=account_repository, household_repository=household_repository
    )


@pytest.fixture
def category_service(
    db_session: Session,
    category_repository: CategoryRepository,
    transaction_repository: TransactionRepository,
    budget_repository: BudgetRepository,
    recurring_rule_repository: RecurringRuleRepository,
) -> CategoryService:
    """Build a category service on the real session.

    Args:
        db_session: The database session.
        category_repository: The category repository.
        transaction_repository: The transaction repository.
        budget_repository: The budget repository.
        recurring_rule_repository: The recurring rule repository.

    Returns:
        A category service.
    """
    return CategoryService(
        session=db_session,
        category_repository=category_repository,
        transaction_repository=transaction_repository,
        budget_repository=budget_repository,
        recurring_rule_repository=recurring_rule_repository,
    )


@pytest.fixture
def reference_resolver(
    account_repository: AccountRepository,
    category_repository: CategoryRepository,
) -> LedgerReferenceResolver:
    """Build a ledger reference resolver on the real session.

    Args:
        account_repository: The account repository.
        category_repository: The category repository.

    Returns:
        A ledger reference resolver.
    """
    return LedgerReferenceResolver(
        account_repository=account_repository,
        category_repository=category_repository,
    )


@pytest.fixture
def transaction_service(
    db_session: Session,
    transaction_repository: TransactionRepository,
    reference_resolver: LedgerReferenceResolver,
) -> TransactionService:
    """Build a transaction service on the real session.

    Args:
        db_session: The database session.
        transaction_repository: The transaction repository.
        reference_resolver: The ledger reference resolver.

    Returns:
        A transaction service.
    """
    return TransactionService(
        session=db_session,
        transaction_repository=transaction_repository,
        reference_resolver=reference_resolver,
    )


@pytest.fixture
def budget_service(
    db_session: Session, budget_repository: BudgetRepository, category_repository: CategoryRepository
) -> BudgetService:
    """Build a budget service on the real session.

    Args:
        db_session: The database session.
        budget_repository: The budget repository.
        category_repository: The category repository.

    Returns:
        A budget service.
    """
    return BudgetService(
        session=db_session, budget_repository=budget_repository, category_repository=category_repository
    )


@pytest.fixture
def recurring_rule_service(
    db_session: Session,
    recurring_rule_repository: RecurringRuleRepository,
    transaction_repository: TransactionRepository,
    reference_resolver: LedgerReferenceResolver,
) -> RecurringRuleService:
    """Build a recurring rule service on the real session.

    Args:
        db_session: The database session.
        recurring_rule_repository: The recurring rule repository.
        transaction_repository: The transaction repository.
        reference_resolver: The ledger reference resolver.

    Returns:
        A recurring rule service.
    """
    return RecurringRuleService(
        session=db_session,
        recurring_rule_repository=recurring_rule_repository,
        transaction_repository=transaction_repository,
        reference_resolver=reference_resolver,
    )


@pytest.fixture
def report_service(
    db_session: Session,
    household_repository: HouseholdRepository,
    category_repository: CategoryRepository,
    budget_repository: BudgetRepository,
    account_repository: AccountRepository,
) -> ReportService:
    """Build a report service on the real session.

    Args:
        db_session: The database session.
        household_repository: The household repository.
        category_repository: The category repository.
        budget_repository: The budget repository.
        account_repository: The account repository.

    Returns:
        A report service.
    """
    return ReportService(
        session=db_session,
        report_repository=ReportRepository(session=db_session),
        household_repository=household_repository,
        category_repository=category_repository,
        budget_repository=budget_repository,
        account_repository=account_repository,
    )


@pytest.fixture
def household_service(
    db_session: Session,
    household_repository: HouseholdRepository,
    household_member_repository: HouseholdMemberRepository,
    household_invite_repository: HouseholdInviteRepository,
    user_repository: UserRepository,
    email_verification_repository: EmailVerificationRepository,
) -> HouseholdService:
    """Build a household service on the real session.

    Args:
        db_session: The database session.
        household_repository: The household repository.
        household_member_repository: The household member repository.
        household_invite_repository: The household invite repository.
        user_repository: The user repository.
        email_verification_repository: The email verification repository.

    Returns:
        A household service.
    """
    return HouseholdService(
        session=db_session,
        household_repository=household_repository,
        household_member_repository=household_member_repository,
        household_invite_repository=household_invite_repository,
        user_repository=user_repository,
        email_verification_repository=email_verification_repository,
    )


@pytest.fixture
def household_member_repository(db_session: Session) -> HouseholdMemberRepository:
    """Build a household member repository on the real session.

    Args:
        db_session: The database session.

    Returns:
        A household member repository.
    """
    return HouseholdMemberRepository(session=db_session)


@pytest.fixture
def household_invite_repository(db_session: Session) -> HouseholdInviteRepository:
    """Build a household invite repository on the real session.

    Args:
        db_session: The database session.

    Returns:
        A household invite repository.
    """
    return HouseholdInviteRepository(session=db_session)


def make_account(
    session: Session,
    household_id: uuid.UUID,
    name: str = "Checking",
    opening_balance_minor: int = 0,
    opening_balance_date: datetime.date = datetime.date(2024, 1, 1),
) -> Account:
    """Seed an account directly, bypassing the service.

    Args:
        session: The database session.
        household_id: The household that owns the account.
        name: The name of the account.
        opening_balance_minor: The balance it held before tracking started.
        opening_balance_date: The date that balance was taken on.

    Returns:
        The stored account.
    """
    account = Account(
        household_id=household_id,
        name=name,
        type=AccountType.CURRENT,
        opening_balance_minor=opening_balance_minor,
        opening_balance_date=opening_balance_date,
    )
    session.add(account)
    session.flush()
    return account


def make_category(
    session: Session,
    household_id: uuid.UUID,
    name: str = "Groceries",
    kind: CategoryKind = CategoryKind.EXPENSE,
    parent_id: uuid.UUID | None = None,
) -> Category:
    """Seed a category directly, bypassing the service.

    Args:
        session: The database session.
        household_id: The household that owns the category.
        name: The name of the category.
        kind: Whether it files expenses or income.
        parent_id: The parent category, for a subcategory.

    Returns:
        The stored category.
    """
    category = Category(household_id=household_id, name=name, kind=kind, parent_id=parent_id)
    session.add(category)
    session.flush()
    return category
