import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.models import TransactionFilters, TransactionKind
from app.repositories.transaction import TransactionRepository

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def repository(mock_db_session: MagicMock) -> TransactionRepository:
    return TransactionRepository(session=mock_db_session)


def search_condition(repository: TransactionRepository, term: str) -> Any:
    """Build the condition a search term contributes to a listing."""
    conditions = repository._conditions(filters=TransactionFilters(q=term), category_ids=None)
    return conditions[-1]


def search_patterns(repository: TransactionRepository, term: str) -> set[str]:
    """Collect the distinct LIKE patterns a search term compiles to."""
    return set(search_condition(repository, term).compile().params.values())


def test_lists_a_page_and_counts_the_whole_match(repository: TransactionRepository, mock_db_session: MagicMock) -> None:
    mock_db_session.exec.return_value.one.return_value = 7
    mock_db_session.exec.return_value.all.return_value = []

    page, count = repository.list_for_household(household_id=HOUSEHOLD_ID, filters=TransactionFilters(skip=10, limit=5))

    assert list(page) == []
    assert count == 7


def test_counts_without_loading_the_rows(repository: TransactionRepository, mock_db_session: MagicMock) -> None:
    repository.list_for_household(household_id=HOUSEHOLD_ID, filters=TransactionFilters())

    count_statement = str(mock_db_session.exec.call_args_list[0].args[0])
    assert "count(" in count_statement
    assert "transaction.household_id = " in count_statement
    assert "LIMIT" not in count_statement


def test_the_page_is_ordered_and_paged(repository: TransactionRepository, mock_db_session: MagicMock) -> None:
    repository.list_for_household(household_id=HOUSEHOLD_ID, filters=TransactionFilters(skip=10, limit=5))

    page_statement = str(mock_db_session.exec.call_args_list[1].args[0])
    assert "ORDER BY transaction.occurred_on" in page_statement
    assert "LIMIT" in page_statement
    assert "OFFSET" in page_statement


def test_the_count_carries_the_same_filters_as_the_page(
    repository: TransactionRepository, mock_db_session: MagicMock
) -> None:
    repository.list_for_household(
        household_id=HOUSEHOLD_ID, filters=TransactionFilters(kind=TransactionKind.EXPENSE, q="coffee")
    )

    count_statement = str(mock_db_session.exec.call_args_list[0].args[0])
    page_statement = str(mock_db_session.exec.call_args_list[1].args[0])
    for statement in (count_statement, page_statement):
        assert "transaction.household_id = " in statement
        assert "transaction.kind = " in statement
        assert "lower(transaction.merchant) LIKE" in statement


@pytest.mark.parametrize(
    ("term", "pattern"),
    [
        ("acme", "%acme%"),
        ("50%", "%50\\%%"),
        ("ACME_LTD", "%ACME\\_LTD%"),
        ("a\\_b", "%a\\\\\\_b%"),
    ],
    ids=["plain term", "percent sign", "underscore", "backslash before a metacharacter"],
)
def test_a_term_is_matched_literally(repository: TransactionRepository, term: str, pattern: str) -> None:
    assert search_patterns(repository, term) == {pattern}


def test_the_search_declares_its_escape_character(repository: TransactionRepository) -> None:
    assert "ESCAPE '\\'" in str(search_condition(repository, "50%"))


def test_the_search_covers_the_merchant_and_the_note(repository: TransactionRepository) -> None:
    compiled = str(search_condition(repository, "acme"))

    assert "transaction.merchant" in compiled
    assert "transaction.note" in compiled
