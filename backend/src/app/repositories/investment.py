import datetime
import uuid
from collections.abc import Sequence

from sqlmodel import Session, col, func, select

from app.models import FxRate, Instrument, Trade
from app.repositories.base import BaseRepository, HouseholdScopedRepository


class InstrumentRepository(HouseholdScopedRepository[Instrument]):
    """Repository for Instrument database operations."""

    def __init__(self, session: Session) -> None:
        """Initialize the instrument repository.

        Args:
            session: The database session.
        """
        super().__init__(session, Instrument)

    def list_for_household(
        self,
        household_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[Instrument], int]:
        """List the instruments a household tracks.

        Args:
            household_id: The ID of the household.
            skip: Number of records to skip.
            limit: Maximum number of records to return.

        Returns:
            Tuple of (instruments, total_count), ordered by symbol.
        """
        count_statement = select(func.count()).select_from(Instrument).where(Instrument.household_id == household_id)
        count = self.session.exec(count_statement).one()

        statement = self._paginate(
            select(Instrument).where(Instrument.household_id == household_id).order_by(col(Instrument.symbol)),
            skip=skip,
            limit=limit,
        )

        return self.session.exec(statement).all(), count

    def get_by_symbol(self, household_id: uuid.UUID, symbol: str) -> Instrument | None:
        """Get an instrument by ticker symbol within a household.

        Args:
            household_id: The ID of the household.
            symbol: The ticker symbol, already normalized to upper case.

        Returns:
            The instrument if one exists with that symbol, None otherwise.
        """
        statement = select(Instrument).where(Instrument.household_id == household_id, Instrument.symbol == symbol)
        return self.session.exec(statement).first()


class TradeRepository(HouseholdScopedRepository[Trade]):
    """Repository for Trade database operations.

    A position is never stored. It is folded from the instrument's trades on
    every read, exactly as an account balance is folded from its ledger, and
    for the same reason: a stored quantity or cost basis is a cache with no
    invalidation story that survives a back-dated trade or a corrected fee.
    """

    def __init__(self, session: Session) -> None:
        """Initialize the trade repository.

        Args:
            session: The database session.
        """
        super().__init__(session, Trade)

    def list_for_household(
        self,
        household_id: uuid.UUID,
        instrument_id: uuid.UUID | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[Trade], int]:
        """List the trades of a household, newest first.

        Args:
            household_id: The ID of the household.
            instrument_id: An optional instrument to filter on.
            skip: Number of records to skip.
            limit: Maximum number of records to return.

        Returns:
            Tuple of (trades, total_count).
        """
        conditions = [Trade.household_id == household_id]
        if instrument_id is not None:
            conditions.append(Trade.instrument_id == instrument_id)

        count_statement = select(func.count()).select_from(Trade).where(*conditions)
        count = self.session.exec(count_statement).one()

        statement = self._paginate(
            select(Trade).where(*conditions).order_by(col(Trade.traded_on).desc(), col(Trade.created_at).desc()),
            skip=skip,
            limit=limit,
        )

        return self.session.exec(statement).all(), count

    def history_for_household(self, household_id: uuid.UUID) -> Sequence[Trade]:
        """Get every trade of a household, oldest first.

        One query for the whole portfolio rather than one per instrument. The
        order is the one the position fold depends on: by instrument, then by
        the date the trade happened, then by the order rows were written, so
        two trades on the same day fold in the sequence they were recorded.

        Args:
            household_id: The ID of the household.

        Returns:
            The trades, ordered for folding.
        """
        statement = (
            select(Trade)
            .where(Trade.household_id == household_id)
            .order_by(col(Trade.instrument_id), col(Trade.traded_on), col(Trade.created_at))
        )
        return self.session.exec(statement).all()

    def history_for_instrument(self, instrument_id: uuid.UUID, household_id: uuid.UUID) -> Sequence[Trade]:
        """Get every trade against one instrument, oldest first.

        Args:
            instrument_id: The ID of the instrument.
            household_id: The ID of the household that owns it.

        Returns:
            The trades, ordered for folding.
        """
        statement = (
            select(Trade)
            .where(Trade.household_id == household_id, Trade.instrument_id == instrument_id)
            .order_by(col(Trade.traded_on), col(Trade.created_at))
        )
        return self.session.exec(statement).all()

    def counts_by_instrument(self, household_id: uuid.UUID) -> dict[uuid.UUID, int]:
        """Count the trades against each instrument a household tracks.

        One grouped query rather than one count per instrument, because the
        caller wants this for a whole list at once.

        Args:
            household_id: The ID of the household.

        Returns:
            A mapping of instrument ID to its number of trades. An instrument
            with no trades is absent rather than zero, which is what a mapping
            lookup with a default already handles.
        """
        statement = (
            select(Trade.instrument_id, func.count())
            .where(Trade.household_id == household_id)
            .group_by(col(Trade.instrument_id))
        )

        return dict(self.session.exec(statement).all())

    def count_for_instrument(self, instrument_id: uuid.UUID, household_id: uuid.UUID) -> int:
        """Count the trades recorded against an instrument.

        Args:
            instrument_id: The ID of the instrument.
            household_id: The ID of the household that owns it.

        Returns:
            The number of trades.
        """
        statement = (
            select(func.count())
            .select_from(Trade)
            .where(Trade.household_id == household_id, Trade.instrument_id == instrument_id)
        )
        return self.session.exec(statement).one()

    def count_for_brokerage_account(self, account_id: uuid.UUID, household_id: uuid.UUID) -> int:
        """Count the trades settled through an account.

        Only trades that moved cash carry a brokerage account, so a household
        can hold trades and still have none pointing at a given account.

        Args:
            account_id: The ID of the account.
            household_id: The ID of the household that owns it.

        Returns:
            The number of trades that name the account as where their cash moved.
        """
        statement = (
            select(func.count())
            .select_from(Trade)
            .where(Trade.household_id == household_id, Trade.brokerage_account_id == account_id)
        )
        return self.session.exec(statement).one()


class FxRateRepository(BaseRepository[FxRate]):
    """Repository for FxRate database operations.

    Not household scoped, and deliberately so: an exchange rate is a fact about
    the world rather than about anyone's money, so one row serves every
    household. Nothing private is stored here, which is what makes the sharing
    safe.
    """

    def __init__(self, session: Session) -> None:
        """Initialize the FX rate repository.

        Args:
            session: The database session.
        """
        super().__init__(session, FxRate)

    def rates_into(self, quote_code: str, base_codes: Sequence[str]) -> dict[str, FxRate]:
        """Get the stored rates converting several currencies into one.

        Args:
            quote_code: The currency being converted into.
            base_codes: The currencies being converted from.

        Returns:
            A mapping of base currency code to its rate. Pairs with no stored
            rate are absent.
        """
        if not base_codes:
            return {}

        statement = select(FxRate).where(FxRate.quote_code == quote_code, col(FxRate.base_code).in_(base_codes))
        return {rate.base_code: rate for rate in self.session.exec(statement).all()}

    def list_into(self, quote_code: str) -> Sequence[FxRate]:
        """Get every stored rate converting into one currency.

        Args:
            quote_code: The currency being converted into.

        Returns:
            The rates, ordered by the currency they convert from.
        """
        statement = select(FxRate).where(FxRate.quote_code == quote_code).order_by(col(FxRate.base_code))
        return self.session.exec(statement).all()

    def upsert(self, base_code: str, quote_code: str, rate_micro: int, as_of: datetime.datetime) -> FxRate:
        """Store the latest rate for a pair, replacing any earlier one.

        Args:
            base_code: The currency being converted from.
            quote_code: The currency being converted into.
            rate_micro: The rate, times MICRO.
            as_of: When the provider says the rate was current.

        Returns:
            The stored rate.
        """
        statement = select(FxRate).where(FxRate.base_code == base_code, FxRate.quote_code == quote_code)
        rate = self.session.exec(statement).first()

        if rate is None:
            rate = FxRate(base_code=base_code, quote_code=quote_code, rate_micro=rate_micro, as_of=as_of)
        else:
            rate.rate_micro = rate_micro
            rate.as_of = as_of

        return self.save(rate)
