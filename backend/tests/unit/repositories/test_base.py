import uuid
from unittest.mock import MagicMock

import pytest
from sqlmodel import Field, Session, SQLModel

from app.models.mixins import CreatedAtMixin, PrimaryKeyMixin, UpdatedAtMixin
from app.repositories.base import BaseRepository, HouseholdScopedRepository


class ScopedThing(PrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, SQLModel, table=True):
    """A stand-in household-owned table, defined only for these tests."""

    __tablename__ = "scopedthing"

    household_id: uuid.UUID = Field(index=True)
    name: str = Field(default="thing")


class ScopedThingRepository(HouseholdScopedRepository[ScopedThing]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ScopedThing)


@pytest.fixture
def household_id() -> uuid.UUID:
    return uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def repository(mock_db_session: MagicMock) -> ScopedThingRepository:
    return ScopedThingRepository(session=mock_db_session)


def test_is_a_base_repository(repository: ScopedThingRepository) -> None:
    assert isinstance(repository, BaseRepository)
    assert repository.model_class is ScopedThing


def test_get_for_household_returns_the_entity(
    repository: ScopedThingRepository, mock_db_session: MagicMock, household_id: uuid.UUID
) -> None:
    entity = ScopedThing(household_id=household_id)
    mock_db_session.exec.return_value.first.return_value = entity

    result = repository.get_for_household(entity_id=entity.id, household_id=household_id)

    assert result is entity


def test_get_for_household_filters_on_id_and_household(
    repository: ScopedThingRepository, mock_db_session: MagicMock, household_id: uuid.UUID
) -> None:
    entity_id = uuid.uuid4()

    repository.get_for_household(entity_id=entity_id, household_id=household_id)

    statement = mock_db_session.exec.call_args.args[0]
    compiled = str(statement)
    assert "scopedthing.id = " in compiled
    assert "scopedthing.household_id = " in compiled


def test_get_for_household_returns_none_when_missing(
    repository: ScopedThingRepository, mock_db_session: MagicMock, household_id: uuid.UUID
) -> None:
    mock_db_session.exec.return_value.first.return_value = None

    assert repository.get_for_household(entity_id=uuid.uuid4(), household_id=household_id) is None


def test_count_for_household_scopes_the_count(
    repository: ScopedThingRepository, mock_db_session: MagicMock, household_id: uuid.UUID
) -> None:
    mock_db_session.exec.return_value.one.return_value = 3

    assert repository.count_for_household(household_id=household_id) == 3
    assert "scopedthing.household_id = " in str(mock_db_session.exec.call_args.args[0])


def test_count_for_household_applies_extra_conditions(
    repository: ScopedThingRepository, mock_db_session: MagicMock, household_id: uuid.UUID
) -> None:
    mock_db_session.exec.return_value.one.return_value = 1

    assert repository.count_for_household(household_id, ScopedThing.name == "thing") == 1

    compiled = str(mock_db_session.exec.call_args.args[0])
    assert "scopedthing.household_id = " in compiled
    assert "scopedthing.name = " in compiled


def test_exists_for_household(
    repository: ScopedThingRepository, mock_db_session: MagicMock, household_id: uuid.UUID
) -> None:
    mock_db_session.exec.return_value.first.return_value = uuid.uuid4()
    assert repository.exists_for_household(entity_id=uuid.uuid4(), household_id=household_id) is True

    mock_db_session.exec.return_value.first.return_value = None
    assert repository.exists_for_household(entity_id=uuid.uuid4(), household_id=household_id) is False


class UnscopedThing(PrimaryKeyMixin, SQLModel, table=True):
    """A table with no household_id, defined only for these tests."""

    __tablename__ = "unscopedthing"

    name: str = Field(default="thing")


def test_rejects_a_model_without_a_household_column(mock_db_session: MagicMock) -> None:
    with pytest.raises(TypeError, match="household_id"):
        HouseholdScopedRepository(session=mock_db_session, model_class=UnscopedThing)
