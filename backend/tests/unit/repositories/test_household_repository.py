import uuid
from unittest.mock import MagicMock

from app.repositories.household import HouseholdRepository

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def test_lists_the_households_that_hold_no_categories(mock_db_session: MagicMock) -> None:
    repository = HouseholdRepository(session=mock_db_session)
    mock_db_session.exec.return_value.all.return_value = [HOUSEHOLD_ID]

    result = repository.list_ids_without_categories()

    assert result == [HOUSEHOLD_ID]
    statement = str(mock_db_session.exec.call_args.args[0])
    assert "LEFT OUTER JOIN category" in statement
    assert "category.id IS NULL" in statement
