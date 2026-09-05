import uuid
from unittest.mock import MagicMock

import pytest

from app.models import Account, AccountType
from app.repositories.account import AccountRepository

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def repository(mock_db_session: MagicMock) -> AccountRepository:
    return AccountRepository(session=mock_db_session)


def test_lists_a_page_and_counts_the_whole_match(
    repository: AccountRepository, mock_db_session: MagicMock
) -> None:
    account = Account(household_id=HOUSEHOLD_ID, name="Current", type=AccountType.CURRENT)
    mock_db_session.exec.return_value.one.return_value = 7
    mock_db_session.exec.return_value.all.return_value = [account]

    page, count = repository.list_for_household(household_id=HOUSEHOLD_ID, skip=10, limit=5)

    assert list(page) == [account]
    assert count == 7


def test_counts_without_loading_the_rows(repository: AccountRepository, mock_db_session: MagicMock) -> None:
    mock_db_session.exec.return_value.one.return_value = 0

    repository.list_for_household(household_id=HOUSEHOLD_ID)

    count_statement = str(mock_db_session.exec.call_args_list[0].args[0])
    assert "count(" in count_statement
    assert "LIMIT" not in count_statement


def test_the_page_is_ordered_and_paged(repository: AccountRepository, mock_db_session: MagicMock) -> None:
    repository.list_for_household(household_id=HOUSEHOLD_ID, skip=10, limit=5)

    page_statement = str(mock_db_session.exec.call_args_list[1].args[0])
    assert "ORDER BY account.name" in page_statement
    assert "LIMIT" in page_statement
    assert "OFFSET" in page_statement


def test_the_count_carries_the_same_filters_as_the_page(
    repository: AccountRepository, mock_db_session: MagicMock
) -> None:
    repository.list_for_household(household_id=HOUSEHOLD_ID, account_type=AccountType.SAVINGS)

    count_statement = str(mock_db_session.exec.call_args_list[0].args[0])
    assert "account.household_id = " in count_statement
    assert "account.archived_at IS NULL" in count_statement
    assert "account.type = " in count_statement


def test_archived_accounts_are_included_on_request(
    repository: AccountRepository, mock_db_session: MagicMock
) -> None:
    repository.list_for_household(household_id=HOUSEHOLD_ID, include_archived=True)

    count_statement = str(mock_db_session.exec.call_args_list[0].args[0])
    assert "archived_at" not in count_statement
