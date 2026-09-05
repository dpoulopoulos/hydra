import uuid
from unittest.mock import MagicMock

import pytest

from app.repositories.recurring_rule import RecurringRuleRepository

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
ACCOUNT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def recurring_rule_repository(mock_db_session: MagicMock) -> RecurringRuleRepository:
    return RecurringRuleRepository(session=mock_db_session)


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
