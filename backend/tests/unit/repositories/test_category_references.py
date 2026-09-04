import uuid
from unittest.mock import MagicMock

import pytest

from app.repositories.budget import BudgetRepository
from app.repositories.recurring_rule import RecurringRuleRepository

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
CATEGORY_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


@pytest.fixture
def budget_repository(mock_db_session: MagicMock) -> BudgetRepository:
    return BudgetRepository(session=mock_db_session)


@pytest.fixture
def recurring_rule_repository(mock_db_session: MagicMock) -> RecurringRuleRepository:
    return RecurringRuleRepository(session=mock_db_session)


def test_counts_the_budgets_of_a_category(budget_repository: BudgetRepository, mock_db_session: MagicMock) -> None:
    mock_db_session.exec.return_value.one.return_value = 2

    result = budget_repository.count_for_category(category_id=CATEGORY_ID, household_id=HOUSEHOLD_ID)

    assert result == 2
    statement = str(mock_db_session.exec.call_args.args[0])
    assert "count(" in statement
    assert "budget" in statement
    assert "category_id" in statement


def test_counts_the_rules_of_a_category(
    recurring_rule_repository: RecurringRuleRepository, mock_db_session: MagicMock
) -> None:
    mock_db_session.exec.return_value.one.return_value = 1

    result = recurring_rule_repository.count_for_category(category_id=CATEGORY_ID, household_id=HOUSEHOLD_ID)

    assert result == 1
    statement = str(mock_db_session.exec.call_args.args[0])
    assert "count(" in statement
    assert "recurringrule" in statement
    assert "category_id" in statement
