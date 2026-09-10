"""Every stored timestamp has to record the zone it was written in.

The values the app writes are tz-aware UTC, so a column declared ``timestamp
without time zone`` keeps the wall time and drops the fact that it is UTC. The
API then serialises it with no offset, and ECMAScript reads a date-time in that
shape as *local* time: ``new Date(value)`` in the browser shifts the instant by
the viewer's own offset. Storing ``timestamptz`` is what makes the response say
what it means, so this walks the metadata rather than trusting each column
declaration to have remembered.
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import DateTime

from app.models import HouseholdInvitePublic, SQLModel

# (table, column) for every timestamp in the schema, read off the metadata so a
# column added later is covered without being listed here.
TIMESTAMP_COLUMNS = sorted(
    (table_name, column.name)
    for table_name, table in SQLModel.metadata.tables.items()
    for column in table.columns
    if isinstance(column.type, DateTime)
)

VERSIONS = Path(__file__).parents[3] / "src" / "app" / "alembic" / "versions"


@pytest.mark.parametrize(("table_name", "column_name"), TIMESTAMP_COLUMNS, ids=lambda value: str(value))
class TestTimestampColumns:
    """The column carries its zone, in the models and in the database."""

    def test_the_column_is_declared_with_a_zone(self, table_name: str, column_name: str) -> None:
        column = SQLModel.metadata.tables[table_name].columns[column_name]

        assert isinstance(column.type, DateTime)
        assert column.type.timezone, f"{table_name}.{column_name} is timestamp without time zone"

    def test_a_migration_gives_the_column_its_zone(self, table_name: str, column_name: str) -> None:
        """A revision has to declare the zone, or the database never gets it.

        The metadata is what the app says the column is; a migration is what
        the database was actually given. Declaring ``timezone=True`` with no
        revision beside it would leave the two disagreeing, which no amount of
        reading the models would catch.
        """
        sources = [source.read_text() for source in VERSIONS.glob("*.py")]
        applied = [
            source for source in sources if table_name in source and column_name in source and "timezone=True" in source
        ]

        assert applied, f"no revision declares {table_name}.{column_name} with a zone"


class TestTheWireFormat:
    """What the offset on the column buys the caller.

    A timestamp read back off a ``timestamptz`` column is tz-aware, and an
    aware datetime serialises with its offset. That offset is the whole point
    of the change: it is what stops the browser from guessing.
    """

    def test_a_response_carries_an_offset(self) -> None:
        invite = HouseholdInvitePublic(
            id=uuid.uuid4(),
            household_id=uuid.uuid4(),
            email="someone@example.com",
            expires_at=datetime(2026, 9, 12, 7, 40, 58, tzinfo=UTC),
            created_at=datetime(2026, 9, 5, 7, 40, 58, tzinfo=UTC),
        )

        assert '"expires_at":"2026-09-12T07:40:58Z"' in invite.model_dump_json()
