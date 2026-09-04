from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Query
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.core.security import TokenType, decode_token
from app.exceptions import HouseholdRoleRequiredError, UserNotAuthorizedError
from app.exceptions.password_exceptions import InvalidCredentialsError
from app.models import HouseholdContext, HouseholdRole, TokenPayload, TransactionFilters, User
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

reusable_oauth2 = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/login/access-token")


def get_db() -> Generator[Session]:
    """Get a database session.

    Yields:
        A database session.
    """
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]


def get_user_repository(session: SessionDep) -> UserRepository:
    """Get a user repository instance.

    Args:
        session: The database session.

    Returns:
        A user repository instance.
    """
    return UserRepository(session=session)


UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]


def get_password_reset_repository(session: SessionDep) -> PasswordResetRepository:
    """Get a password reset repository instance.

    Args:
        session: The database session.

    Returns:
        A password reset repository instance.
    """
    return PasswordResetRepository(session=session)


PasswordResetRepositoryDep = Annotated[PasswordResetRepository, Depends(get_password_reset_repository)]


def get_email_verification_repository(session: SessionDep) -> EmailVerificationRepository:
    """Get an email verification repository instance.

    Args:
        session: The database session.

    Returns:
        An email verification repository instance.
    """
    return EmailVerificationRepository(session=session)


EmailVerificationRepositoryDep = Annotated[EmailVerificationRepository, Depends(get_email_verification_repository)]


def get_account_repository(session: SessionDep) -> AccountRepository:
    """Get an account repository instance.

    Args:
        session: The database session.

    Returns:
        An account repository instance.
    """
    return AccountRepository(session=session)


AccountRepositoryDep = Annotated[AccountRepository, Depends(get_account_repository)]


def get_category_repository(session: SessionDep) -> CategoryRepository:
    """Get a category repository instance.

    Args:
        session: The database session.

    Returns:
        A category repository instance.
    """
    return CategoryRepository(session=session)


CategoryRepositoryDep = Annotated[CategoryRepository, Depends(get_category_repository)]


def get_budget_repository(session: SessionDep) -> BudgetRepository:
    """Get a budget repository instance.

    Args:
        session: The database session.

    Returns:
        A budget repository instance.
    """
    return BudgetRepository(session=session)


BudgetRepositoryDep = Annotated[BudgetRepository, Depends(get_budget_repository)]


def get_budget_service(
    session: SessionDep,
    budget_repository: BudgetRepositoryDep,
    category_repository: CategoryRepositoryDep,
) -> BudgetService:
    """Get a budget service instance.

    Args:
        session: The database session.
        budget_repository: The budget repository instance.
        category_repository: The category repository instance.

    Returns:
        A budget service instance.
    """
    return BudgetService(
        session=session,
        budget_repository=budget_repository,
        category_repository=category_repository,
    )


BudgetServiceDep = Annotated[BudgetService, Depends(get_budget_service)]


def get_transaction_repository(session: SessionDep) -> TransactionRepository:
    """Get a transaction repository instance.

    Args:
        session: The database session.

    Returns:
        A transaction repository instance.
    """
    return TransactionRepository(session=session)


TransactionRepositoryDep = Annotated[TransactionRepository, Depends(get_transaction_repository)]


def get_transaction_service(
    session: SessionDep,
    transaction_repository: TransactionRepositoryDep,
    account_repository: AccountRepositoryDep,
    category_repository: CategoryRepositoryDep,
) -> TransactionService:
    """Get a transaction service instance.

    Args:
        session: The database session.
        transaction_repository: The transaction repository instance.
        account_repository: The account repository instance.
        category_repository: The category repository instance.

    Returns:
        A transaction service instance.
    """
    return TransactionService(
        session=session,
        transaction_repository=transaction_repository,
        account_repository=account_repository,
        category_repository=category_repository,
    )


TransactionServiceDep = Annotated[TransactionService, Depends(get_transaction_service)]


def get_household_repository(session: SessionDep) -> HouseholdRepository:
    """Get a household repository instance.

    Args:
        session: The database session.

    Returns:
        A household repository instance.
    """
    return HouseholdRepository(session=session)


HouseholdRepositoryDep = Annotated[HouseholdRepository, Depends(get_household_repository)]


def get_household_member_repository(session: SessionDep) -> HouseholdMemberRepository:
    """Get a household member repository instance.

    Args:
        session: The database session.

    Returns:
        A household member repository instance.
    """
    return HouseholdMemberRepository(session=session)


HouseholdMemberRepositoryDep = Annotated[HouseholdMemberRepository, Depends(get_household_member_repository)]


def get_account_service(
    session: SessionDep,
    account_repository: AccountRepositoryDep,
    household_repository: HouseholdRepositoryDep,
) -> AccountService:
    """Get an account service instance.

    Args:
        session: The database session.
        account_repository: The account repository instance.
        household_repository: The household repository instance.

    Returns:
        An account service instance.
    """
    return AccountService(
        session=session,
        account_repository=account_repository,
        household_repository=household_repository,
    )


AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]


def get_household_invite_repository(session: SessionDep) -> HouseholdInviteRepository:
    """Get a household invite repository instance.

    Args:
        session: The database session.

    Returns:
        A household invite repository instance.
    """
    return HouseholdInviteRepository(session=session)


HouseholdInviteRepositoryDep = Annotated[HouseholdInviteRepository, Depends(get_household_invite_repository)]


def get_household_service(
    session: SessionDep,
    household_repository: HouseholdRepositoryDep,
    household_member_repository: HouseholdMemberRepositoryDep,
    household_invite_repository: HouseholdInviteRepositoryDep,
) -> HouseholdService:
    """Get a household service instance.

    Args:
        session: The database session.
        household_repository: The household repository instance.
        household_member_repository: The household member repository instance.
        household_invite_repository: The household invite repository instance.

    Returns:
        A household service instance.
    """
    return HouseholdService(
        session=session,
        household_repository=household_repository,
        household_member_repository=household_member_repository,
        household_invite_repository=household_invite_repository,
    )


HouseholdServiceDep = Annotated[HouseholdService, Depends(get_household_service)]


def get_user_service(session: SessionDep, user_repository: UserRepositoryDep) -> UserService:
    """Get a user service instance.

    Args:
        session: The database session.
        user_repository: The user repository instance.

    Returns:
        A user service instance.
    """
    return UserService(session=session, user_repository=user_repository)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]


def get_password_reset_service(
    session: SessionDep, password_reset_repository: PasswordResetRepositoryDep
) -> PasswordResetService:
    """Get a password reset service instance.

    Args:
        session: The database session.
        password_reset_repository: The password reset repository instance.

    Returns:
        A password reset service instance.
    """
    return PasswordResetService(session=session, password_reset_repository=password_reset_repository)


PasswordResetServiceDep = Annotated[PasswordResetService, Depends(get_password_reset_service)]


def get_email_verification_service(
    session: SessionDep, email_verification_repository: EmailVerificationRepositoryDep
) -> EmailVerificationService:
    """Get an email verification service instance.

    Args:
        session: The database session.
        email_verification_repository: The email verification repository instance.

    Returns:
        An email verification service instance.
    """
    return EmailVerificationService(session=session, email_verification_repository=email_verification_repository)


EmailVerificationServiceDep = Annotated[EmailVerificationService, Depends(get_email_verification_service)]


TokenDep = Annotated[str, Depends(reusable_oauth2)]


def get_current_user(user_service: UserServiceDep, token: TokenDep) -> User:
    """Get the current authenticated user.

    Args:
        user_service: The user service instance.
        token: The OAuth2 bearer token.

    Returns:
        The authenticated user.

    Raises:
        InvalidCredentialsError: If the token is invalid or expired.
        UserNotFoundError: If the user associated with the token is not found.
        UserNotAuthorizedError: If the user is inactive.
    """
    try:
        payload = decode_token(token, expected_type=TokenType.SESSION)
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError) as exc:
        raise InvalidCredentialsError from exc

    return user_service.get_authenticated_user(token_data=token_data)


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_active_superuser(current_user: CurrentUser) -> User:
    """Get the current active superuser.

    Args:
        current_user: The current user.

    Returns:
        The current active superuser.

    Raises:
        UserNotAuthorizedError: If the user is not a superuser.
    """
    if not current_user.is_superuser:
        raise UserNotAuthorizedError(current_user)

    return current_user


def get_recurring_rule_repository(session: SessionDep) -> RecurringRuleRepository:
    """Get a recurring rule repository instance.

    Args:
        session: The database session.

    Returns:
        A recurring rule repository instance.
    """
    return RecurringRuleRepository(session=session)


RecurringRuleRepositoryDep = Annotated[RecurringRuleRepository, Depends(get_recurring_rule_repository)]


def get_category_service(
    session: SessionDep,
    category_repository: CategoryRepositoryDep,
    transaction_repository: TransactionRepositoryDep,
    budget_repository: BudgetRepositoryDep,
    recurring_rule_repository: RecurringRuleRepositoryDep,
) -> CategoryService:
    """Get a category service instance.

    Args:
        session: The database session.
        category_repository: The category repository instance.
        transaction_repository: The transaction repository instance.
        budget_repository: The budget repository instance.
        recurring_rule_repository: The recurring rule repository instance.

    Returns:
        A category service instance.
    """
    return CategoryService(
        session=session,
        category_repository=category_repository,
        transaction_repository=transaction_repository,
        budget_repository=budget_repository,
        recurring_rule_repository=recurring_rule_repository,
    )


CategoryServiceDep = Annotated[CategoryService, Depends(get_category_service)]


def get_recurring_rule_service(
    session: SessionDep,
    recurring_rule_repository: RecurringRuleRepositoryDep,
    transaction_repository: TransactionRepositoryDep,
    account_repository: AccountRepositoryDep,
    category_repository: CategoryRepositoryDep,
) -> RecurringRuleService:
    """Get a recurring rule service instance.

    Args:
        session: The database session.
        recurring_rule_repository: The recurring rule repository instance.
        transaction_repository: The transaction repository instance.
        account_repository: The account repository instance.
        category_repository: The category repository instance.

    Returns:
        A recurring rule service instance.
    """
    return RecurringRuleService(
        session=session,
        recurring_rule_repository=recurring_rule_repository,
        transaction_repository=transaction_repository,
        account_repository=account_repository,
        category_repository=category_repository,
    )


RecurringRuleServiceDep = Annotated[RecurringRuleService, Depends(get_recurring_rule_service)]


def get_report_repository(session: SessionDep) -> ReportRepository:
    """Get a report repository instance.

    Args:
        session: The database session.

    Returns:
        A report repository instance.
    """
    return ReportRepository(session=session)


ReportRepositoryDep = Annotated[ReportRepository, Depends(get_report_repository)]


def get_report_service(
    session: SessionDep,
    report_repository: ReportRepositoryDep,
    household_repository: HouseholdRepositoryDep,
    category_repository: CategoryRepositoryDep,
    budget_repository: BudgetRepositoryDep,
    account_repository: AccountRepositoryDep,
) -> ReportService:
    """Get a report service instance.

    Args:
        session: The database session.
        report_repository: The report repository instance.
        household_repository: The household repository instance.
        category_repository: The category repository instance.
        budget_repository: The budget repository instance.
        account_repository: The account repository instance.

    Returns:
        A report service instance.
    """
    return ReportService(
        session=session,
        report_repository=report_repository,
        household_repository=household_repository,
        category_repository=category_repository,
        budget_repository=budget_repository,
        account_repository=account_repository,
    )


ReportServiceDep = Annotated[ReportService, Depends(get_report_service)]


def get_household_context(current_user: CurrentUser, household_service: HouseholdServiceDep) -> HouseholdContext:
    """Resolve the household scope of the current request.

    The household is derived from the membership row rather than from the token,
    so joining a different household takes effect without logging in again.

    Args:
        current_user: The current user.
        household_service: The household service instance.

    Returns:
        The household context of the request.

    Raises:
        HouseholdMembershipNotFoundError: If the user belongs to no household.
    """
    return household_service.get_context(user=current_user)


CurrentHousehold = Annotated[HouseholdContext, Depends(get_household_context)]


def get_household_owner(household: CurrentHousehold) -> HouseholdContext:
    """Require that the current user owns their household.

    Args:
        household: The current household context.

    Returns:
        The household context.

    Raises:
        HouseholdRoleRequiredError: If the user is not an owner of the household.
    """
    if not household.is_owner:
        raise HouseholdRoleRequiredError(role=HouseholdRole.OWNER)

    return household


OwnerHousehold = Annotated[HouseholdContext, Depends(get_household_owner)]


TransactionFiltersDep = Annotated[TransactionFilters, Query()]
