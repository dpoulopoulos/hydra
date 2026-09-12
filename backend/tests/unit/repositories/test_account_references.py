import uuid
from unittest.mock import MagicMock

import pytest

from app.repositories.income import IncomeClientRepository
from app.repositories.investment import TradeRepository
from app.repositories.recurring_rule import RecurringRuleRepository

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
ACCOUNT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def recurring_rule_repository(mock_db_session: MagicMock) -> RecurringRuleRepository:
    return RecurringRuleRepository(session=mock_db_session)


@pytest.fixture
def income_client_repository(mock_db_session: MagicMock) -> IncomeClientRepository:
    return IncomeClientRepository(session=mock_db_session)


@pytest.fixture
def trade_repository(mock_db_session: MagicMock) -> TradeRepository:
    return TradeRepository(session=mock_db_session)


def test_counts_the_rules_paid_from_an_account(
    recurring_rule_repository: RecurringRuleRepository, mock_db_session: MagicMock
) -> None:
    mock_db_session.exec.return_value.one.return_value = 2

    result = recurring_rule_repository.count_for_account(account_id=ACCOUNT_ID, household_id=HOUSEHOLD_ID)

    assert result == 2
    statement = str(mock_db_session.exec.call_args.args[0])
    assert "count(" in statement
    assert "recurringrule" in statement
    assert "recurringrule.account_id" in statement
    assert "counter_account_id" not in statement


def test_counts_the_transfer_rules_pointing_at_an_account(
    recurring_rule_repository: RecurringRuleRepository, mock_db_session: MagicMock
) -> None:
    mock_db_session.exec.return_value.one.return_value = 1

    result = recurring_rule_repository.count_for_counter_account(account_id=ACCOUNT_ID, household_id=HOUSEHOLD_ID)

    assert result == 1
    statement = str(mock_db_session.exec.call_args.args[0])
    assert "count(" in statement
    assert "recurringrule" in statement
    assert "counter_account_id" in statement


def test_counts_the_clients_paid_into_an_account(
    income_client_repository: IncomeClientRepository, mock_db_session: MagicMock
) -> None:
    mock_db_session.exec.return_value.one.return_value = 3

    result = income_client_repository.count_for_default_account(account_id=ACCOUNT_ID, household_id=HOUSEHOLD_ID)

    assert result == 3
    statement = str(mock_db_session.exec.call_args.args[0])
    assert "count(" in statement
    assert "incomeclient" in statement
    assert "default_account_id" in statement


def test_counts_archived_clients_as_blockers_too(
    income_client_repository: IncomeClientRepository, mock_db_session: MagicMock
) -> None:
    """Archiving a client hides it from the user but leaves its foreign key in place."""
    income_client_repository.count_for_default_account(account_id=ACCOUNT_ID, household_id=HOUSEHOLD_ID)

    statement = str(mock_db_session.exec.call_args.args[0])
    assert "archived_at" not in statement


def test_counts_the_trades_settled_through_an_account(
    trade_repository: TradeRepository, mock_db_session: MagicMock
) -> None:
    mock_db_session.exec.return_value.one.return_value = 4

    result = trade_repository.count_for_brokerage_account(account_id=ACCOUNT_ID, household_id=HOUSEHOLD_ID)

    assert result == 4
    statement = str(mock_db_session.exec.call_args.args[0])
    assert "count(" in statement
    assert "trade" in statement
    assert "brokerage_account_id" in statement
