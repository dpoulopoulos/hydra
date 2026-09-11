"""Machinery for the tests that run revisions instead of creating a schema.

The rest of the integration suite builds its schema from ``SQLModel.metadata``,
which skips every revision and so can say nothing about what one does. A test
that is about a revision needs the other thing: a database of its own, walked
up to the revision before the one under test, seeded while the old shape is
still in place, and then migrated across.

That is the same handful of steps whichever revision is under test, so it lives
here rather than in each of them.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text

from app.core.config import settings


def database_url(database: str) -> str:
    """Build a connection URL for a database on the configured server.

    Args:
        database: The name of the database to connect to.

    Returns:
        The URL of that database on the server the settings point at.
    """
    return str(settings.SQLALCHEMY_DATABASE_URI).rsplit("/", 1)[0] + f"/{database}"


@contextmanager
def settings_pointed_at(database: str) -> Iterator[None]:
    """Point the settings at another database for the duration of the block.

    ``alembic/env.py`` builds its URL from the settings and takes no override,
    so this is what makes a revision run somewhere other than the application's
    own database. It is put back afterwards, since the rest of the suite reads
    the same object.

    Args:
        database: The name of the database the revisions should run against.

    Yields:
        None, with the settings pointed at that database.
    """
    original = settings.POSTGRES_DB
    settings.POSTGRES_DB = database
    try:
        yield
    finally:
        settings.POSTGRES_DB = original


def alembic_config() -> Config:
    """Build an alembic configuration that points at the revisions.

    The script location is set here rather than read from ``alembic.ini``:
    ``env.py`` runs ``fileConfig`` on whichever file it was handed, which
    reconfigures logging for the whole process and silences the loggers other
    tests in the run assert on.

    Returns:
        A configuration alembic can run a revision from.
    """
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[2] / "src" / "app" / "alembic"))
    return config


@contextmanager
def migrated_database(
    *,
    suffix: str,
    previous: str,
    revision: str,
    seed: list[str],
    parameters: Mapping[str, object],
) -> Iterator[Engine]:
    """Seed a database at one revision and migrate it across the next.

    Args:
        suffix: What to call the database, after the application's own name.
            A database per test module, so migrating one in place cannot leave
            another module running against whichever revision it stopped at.
        previous: The revision to walk up to before seeding, which is where the
            rows are written in the shape the old schema allowed.
        revision: The revision under test, the one the seeded rows are migrated
            across.
        seed: The statements that write the rows, in order.
        parameters: The values those statements bind.

    Yields:
        An engine bound to the migrated database.
    """
    database = f"{settings.POSTGRES_DB}{suffix}"

    # CREATE DATABASE cannot run inside a transaction block, hence autocommit.
    # It is dropped first rather than reused: a run that failed half way leaves
    # the schema at whichever revision it stopped on.
    admin = create_engine(database_url("postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{database}"'))

    engine = create_engine(database_url(database))
    config = alembic_config()

    with settings_pointed_at(database):
        command.upgrade(config, previous)

        with engine.begin() as connection:
            for statement in seed:
                connection.execute(text(statement), parameters)

        command.upgrade(config, revision)

    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        admin.dispose()
