"""Every numeric ceiling on an input model has to be mirrored in SQL.

A bound that lives only in Pydantic holds for what arrives through the API and
for nothing else. A script, a data migration or a service that writes a row
directly reaches the column with no validator in between, which is exactly the
gap the floors already in SQL — ``ck_transaction_amount_positive`` and friends —
were added to close. The expressions are built from the constants, so the number
in Python and the number in the constraint cannot drift.
"""

import importlib
import pkgutil
from pathlib import Path

import pytest
from annotated_types import Le
from sqlalchemy import CheckConstraint
from sqlmodel import SQLModel

from app import models
from app.models.category import MAX_SORT_ORDER
from app.models.fields import MAX_AMOUNT_MINOR, MAX_FX_RATE_MICRO, MAX_PRICE_MICRO, MAX_QUANTITY_MICRO
from app.models.recurring_rule import MAX_RECURRENCE_INTERVAL

# (table, constraint name, the SQL the constraint has to carry). Every numeric
# ceiling an input model enforces belongs here, so a new bound added in Python
# with no constraint beside it fails the suite rather than shipping as a rule
# the database does not know about.
CEILINGS = [
    # Money.
    ("transaction", "ck_transaction_amount_within_cap", f"amount_minor <= {MAX_AMOUNT_MINOR}"),
    ("budget", "ck_budget_limit_within_cap", f"limit_minor <= {MAX_AMOUNT_MINOR}"),
    ("recurringrule", "ck_recurringrule_amount_within_cap", f"amount_minor <= {MAX_AMOUNT_MINOR}"),
    ("incomeclient", "ck_incomeclient_rate_within_cap", f"default_rate_minor <= {MAX_AMOUNT_MINOR}"),
    ("incomesession", "ck_incomesession_fee_within_cap", f"fee_minor <= {MAX_AMOUNT_MINOR}"),
    ("trade", "ck_trade_fee_within_cap", f"fee_minor <= {MAX_AMOUNT_MINOR}"),
    (
        "trade",
        "ck_trade_cash_within_cap",
        f"cash_amount_minor IS NULL OR (cash_amount_minor <= {MAX_AMOUNT_MINOR})",
    ),
    (
        "account",
        "ck_account_opening_balance_within_cap",
        f"opening_balance_minor >= -{MAX_AMOUNT_MINOR} AND opening_balance_minor <= {MAX_AMOUNT_MINOR}",
    ),
    # Quantities, prices and rates. The first two are a pair: their product, in
    # minor units, has to stay under the money cap or a position's market value
    # overflows the column it is summed into.
    ("trade", "ck_trade_quantity_within_cap", f"quantity_micro <= {MAX_QUANTITY_MICRO}"),
    ("trade", "ck_trade_price_within_cap", f"price_micro <= {MAX_PRICE_MICRO}"),
    (
        "instrument",
        "ck_instrument_price_within_cap",
        f"last_price_micro IS NULL OR (last_price_micro <= {MAX_PRICE_MICRO})",
    ),
    ("fxrate", "ck_fx_rate_within_cap", f"rate_micro <= {MAX_FX_RATE_MICRO}"),
    # Plain integers.
    ("recurringrule", "ck_recurringrule_interval_within_cap", f"interval <= {MAX_RECURRENCE_INTERVAL}"),
    (
        "incomeclient",
        "ck_incomeclient_cadence_interval_within_cap",
        f"cadence_interval <= {MAX_RECURRENCE_INTERVAL}",
    ),
    ("category", "ck_category_sort_order_range", f"sort_order >= 0 AND sort_order <= {MAX_SORT_ORDER}"),
]

VERSIONS = Path(__file__).parents[3] / "src" / "app" / "alembic" / "versions"


def _check_constraint(table_name: str, constraint_name: str) -> CheckConstraint | None:
    """Find a named check constraint on a table.

    Args:
        table_name: The name of the table.
        constraint_name: The name of the constraint.

    Returns:
        The constraint, or None if the table does not carry one by that name.
    """
    table = SQLModel.metadata.tables[table_name]

    for constraint in table.constraints:
        if isinstance(constraint, CheckConstraint) and constraint.name == constraint_name:
            return constraint

    return None


@pytest.mark.parametrize(("table_name", "constraint_name", "sql"), CEILINGS, ids=lambda value: str(value))
class TestNumericCeilings:
    """The table mirrors the ceiling the input models enforce."""

    def test_the_table_carries_the_constraint(self, table_name: str, constraint_name: str, sql: str) -> None:
        constraint = _check_constraint(table_name, constraint_name)

        assert constraint is not None, f"{table_name} has no {constraint_name}"

    def test_the_constraint_is_built_from_the_constant(self, table_name: str, constraint_name: str, sql: str) -> None:
        """The number in the SQL is the constant itself, so the two cannot drift."""
        constraint = _check_constraint(table_name, constraint_name)

        assert constraint is not None
        assert str(constraint.sqltext) == sql

    def test_a_migration_applies_the_same_expression(self, table_name: str, constraint_name: str, sql: str) -> None:
        """A revision has to carry the constraint, or the database never gets it.

        The model metadata is what the app declares and a migration is what the
        database was actually given. Raising a constant without adding a
        revision would leave the two saying different things, which this
        catches without needing a server to compare them on.
        """
        applied = [source.read_text() for source in VERSIONS.glob("*.py") if constraint_name in source.read_text()]

        assert applied, f"no revision creates {constraint_name}"
        assert any(f"'{sql}'" in source for source in applied), f"no revision applies {sql}"


def _bounded_field_names() -> set[str]:
    """Collect every field name an input model puts a numeric ceiling on.

    Returns:
        The field names carrying a ``le=`` bound, across every model in the
        package.
    """
    for module in pkgutil.iter_modules(models.__path__):
        importlib.import_module(f"app.models.{module.name}")

    subclasses: set[type[SQLModel]] = set()
    pending = [SQLModel]

    while pending:
        for subclass in pending.pop().__subclasses__():
            if subclass not in subclasses:
                subclasses.add(subclass)
                pending.append(subclass)

    return {
        name
        for subclass in subclasses
        for name, field in subclass.model_fields.items()
        if any(isinstance(meta, Le) for meta in field.metadata)
    }


class TestEveryCeilingReachesSql:
    """The rule the README states, checked rather than trusted.

    The list above is written by hand, so it only covers the bounds somebody
    remembered to add to it. This walks the models instead: every ``le=`` on an
    input model whose field is also a stored column has to have a check
    constraint on that column, which is what a new bound added in Python with
    no SQL beside it trips over.
    """

    def test_a_bounded_column_carries_a_check(self) -> None:
        missing = []

        for field_name in sorted(_bounded_field_names()):
            for table_name, table in SQLModel.metadata.tables.items():
                # A bound on something that is not a column — a page size, a
                # filter's range — has no SQL half to mirror and is skipped.
                if field_name not in table.columns:
                    continue

                expressions = [
                    str(constraint.sqltext)
                    for constraint in table.constraints
                    if isinstance(constraint, CheckConstraint)
                ]

                if not any(f"{field_name} <=" in expression for expression in expressions):
                    missing.append(f"{table_name}.{field_name}")

        assert not missing, f"bounded in Python with no CHECK in SQL: {', '.join(missing)}"
