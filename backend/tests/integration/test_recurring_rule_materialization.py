"""A materialization pass, against the ledger it writes into.

``materialize_due`` runs from the read paths, so anything it gets wrong lands
on an ordinary page load. One of its guarantees exists only in the database:
``uq_transaction_rule_occurrence``, the unique index that stops two requests
writing the same occurrence. A mocked session enforces no index, so the only
way to tell "already there" from a 500 is to run the pass twice against a real
server.
"""

import datetime
import uuid

from sqlmodel import Session, func, select

from app.models import (
    HouseholdContext,
    RecurrenceFrequency,
    RecurringRuleCreate,
    RecurringRulePublic,
    Transaction,
    TransactionKind,
)
from app.repositories import RecurringRuleRepository
from app.services import RecurringRuleService
from tests.integration.conftest import make_account

# The window every pass in this module runs over. Fixed rather than relative to
# today, so which occurrences fall due does not depend on the day the suite is
# run: the first of January, February and March.
START = datetime.date(2024, 1, 1)
UNTIL = datetime.date(2024, 3, 31)
OCCURRENCES_IN_WINDOW = 3


def make_monthly_rule(
    service: RecurringRuleService, household: HouseholdContext, account_id: uuid.UUID
) -> RecurringRulePublic:
    """Create a monthly expense rule that is due three times in the window.

    Args:
        service: The recurring rule service.
        household: The household the rule belongs to.
        account_id: The account the rule draws on.

    Returns:
        The created rule.
    """
    return service.create_rule(
        household=household,
        rule_create=RecurringRuleCreate(
            name="Rent",
            kind=TransactionKind.EXPENSE,
            amount_minor=80_000,
            start_date=START,
            frequency=RecurrenceFrequency.MONTHLY,
            account_id=account_id,
        ),
    )


def count_generated(session: Session, rule_id: uuid.UUID) -> int:
    """Count the transactions a rule has generated.

    Args:
        session: The database session.
        rule_id: The ID of the rule.

    Returns:
        How many rows in the ledger name the rule.
    """
    statement = select(func.count()).select_from(Transaction).where(Transaction.recurring_rule_id == rule_id)
    return session.exec(statement).one()


class TestMaterializeTwice:
    """Tests for running the same window through a second pass."""

    def test_a_second_pass_over_the_same_window_creates_nothing(
        self,
        db_session: Session,
        recurring_rule_service: RecurringRuleService,
        household_a: HouseholdContext,
    ) -> None:
        """The cursor has moved on, so the second pass finds nothing due."""
        account = make_account(db_session, household_id=household_a.household_id)
        rule = make_monthly_rule(recurring_rule_service, household_a, account.id)

        first = recurring_rule_service.materialize_due(household=household_a, until=UNTIL)
        second = recurring_rule_service.materialize_due(household=household_a, until=UNTIL)

        assert first.created_count == OCCURRENCES_IN_WINDOW
        assert second.created_count == 0
        assert second.rules_advanced == 0
        assert count_generated(db_session, rule.id) == OCCURRENCES_IN_WINDOW

    def test_an_occurrence_already_in_the_ledger_is_skipped(
        self,
        db_session: Session,
        recurring_rule_service: RecurringRuleService,
        recurring_rule_repository: RecurringRuleRepository,
        household_a: HouseholdContext,
    ) -> None:
        """A pass over occurrences that already exist counts them, not a 500.

        This is the race the unique index is there for: two members opening
        the app at the same moment read the same cursor, and the request that
        loses gets an integrity error on the insert. Rewinding the cursor is
        the same starting position as losing that race, without needing two
        connections to arrange it.
        """
        account = make_account(db_session, household_id=household_a.household_id)
        rule = make_monthly_rule(recurring_rule_service, household_a, account.id)
        recurring_rule_service.materialize_due(household=household_a, until=UNTIL)

        stored = recurring_rule_repository.get_for_household(entity_id=rule.id, household_id=household_a.household_id)
        assert stored is not None
        stored.next_occurrence_on = START
        recurring_rule_repository.save(stored)

        result = recurring_rule_service.materialize_due(household=household_a, until=UNTIL)

        assert result.created_count == 0
        assert result.skipped_count == OCCURRENCES_IN_WINDOW
        assert count_generated(db_session, rule.id) == OCCURRENCES_IN_WINDOW


class TestMaterializeArchivedAccount:
    """Tests for a rule whose account can no longer take a transaction."""

    def test_a_rule_on_an_archived_account_is_reported_as_skipped(
        self,
        db_session: Session,
        recurring_rule_service: RecurringRuleService,
        recurring_rule_repository: RecurringRuleRepository,
        household_a: HouseholdContext,
    ) -> None:
        """Archiving the account stops the rule instead of writing behind it.

        The ledger refuses an archived account by hand, so a rule must not put
        rows into one either. The occurrences are counted as skipped and the
        cursor stays where it was, so putting the account back picks the rule
        up where it stopped.
        """
        account = make_account(db_session, household_id=household_a.household_id)
        rule = make_monthly_rule(recurring_rule_service, household_a, account.id)

        # Archived after the rule was written, which is the only order the
        # services allow: a rule cannot be created on an archived account.
        account.archived_at = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
        db_session.add(account)
        db_session.flush()

        result = recurring_rule_service.materialize_due(household=household_a, until=UNTIL)

        assert result.created_count == 0
        assert result.skipped_count == OCCURRENCES_IN_WINDOW
        assert result.rules_advanced == 0
        assert count_generated(db_session, rule.id) == 0

        stored = recurring_rule_repository.get_for_household(entity_id=rule.id, household_id=household_a.household_id)
        assert stored is not None
        assert stored.next_occurrence_on == START


class TestMaterializeAcrossHouseholds:
    """Tests for the household a materialized transaction belongs to."""

    def test_a_generated_transaction_carries_the_household_of_its_rule(
        self,
        db_session: Session,
        recurring_rule_service: RecurringRuleService,
        household_a: HouseholdContext,
    ) -> None:
        """Every row the pass writes is stamped with the rule's household.

        The composite foreign keys on the ledger only hold a transaction to an
        account of its own household, so a generated row that carried the
        wrong household would be refused rather than leak. Pinning the value
        keeps the constraint from being the only thing that notices.
        """
        account = make_account(db_session, household_id=household_a.household_id)
        rule = make_monthly_rule(recurring_rule_service, household_a, account.id)

        recurring_rule_service.materialize_due(household=household_a, until=UNTIL)

        generated = db_session.exec(select(Transaction).where(Transaction.recurring_rule_id == rule.id)).all()
        assert len(generated) == OCCURRENCES_IN_WINDOW
        assert {row.household_id for row in generated} == {household_a.household_id}
        assert {row.account_id for row in generated} == {account.id}

    def test_a_rule_of_another_household_is_not_materialized_into_this_one(
        self,
        db_session: Session,
        recurring_rule_service: RecurringRuleService,
        household_a: HouseholdContext,
        household_b: HouseholdContext,
    ) -> None:
        """A pass is scoped to the household that asked for it.

        Materialization runs from the read paths, so an unscoped pass would
        write another household's rules into the ledger of whoever happened to
        open the app first.
        """
        foreign_account = make_account(db_session, household_id=household_b.household_id)
        foreign_rule = make_monthly_rule(recurring_rule_service, household_b, foreign_account.id)

        result = recurring_rule_service.materialize_due(household=household_a, until=UNTIL)

        assert result.created_count == 0
        assert result.rules_advanced == 0
        assert count_generated(db_session, foreign_rule.id) == 0
