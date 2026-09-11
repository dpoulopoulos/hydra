from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.core.security import TokenType, decode_token, split_api_token
from app.exceptions import (
    ApiTokenNotPermittedError,
    HouseholdRoleRequiredError,
    UserNotAuthorizedError,
)
from app.exceptions.password_exceptions import InvalidCredentialsError
from app.models import (
    HouseholdContext,
    HouseholdRole,
    IncomeClientFilters,
    IncomeSessionFilters,
    TokenPayload,
    TransactionFilters,
    User,
)
from app.repositories import (
    AccountRepository,
    ApiTokenRepository,
    BudgetRepository,
    CategoryRepository,
    EmailOutboxRepository,
    EmailVerificationRepository,
    FxRateRepository,
    HouseholdInviteRepository,
    HouseholdMemberRepository,
    HouseholdRepository,
    IncomeClientRepository,
    IncomeSessionRepository,
    IncomeVaultRepository,
    InstrumentRepository,
    PasswordResetRepository,
    RecurringRuleRepository,
    ReportRepository,
    TradeRepository,
    TransactionRepository,
    UserRepository,
)
from app.services import (
    AccountService,
    ApiTokenService,
    BudgetService,
    CategoryService,
    EmailOutboxService,
    EmailVerificationService,
    HouseholdService,
    IncomeService,
    InvestmentService,
    LedgerReferenceResolver,
    PasswordResetService,
    RecurringRuleService,
    ReportService,
    TransactionService,
    UserService,
)
from app.services.prices import (
    EodhdProvider,
    FrankfurterFxProvider,
    NullPriceProvider,
    PriceProvider,
    YahooFinanceProvider,
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


def get_ledger_reference_resolver(
    account_repository: AccountRepositoryDep,
    category_repository: CategoryRepositoryDep,
) -> LedgerReferenceResolver:
    """Get a ledger reference resolver instance.

    Args:
        account_repository: The account repository instance.
        category_repository: The category repository instance.

    Returns:
        A ledger reference resolver instance.
    """
    return LedgerReferenceResolver(
        account_repository=account_repository,
        category_repository=category_repository,
    )


LedgerReferenceResolverDep = Annotated[LedgerReferenceResolver, Depends(get_ledger_reference_resolver)]


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
    reference_resolver: LedgerReferenceResolverDep,
) -> TransactionService:
    """Get a transaction service instance.

    Args:
        session: The database session.
        transaction_repository: The transaction repository instance.
        reference_resolver: The ledger reference resolver instance.

    Returns:
        A transaction service instance.
    """
    return TransactionService(
        session=session,
        transaction_repository=transaction_repository,
        reference_resolver=reference_resolver,
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
    user_repository: UserRepositoryDep,
    email_verification_repository: EmailVerificationRepositoryDep,
) -> HouseholdService:
    """Get a household service instance.

    Args:
        session: The database session.
        household_repository: The household repository instance.
        household_member_repository: The household member repository instance.
        household_invite_repository: The household invite repository instance.
        user_repository: The user repository instance.
        email_verification_repository: The email verification repository instance.

    Returns:
        A household service instance.
    """
    return HouseholdService(
        session=session,
        household_repository=household_repository,
        household_member_repository=household_member_repository,
        household_invite_repository=household_invite_repository,
        user_repository=user_repository,
        email_verification_repository=email_verification_repository,
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


def get_api_token_repository(session: SessionDep) -> ApiTokenRepository:
    """Get an API token repository instance.

    Args:
        session: The database session.

    Returns:
        An API token repository instance.
    """
    return ApiTokenRepository(session=session)


ApiTokenRepositoryDep = Annotated[ApiTokenRepository, Depends(get_api_token_repository)]


def get_api_token_service(
    session: SessionDep,
    api_token_repository: ApiTokenRepositoryDep,
    user_repository: UserRepositoryDep,
) -> ApiTokenService:
    """Get an API token service instance.

    Args:
        session: The database session.
        api_token_repository: The API token repository instance.
        user_repository: The user repository instance.

    Returns:
        An API token service instance.
    """
    return ApiTokenService(
        session=session,
        api_token_repository=api_token_repository,
        user_repository=user_repository,
    )


ApiTokenServiceDep = Annotated[ApiTokenService, Depends(get_api_token_service)]


def get_email_outbox_repository(session: SessionDep) -> EmailOutboxRepository:
    """Get an email outbox repository instance.

    Args:
        session: The database session.

    Returns:
        An email outbox repository instance.
    """
    return EmailOutboxRepository(session=session)


EmailOutboxRepositoryDep = Annotated[EmailOutboxRepository, Depends(get_email_outbox_repository)]


def get_email_outbox_service(
    session: SessionDep, email_outbox_repository: EmailOutboxRepositoryDep
) -> EmailOutboxService:
    """Get an email outbox service instance.

    Args:
        session: The database session.
        email_outbox_repository: The email outbox repository instance.

    Returns:
        An email outbox service instance.
    """
    return EmailOutboxService(session=session, email_outbox_repository=email_outbox_repository)


EmailOutboxServiceDep = Annotated[EmailOutboxService, Depends(get_email_outbox_service)]


TokenDep = Annotated[str, Depends(reusable_oauth2)]


def get_current_user(
    request: Request,
    user_service: UserServiceDep,
    api_token_service: ApiTokenServiceDep,
    token: TokenDep,
) -> User:
    """Get the current authenticated user, from a session token or an API token.

    Two kinds of credential arrive at the same place, and which one was
    presented is decided by the shape of the string rather than by a second
    header: a JWT is base64url of a JSON header, so it cannot carry the API
    token prefix.

    Resolving both here is what lets every existing route accept an API token
    without being edited, and keeps the household scope derived from the
    membership row either way. It is also the one place a read scoped token can
    be stopped from making a request that changes something, so a route added
    later is covered without being told that scopes exist.

    Args:
        request: The incoming request, whose method decides what a read scoped
            token may do.
        user_service: The user service instance.
        api_token_service: The API token service instance.
        token: The OAuth2 bearer token.

    Returns:
        The authenticated user.

    Raises:
        InvalidCredentialsError: If the session token is invalid or expired.
        InvalidApiTokenError: If the API token does not check out.
        ApiTokenReadOnlyError: If a read scoped token is changing something.
        UserNotFoundError: If the user associated with the token is not found.
        UserNotAuthorizedError: If the user is inactive.
    """
    if split_api_token(token) is not None:
        user = api_token_service.authenticate_request(credential=token, method=request.method)
        request.state.api_token_authenticated = True
        return user

    request.state.api_token_authenticated = False

    try:
        payload = decode_token(token, expected_type=TokenType.SESSION)
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError) as exc:
        raise InvalidCredentialsError from exc

    return user_service.get_authenticated_user(token_data=token_data)


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_session_user(request: Request, current_user: CurrentUser) -> User:
    """Require that the request was authenticated with a session, not an API token.

    Minting a credential, revoking one, changing the password or the address
    behind them, and giving somebody access to the household are the operations
    that would let a leaked API token entrench itself, so they stay with the
    browser session. Everything else a token may do is decided by its scope.

    Which kind of credential arrived is read off the request rather than by
    inspecting the bearer token a second time, so this depends on nothing but
    the answer :func:`get_current_user` already worked out.

    Args:
        request: The incoming request, carrying how it was authenticated.
        current_user: The current user.

    Returns:
        The current user.

    Raises:
        ApiTokenNotPermittedError: If the request was authenticated with an API token.
    """
    if getattr(request.state, "api_token_authenticated", False):
        raise ApiTokenNotPermittedError from None

    return current_user


SessionUser = Annotated[User, Depends(get_session_user)]


def get_current_active_superuser(current_user: SessionUser) -> User:
    """Get the current active superuser.

    A browser session, not an API token. These routes create users, set any
    user's password and delete accounts, so a token that reached them could
    mint a second superuser it knows the password of, or take its own owner's
    account away. That is the entrenchment session-only exists to stop, and a
    superuser's token is the one most worth stealing.

    Args:
        current_user: The signed-in user, from a browser session.

    Returns:
        The current active superuser.

    Raises:
        ApiTokenNotPermittedError: If the request was authenticated with an API token.
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


def get_account_service(
    session: SessionDep,
    account_repository: AccountRepositoryDep,
    household_repository: HouseholdRepositoryDep,
    transaction_repository: TransactionRepositoryDep,
    recurring_rule_repository: RecurringRuleRepositoryDep,
) -> AccountService:
    """Get an account service instance.

    Args:
        session: The database session.
        account_repository: The account repository instance.
        household_repository: The household repository instance.
        transaction_repository: The transaction repository instance.
        recurring_rule_repository: The recurring rule repository instance.

    Returns:
        An account service instance.
    """
    return AccountService(
        session=session,
        account_repository=account_repository,
        household_repository=household_repository,
        transaction_repository=transaction_repository,
        recurring_rule_repository=recurring_rule_repository,
    )


AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]


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
    reference_resolver: LedgerReferenceResolverDep,
) -> RecurringRuleService:
    """Get a recurring rule service instance.

    Args:
        session: The database session.
        recurring_rule_repository: The recurring rule repository instance.
        transaction_repository: The transaction repository instance.
        reference_resolver: The ledger reference resolver instance.

    Returns:
        A recurring rule service instance.
    """
    return RecurringRuleService(
        session=session,
        recurring_rule_repository=recurring_rule_repository,
        transaction_repository=transaction_repository,
        reference_resolver=reference_resolver,
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


def get_instrument_repository(session: SessionDep) -> InstrumentRepository:
    """Get an instrument repository instance.

    Args:
        session: The database session.

    Returns:
        An instrument repository instance.
    """
    return InstrumentRepository(session=session)


InstrumentRepositoryDep = Annotated[InstrumentRepository, Depends(get_instrument_repository)]


def get_trade_repository(session: SessionDep) -> TradeRepository:
    """Get a trade repository instance.

    Args:
        session: The database session.

    Returns:
        A trade repository instance.
    """
    return TradeRepository(session=session)


TradeRepositoryDep = Annotated[TradeRepository, Depends(get_trade_repository)]


def get_fx_rate_repository(session: SessionDep) -> FxRateRepository:
    """Get an FX rate repository instance.

    Args:
        session: The database session.

    Returns:
        An FX rate repository instance.
    """
    return FxRateRepository(session=session)


FxRateRepositoryDep = Annotated[FxRateRepository, Depends(get_fx_rate_repository)]


def get_price_provider() -> PriceProvider:
    """Get the configured source of market prices.

    Returns:
        The provider named in the settings, or one that refuses every call when
        market data is switched off.
    """
    if settings.MARKET_DATA_PROVIDER == "eodhd":
        # No key means no provider, rather than a provider that fails on every
        # call. The difference is what the caller is told: "market data is not
        # set up" points at the missing setting, where "the provider refused"
        # points at the provider.
        if not settings.EODHD_API_KEY:
            return NullPriceProvider()

        return EodhdProvider(
            api_key=settings.EODHD_API_KEY,
            base_url=settings.EODHD_BASE_URL,
            timeout_seconds=settings.MARKET_DATA_TIMEOUT_SECONDS,
            fx_provider=FrankfurterFxProvider(
                base_url=settings.FRANKFURTER_BASE_URL,
                timeout_seconds=settings.MARKET_DATA_TIMEOUT_SECONDS,
            ),
        )

    if settings.MARKET_DATA_PROVIDER == "yahoo":
        return YahooFinanceProvider(
            base_url=settings.YAHOO_FINANCE_BASE_URL,
            search_url=settings.YAHOO_FINANCE_SEARCH_URL,
            timeout_seconds=settings.MARKET_DATA_TIMEOUT_SECONDS,
            user_agent=settings.MARKET_DATA_USER_AGENT,
        )

    return NullPriceProvider()


PriceProviderDep = Annotated[PriceProvider, Depends(get_price_provider)]


def get_investment_service(
    session: SessionDep,
    instrument_repository: InstrumentRepositoryDep,
    trade_repository: TradeRepositoryDep,
    fx_rate_repository: FxRateRepositoryDep,
    household_repository: HouseholdRepositoryDep,
    price_provider: PriceProviderDep,
    account_repository: AccountRepositoryDep,
) -> InvestmentService:
    """Get an investment service instance.

    Args:
        session: The database session.
        instrument_repository: The instrument repository instance.
        trade_repository: The trade repository instance.
        fx_rate_repository: The FX rate repository instance.
        household_repository: The household repository instance.
        price_provider: The configured source of market prices.
        account_repository: The account repository instance.

    Returns:
        An investment service instance.
    """
    return InvestmentService(
        session=session,
        instrument_repository=instrument_repository,
        trade_repository=trade_repository,
        fx_rate_repository=fx_rate_repository,
        household_repository=household_repository,
        price_provider=price_provider,
        account_repository=account_repository,
        price_cache_hours=settings.MARKET_DATA_CACHE_HOURS,
    )


InvestmentServiceDep = Annotated[InvestmentService, Depends(get_investment_service)]


IncomeClientFiltersDep = Annotated[IncomeClientFilters, Query()]
IncomeSessionFiltersDep = Annotated[IncomeSessionFilters, Query()]


def get_income_client_repository(session: SessionDep) -> IncomeClientRepository:
    """Get an income client repository instance.

    Args:
        session: The database session.

    Returns:
        An income client repository instance.
    """
    return IncomeClientRepository(session=session)


IncomeClientRepositoryDep = Annotated[IncomeClientRepository, Depends(get_income_client_repository)]


def get_income_session_repository(session: SessionDep) -> IncomeSessionRepository:
    """Get an income session repository instance.

    Args:
        session: The database session.

    Returns:
        An income session repository instance.
    """
    return IncomeSessionRepository(session=session)


IncomeSessionRepositoryDep = Annotated[IncomeSessionRepository, Depends(get_income_session_repository)]


def get_income_vault_repository(session: SessionDep) -> IncomeVaultRepository:
    """Get an income vault repository instance.

    Args:
        session: The database session.

    Returns:
        An income vault repository instance.
    """
    return IncomeVaultRepository(session=session)


IncomeVaultRepositoryDep = Annotated[IncomeVaultRepository, Depends(get_income_vault_repository)]


def get_income_service(
    session: SessionDep,
    income_client_repository: IncomeClientRepositoryDep,
    income_session_repository: IncomeSessionRepositoryDep,
    income_vault_repository: IncomeVaultRepositoryDep,
    transaction_repository: TransactionRepositoryDep,
    account_repository: AccountRepositoryDep,
    category_repository: CategoryRepositoryDep,
    household_repository: HouseholdRepositoryDep,
) -> IncomeService:
    """Get an income service instance.

    Args:
        session: The database session.
        income_client_repository: The client repository instance.
        income_session_repository: The session repository instance.
        income_vault_repository: The vault repository instance.
        transaction_repository: The transaction repository instance.
        account_repository: The account repository instance.
        category_repository: The category repository instance.
        household_repository: The household repository instance.

    Returns:
        An income service instance.
    """
    return IncomeService(
        session=session,
        income_client_repository=income_client_repository,
        income_session_repository=income_session_repository,
        income_vault_repository=income_vault_repository,
        transaction_repository=transaction_repository,
        account_repository=account_repository,
        category_repository=category_repository,
        household_repository=household_repository,
    )


IncomeServiceDep = Annotated[IncomeService, Depends(get_income_service)]
