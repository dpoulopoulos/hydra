"""Schema changes a database with history in it can take while it is serving.

``op.create_check_constraint`` renders a plain ``ALTER TABLE ... ADD
CONSTRAINT``, which takes an ``ACCESS EXCLUSIVE`` lock on the table and holds it
for a sequential scan of every row. On a household that started last month that
is milliseconds. On a ``transaction`` table with years of ledger in it, it is a
window in which nothing can read or write the largest table in the schema.

Postgres offers the same constraint in two steps instead:

* ``ADD CONSTRAINT ... NOT VALID`` takes the exclusive lock for as long as it
  takes to write a catalogue row, and from that moment the check holds for
  every insert and update.
* ``VALIDATE CONSTRAINT`` reads the rows that were already there under a
  ``SHARE UPDATE EXCLUSIVE`` lock, which readers and writers do not wait on.

The split only buys anything if the two statements commit separately, and
alembic wraps a revision in one transaction, so ``ADD ... NOT VALID`` would
hold its lock until the end of the revision and the scan would happen under it
after all. :func:`add_check_constraint` therefore runs in
``autocommit_block()``.

That has a consequence worth knowing before writing a revision against it: a
revision that stops part way leaves the constraints it already applied behind,
and no version row is written, so alembic will run the whole revision again.
Postgres has no ``ADD CONSTRAINT IF NOT EXISTS``, and a second ``ADD`` would
fail on the first constraint the first run managed. The helper reads the
catalogue and picks up where the previous run stopped: a constraint that is
missing is added and validated, one that exists unvalidated is only validated,
and one that is already validated is left alone. Repair the rows the scan
stopped on and re-run the upgrade.

Both helpers are Postgres-only, which is what the application runs on, and they
are what revisions call rather than only the code of the day: their behaviour
has to stay what the revisions that already used them were written against.
"""

from alembic import op
from sqlalchemy import text

# Whether a check constraint of this name is on this table, and whether it has
# been validated. Constraint names are unique per table rather than per schema,
# so the table is half of the question.
_CONSTRAINT_STATE = text(
    "SELECT convalidated FROM pg_constraint WHERE conname = :name AND contype = 'c' AND conrelid = to_regclass(:table)"
)


def _quoted(identifier: str) -> str:
    """Wrap an identifier in double quotes so Postgres reads it as a name.

    ``transaction`` is a reserved word and the ledger table is called exactly
    that, so this is not decoration.

    Args:
        identifier: The name of a table or a constraint.

    Returns:
        The name, quoted.
    """
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def _validation_state(name: str, table: str) -> bool | None:
    """Report what a previous run of the revision left behind.

    Args:
        name: The name of the constraint.
        table: The table it is on.

    Returns:
        ``None`` when the constraint is not there, ``False`` when it is there
        but has not been validated, and ``True`` when it is validated.
    """
    row = op.get_bind().execute(_CONSTRAINT_STATE, {"name": name, "table": _quoted(table)}).first()
    return None if row is None else bool(row.convalidated)


def add_check_constraint(name: str, table: str, condition: str) -> None:
    """Apply a ``CHECK`` constraint without holding the table shut for the scan.

    The constraint is added unvalidated, which is quick and starts enforcing
    the condition on everything written from then on, and the rows that were
    already there are checked afterwards without blocking readers or writers.
    A row that fails the check stops the revision, which is the point: it is
    for a person to look at rather than for a migration to quietly rewrite.

    Args:
        name: The name of the constraint, which is what a re-run recognises it
            by and what the downgrade drops.
        table: The table to put it on.
        condition: The SQL expression the rows have to satisfy, written out in
            full rather than built from a constant, since a revision is a
            record of what was applied.
    """
    with op.get_context().autocommit_block():
        state = _validation_state(name, table)
        if state is None:
            op.execute(f"ALTER TABLE {_quoted(table)} ADD CONSTRAINT {_quoted(name)} CHECK ({condition}) NOT VALID")
        if not state:
            op.execute(f"ALTER TABLE {_quoted(table)} VALIDATE CONSTRAINT {_quoted(name)}")


def drop_check_constraint(name: str, table: str) -> None:
    """Remove a ``CHECK`` constraint applied by :func:`add_check_constraint`.

    ``IF EXISTS`` because the upgrade this undoes may have stopped part way
    through and left only some of its constraints behind: a downgrade of a
    half-applied revision should take away what is there rather than fail on
    the first thing that is not.

    Args:
        name: The name of the constraint.
        table: The table it is on.
    """
    op.execute(f"ALTER TABLE {_quoted(table)} DROP CONSTRAINT IF EXISTS {_quoted(name)}")
