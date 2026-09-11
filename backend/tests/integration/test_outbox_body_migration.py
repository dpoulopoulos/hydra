"""The revision ``e3a7b0c91f52`` empties the bodies the outbox already settled.

The application stopped keeping the rendered body of a settled message, but a
deployment that has been running holds one for every reset, verification and
invite it has ever sent, each spelling a single-use credential out in plain
text. Nothing would take those away until retention eventually removed the row.

This test gives the revision such a table: the schema is walked up to the
revision before it, seeded with settled rows that still have their bodies and
a pending row that still needs its own, and then migrated across.
"""

import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import Engine, text

from tests.integration.migrations import migrated_database

# The revision under test and the one it follows, which is where the rows are
# written: at that point the outbox still stored the body of a settled message.
REVISION = "e3a7b0c91f52"
PREVIOUS = "749d6ee122a6"

# A database of its own, next to the one the rest of the suite creates from the
# model metadata.
MIGRATION_DATABASE_SUFFIX = "_outbox_migration"

SENT_ID = uuid.UUID("00000000-0000-0000-0000-00000000b001")
FAILED_ID = uuid.UUID("00000000-0000-0000-0000-00000000b002")
PENDING_ID = uuid.UUID("00000000-0000-0000-0000-00000000b003")

# What the stored body looks like: the link is the whole point, since it is the
# token in it that a reader of the table would be able to redeem.
RESET_BODY = "<p><a href='https://example.com/reset-password?token=a-redeemable-token'>Reset</a></p>"

SEED = [
    "INSERT INTO emailoutbox (id, email_to, subject, html_content, status, attempts, next_attempt_at, sent_at)"
    " VALUES (:sent_id, 'sent@example.com', 'Reset your password', :body, 'SENT', 1, now(), now())",
    "INSERT INTO emailoutbox (id, email_to, subject, html_content, status, attempts, next_attempt_at)"
    " VALUES (:failed_id, 'failed@example.com', 'Verify your email', :body, 'FAILED', 5, now())",
    "INSERT INTO emailoutbox (id, email_to, subject, html_content, status, attempts, next_attempt_at)"
    " VALUES (:pending_id, 'pending@example.com', 'You have been invited', :body, 'PENDING', 0, now())",
]

SEED_PARAMETERS = {
    "sent_id": SENT_ID,
    "failed_id": FAILED_ID,
    "pending_id": PENDING_ID,
    "body": RESET_BODY,
}


@pytest.fixture(scope="module")
def migrated_engine() -> Generator[Engine]:
    """Migrate a seeded outbox across the revision that empties its settled rows.

    Yields:
        An engine bound to a database holding the rows the revision rewrote.
    """
    with migrated_database(
        suffix=MIGRATION_DATABASE_SUFFIX,
        previous=PREVIOUS,
        revision=REVISION,
        seed=SEED,
        parameters=SEED_PARAMETERS,
    ) as engine:
        yield engine


def _body(engine: Engine, entry_id: uuid.UUID) -> str:
    """Read back the body stored for an outbox row.

    Args:
        engine: The engine bound to the migrated database.
        entry_id: The message to read.

    Returns:
        The stored body.
    """
    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT html_content FROM emailoutbox WHERE id = :id"), {"id": entry_id}
        ).scalar_one()
    return str(stored)


class TestTheOutboxBodyRevision:
    """It takes the credentials out of the rows that were settled before it."""

    def test_it_applies(self, migrated_engine: Engine) -> None:
        """The revision is the one the database is now at."""
        with migrated_engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION

    def test_a_delivered_message_no_longer_holds_its_link(self, migrated_engine: Engine) -> None:
        """The message is long gone; what is left is a row saying it went."""
        assert _body(migrated_engine, SENT_ID) == ""

    def test_a_message_that_gave_up_no_longer_holds_its_link(self, migrated_engine: Engine) -> None:
        """Nobody is going to send it, so the body is a credential and nothing else."""
        assert _body(migrated_engine, FAILED_ID) == ""

    def test_a_message_still_waiting_keeps_its_body(self, migrated_engine: Engine) -> None:
        """It is still owed to somebody, and the body is what the next attempt sends."""
        assert _body(migrated_engine, PENDING_ID) == RESET_BODY
