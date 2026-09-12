"""The two-step ``CHECK`` helper, run against a real Postgres.

The unit tier next to this one asserts on the statements the helper emits. What
it cannot see is what Postgres makes of them: whether the constraint is
recorded as validated, whether it is enforced on new writes before the scan has
happened, and what a run that stops in the scan leaves behind for the next one.
That last part is the whole reason the helper reads the catalogue, so it is
worth a database.

The helper runs through alembic's operations proxy, which a revision gets for
free and a test has to install. It is given a connection with no transaction
open on it: the autocommit block commits whatever transaction it finds, and the
one this suite wraps its tests in is not the helper's to commit.
"""

from collections.abc import Iterator

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from app.core.migrations import add_check_constraint, drop_check_constraint

# A table of the suite's own, so a helper that reaches past the table it was
# given cannot damage the schema the other integration tests share.
TABLE = "check_constraint_probe"
CONSTRAINT = "ck_check_constraint_probe_amount_within_cap"
CAP = 1000


@pytest.fixture
def probe_table(engine: Engine) -> Iterator[Engine]:
    """Create an empty table for a constraint to be applied to.

    Args:
        engine: The engine bound to the test database.

    Yields:
        The same engine, with the table in place.
    """
    with engine.begin() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
        connection.execute(text(f"CREATE TABLE {TABLE} (id integer PRIMARY KEY, amount_minor bigint NOT NULL)"))

    yield engine

    with engine.begin() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))


def apply_the_cap(engine: Engine) -> None:
    """Run the helper the way a revision would.

    Args:
        engine: The engine bound to the test database.
    """
    with engine.connect() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            add_check_constraint(CONSTRAINT, TABLE, f"amount_minor <= {CAP}")


def drop_the_cap(engine: Engine) -> None:
    """Run the downgrade half of the pair the way a revision would.

    Args:
        engine: The engine bound to the test database.
    """
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            drop_check_constraint(CONSTRAINT, TABLE)


def store(engine: Engine, identifier: int, amount_minor: int) -> None:
    """Write a row straight to the probe table.

    Args:
        engine: The engine bound to the test database.
        identifier: The primary key to store it under.
        amount_minor: The amount to store.
    """
    with engine.begin() as connection:
        connection.execute(
            text(f"INSERT INTO {TABLE} (id, amount_minor) VALUES (:id, :amount)"),
            {"id": identifier, "amount": amount_minor},
        )


def validation_state(engine: Engine) -> bool | None:
    """Read back what Postgres holds for the constraint.

    Args:
        engine: The engine bound to the test database.

    Returns:
        ``None`` when the constraint is not there, otherwise whether it is
        recorded as validated.
    """
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT convalidated FROM pg_constraint WHERE conname = :name"), {"name": CONSTRAINT}
        ).first()
    return None if row is None else bool(row.convalidated)


class TestApplyingACheckConstraint:
    """It ends up as a constraint Postgres considers validated."""

    def test_it_leaves_the_constraint_validated(self, probe_table: Engine) -> None:
        """`NOT VALID` on its own would let a row outside the cap sit there quietly, so the scan is not optional."""
        store(probe_table, 1, CAP - 1)

        apply_the_cap(probe_table)

        assert validation_state(probe_table) is True

    def test_it_rejects_a_row_outside_the_cap_afterwards(self, probe_table: Engine) -> None:
        """The point of the constraint, whichever way it was applied."""
        apply_the_cap(probe_table)

        with pytest.raises(IntegrityError):
            store(probe_table, 1, CAP + 1)

    def test_it_keeps_the_rows_that_were_already_inside_the_cap(self, probe_table: Engine) -> None:
        """The validation reads the table; it does not rewrite it."""
        store(probe_table, 1, CAP)

        apply_the_cap(probe_table)

        with probe_table.connect() as connection:
            stored = connection.execute(text(f"SELECT amount_minor FROM {TABLE} WHERE id = 1")).scalar_one()
        assert stored == CAP


class TestAStoredRowOutsideTheCap:
    """The validation stops on it, and what it leaves behind can be resumed."""

    def test_the_validation_fails_rather_than_repairing_the_row(self, probe_table: Engine) -> None:
        """A ledger row outside its cap is a record of something: it is for a person to look at."""
        store(probe_table, 1, CAP + 1)

        with pytest.raises(IntegrityError):
            apply_the_cap(probe_table)

    def test_the_unvalidated_constraint_is_left_behind(self, probe_table: Engine) -> None:
        """The two halves commit separately, so a failed scan does not take the add back with it."""
        store(probe_table, 1, CAP + 1)
        with pytest.raises(IntegrityError):
            apply_the_cap(probe_table)

        assert validation_state(probe_table) is False

    def test_it_is_enforced_on_new_writes_even_unvalidated(self, probe_table: Engine) -> None:
        """`NOT VALID` is about the rows that were already there, not about the ones arriving."""
        store(probe_table, 1, CAP + 1)
        with pytest.raises(IntegrityError):
            apply_the_cap(probe_table)

        with pytest.raises(IntegrityError):
            store(probe_table, 2, CAP + 2)

    def test_repairing_the_row_and_running_again_validates_it(self, probe_table: Engine) -> None:
        """This is the answer to a revision that stopped in the scan: fix the rows, upgrade again."""
        store(probe_table, 1, CAP + 1)
        with pytest.raises(IntegrityError):
            apply_the_cap(probe_table)

        with probe_table.begin() as connection:
            connection.execute(text(f"UPDATE {TABLE} SET amount_minor = {CAP} WHERE id = 1"))
        apply_the_cap(probe_table)

        assert validation_state(probe_table) is True


class TestRunningTheHelperTwice:
    """A revision alembic re-runs from the top does not fall over on its own work."""

    def test_a_second_run_over_a_validated_constraint_is_a_no_op(self, probe_table: Engine) -> None:
        """Postgres has no ADD CONSTRAINT IF NOT EXISTS, so a plain second ADD would fail here."""
        apply_the_cap(probe_table)

        apply_the_cap(probe_table)

        assert validation_state(probe_table) is True


class TestDroppingACheckConstraint:
    """The downgrade half takes away whatever the upgrade managed to apply."""

    def test_it_removes_the_constraint(self, probe_table: Engine) -> None:
        """The pair has to be symmetric or a downgrade leaves the table stricter than the revision before it."""
        apply_the_cap(probe_table)

        drop_the_cap(probe_table)

        assert validation_state(probe_table) is None

    def test_it_says_nothing_about_a_constraint_that_was_never_applied(self, probe_table: Engine) -> None:
        """A downgrade of a revision that stopped part way through would otherwise fail on the first gap."""
        drop_the_cap(probe_table)

        assert validation_state(probe_table) is None
