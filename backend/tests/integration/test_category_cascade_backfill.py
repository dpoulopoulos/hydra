"""The one-off back-fill of ``category.archived_with_parent``.

The column that records which subcategories a parent's archive took down was
added with every existing row set to ``False``, because nothing in the old data
said so outright. It does say so indirectly: the cascade wrote the parent's own
``archived_at`` onto each child it archived, to the microsecond, so a child
carrying exactly its parent's archive instant was taken down by that cascade
rather than retired on a day of its own.

This exercises that rule against a real Postgres, because it lives entirely in
SQL. The statement is read off the revision module rather than restated here,
so a passing test says something about the migration a deployment will run.
"""

import datetime
import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlmodel import Session

from app.models import Category, HouseholdContext

from .conftest import make_category

REVISION = (
    Path(__file__).parents[2]
    / "src"
    / "app"
    / "alembic"
    / "versions"
    / "d9f4c1b73a85_back_fill_the_category_cascade_mark.py"
)

# An instant with microseconds, as ``datetime.now(UTC)`` produces: the whole
# rule rests on the child having been given the parent's value verbatim.
ARCHIVED_AT = datetime.datetime(2026, 6, 1, 9, 30, 15, 123456, tzinfo=datetime.UTC)


def _revision() -> ModuleType:
    """Import the revision module, which no package on the import path contains.

    Returns:
        The migration module, for the statement it holds.
    """
    spec = importlib.util.spec_from_file_location("category_cascade_back_fill", REVISION)
    assert spec is not None and spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _archive(session: Session, category: Category, at: datetime.datetime) -> Category:
    """Archive a category the way a deployment predating the column left it.

    Args:
        session: The database session.
        category: The category to archive.
        at: The instant to record as its archive date.

    Returns:
        The archived category.
    """
    category.archived_at = at
    session.add(category)
    session.flush()
    return category


@pytest.fixture
def back_fill(db_session: Session) -> Callable[[], None]:
    """Apply the back-fill the revision performs.

    Args:
        db_session: The session the rows are seeded through.

    Returns:
        A callable that runs the statement and re-reads the seeded rows.
    """

    def run() -> None:
        db_session.flush()
        db_session.execute(text(_revision().BACK_FILL_SQL))
        db_session.expire_all()

    return run


class TestTheCascadeBackFill:
    """What the statement concludes about an archive that predates the column."""

    def test_a_child_archived_with_its_parent_is_marked(
        self, db_session: Session, household_a: HouseholdContext, back_fill: Callable[[], None]
    ) -> None:
        parent = make_category(db_session, household_a.household_id, name="Food")
        child = make_category(db_session, household_a.household_id, name="Groceries", parent_id=parent.id)
        _archive(db_session, parent, ARCHIVED_AT)
        _archive(db_session, child, ARCHIVED_AT)

        back_fill()

        assert child.archived_with_parent is True

    def test_a_child_archived_on_its_own_day_is_left_alone(
        self, db_session: Session, household_a: HouseholdContext, back_fill: Callable[[], None]
    ) -> None:
        """The whole point of the column: this child stays archived when the parent comes back."""
        parent = make_category(db_session, household_a.household_id, name="Food")
        child = make_category(db_session, household_a.household_id, name="Groceries", parent_id=parent.id)
        _archive(db_session, parent, ARCHIVED_AT)
        _archive(db_session, child, ARCHIVED_AT - datetime.timedelta(days=30))

        back_fill()

        assert child.archived_with_parent is False

    def test_a_child_archived_a_moment_after_its_parent_is_left_alone(
        self, db_session: Session, household_a: HouseholdContext, back_fill: Callable[[], None]
    ) -> None:
        """Two requests do not land on the same microsecond, so this one was a separate decision."""
        parent = make_category(db_session, household_a.household_id, name="Food")
        child = make_category(db_session, household_a.household_id, name="Groceries", parent_id=parent.id)
        _archive(db_session, parent, ARCHIVED_AT)
        _archive(db_session, child, ARCHIVED_AT + datetime.timedelta(microseconds=1))

        back_fill()

        assert child.archived_with_parent is False

    def test_a_live_child_is_left_alone(
        self, db_session: Session, household_a: HouseholdContext, back_fill: Callable[[], None]
    ) -> None:
        parent = make_category(db_session, household_a.household_id, name="Food")
        child = make_category(db_session, household_a.household_id, name="Groceries", parent_id=parent.id)
        _archive(db_session, parent, ARCHIVED_AT)

        back_fill()

        assert child.archived_at is None
        assert child.archived_with_parent is False

    def test_a_child_of_a_live_parent_is_left_alone(
        self, db_session: Session, household_a: HouseholdContext, back_fill: Callable[[], None]
    ) -> None:
        parent = make_category(db_session, household_a.household_id, name="Food")
        child = make_category(db_session, household_a.household_id, name="Groceries", parent_id=parent.id)
        _archive(db_session, child, ARCHIVED_AT)

        back_fill()

        assert child.archived_with_parent is False

    def test_a_top_level_category_is_never_marked(
        self, db_session: Session, household_a: HouseholdContext, back_fill: Callable[[], None]
    ) -> None:
        """The mark says a parent took the row down, which a top level row cannot mean."""
        parent = make_category(db_session, household_a.household_id, name="Food")
        _archive(db_session, parent, ARCHIVED_AT)

        back_fill()

        assert parent.archived_with_parent is False

    def test_an_unrelated_category_sharing_the_instant_is_left_alone(
        self, db_session: Session, household_a: HouseholdContext, back_fill: Callable[[], None]
    ) -> None:
        """The instant only means anything between a row and its own parent."""
        parent = make_category(db_session, household_a.household_id, name="Food")
        unrelated = make_category(db_session, household_a.household_id, name="Travel")
        _archive(db_session, parent, ARCHIVED_AT)
        _archive(db_session, unrelated, ARCHIVED_AT)

        back_fill()

        assert unrelated.archived_with_parent is False

    def test_a_row_under_another_household_is_not_reached(
        self,
        db_session: Session,
        household_a: HouseholdContext,
        household_b: HouseholdContext,
        back_fill: Callable[[], None],
    ) -> None:
        """A category is only ever the parent of rows in its own household."""
        parent = make_category(db_session, household_a.household_id, name="Food")
        other = make_category(db_session, household_b.household_id, name="Food")
        _archive(db_session, parent, ARCHIVED_AT)
        _archive(db_session, other, ARCHIVED_AT)

        back_fill()

        assert other.archived_with_parent is False

    def test_running_it_twice_changes_nothing_more(
        self, db_session: Session, household_a: HouseholdContext, back_fill: Callable[[], None]
    ) -> None:
        """A back-fill has to survive being re-run, since a deploy can be retried."""
        parent = make_category(db_session, household_a.household_id, name="Food")
        cascaded = make_category(db_session, household_a.household_id, name="Groceries", parent_id=parent.id)
        by_hand = make_category(db_session, household_a.household_id, name="Takeaway", parent_id=parent.id)
        _archive(db_session, parent, ARCHIVED_AT)
        _archive(db_session, cascaded, ARCHIVED_AT)
        _archive(db_session, by_hand, ARCHIVED_AT - datetime.timedelta(days=1))

        back_fill()
        back_fill()

        assert cascaded.archived_with_parent is True
        assert by_hand.archived_with_parent is False
