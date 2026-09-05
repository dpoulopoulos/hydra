"""The constraints the schema carries, verified by making them fire.

A mocked session enforces no ``CHECK``, no ``RESTRICT`` foreign key and no
``UNIQUE`` index, so the unit suite cannot tell a service that guards an
invariant from one that leaves it to the database and turns the resulting
``IntegrityError`` into a 500.

Two kinds of test live here. The service tests assert that a refusal arrives as
a domain error, which the API maps to a 4xx. The raw tests write straight to the
session, so they assert the constraint itself is present and would catch a write
path that forgets its guard.
"""

import datetime
import uuid
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.exceptions import (
    AccountExistsError,
    AccountInUseError,
    BudgetExistsError,
    CategoryExistsError,
    CategoryInUseError,
    SameAccountTransferError,
    TransferShapeError,
)
from app.models import (
    AccountCreate,
    AccountType,
    Budget,
    BudgetCreate,
    CategoryCreate,
    HouseholdContext,
    RecurringRule,
    Transaction,
    TransactionCreate,
    TransactionKind,
)
from app.services import AccountService, BudgetService, CategoryService, TransactionService
from tests.integration.conftest import make_account, make_category

MARCH = datetime.date(2024, 3, 1)


def add_transaction(session: Session, household_id: uuid.UUID, **fields: Any) -> Transaction:
    """Write a transaction straight to the session, with no service in the way.

    Args:
        session: The database session.
        household_id: The household that owns the row.
        **fields: The columns of the transaction.

    Returns:
        The stored transaction.
    """
    transaction = Transaction(household_id=household_id, **fields)
    session.add(transaction)
    session.flush()
    return transaction


class TestCategoryReferences:
    """Every foreign key onto a category is RESTRICT, so a delete is guarded."""

    def test_a_category_with_transactions_cannot_be_deleted(
        self,
        db_session: Session,
        category_service: CategoryService,
        household_a: HouseholdContext,
    ) -> None:
        """The refusal names the transactions rather than reaching the database."""
        category = make_category(db_session, household_id=household_a.household_id)
        account = make_account(db_session, household_id=household_a.household_id)
        add_transaction(
            db_session,
            household_a.household_id,
            account_id=account.id,
            category_id=category.id,
            kind=TransactionKind.EXPENSE,
            amount_minor=1_000,
            occurred_on=MARCH,
        )

        with pytest.raises(CategoryInUseError):
            category_service.delete_category(household=household_a, category_id=category.id)

    def test_a_category_with_a_budget_cannot_be_deleted(
        self,
        db_session: Session,
        category_service: CategoryService,
        household_a: HouseholdContext,
    ) -> None:
        """A budget holds the category just as a transaction does."""
        category = make_category(db_session, household_id=household_a.household_id)
        db_session.add(
            Budget(
                household_id=household_a.household_id,
                category_id=category.id,
                period_month=MARCH,
                limit_minor=10_000,
            )
        )
        db_session.flush()

        with pytest.raises(CategoryInUseError):
            category_service.delete_category(household=household_a, category_id=category.id)

    def test_a_category_with_a_recurring_rule_cannot_be_deleted(
        self,
        db_session: Session,
        category_service: CategoryService,
        household_a: HouseholdContext,
    ) -> None:
        """A rule holds the category too, even before it has generated anything."""
        category = make_category(db_session, household_id=household_a.household_id)
        account = make_account(db_session, household_id=household_a.household_id)
        db_session.add(
            RecurringRule(
                household_id=household_a.household_id,
                account_id=account.id,
                category_id=category.id,
                name="Groceries box",
                kind=TransactionKind.EXPENSE,
                amount_minor=4_000,
                start_date=MARCH,
                next_occurrence_on=MARCH,
            )
        )
        db_session.flush()

        with pytest.raises(CategoryInUseError):
            category_service.delete_category(household=household_a, category_id=category.id)

    def test_a_category_with_subcategories_cannot_be_deleted(
        self,
        db_session: Session,
        category_service: CategoryService,
        household_a: HouseholdContext,
    ) -> None:
        """A parent is held by its children."""
        parent = make_category(db_session, household_id=household_a.household_id)
        make_category(db_session, household_id=household_a.household_id, name="Coffee", parent_id=parent.id)

        with pytest.raises(CategoryInUseError):
            category_service.delete_category(household=household_a, category_id=parent.id)

    def test_a_category_nothing_references_is_deleted(
        self,
        db_session: Session,
        category_service: CategoryService,
        household_a: HouseholdContext,
    ) -> None:
        """The guard refuses references, not every delete."""
        category = make_category(db_session, household_id=household_a.household_id)

        category_service.delete_category(household=household_a, category_id=category.id)

        assert db_session.get(type(category), category.id) is None


class TestAccountReferences:
    """The ledger's foreign keys onto an account are RESTRICT."""

    def test_an_account_with_transactions_cannot_be_deleted(
        self,
        db_session: Session,
        account_service: AccountService,
        household_a: HouseholdContext,
    ) -> None:
        """The database refuses the delete and the service reports it as advice."""
        account = make_account(db_session, household_id=household_a.household_id)
        add_transaction(
            db_session,
            household_a.household_id,
            account_id=account.id,
            kind=TransactionKind.EXPENSE,
            amount_minor=1_000,
            occurred_on=MARCH,
        )

        with pytest.raises(AccountInUseError):
            account_service.delete_account(household=household_a, account_id=account.id)

    def test_an_account_with_no_history_is_deleted(
        self,
        db_session: Session,
        account_service: AccountService,
        household_a: HouseholdContext,
    ) -> None:
        """An untouched account carries nothing that could hold it."""
        account = make_account(db_session, household_id=household_a.household_id)

        account_service.delete_account(household=household_a, account_id=account.id)

        assert db_session.get(type(account), account.id) is None


class TestUniqueness:
    """The unique indexes that keep a household's names unambiguous."""

    def test_two_accounts_cannot_share_a_name_in_one_household(
        self, account_service: AccountService, household_a: HouseholdContext
    ) -> None:
        """uq_account_household_name, reported as a conflict rather than a 500."""
        account_create = AccountCreate(
            name="Joint", type=AccountType.CURRENT, opening_balance_date=datetime.date(2024, 1, 1)
        )
        account_service.create_account(household=household_a, account_create=account_create)

        with pytest.raises(AccountExistsError):
            account_service.create_account(household=household_a, account_create=account_create)

    def test_two_households_can_use_the_same_account_name(
        self, account_service: AccountService, household_a: HouseholdContext, household_b: HouseholdContext
    ) -> None:
        """The index is per household, so the name is not globally taken."""
        account_create = AccountCreate(
            name="Joint", type=AccountType.CURRENT, opening_balance_date=datetime.date(2024, 1, 1)
        )
        account_service.create_account(household=household_a, account_create=account_create)

        created = account_service.create_account(household=household_b, account_create=account_create)

        assert created.household_id == household_b.household_id

    def test_two_root_categories_cannot_share_a_name(
        self, category_service: CategoryService, household_a: HouseholdContext
    ) -> None:
        """uq_category_household_root_name covers the top level, where parent_id is NULL."""
        category_service.create_category(household=household_a, category_create=CategoryCreate(name="Travel"))

        with pytest.raises(CategoryExistsError):
            category_service.create_category(household=household_a, category_create=CategoryCreate(name="Travel"))

    def test_two_subcategories_of_different_parents_can_share_a_name(
        self, db_session: Session, category_service: CategoryService, household_a: HouseholdContext
    ) -> None:
        """uq_category_household_child_name includes the parent, so siblings only clash."""
        first = make_category(db_session, household_id=household_a.household_id, name="Home")
        second = make_category(db_session, household_id=household_a.household_id, name="Work")

        category_service.create_category(
            household=household_a, category_create=CategoryCreate(name="Internet", parent_id=first.id)
        )
        created = category_service.create_category(
            household=household_a, category_create=CategoryCreate(name="Internet", parent_id=second.id)
        )

        assert created.parent_id == second.id

    def test_a_category_can_have_only_one_limit_per_month(
        self, db_session: Session, budget_service: BudgetService, household_a: HouseholdContext
    ) -> None:
        """uq_budget_household_category_month, reported as a conflict."""
        category = make_category(db_session, household_id=household_a.household_id)
        budget_create = BudgetCreate(category_id=category.id, month="2024-03", limit_minor=30_000)
        budget_service.create_budget(household=household_a, budget_create=budget_create)

        with pytest.raises(BudgetExistsError):
            budget_service.create_budget(household=household_a, budget_create=budget_create)


class TestTransferShape:
    """A transfer is one row, and its shape is a CHECK rather than a convention."""

    def test_a_transfer_with_a_category_is_refused(
        self, db_session: Session, transaction_service: TransactionService, household_a: HouseholdContext
    ) -> None:
        """The service refuses it, so the CHECK is never reached."""
        source = make_account(db_session, household_id=household_a.household_id, name="Current")
        destination = make_account(db_session, household_id=household_a.household_id, name="Savings")
        category = make_category(db_session, household_id=household_a.household_id)

        with pytest.raises(TransferShapeError):
            transaction_service.create_transaction(
                household=household_a,
                transaction_create=TransactionCreate(
                    kind=TransactionKind.TRANSFER,
                    amount_minor=5_000,
                    occurred_on=MARCH,
                    account_id=source.id,
                    counter_account_id=destination.id,
                    category_id=category.id,
                ),
            )

    def test_a_transfer_to_the_same_account_is_refused(
        self, db_session: Session, transaction_service: TransactionService, household_a: HouseholdContext
    ) -> None:
        """Money that goes nowhere is a mistake, not a ledger entry."""
        account = make_account(db_session, household_id=household_a.household_id)

        with pytest.raises(SameAccountTransferError):
            transaction_service.create_transaction(
                household=household_a,
                transaction_create=TransactionCreate(
                    kind=TransactionKind.TRANSFER,
                    amount_minor=5_000,
                    occurred_on=MARCH,
                    account_id=account.id,
                    counter_account_id=account.id,
                ),
            )

    def test_the_shape_check_exists_in_the_database(self, db_session: Session, household_a: HouseholdContext) -> None:
        """A write that skips the service is still refused."""
        source = make_account(db_session, household_id=household_a.household_id, name="Current")
        destination = make_account(db_session, household_id=household_a.household_id, name="Savings")
        category = make_category(db_session, household_id=household_a.household_id)

        with pytest.raises(IntegrityError, match="ck_transaction_transfer_shape"):
            add_transaction(
                db_session,
                household_a.household_id,
                account_id=source.id,
                counter_account_id=destination.id,
                category_id=category.id,
                kind=TransactionKind.TRANSFER,
                amount_minor=5_000,
                occurred_on=MARCH,
            )

    def test_an_expense_cannot_name_a_counter_account(self, db_session: Session, household_a: HouseholdContext) -> None:
        """The same CHECK covers the other direction: only a transfer has two legs."""
        source = make_account(db_session, household_id=household_a.household_id, name="Current")
        destination = make_account(db_session, household_id=household_a.household_id, name="Savings")

        with pytest.raises(IntegrityError, match="ck_transaction_transfer_shape"):
            add_transaction(
                db_session,
                household_a.household_id,
                account_id=source.id,
                counter_account_id=destination.id,
                kind=TransactionKind.EXPENSE,
                amount_minor=5_000,
                occurred_on=MARCH,
            )


class TestRawWrites:
    """Constraints that hold even when no service is involved."""

    def test_an_amount_of_zero_is_refused(self, db_session: Session, household_a: HouseholdContext) -> None:
        """ck_transaction_amount_positive: the magnitude carries no sign, so zero is meaningless."""
        account = make_account(db_session, household_id=household_a.household_id)

        with pytest.raises(IntegrityError, match="ck_transaction_amount_positive"):
            add_transaction(
                db_session,
                household_a.household_id,
                account_id=account.id,
                kind=TransactionKind.EXPENSE,
                amount_minor=0,
                occurred_on=MARCH,
            )

    def test_a_transfer_between_one_account_and_itself_is_refused(
        self, db_session: Session, household_a: HouseholdContext
    ) -> None:
        """ck_transaction_distinct_accounts, independently of the service guard."""
        account = make_account(db_session, household_id=household_a.household_id)

        with pytest.raises(IntegrityError, match="ck_transaction_distinct_accounts"):
            add_transaction(
                db_session,
                household_a.household_id,
                account_id=account.id,
                counter_account_id=account.id,
                kind=TransactionKind.TRANSFER,
                amount_minor=5_000,
                occurred_on=MARCH,
            )

    def test_a_budget_month_must_be_the_first_of_a_month(
        self, db_session: Session, household_a: HouseholdContext
    ) -> None:
        """ck_budget_period_month_first, which is what makes the unique index mean one limit per month."""
        category = make_category(db_session, household_id=household_a.household_id)

        db_session.add(
            Budget(
                household_id=household_a.household_id,
                category_id=category.id,
                period_month=datetime.date(2024, 3, 15),
                limit_minor=10_000,
            )
        )

        with pytest.raises(IntegrityError, match="ck_budget_period_month_first"):
            db_session.flush()

    def test_a_transaction_cannot_reference_another_household_account(
        self, db_session: Session, household_a: HouseholdContext, household_b: HouseholdContext
    ) -> None:
        """The composite foreign key holds even if a service forgets to scope its read."""
        foreign = make_account(db_session, household_id=household_b.household_id)

        with pytest.raises(IntegrityError, match="fk_transaction_account_household"):
            add_transaction(
                db_session,
                household_a.household_id,
                account_id=foreign.id,
                kind=TransactionKind.EXPENSE,
                amount_minor=1_000,
                occurred_on=MARCH,
            )

    def test_a_transaction_cannot_reference_another_household_category(
        self, db_session: Session, household_a: HouseholdContext, household_b: HouseholdContext
    ) -> None:
        """The same holds for the category leg of the reference."""
        account = make_account(db_session, household_id=household_a.household_id)
        foreign = make_category(db_session, household_id=household_b.household_id)

        with pytest.raises(IntegrityError, match="fk_transaction_category_household"):
            add_transaction(
                db_session,
                household_a.household_id,
                account_id=account.id,
                category_id=foreign.id,
                kind=TransactionKind.EXPENSE,
                amount_minor=1_000,
                occurred_on=MARCH,
            )
