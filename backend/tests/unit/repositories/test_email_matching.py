import uuid
from unittest.mock import MagicMock

import pytest

from app.repositories.email_verification import EmailVerificationRepository
from app.repositories.user import UserRepository


@pytest.fixture
def user_repository(mock_db_session: MagicMock) -> UserRepository:
    return UserRepository(session=mock_db_session)


@pytest.fixture
def email_verification_repository(mock_db_session: MagicMock) -> EmailVerificationRepository:
    return EmailVerificationRepository(session=mock_db_session)


def test_looks_a_user_up_by_address_ignoring_case(user_repository: UserRepository, mock_db_session: MagicMock) -> None:
    """Addresses are stored as typed, so equality would miss a normalised caller."""
    mock_db_session.exec.return_value.first.return_value = None

    assert user_repository.get_by_email_ignoring_case("Partner@Example.com") is None

    statement = mock_db_session.exec.call_args.args[0]
    assert "lower(" in str(statement)
    assert "partner@example.com" in statement.compile().params.values()


def test_looks_a_proof_up_by_address_ignoring_case(
    email_verification_repository: EmailVerificationRepository, mock_db_session: MagicMock
) -> None:
    """The proof records the address as typed, the invited address is normalised."""
    mock_db_session.exec.return_value.first.return_value = None

    assert not email_verification_repository.has_verified(user_id=uuid.uuid4(), email="Partner@Example.com")

    statement = mock_db_session.exec.call_args.args[0]
    assert "lower(" in str(statement)
    assert "partner@example.com" in statement.compile().params.values()
