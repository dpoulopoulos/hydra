"""What the migration helpers emit, without a database to emit it against.

The statements are what matters here: that a check is added as ``NOT VALID``
and validated separately, in that order, and that a second run over a database
where one or both of those already happened does not repeat them. The
integration tier next to this one runs the same helper against a real Postgres
and asserts on the locks and the rows; this one is about the SQL.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core import migrations


@pytest.fixture
def alembic_op(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace the alembic operations proxy the helpers run through.

    Args:
        monkeypatch: The fixture that puts the real proxy back afterwards.

    Returns:
        The stand-in the helpers call, with no constraint in place yet.
    """
    fake = MagicMock()
    fake.get_bind.return_value.execute.return_value.first.return_value = None
    monkeypatch.setattr(migrations, "op", fake)
    return fake


def statements(alembic_op: MagicMock) -> list[str]:
    """Collect the DDL the helper asked alembic to run.

    Args:
        alembic_op: The stand-in for the operations proxy.

    Returns:
        The statements, in the order they were emitted.
    """
    return [str(call.args[0]) for call in alembic_op.execute.call_args_list]


def set_existing(alembic_op: MagicMock, *, validated: bool) -> None:
    """Say that the constraint is already on the table.

    Args:
        alembic_op: The stand-in for the operations proxy.
        validated: Whether the existing constraint has been validated.
    """
    alembic_op.get_bind.return_value.execute.return_value.first.return_value = SimpleNamespace(convalidated=validated)


class TestAddCheckConstraint:
    """It adds the constraint unvalidated, then validates it."""

    def test_it_adds_the_constraint_before_validating_it(self, alembic_op: MagicMock) -> None:
        """Two statements rather than one: the add is what makes the check hold from now on."""
        migrations.add_check_constraint("ck_transaction_amount_within_cap", "transaction", "amount_minor <= 10")

        assert statements(alembic_op) == [
            'ALTER TABLE "transaction" ADD CONSTRAINT "ck_transaction_amount_within_cap"'
            " CHECK (amount_minor <= 10) NOT VALID",
            'ALTER TABLE "transaction" VALIDATE CONSTRAINT "ck_transaction_amount_within_cap"',
        ]

    def test_it_runs_outside_the_migration_transaction(self, alembic_op: MagicMock) -> None:
        """Both halves under alembic's one transaction would hold the exclusive lock across the scan anyway."""
        migrations.add_check_constraint("ck_budget_limit_within_cap", "budget", "limit_minor <= 10")

        alembic_op.get_context.return_value.autocommit_block.assert_called_once_with()

    def test_it_only_validates_a_constraint_that_is_already_there(self, alembic_op: MagicMock) -> None:
        """Re-running a revision that stopped in the scan: Postgres has no ADD CONSTRAINT IF NOT EXISTS."""
        set_existing(alembic_op, validated=False)

        migrations.add_check_constraint("ck_budget_limit_within_cap", "budget", "limit_minor <= 10")

        assert statements(alembic_op) == ['ALTER TABLE "budget" VALIDATE CONSTRAINT "ck_budget_limit_within_cap"']

    def test_it_does_nothing_for_a_constraint_that_is_already_validated(self, alembic_op: MagicMock) -> None:
        """A revision re-run after it succeeded is a no-op, not a second scan of the table."""
        set_existing(alembic_op, validated=True)

        migrations.add_check_constraint("ck_budget_limit_within_cap", "budget", "limit_minor <= 10")

        assert statements(alembic_op) == []

    def test_it_quotes_names_that_the_parser_would_read_as_something_else(self, alembic_op: MagicMock) -> None:
        """`transaction` is a keyword, and the ledger table is named after it."""
        migrations.add_check_constraint("ck_transaction_amount_positive", "transaction", "amount_minor > 0")

        assert all('"transaction"' in statement for statement in statements(alembic_op))

    def test_it_looks_the_constraint_up_on_the_table_it_belongs_to(self, alembic_op: MagicMock) -> None:
        """Constraint names are unique per table in Postgres, so the name alone is not the question."""
        migrations.add_check_constraint("ck_trade_fee_within_cap", "trade", "fee_minor <= 10")

        parameters = alembic_op.get_bind.return_value.execute.call_args.args[1]
        assert parameters == {"name": "ck_trade_fee_within_cap", "table": '"trade"'}


class TestDropCheckConstraint:
    """It drops the constraint whether or not the upgrade got as far as adding it."""

    def test_it_drops_the_constraint(self, alembic_op: MagicMock) -> None:
        """The downgrade half of the pair."""
        migrations.drop_check_constraint("ck_trade_fee_within_cap", "trade")

        assert statements(alembic_op) == ['ALTER TABLE "trade" DROP CONSTRAINT IF EXISTS "ck_trade_fee_within_cap"']
