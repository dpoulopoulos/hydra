import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentHousehold, CurrentUser, InvestmentServiceDep, get_household_context
from app.exceptions import (
    InstrumentExistsError,
    InstrumentInUseError,
    InstrumentNotFoundError,
    InstrumentNotPriceableError,
    InsufficientUnitsError,
    NotABrokerageAccountError,
    PriceProviderError,
    PriceProviderNotConfiguredError,
    ServiceError,
    TradeNotConvertibleError,
    TradeNotFoundError,
)
from app.models import (
    FxRatesPublic,
    InstrumentCreate,
    InstrumentPriceUpdate,
    InstrumentPublic,
    InstrumentsPublic,
    InstrumentUpdate,
    Message,
    PortfolioPublic,
    PriceRefreshResult,
    SymbolMatchesPublic,
    TradeCreate,
    TradePublic,
    TradesPublic,
    TradeUpdate,
)

router = APIRouter(prefix="/investments", tags=["investments"])


def investment_exception_mappings() -> dict[type[ServiceError], int]:
    """Map service exceptions to appropriate HTTP status codes.

    Returns:
        A dictionary mapping exception types to HTTP status codes.
    """
    return {
        InstrumentNotFoundError: status.HTTP_404_NOT_FOUND,
        InstrumentExistsError: status.HTTP_409_CONFLICT,
        InstrumentInUseError: status.HTTP_409_CONFLICT,
        InstrumentNotPriceableError: status.HTTP_400_BAD_REQUEST,
        TradeNotFoundError: status.HTTP_404_NOT_FOUND,
        InsufficientUnitsError: status.HTTP_400_BAD_REQUEST,
        TradeNotConvertibleError: status.HTTP_400_BAD_REQUEST,
        NotABrokerageAccountError: status.HTTP_400_BAD_REQUEST,
        # The request was fine and the app is fine; something upstream is not.
        # 502 says so, and says a retry is worth trying, which 500 does not.
        PriceProviderError: status.HTTP_502_BAD_GATEWAY,
        # Nothing is broken, the feature is simply switched off in this
        # deployment, which is a different thing for a client to react to.
        PriceProviderNotConfiguredError: status.HTTP_503_SERVICE_UNAVAILABLE,
    }


@router.post("/instruments", response_model=InstrumentPublic)
def create_instrument(
    *, investment_service: InvestmentServiceDep, household: CurrentHousehold, instrument_in: InstrumentCreate
) -> InstrumentPublic:
    """Start tracking an instrument.

    The symbol is priced once on the way in. That confirms the provider carries
    it, so a typo is caught here rather than becoming a position that is never
    worth anything, and it settles which currency the listing quotes in. Send a
    currency to skip the check and track something by hand.

    Args:
        investment_service: The investment service dependency.
        household: The current household context.
        instrument_in: The instrument to track.

    Returns:
        The instrument, priced if the provider knew it.

    Raises:
        HTTPException: If the household already tracks that symbol (409), the
            provider does not know it and no currency was given (400), market
            data is switched off (503), or the provider is unreachable (502).
    """
    return investment_service.create_instrument(household=household, instrument_create=instrument_in)


@router.get("/instruments", response_model=InstrumentsPublic)
def list_instruments(
    *,
    investment_service: InvestmentServiceDep,
    household: CurrentHousehold,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> InstrumentsPublic:
    """List the instruments the household tracks.

    Args:
        investment_service: The investment service dependency.
        household: The current household context.
        skip: Number of records to skip.
        limit: Maximum number of records to return.

    Returns:
        The instruments, and how many there are in total.

    Raises:
        HTTPException: If the user belongs to no household (404).
    """
    return investment_service.list_instruments(household=household, skip=skip, limit=limit)


# Household membership is required but never read: it is what keeps this from
# being an open proxy onto the provider's search. Declared on the route rather
# than as a parameter, since a parameter nothing uses reads like an oversight.
@router.get("/symbols", response_model=SymbolMatchesPublic, dependencies=[Depends(get_household_context)])
def search_symbols(
    *,
    investment_service: InvestmentServiceDep,
    q: str = Query(min_length=1, max_length=64),
    limit: int = Query(default=10, ge=1, le=25),
) -> SymbolMatchesPublic:
    """Look up listings by name or partial ticker.

    Matches carry no currency: the provider's search index does not have one,
    and it is only certain once the listing is priced, which is what creating
    the instrument does.

    Args:
        investment_service: The investment service dependency.
        q: What the user typed.
        limit: The most matches to return.

    Returns:
        The matching listings.

    Raises:
        HTTPException: If market data is switched off (503), or the provider is
            unreachable (502).
    """
    return investment_service.search_symbols(query=q, limit=limit)


@router.get("/fx-rates", response_model=FxRatesPublic)
def list_fx_rates(
    *,
    investment_service: InvestmentServiceDep,
    household: CurrentHousehold,
) -> FxRatesPublic:
    """Show the exchange rates behind the household's converted figures.

    Reads what is stored rather than fetching, so it never waits on the network
    and never spends an API call.

    Args:
        investment_service: The investment service dependency.
        household: The current household context.

    Returns:
        The rates converting into the household's currency, and any currency
        held that has no rate.

    Raises:
        HTTPException: If the household no longer exists (404).
    """
    return investment_service.list_fx_rates(household=household)


@router.get("/portfolio", response_model=PortfolioPublic)
def get_portfolio(
    *,
    investment_service: InvestmentServiceDep,
    household: CurrentHousehold,
    include_closed: bool = Query(default=False),
) -> PortfolioPublic:
    """Value everything the household holds, in the household's currency.

    Prices come from what was last fetched rather than from the provider, so
    this endpoint never waits on the network. Refresh them explicitly.

    Args:
        investment_service: The investment service dependency.
        household: The current household context.
        include_closed: Whether to include positions sold down to nothing.

    Returns:
        The positions and the totals over them.

    Raises:
        HTTPException: If the household no longer exists (404).
    """
    return investment_service.get_portfolio(household=household, include_closed=include_closed)


@router.post("/prices/refresh", response_model=PriceRefreshResult)
def refresh_prices(*, investment_service: InvestmentServiceDep, household: CurrentHousehold) -> PriceRefreshResult:
    """Fetch a fresh price for every instrument, and the rates to value them.

    A symbol the provider cannot answer for is reported rather than raised:
    one delisted ticker must not stop the rest of the portfolio being priced.

    Args:
        investment_service: The investment service dependency.
        household: The current household context.

    Returns:
        What was updated, and what could not be.

    Raises:
        HTTPException: If market data is switched off (503), or the provider is
            unreachable (502).
    """
    return investment_service.refresh_prices(household=household)


@router.get("/instruments/{instrument_id}", response_model=InstrumentPublic)
def get_instrument(
    *, investment_service: InvestmentServiceDep, household: CurrentHousehold, instrument_id: uuid.UUID
) -> InstrumentPublic:
    """Get one instrument of the household.

    Args:
        investment_service: The investment service dependency.
        household: The current household context.
        instrument_id: The ID of the instrument.

    Returns:
        The instrument.

    Raises:
        HTTPException: If it does not exist in the household (404).
    """
    return investment_service.get_instrument(household=household, instrument_id=instrument_id)


@router.patch("/instruments/{instrument_id}", response_model=InstrumentPublic)
def update_instrument(
    *,
    investment_service: InvestmentServiceDep,
    household: CurrentHousehold,
    instrument_id: uuid.UUID,
    instrument_in: InstrumentUpdate,
) -> InstrumentPublic:
    """Rename or re-label an instrument.

    The symbol and the currency cannot be changed. Both describe the listing
    that every stored price and every recorded trade was measured against.

    Args:
        investment_service: The investment service dependency.
        household: The current household context.
        instrument_id: The ID of the instrument to update.
        instrument_in: The fields to update.

    Returns:
        The updated instrument.

    Raises:
        HTTPException: If it does not exist in the household (404).
    """
    return investment_service.update_instrument(
        household=household, instrument_id=instrument_id, instrument_update=instrument_in
    )


@router.put("/instruments/{instrument_id}/price", response_model=InstrumentPublic)
def set_instrument_price(
    *,
    investment_service: InvestmentServiceDep,
    household: CurrentHousehold,
    instrument_id: uuid.UUID,
    price_in: InstrumentPriceUpdate,
) -> InstrumentPublic:
    """Record a price by hand, for when the provider cannot supply one.

    The provider bills per holding out of a small daily allowance, and can also
    be switched off or simply not carry a listing. This is the way round all
    three. The price is stored and used exactly as a fetched one is; the row
    remembers that it was typed, and says so.

    Args:
        investment_service: The investment service dependency.
        household: The current household context.
        instrument_id: The ID of the instrument to price.
        price_in: The price, in the instrument's own currency.

    Returns:
        The instrument, carrying the new price.

    Raises:
        HTTPException: If it does not exist in the household (404).
    """
    return investment_service.set_instrument_price(
        household=household, instrument_id=instrument_id, price_update=price_in
    )


@router.delete("/instruments/{instrument_id}", response_model=Message)
def delete_instrument(
    *, investment_service: InvestmentServiceDep, household: CurrentHousehold, instrument_id: uuid.UUID
) -> Message:
    """Stop tracking an instrument that has no trades.

    Args:
        investment_service: The investment service dependency.
        household: The current household context.
        instrument_id: The ID of the instrument to delete.

    Returns:
        A confirmation message.

    Raises:
        HTTPException: If it does not exist in the household (404), or it still
            has trades (409).
    """
    return investment_service.delete_instrument(household=household, instrument_id=instrument_id)


@router.post("/trades", response_model=TradePublic)
def create_trade(
    *,
    investment_service: InvestmentServiceDep,
    household: CurrentHousehold,
    current_user: CurrentUser,
    trade_in: TradeCreate,
) -> TradePublic:
    """Record a buy or a sell.

    Args:
        investment_service: The investment service dependency.
        household: The current household context.
        current_user: The user recording it, for the audit trail.
        trade_in: The trade to record.

    Returns:
        The recorded trade.

    Raises:
        HTTPException: If the instrument does not exist in the household (404),
            or the trade would sell units the household does not hold (400).
    """
    return investment_service.create_trade(
        household=household, trade_create=trade_in, created_by_user_id=current_user.id
    )


@router.get("/trades", response_model=TradesPublic)
def list_trades(
    *,
    investment_service: InvestmentServiceDep,
    household: CurrentHousehold,
    instrument_id: uuid.UUID | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> TradesPublic:
    """List the household's trades, newest first.

    Args:
        investment_service: The investment service dependency.
        household: The current household context.
        instrument_id: An optional instrument to filter on.
        skip: Number of records to skip.
        limit: Maximum number of records to return.

    Returns:
        The trades, and how many there are in total.

    Raises:
        HTTPException: If the instrument does not exist in the household (404).
    """
    return investment_service.list_trades(household=household, instrument_id=instrument_id, skip=skip, limit=limit)


@router.get("/trades/{trade_id}", response_model=TradePublic)
def get_trade(
    *, investment_service: InvestmentServiceDep, household: CurrentHousehold, trade_id: uuid.UUID
) -> TradePublic:
    """Get one trade of the household.

    Args:
        investment_service: The investment service dependency.
        household: The current household context.
        trade_id: The ID of the trade.

    Returns:
        The trade.

    Raises:
        HTTPException: If it does not exist in the household (404).
    """
    return investment_service.get_trade(household=household, trade_id=trade_id)


@router.patch("/trades/{trade_id}", response_model=TradePublic)
def update_trade(
    *,
    investment_service: InvestmentServiceDep,
    household: CurrentHousehold,
    trade_id: uuid.UUID,
    trade_in: TradeUpdate,
) -> TradePublic:
    """Correct a recorded trade.

    The instrument cannot be changed: moving a trade rewrites the history of
    two positions at once. Delete it and record it again.

    Args:
        investment_service: The investment service dependency.
        household: The current household context.
        trade_id: The ID of the trade to correct.
        trade_in: The fields to change.

    Returns:
        The corrected trade.

    Raises:
        HTTPException: If it does not exist in the household (404), or the
            correction would leave the position holding fewer than zero units
            at some point in its history (400).
    """
    return investment_service.update_trade(household=household, trade_id=trade_id, trade_update=trade_in)


@router.delete("/trades/{trade_id}", response_model=Message)
def delete_trade(
    *, investment_service: InvestmentServiceDep, household: CurrentHousehold, trade_id: uuid.UUID
) -> Message:
    """Remove a trade that should not have been recorded.

    Args:
        investment_service: The investment service dependency.
        household: The current household context.
        trade_id: The ID of the trade to remove.

    Returns:
        A confirmation message.

    Raises:
        HTTPException: If it does not exist in the household (404), or a later
            sale depended on the units this trade brought in (400).
    """
    return investment_service.delete_trade(household=household, trade_id=trade_id)
