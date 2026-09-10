import datetime
import uuid
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKeyConstraint, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from .fields import MAX_AMOUNT_MINOR, MAX_FX_RATE_MICRO, MAX_PRICE_MICRO, MAX_QUANTITY_MICRO, within_cap_sql
from .mixins import CreatedAtMixin, PrimaryKeyMixin, UpdatedAtMixin, UtcDateTime


class InstrumentKind(StrEnum):
    ETF = "etf"
    STOCK = "stock"
    FUND = "fund"
    BOND = "bond"
    CRYPTO = "crypto"
    OTHER = "other"


class TradeSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class InstrumentBase(SQLModel):
    # The ticker as the price provider knows it, exchange suffix included:
    # "VWCE.DE" is not the same listing as "VWCE.AS", and they do not quote the
    # same price or even the same currency.
    symbol: str = Field(max_length=32)
    name: str = Field(max_length=255)
    kind: InstrumentKind = InstrumentKind.ETF
    exchange: str | None = Field(default=None, max_length=64)


class InstrumentCreate(InstrumentBase):
    # The currency the instrument quotes in is a property of the listing, and
    # the provider is the authority on it, so it is asked at creation rather
    # than required here. Supplying it is the escape hatch for something the
    # provider does not carry, which is then tracked by hand: giving it means
    # "trust me", leaving it out means "go and find out", and the second is the
    # better default. It is why this field does not live on the shared base.
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)


class InstrumentUpdate(SQLModel):
    # The symbol is deliberately absent. It is what every stored price was
    # fetched against, so changing it would leave a price belonging to a
    # different listing sitting on the row. Delete and re-add instead.
    name: str | None = Field(default=None, max_length=255)
    kind: InstrumentKind | None = Field(default=None)
    exchange: str | None = Field(default=None, max_length=64)


class InstrumentPriceUpdate(SQLModel):
    """A price typed in by hand.

    The escape hatch for a provider that is rate limited, does not carry a
    listing, or is switched off entirely. A portfolio should not be unusable
    because somebody else's server said no.
    """

    # In minor units of the instrument's own currency, times MICRO, exactly as
    # a fetched price is stored. The currency is the instrument's and cannot be
    # changed here: a price in a different currency is a different listing.
    price_micro: int = Field(ge=0, le=MAX_PRICE_MICRO)
    # What moment the price refers to, if the caller knows. Left out, it is
    # taken as now, which is what typing today's screen price means.
    as_of: datetime.datetime | None = Field(default=None)


class InstrumentPublic(InstrumentBase):
    id: uuid.UUID
    household_id: uuid.UUID
    currency_code: str
    last_price_micro: int | None = None
    last_price_at: datetime.datetime | None = None
    last_priced_at: datetime.datetime | None = None
    last_price_is_manual: bool = False
    # How many trades reference this instrument. Reported because it decides
    # whether it can be deleted: an instrument with trades cannot be, and a
    # list offering a delete that will be refused is a worse list.
    trade_count: int = 0
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None


class InstrumentsPublic(SQLModel):
    data: list[InstrumentPublic]
    count: int


class TradeBase(SQLModel):
    side: TradeSide
    traded_on: datetime.date
    # Always a positive magnitude, like a transaction amount. Which way the
    # units moved lives in `side`, where a constraint can hold it.
    quantity_micro: int = Field(gt=0)
    # The price paid or received for one unit, in minor units of the
    # instrument's currency, times MICRO. Zero is allowed: a bonus share, a
    # stock grant and a spin-off all arrive at no cost.
    price_micro: int = Field(ge=0)
    # Commission and taxes, in minor units of the instrument's currency. Added
    # to the cost of a buy and taken off the proceeds of a sell, so a gain is
    # what actually landed rather than what the screen quoted.
    fee_minor: int = Field(default=0, ge=0)
    note: str | None = Field(default=None, max_length=1024)


class TradeCreate(TradeBase):
    # The caps live on the input models rather than on the shared base, so a
    # row stored before a cap existed stays readable on the way out.
    quantity_micro: int = Field(gt=0, le=MAX_QUANTITY_MICRO)
    price_micro: int = Field(ge=0, le=MAX_PRICE_MICRO)
    fee_minor: int = Field(default=0, ge=0, le=MAX_AMOUNT_MINOR)
    instrument_id: uuid.UUID
    # The brokerage account the cash comes out of on a buy and lands in on a
    # sell. No bank account is named: moving money between a bank and a broker
    # is its own event, on its own day, and is recorded as an ordinary transfer.
    # Optional, because a trade is a fact about a holding whether or not the
    # cash is tracked here, and every trade recorded before this has none.
    brokerage_account_id: uuid.UUID | None = Field(default=None)
    # What actually left or reached that account, in the household's currency.
    # Left out, it is worked out from the trade. That calculation is exact when
    # the listing quotes in the household's currency and an estimate when it
    # does not, which is the case worth overriding: a bank's rate on the day is
    # never the reference rate this app stores.
    cash_amount_minor: int | None = Field(default=None, ge=0, le=MAX_AMOUNT_MINOR)


class TradeUpdate(SQLModel):
    # The instrument is absent for the same reason the symbol is: moving a
    # trade to another instrument rewrites the history of two positions at
    # once. Delete it and record it again.
    side: TradeSide | None = Field(default=None)
    traded_on: datetime.date | None = Field(default=None)
    quantity_micro: int | None = Field(default=None, gt=0, le=MAX_QUANTITY_MICRO)
    price_micro: int | None = Field(default=None, ge=0, le=MAX_PRICE_MICRO)
    fee_minor: int | None = Field(default=None, ge=0, le=MAX_AMOUNT_MINOR)
    note: str | None = Field(default=None, max_length=1024)
    brokerage_account_id: uuid.UUID | None = Field(default=None)
    cash_amount_minor: int | None = Field(default=None, ge=0, le=MAX_AMOUNT_MINOR)


class TradePublic(TradeBase):
    id: uuid.UUID
    household_id: uuid.UUID
    instrument_id: uuid.UUID
    # Denormalized into the response so a ledger of trades reads without a
    # second request per row.
    symbol: str = ""
    currency_code: str = "EUR"
    # The cash side, when the trade has one.
    brokerage_account_id: uuid.UUID | None = None
    cash_amount_minor: int | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None


class TradesPublic(SQLModel):
    data: list[TradePublic]
    count: int


class PositionPublic(SQLModel):
    """What a household holds in one instrument, and what it is worth.

    Every money figure here is in the household's own currency, so a portfolio
    of listings in three currencies still adds up. Conversion uses the one
    exchange rate the app keeps per pair, which is the latest one fetched: a
    cost basis paid years ago is therefore restated at today's rate, and the
    gain shown mixes the market's movement with the currency's. That is the
    price of not storing a rate per trade date, and it is stated here rather
    than hidden. `currency_code` and `last_price_micro` stay native, because a
    quote restated into another currency is no longer the quote.
    """

    instrument_id: uuid.UUID
    symbol: str
    name: str
    kind: InstrumentKind
    currency_code: str
    exchange: str | None = None

    # Units still held: buys less sells. Zero for a position fully sold, which
    # is kept because its realised gain is real.
    quantity_micro: int = 0
    is_open: bool = True

    last_price_micro: int | None = None
    last_price_at: datetime.datetime | None = None
    last_price_is_manual: bool = False
    # Native currency to household currency, times MICRO. MICRO exactly when
    # the two are the same currency.
    fx_rate_micro: int | None = None

    # All absent rather than zero when the figure cannot be worked out: no
    # price fetched for the instrument, or no exchange rate known for its
    # currency. Absent is honest; zero would be read as "worth nothing", and a
    # cost basis or a realised gain reported as zero because a rate is missing
    # understates by exactly the amount nobody can see.
    cost_basis_minor: int | None = None
    market_value_minor: int | None = None
    unrealised_gain_minor: int | None = None
    realised_gain_minor: int | None = None


class PortfolioPublic(SQLModel):
    """The whole portfolio, valued in the household's currency."""

    currency_code: str
    data: list[PositionPublic]
    count: int
    total_cost_basis_minor: int = 0
    # Covers only the positions that could be valued, so it is not compared
    # against a cost basis that includes the ones that could not.
    total_market_value_minor: int = 0
    total_unrealised_gain_minor: int = 0
    total_realised_gain_minor: int = 0
    # How many positions could not be fully converted, whether because no price
    # has been fetched or because no exchange rate is known. Closed ones count
    # too: without a rate their realised gain is missing from the total, and
    # nothing else on the page would say so.
    unpriced_count: int = 0
    # The oldest quote behind the total: the age of the figure is the age of
    # its stalest part.
    priced_as_of: datetime.datetime | None = None


class FxRatePublic(SQLModel):
    """One exchange rate, and how it is being applied.

    Reported so the conversion behind a portfolio total is inspectable rather
    than implicit. A figure in the household's currency that came from a rate
    nobody can see is a figure nobody can check.
    """

    base_code: str
    quote_code: str
    # How many units of the quote currency one unit of the base buys, times
    # MICRO. 860440 means one dollar buys 0.86044 euro.
    rate_micro: int
    # The day the rate refers to, which for a central bank reference rate is
    # the working day it was published.
    as_of: datetime.datetime
    # When this app last stored it, which is what the cache window measures
    # against. Distinct from `as_of`: a Friday rate fetched on Monday has an
    # `as_of` of Friday and a `fetched_at` of Monday.
    fetched_at: datetime.datetime | None = None
    # Whether any instrument currently quotes in the base currency. A rate kept
    # from a holding since sold is still shown, marked as no longer in use.
    in_use: bool = True


class FxRatesPublic(SQLModel):
    """The rates behind a household's converted figures."""

    # The currency everything is converted into: the household's own.
    quote_code: str
    data: list[FxRatePublic]
    count: int
    # Currencies held that have no stored rate, so their holdings cannot be
    # valued. Named rather than counted, because the fix is per currency.
    missing: list[str] = Field(default_factory=list)


class QuoteFailure(SQLModel):
    symbol: str
    reason: str


class PriceRefreshResult(SQLModel):
    """What a refresh managed to fetch."""

    updated_count: int = 0
    # Holdings answered from the stored price because it was still inside the
    # cache window, and so cost no API call. Reported because the budget is
    # small enough that someone will want to know where it went.
    cached_count: int = 0
    failures: list[QuoteFailure] = Field(default_factory=list)
    refreshed_at: datetime.datetime


class SymbolMatch(SQLModel):
    """One candidate listing from the provider's symbol search."""

    symbol: str
    name: str
    # Absent from a search result: the search index does not carry it, and it
    # is only known once the listing is actually priced. The create endpoint
    # fills it in from the first quote rather than making the user guess.
    currency_code: str | None = None
    exchange: str | None = None
    kind: InstrumentKind = InstrumentKind.OTHER


class SymbolMatchesPublic(SQLModel):
    data: list[SymbolMatch]
    count: int


class Instrument(InstrumentBase, PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, table=True):
    __table_args__ = (
        UniqueConstraint("household_id", "symbol", name="uq_instrument_household_symbol"),
        # Composite foreign key target, so a trade cannot reference an
        # instrument belonging to a different household.
        UniqueConstraint("id", "household_id", name="uq_instrument_id_household"),
        CheckConstraint("length(currency_code) = 3", name="ck_instrument_currency_code_len"),
        CheckConstraint("last_price_micro IS NULL OR last_price_micro >= 0", name="ck_instrument_price_non_negative"),
        CheckConstraint(
            within_cap_sql("last_price_micro", MAX_PRICE_MICRO, nullable=True),
            name="ck_instrument_price_within_cap",
        ),
    )

    household_id: uuid.UUID = Field(foreign_key="household.id", ondelete="CASCADE", index=True)
    # Never kept equal to the household's currency, unlike an account's:
    # restating what an exchange reports would be a lie about the listing.
    currency_code: str = Field(min_length=3, max_length=3)
    # The last quote fetched, cached on the row. A quote is not a fact about
    # the household, it is a fact about the market, so it is not derived from
    # anything here and there is nothing to recompute it from: caching it is
    # the only way to show a value when the provider is unreachable.
    last_price_micro: int | None = Field(default=None, sa_type=BigInteger)
    last_price_at: datetime.datetime | None = Field(default=None, sa_type=UtcDateTime)
    # When the provider was last asked, as opposed to what moment the price it
    # returned refers to. The two are days apart over a weekend, and it is this
    # one that decides whether asking again is worth an API call. Reading
    # `last_price_at` instead would re-fetch every closed market forever.
    last_priced_at: datetime.datetime | None = Field(default=None, sa_type=UtcDateTime)
    # Whether the price on this row was typed in rather than fetched. A number
    # someone entered and a number a market reported are both useful and are
    # not the same claim, so the row says which it is holding.
    last_price_is_manual: bool = Field(default=False)


class Trade(TradeBase, PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, table=True):
    __table_args__ = (
        CheckConstraint("quantity_micro > 0", name="ck_trade_quantity_positive"),
        # The quantity cap and the price cap are a pair: their product, in
        # minor units, has to stay below MAX_AMOUNT_MINOR or a position's
        # market value overflows the column it is summed into. That promise
        # only held for writes that came through the API until these.
        CheckConstraint(
            within_cap_sql("quantity_micro", MAX_QUANTITY_MICRO),
            name="ck_trade_quantity_within_cap",
        ),
        CheckConstraint("price_micro >= 0", name="ck_trade_price_non_negative"),
        CheckConstraint(within_cap_sql("price_micro", MAX_PRICE_MICRO), name="ck_trade_price_within_cap"),
        CheckConstraint("fee_minor >= 0", name="ck_trade_fee_non_negative"),
        CheckConstraint(within_cap_sql("fee_minor", MAX_AMOUNT_MINOR), name="ck_trade_fee_within_cap"),
        CheckConstraint("cash_amount_minor IS NULL OR cash_amount_minor >= 0", name="ck_trade_cash_non_negative"),
        CheckConstraint(
            within_cap_sql("cash_amount_minor", MAX_AMOUNT_MINOR, nullable=True),
            name="ck_trade_cash_within_cap",
        ),
        # The cash side is both or neither: an account with no amount does not
        # say how much moved, and an amount with no account has nowhere to move
        # from. Either alone describes no movement at all.
        CheckConstraint(
            "(brokerage_account_id IS NULL AND cash_amount_minor IS NULL)"
            " OR (brokerage_account_id IS NOT NULL AND cash_amount_minor IS NOT NULL)",
            name="ck_trade_cash_side_complete",
        ),
        ForeignKeyConstraint(
            ["instrument_id", "household_id"],
            ["instrument.id", "instrument.household_id"],
            name="fk_trade_instrument_household",
            ondelete="RESTRICT",
        ),
        # Composite, like every other cross-entity reference here, so a trade
        # can never move money through another household's account.
        ForeignKeyConstraint(
            ["brokerage_account_id", "household_id"],
            ["account.id", "account.household_id"],
            name="fk_trade_brokerage_account_household",
            ondelete="RESTRICT",
        ),
        # Every position is built by walking one instrument's trades in date
        # order, so this is the index that serves the portfolio page.
        Index("ix_trade_instrument_traded_on", "instrument_id", "traded_on"),
        Index("ix_trade_household_traded_on", "household_id", "traded_on"),
    )

    household_id: uuid.UUID = Field(foreign_key="household.id", ondelete="CASCADE", index=True)
    # Declared without a single-column foreign key: the composite constraint
    # above is what enforces the reference.
    instrument_id: uuid.UUID = Field(nullable=False)
    quantity_micro: int = Field(sa_type=BigInteger)
    price_micro: int = Field(sa_type=BigInteger)
    fee_minor: int = Field(default=0, sa_type=BigInteger)
    traded_on: datetime.date = Field(sa_type=Date)
    # The brokerage account the cash moved through. Declared without a
    # single-column foreign key: the composite constraint above enforces it.
    brokerage_account_id: uuid.UUID | None = Field(default=None, nullable=True)
    # What moved, in the household's currency. Stored rather than recomputed,
    # because it is a historical fact: recomputing a cross-currency trade would
    # quietly restate what left someone's bank account every time a rate moved.
    cash_amount_minor: int | None = Field(default=None, sa_type=BigInteger, nullable=True)
    created_by_user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id", ondelete="SET NULL")


class FxRate(SQLModel, PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, table=True):
    """The latest exchange rate fetched for one currency pair.

    Not scoped to a household: what a dollar buys in euro is the same fact for
    everyone, so one row serves every household and one fetch refreshes them
    all. Only the latest rate is kept. A history of rates would let a cost
    basis be converted at the rate of its trade date, which is the more correct
    answer, but it is a second feature and this table does not stand in its
    way: adding a dated table later leaves this one as the cache it is.
    """

    __table_args__ = (
        UniqueConstraint("base_code", "quote_code", name="uq_fx_rate_pair"),
        CheckConstraint("length(base_code) = 3", name="ck_fx_rate_base_code_len"),
        CheckConstraint("length(quote_code) = 3", name="ck_fx_rate_quote_code_len"),
        CheckConstraint("rate_micro > 0", name="ck_fx_rate_positive"),
        CheckConstraint(within_cap_sql("rate_micro", MAX_FX_RATE_MICRO), name="ck_fx_rate_within_cap"),
    )

    base_code: str = Field(min_length=3, max_length=3)
    quote_code: str = Field(min_length=3, max_length=3)
    # How many units of the quote currency one unit of the base currency buys,
    # times MICRO.
    rate_micro: int = Field(sa_type=BigInteger, le=MAX_FX_RATE_MICRO)
    as_of: datetime.datetime = Field(sa_type=UtcDateTime)
