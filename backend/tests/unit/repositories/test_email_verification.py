import uuid
from unittest.mock import MagicMock

import pytest

from app.repositories.email_verification import EmailVerificationRepository


@pytest.fixture
def repository(mock_db_session: MagicMock) -> EmailVerificationRepository:
    return EmailVerificationRepository(session=mock_db_session)


def test_a_pending_activation_is_a_row_without_a_new_address(
    repository: EmailVerificationRepository, mock_db_session: MagicMock
) -> None:
    """An activation proves the address the account already holds, so it names no other one."""
    mock_db_session.exec.return_value.first.return_value = None

    assert repository.get_pending_activation_by_user_id(uuid.uuid4()) is None

    statement = str(mock_db_session.exec.call_args.args[0])
    assert "new_email IS NULL" in statement


def test_a_pending_change_is_a_row_that_names_a_new_address(
    repository: EmailVerificationRepository, mock_db_session: MagicMock
) -> None:
    """A change of address is only ever recorded by the address it moves to."""
    mock_db_session.exec.return_value.first.return_value = None

    assert repository.get_pending_change_by_user_id(uuid.uuid4()) is None

    statement = str(mock_db_session.exec.call_args.args[0])
    assert "new_email IS NOT NULL" in statement


@pytest.mark.parametrize(
    "lookup",
    ["get_pending_activation_by_user_id", "get_pending_change_by_user_id"],
)
def test_either_lookup_only_considers_pending_rows_of_one_user(
    repository: EmailVerificationRepository, mock_db_session: MagicMock, lookup: str
) -> None:
    """A redeemed or expired row is spent, and another account's row is none of this one's business."""
    mock_db_session.exec.return_value.first.return_value = None
    user_id = uuid.uuid4()

    getattr(repository, lookup)(user_id)

    statement = mock_db_session.exec.call_args.args[0]
    assert "user_id = " in str(statement)
    parameters = statement.compile().params
    assert user_id in parameters.values()
    assert "pending" in parameters.values()


@pytest.mark.parametrize(
    "lookup",
    [
        "get_pending_by_user_id",
        "get_pending_activation_by_user_id",
        "get_pending_change_by_user_id",
    ],
)
def test_every_lookup_takes_the_newest_row_it_matches(
    repository: EmailVerificationRepository, mock_db_session: MagicMock, lookup: str
) -> None:
    """Taking the first of several rows only means something once the order is said."""
    mock_db_session.exec.return_value.first.return_value = None

    getattr(repository, lookup)(uuid.uuid4())

    statement = str(mock_db_session.exec.call_args.args[0])
    assert "ORDER BY emailverification.created_at DESC" in statement
