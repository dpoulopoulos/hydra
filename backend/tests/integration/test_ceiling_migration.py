"""The repair revision ``2cd2b8081af4`` performs before it adds its ceilings.

Every bound was reachable through the API before it existed, so a database with
history in it can hold a row outside one, and ``ADD CONSTRAINT`` scans every
row: the revision would stop on such a row rather than apply. It therefore
repairs the rows it can: an ordering hint and two schedules are clamped, and a
stale exchange rate and a stale quote, which are caches of somebody else's
number rather than records of anything, are thrown away. That repair only ever
runs against a database nobody has in front of them, and half of it destroys
data that a downgrade cannot put back.

These tests give it one. The schema is built by walking the revisions up to the
one before the ceilings, seeded with rows outside the bounds, and then migrated
across. The rest of the integration suite creates its schema from the model
metadata instead, which skips every revision and so can say nothing about what
one does.
"""

import datetime
import uuid
from collections.abc import Generator

import pytest
from alembic import command
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from app.models.category import MAX_SORT_ORDER
from app.models.fields import MAX_FX_RATE_MICRO, MAX_PRICE_MICRO
from app.models.recurring_rule import MAX_RECURRENCE_INTERVAL
from tests.integration.migrations import alembic_config, migrated_database, settings_pointed_at

# The revision under test and the one it follows, which is where the seeded
# rows are written: at that point none of the ceilings exists yet, so a row
# outside one can still be stored.
REVISION = "2cd2b8081af4"
PREVIOUS = "8fe178da1853"

# A database of its own, next to the one the rest of the suite creates from the
# model metadata. Migrating a schema in place would leave the other tests
# running against whatever revision this one stopped at.
MIGRATION_DATABASE_SUFFIX = "_migration"

MARCH = datetime.date(2024, 3, 1)

# The three columns the price reset clears together, read back as one value so
# a reset that leaves a timestamp behind cannot pass.
CachedQuote = tuple[int | None, datetime.datetime | None, datetime.datetime | None]

HOUSEHOLD_ID = uuid.UUID("00000000-0000-0000-0000-00000000a001")
ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-00000000a002")
USER_ID = uuid.UUID("00000000-0000-0000-0000-00000000a008")
# One category per value the clamp has to handle, so a clamp that repairs one
# end of the range and not the other is visible.
ABOVE_CATEGORY_ID = uuid.UUID("00000000-0000-0000-0000-00000000a003")
BELOW_CATEGORY_ID = uuid.UUID("00000000-0000-0000-0000-00000000a004")
IN_RANGE_CATEGORY_ID = uuid.UUID("00000000-0000-0000-0000-00000000a005")
LONG_RULE_ID = uuid.UUID("00000000-0000-0000-0000-00000000a006")
SHORT_RULE_ID = uuid.UUID("00000000-0000-0000-0000-00000000a007")
# The same, for the clamp on a client's cadence.
LONG_CLIENT_ID = uuid.UUID("00000000-0000-0000-0000-00000000a009")
SHORT_CLIENT_ID = uuid.UUID("00000000-0000-0000-0000-00000000a00a")
# The two repairs that remove data rather than move it: a rate outside the cap
# is deleted outright, and a quote outside it is cleared off the instrument. A
# row inside the cap is seeded beside each, because a repair that took the rest
# of the table with it would otherwise look exactly like a correct one.
ABSURD_RATE_ID = uuid.UUID("00000000-0000-0000-0000-00000000a00b")
IN_RANGE_RATE_ID = uuid.UUID("00000000-0000-0000-0000-00000000a00c")
ABSURD_PRICE_INSTRUMENT_ID = uuid.UUID("00000000-0000-0000-0000-00000000a00d")
IN_RANGE_PRICE_INSTRUMENT_ID = uuid.UUID("00000000-0000-0000-0000-00000000a00e")

# Far enough past each bound that a clamp landing anywhere but exactly on it is
# obvious, and well inside what the column can hold.
STORED_SORT_ORDER_ABOVE = MAX_SORT_ORDER * 100
STORED_SORT_ORDER_BELOW = -5
STORED_INTERVAL_ABOVE = MAX_RECURRENCE_INTERVAL * 100
STORED_RATE_ABOVE = MAX_FX_RATE_MICRO * 100
STORED_PRICE_ABOVE = MAX_PRICE_MICRO * 100
IN_RANGE_SORT_ORDER = 7
IN_RANGE_INTERVAL = 3
IN_RANGE_RATE = 860_440
IN_RANGE_PRICE = 128_450_000

PRICED_AT = datetime.datetime(2024, 2, 29, 17, 30)

# The rows the ceilings were reachable around, written straight to the tables
# as they stand at PREVIOUS rather than through the models, which carry the
# constraints these rows are meant to violate.
SEED = [
    'INSERT INTO "user" (id, email, full_name, is_active, is_superuser, hashed_password)'
    " VALUES (:user_id, 'owner@example.com', 'Owner', true, false, 'not-a-real-hash')",
    "INSERT INTO household (id, name, currency_code) VALUES (:household_id, 'Migrated', 'EUR')",
    "INSERT INTO category (id, household_id, name, kind, sort_order, is_system)"
    " VALUES (:above_id, :household_id, 'Above', 'EXPENSE', :sort_order_above, false)",
    "INSERT INTO category (id, household_id, name, kind, sort_order, is_system)"
    " VALUES (:below_id, :household_id, 'Below', 'EXPENSE', :sort_order_below, false)",
    "INSERT INTO category (id, household_id, name, kind, sort_order, is_system)"
    " VALUES (:in_range_id, :household_id, 'In range', 'EXPENSE', :sort_order_in_range, false)",
    "INSERT INTO account (id, household_id, name, type, currency_code, opening_balance_minor, opening_balance_date)"
    " VALUES (:account_id, :household_id, 'Current', 'CURRENT', 'EUR', 0, :march)",
    "INSERT INTO recurringrule"
    " (id, household_id, name, frequency, interval, kind, amount_minor, is_active, start_date, account_id)"
    " VALUES (:long_id, :household_id, 'Long', 'MONTHLY', :interval_above, 'EXPENSE', 100000, true, :march,"
    " :account_id)",
    "INSERT INTO recurringrule"
    " (id, household_id, name, frequency, interval, kind, amount_minor, is_active, start_date, account_id)"
    " VALUES (:short_id, :household_id, 'Short', 'MONTHLY', :interval_in_range, 'EXPENSE', 100000, true, :march,"
    " :account_id)",
    "INSERT INTO incomeclient"
    " (id, household_id, owner_user_id, name_ct, default_rate_minor, cadence_interval, default_account_id)"
    " VALUES (:long_client_id, :household_id, :user_id, 'Y2lwaGVydGV4dA==', 0, :interval_above, :account_id)",
    "INSERT INTO incomeclient"
    " (id, household_id, owner_user_id, name_ct, default_rate_minor, cadence_interval, default_account_id)"
    " VALUES (:short_client_id, :household_id, :user_id, 'Y2lwaGVydGV4dA==', 0, :interval_in_range, :account_id)",
    "INSERT INTO fxrate (id, base_code, quote_code, rate_micro, as_of)"
    " VALUES (:absurd_rate_id, 'USD', 'EUR', :rate_above, :priced_at)",
    "INSERT INTO fxrate (id, base_code, quote_code, rate_micro, as_of)"
    " VALUES (:in_range_rate_id, 'GBP', 'EUR', :rate_in_range, :priced_at)",
    "INSERT INTO instrument"
    " (id, household_id, symbol, name, kind, currency_code, last_price_micro, last_price_at, last_priced_at,"
    " last_price_is_manual)"
    " VALUES (:absurd_price_id, :household_id, 'ABSURD', 'Absurdly priced', 'ETF', 'EUR', :price_above, :priced_at,"
    " :priced_at, false)",
    "INSERT INTO instrument"
    " (id, household_id, symbol, name, kind, currency_code, last_price_micro, last_price_at, last_priced_at,"
    " last_price_is_manual)"
    " VALUES (:in_range_price_id, :household_id, 'VWCE.DE', 'Vanguard FTSE All-World', 'ETF', 'EUR', :price_in_range,"
    " :priced_at, :priced_at, false)",
]

SEED_PARAMETERS = {
    "household_id": HOUSEHOLD_ID,
    "account_id": ACCOUNT_ID,
    "user_id": USER_ID,
    "above_id": ABOVE_CATEGORY_ID,
    "below_id": BELOW_CATEGORY_ID,
    "in_range_id": IN_RANGE_CATEGORY_ID,
    "long_id": LONG_RULE_ID,
    "short_id": SHORT_RULE_ID,
    "sort_order_above": STORED_SORT_ORDER_ABOVE,
    "sort_order_below": STORED_SORT_ORDER_BELOW,
    "sort_order_in_range": IN_RANGE_SORT_ORDER,
    "interval_above": STORED_INTERVAL_ABOVE,
    "interval_in_range": IN_RANGE_INTERVAL,
    "long_client_id": LONG_CLIENT_ID,
    "short_client_id": SHORT_CLIENT_ID,
    "absurd_rate_id": ABSURD_RATE_ID,
    "in_range_rate_id": IN_RANGE_RATE_ID,
    "rate_above": STORED_RATE_ABOVE,
    "rate_in_range": IN_RANGE_RATE,
    "absurd_price_id": ABSURD_PRICE_INSTRUMENT_ID,
    "in_range_price_id": IN_RANGE_PRICE_INSTRUMENT_ID,
    "price_above": STORED_PRICE_ABOVE,
    "price_in_range": IN_RANGE_PRICE,
    "priced_at": PRICED_AT,
    "march": MARCH,
}


@pytest.fixture(scope="module")
def migrated_engine() -> Generator[Engine]:
    """Migrate a seeded database across the revision that adds the ceilings.

    Yields:
        An engine bound to a database holding the rows the revision repaired.
    """
    with migrated_database(
        suffix=MIGRATION_DATABASE_SUFFIX,
        previous=PREVIOUS,
        revision=REVISION,
        seed=SEED,
        parameters=SEED_PARAMETERS,
    ) as engine:
        yield engine


def _sort_order(engine: Engine, category_id: uuid.UUID) -> int:
    """Read back the ordering hint stored for a category.

    Args:
        engine: The engine bound to the migrated database.
        category_id: The category to read.

    Returns:
        The stored sort order.
    """
    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT sort_order FROM category WHERE id = :id"), {"id": category_id}
        ).scalar_one()
    return int(stored)


def _interval(engine: Engine, rule_id: uuid.UUID) -> int:
    """Read back the interval stored for a recurring rule.

    Args:
        engine: The engine bound to the migrated database.
        rule_id: The rule to read.

    Returns:
        The stored interval.
    """
    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT interval FROM recurringrule WHERE id = :id"), {"id": rule_id}
        ).scalar_one()
    return int(stored)


def _cadence_interval(engine: Engine, client_id: uuid.UUID) -> int:
    """Read back the cadence stored for an income client.

    Args:
        engine: The engine bound to the migrated database.
        client_id: The client to read.

    Returns:
        The stored cadence interval.
    """
    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT cadence_interval FROM incomeclient WHERE id = :id"), {"id": client_id}
        ).scalar_one()
    return int(stored)


def _rate_exists(engine: Engine, rate_id: uuid.UUID) -> bool:
    """Say whether an exchange rate survived the revision.

    Args:
        engine: The engine bound to the migrated database.
        rate_id: The rate to look for.

    Returns:
        Whether the row is still there.
    """
    with engine.connect() as connection:
        found = connection.execute(text("SELECT 1 FROM fxrate WHERE id = :id"), {"id": rate_id}).first()
    return found is not None


def _price_columns(engine: Engine, instrument_id: uuid.UUID) -> CachedQuote:
    """Read back the cached quote stored on an instrument.

    Args:
        engine: The engine bound to the migrated database.
        instrument_id: The instrument to read.

    Returns:
        The price, the moment it refers to, and when it was last fetched.
    """
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT last_price_micro, last_price_at, last_priced_at FROM instrument WHERE id = :id"),
            {"id": instrument_id},
        ).one()
    return row.last_price_micro, row.last_price_at, row.last_priced_at


def _unvalidated_checks(engine: Engine) -> list[str]:
    """List the check constraints Postgres has not yet checked the stored rows against.

    Args:
        engine: The engine bound to the migrated database.

    Returns:
        The names of the constraints still marked NOT VALID.
    """
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT conname FROM pg_constraint WHERE contype = 'c' AND NOT convalidated ORDER BY conname")
        ).all()
    return [row.conname for row in rows]


def _rerun_the_revision(engine: Engine) -> None:
    """Put the database back at the previous revision and migrate across again.

    What a run that stopped in a validation leaves behind is a database at the
    previous revision with some of the constraints already on it, which is what
    stamping back reproduces.

    Args:
        engine: The engine bound to the migrated database.
    """
    database = engine.url.database
    assert database is not None
    config = alembic_config()
    with settings_pointed_at(database):
        command.stamp(config, PREVIOUS)
        command.upgrade(config, REVISION)


class TestTheCeilingRevision:
    """It repairs the rows that would otherwise stop it, and applies."""

    def test_it_applies_over_rows_that_sit_outside_the_new_bounds(self, migrated_engine: Engine) -> None:
        """The revision is the one the database is now at, so no constraint failed to validate."""
        with migrated_engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION

    def test_an_ordering_above_the_ceiling_is_pulled_back_to_it(self, migrated_engine: Engine) -> None:
        """Not to zero and not to some other number: exactly the bound the constraint now enforces."""
        assert _sort_order(migrated_engine, ABOVE_CATEGORY_ID) == MAX_SORT_ORDER

    def test_an_ordering_below_zero_is_pulled_up_to_it(self, migrated_engine: Engine) -> None:
        """The constraint bounds both ends, so the repair has to as well."""
        assert _sort_order(migrated_engine, BELOW_CATEGORY_ID) == 0

    def test_an_ordering_already_in_range_is_left_alone(self, migrated_engine: Engine) -> None:
        """The clamp is a repair of the rows outside the range, not a rewrite of the column."""
        assert _sort_order(migrated_engine, IN_RANGE_CATEGORY_ID) == IN_RANGE_SORT_ORDER

    def test_a_schedule_longer_than_the_ceiling_is_pulled_back_to_it(self, migrated_engine: Engine) -> None:
        """A rule repeating less often than a hundred years already fails on every read."""
        assert _interval(migrated_engine, LONG_RULE_ID) == MAX_RECURRENCE_INTERVAL

    def test_a_schedule_already_in_range_is_left_alone(self, migrated_engine: Engine) -> None:
        """The same, for the column the other clamp touches."""
        assert _interval(migrated_engine, SHORT_RULE_ID) == IN_RANGE_INTERVAL

    def test_a_cadence_longer_than_the_ceiling_is_pulled_back_to_it(self, migrated_engine: Engine) -> None:
        """A client's schedule is clamped the same way a recurring rule's is."""
        assert _cadence_interval(migrated_engine, LONG_CLIENT_ID) == MAX_RECURRENCE_INTERVAL

    def test_a_cadence_already_in_range_is_left_alone(self, migrated_engine: Engine) -> None:
        """The clamp is a repair of the rows outside the range, not a rewrite of the column."""
        assert _cadence_interval(migrated_engine, SHORT_CLIENT_ID) == IN_RANGE_INTERVAL

    def test_an_exchange_rate_above_the_ceiling_is_deleted(self, migrated_engine: Engine) -> None:
        """A rate is a cache of somebody else's number, so one this far out is junk and is thrown away."""
        assert not _rate_exists(migrated_engine, ABSURD_RATE_ID)

    def test_an_exchange_rate_already_in_range_is_kept(self, migrated_engine: Engine) -> None:
        """The delete is aimed at the rows outside the cap, not at the table: this is the destructive one."""
        assert _rate_exists(migrated_engine, IN_RANGE_RATE_ID)

    def test_a_quote_above_the_ceiling_is_cleared_along_with_its_timestamps(self, migrated_engine: Engine) -> None:
        """`last_priced_at` goes with the price, or the next refresh would skip the row as recently fetched."""
        assert _price_columns(migrated_engine, ABSURD_PRICE_INSTRUMENT_ID) == (None, None, None)

    def test_a_quote_already_in_range_is_left_alone(self, migrated_engine: Engine) -> None:
        """The reset touches the instruments priced outside the cap and no others."""
        assert _price_columns(migrated_engine, IN_RANGE_PRICE_INSTRUMENT_ID) == (IN_RANGE_PRICE, PRICED_AT, PRICED_AT)


class TestTheCeilingsItApplies:
    """They are checked against the rows that were already stored, not only against new ones."""

    def test_every_constraint_is_validated(self, migrated_engine: Engine) -> None:
        """Applying as NOT VALID and stopping there would leave a stored row outside its cap unnoticed."""
        assert _unvalidated_checks(migrated_engine) == []

    def test_a_row_outside_a_cap_is_refused_afterwards(self, migrated_engine: Engine) -> None:
        """The ledger is the table the two-step form is really for, so it is the one asserted on."""
        with pytest.raises(IntegrityError):
            with migrated_engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO transaction (id, household_id, account_id, kind, amount_minor, occurred_on)"
                        " VALUES (gen_random_uuid(), :household_id, :account_id, 'EXPENSE',"
                        " 4611686018427387905, :march)"
                    ),
                    {"household_id": HOUSEHOLD_ID, "account_id": ACCOUNT_ID, "march": MARCH},
                )

    def test_it_can_be_run_again_over_the_constraints_it_already_applied(self, migrated_engine: Engine) -> None:
        """A revision that stops in a validation writes no version row, so alembic runs it from the top."""
        _rerun_the_revision(migrated_engine)

        assert _unvalidated_checks(migrated_engine) == []
