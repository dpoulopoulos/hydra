from sqlmodel import Session

from app.core.db import engine, init_db
from app.logging import get_logger
from app.repositories import (
    BudgetRepository,
    CategoryRepository,
    HouseholdInviteRepository,
    HouseholdMemberRepository,
    HouseholdRepository,
    RecurringRuleRepository,
    TransactionRepository,
    UserRepository,
)
from app.services import CategoryService, HouseholdService, UserService

logger = get_logger(__name__)


def init() -> None:
    """Initialize the database."""
    with Session(engine) as session:
        user_repository = UserRepository(session=session)
        user_service = UserService(session=session, user_repository=user_repository)
        household_service = HouseholdService(
            session=session,
            household_repository=HouseholdRepository(session=session),
            household_member_repository=HouseholdMemberRepository(session=session),
            household_invite_repository=HouseholdInviteRepository(session=session),
        )
        category_service = CategoryService(
            session=session,
            category_repository=CategoryRepository(session=session),
            transaction_repository=TransactionRepository(session=session),
            budget_repository=BudgetRepository(session=session),
            recurring_rule_repository=RecurringRuleRepository(session=session),
        )
        init_db(
            user_service=user_service,
            household_service=household_service,
            category_service=category_service,
        )


def main() -> None:
    """Create initial data."""
    logger.info("Creating initial data")
    init()
    logger.info("Initial data created")


if __name__ == "__main__":
    main()
