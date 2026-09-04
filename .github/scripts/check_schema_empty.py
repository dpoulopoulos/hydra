"""Verify that reverting every migration leaves the database schema empty.

Alembic drops tables on downgrade but does not drop the enum types those tables
introduced, so a revert can silently leave objects behind. They only surface
later, when the next upgrade fails with DuplicateObject.

Exits non-zero, naming what was left behind, if anything other than alembic's
own version table remains.
"""

import sys

from sqlalchemy import text

from app.core.db import engine

TABLES = text("""
    SELECT tablename FROM pg_tables
    WHERE schemaname = 'public' AND tablename <> 'alembic_version'
    ORDER BY tablename
""")

# 'e' is the enum type category.
ENUMS = text("""
    SELECT t.typname FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'public' AND t.typtype = 'e'
    ORDER BY t.typname
""")


def main() -> int:
    """Report any tables or enum types the revert failed to remove.

    Returns:
        0 if the schema is empty, 1 otherwise.
    """
    with engine.connect() as connection:
        tables = [row[0] for row in connection.execute(TABLES)]
        enums = [row[0] for row in connection.execute(ENUMS)]

    if not tables and not enums:
        print("Schema is empty: the revert removed every table and enum type.")  # noqa: T201
        return 0

    if tables:
        print(f"Tables left behind by the revert: {', '.join(tables)}")  # noqa: T201
    if enums:
        print(f"Enum types left behind by the revert: {', '.join(enums)}")  # noqa: T201
    print("Add the matching drops to the downgrade() of the revision that created them.")  # noqa: T201
    return 1


if __name__ == "__main__":
    sys.exit(main())
