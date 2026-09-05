from unittest.mock import MagicMock

import pytest

from app.repositories.user import UserRepository


@pytest.fixture
def repository(mock_db_session: MagicMock) -> UserRepository:
    return UserRepository(session=mock_db_session)


def test_lists_a_page_and_counts_the_whole_table(repository: UserRepository, mock_db_session: MagicMock) -> None:
    mock_db_session.exec.return_value.one.return_value = 12
    mock_db_session.exec.return_value.all.return_value = []

    users, count = repository.get_all_paginated(skip=10, limit=5)

    assert list(users) == []
    assert count == 12


def test_counts_without_loading_the_rows(repository: UserRepository, mock_db_session: MagicMock) -> None:
    repository.get_all_paginated()

    count_statement = str(mock_db_session.exec.call_args_list[0].args[0])
    assert "count(" in count_statement
    assert "LIMIT" not in count_statement


def test_the_page_is_paged_through_the_shared_helper(repository: UserRepository, mock_db_session: MagicMock) -> None:
    repository.get_all_paginated(skip=10, limit=5)

    page_statement = mock_db_session.exec.call_args_list[1].args[0]
    compiled = str(page_statement.compile(compile_kwargs={"literal_binds": True}))
    assert "LIMIT 5" in compiled
    assert "OFFSET 10" in compiled
