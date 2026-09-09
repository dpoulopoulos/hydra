"""The write paths of a recurring rule, against the constraints behind them.

``ck_recurringrule_transfer_shape`` is the reason these tests need a server: it
is the table's own statement of which fields belong to which kind, and a mocked
session enforces none of it. The service checks the same rules before the flush
so the API answers with a domain error instead of a 500, and that agreement
between the two is what is pinned here.
"""

import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.exceptions import TransferShapeError
from app.models import (
    HouseholdContext,
    RecurrenceFrequency,
    RecurringRule,
    RecurringRuleCreate,
    RecurringRuleUpdate,
    TransactionKind,
)
from app.repositories import RecurringRuleRepository
from app.services import RecurringRuleService
from tests.integration.conftest import make_account, make_category

TRANSFER_SHAPE_CONSTRAINT = "ck_recurringrule_transfer_shape"


class TestRecurringRuleShape:
    """Tests for the shape a rule has to keep across an edit."""

    def test_a_transfer_rule_cannot_be_given_a_category(
        self,
        db_session: Session,
        recurring_rule_service: RecurringRuleService,
        household_a: HouseholdContext,
    ) -> None:
        """The edit is refused as a domain error, not as an integrity error.

        Which fields a rule may carry depends on its kind, so an edit that
        checks only the field it was sent lets a transfer through with a
        category on it. The table refuses that row, and the refusal arrives as
        a 500 on the flush rather than as an answer the caller can act on.
        """
        source = make_account(db_session, household_id=household_a.household_id, name="Current")
        destination = make_account(db_session, household_id=household_a.household_id, name="Savings")
        category = make_category(db_session, household_id=household_a.household_id)
        rule = recurring_rule_service.create_rule(
            household=household_a,
            rule_create=RecurringRuleCreate(
                name="Monthly saving",
                kind=TransactionKind.TRANSFER,
                amount_minor=20_000,
                start_date=datetime.date(2024, 1, 1),
                frequency=RecurrenceFrequency.MONTHLY,
                account_id=source.id,
                counter_account_id=destination.id,
            ),
        )

        with pytest.raises(TransferShapeError):
            recurring_rule_service.update_rule(
                household=household_a,
                rule_id=rule.id,
                rule_update=RecurringRuleUpdate(category_id=category.id),
            )

        stored = recurring_rule_service.get_rule(household=household_a, rule_id=rule.id)
        assert stored.category_id is None

    def test_an_expense_rule_cannot_be_given_a_counter_account(
        self,
        db_session: Session,
        recurring_rule_service: RecurringRuleService,
        household_a: HouseholdContext,
    ) -> None:
        """The other half of the same constraint: only a transfer has a destination."""
        source = make_account(db_session, household_id=household_a.household_id, name="Current")
        destination = make_account(db_session, household_id=household_a.household_id, name="Savings")

        with pytest.raises(TransferShapeError):
            recurring_rule_service.create_rule(
                household=household_a,
                rule_create=RecurringRuleCreate(
                    name="Rent",
                    kind=TransactionKind.EXPENSE,
                    amount_minor=80_000,
                    start_date=datetime.date(2024, 1, 1),
                    frequency=RecurrenceFrequency.MONTHLY,
                    account_id=source.id,
                    counter_account_id=destination.id,
                ),
            )

    def test_the_table_refuses_a_rule_that_does_not_match_its_kind(
        self,
        db_session: Session,
        recurring_rule_repository: RecurringRuleRepository,
        household_a: HouseholdContext,
    ) -> None:
        """The constraint holds even when the service checks are bypassed.

        Written through the repository rather than the service, which is the
        shape a future editable ``counter_account_id`` would take if it were
        added without the matching validation.
        """
        source = make_account(db_session, household_id=household_a.household_id, name="Current")
        destination = make_account(db_session, household_id=household_a.household_id, name="Savings")
        savepoint = db_session.begin_nested()

        recurring_rule_repository.add(
            RecurringRule(
                household_id=household_a.household_id,
                name="Rent",
                kind=TransactionKind.EXPENSE,
                amount_minor=80_000,
                start_date=datetime.date(2024, 1, 1),
                frequency=RecurrenceFrequency.MONTHLY,
                account_id=source.id,
                counter_account_id=destination.id,
            )
        )

        with pytest.raises(IntegrityError) as error:
            db_session.flush()

        assert TRANSFER_SHAPE_CONSTRAINT in str(error.value.orig)
        savepoint.rollback()
