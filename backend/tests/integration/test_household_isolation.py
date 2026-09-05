"""Cross-household isolation, verified against real SQL.

The unit suite makes the service raise the not-found error itself, so it proves
the route maps that error to a 404 and nothing more. These tests seed two
households in the database and ask the first for the second's rows. They fail
if a service is ever changed to reach a row through an unscoped read.
"""

import datetime
import uuid

import pytest
from sqlmodel import Session

from app.exceptions import (
    AccountNotFoundError,
    BudgetNotFoundError,
    CategoryNotFoundError,
    HouseholdInviteNotFoundError,
    HouseholdMemberNotFoundError,
    RecurringRuleNotFoundError,
    TransactionNotFoundError,
)
from app.models import (
    AccountUpdate,
    Budget,
    BudgetUpdate,
    CategoryUpdate,
    HouseholdContext,
    HouseholdInvite,
    HouseholdMember,
    HouseholdMemberUpdate,
    HouseholdRole,
    RecurringRule,
    RecurringRuleUpdate,
    Transaction,
    TransactionKind,
    TransactionUpdate,
)
from app.services import (
    AccountService,
    BudgetService,
    CategoryService,
    HouseholdService,
    RecurringRuleService,
    TransactionService,
)
from tests.integration.conftest import make_account, make_category


class TestAccountIsolation:
    """An account of another household is out of reach."""

    def test_reading_a_foreign_account_is_not_found(
        self,
        db_session: Session,
        account_service: AccountService,
        household_a: HouseholdContext,
        household_b: HouseholdContext,
    ) -> None:
        """A read is scoped to the household, so the row is simply not there."""
        foreign = make_account(db_session, household_id=household_b.household_id)

        with pytest.raises(AccountNotFoundError):
            account_service.get_account(household=household_a, account_id=foreign.id)

    def test_updating_a_foreign_account_is_not_found(
        self,
        db_session: Session,
        account_service: AccountService,
        household_a: HouseholdContext,
        household_b: HouseholdContext,
    ) -> None:
        """An update resolves the ID the same way a read does."""
        foreign = make_account(db_session, household_id=household_b.household_id)

        with pytest.raises(AccountNotFoundError):
            account_service.update_account(
                household=household_a, account_id=foreign.id, account_update=AccountUpdate(name="Taken")
            )

        db_session.refresh(foreign)
        assert foreign.name == "Checking"

    def test_deleting_a_foreign_account_is_not_found(
        self,
        db_session: Session,
        account_service: AccountService,
        household_a: HouseholdContext,
        household_b: HouseholdContext,
    ) -> None:
        """A delete cannot remove a row the household cannot see."""
        foreign = make_account(db_session, household_id=household_b.household_id)

        with pytest.raises(AccountNotFoundError):
            account_service.delete_account(household=household_a, account_id=foreign.id)

        assert db_session.get(type(foreign), foreign.id) is not None


class TestCategoryIsolation:
    """A category of another household is out of reach."""

    def test_reading_a_foreign_category_is_not_found(
        self,
        db_session: Session,
        category_service: CategoryService,
        household_a: HouseholdContext,
        household_b: HouseholdContext,
    ) -> None:
        """A read is scoped to the household."""
        foreign = make_category(db_session, household_id=household_b.household_id)

        with pytest.raises(CategoryNotFoundError):
            category_service.get_category(household=household_a, category_id=foreign.id)

    def test_updating_a_foreign_category_is_not_found(
        self,
        db_session: Session,
        category_service: CategoryService,
        household_a: HouseholdContext,
        household_b: HouseholdContext,
    ) -> None:
        """An update resolves the ID the same way a read does."""
        foreign = make_category(db_session, household_id=household_b.household_id)

        with pytest.raises(CategoryNotFoundError):
            category_service.update_category(
                household=household_a, category_id=foreign.id, category_update=CategoryUpdate(name="Taken")
            )

        db_session.refresh(foreign)
        assert foreign.name == "Groceries"

    def test_deleting_a_foreign_category_is_not_found(
        self,
        db_session: Session,
        category_service: CategoryService,
        household_a: HouseholdContext,
        household_b: HouseholdContext,
    ) -> None:
        """A delete cannot remove a row the household cannot see."""
        foreign = make_category(db_session, household_id=household_b.household_id)

        with pytest.raises(CategoryNotFoundError):
            category_service.delete_category(household=household_a, category_id=foreign.id)

        assert db_session.get(type(foreign), foreign.id) is not None

    def test_a_foreign_category_cannot_become_a_parent(
        self,
        db_session: Session,
        category_service: CategoryService,
        household_a: HouseholdContext,
        household_b: HouseholdContext,
    ) -> None:
        """A write that names another household's ID re-resolves it and fails."""
        own = make_category(db_session, household_id=household_a.household_id, name="Transport")
        foreign = make_category(db_session, household_id=household_b.household_id)

        with pytest.raises(CategoryNotFoundError):
            category_service.update_category(
                household=household_a, category_id=own.id, category_update=CategoryUpdate(parent_id=foreign.id)
            )


class TestTransactionIsolation:
    """A transaction of another household is out of reach."""

    @pytest.fixture
    def foreign_transaction(self, db_session: Session, household_b: HouseholdContext) -> Transaction:
        """Seed a transaction owned by the other household.

        Args:
            db_session: The database session.
            household_b: The other household.

        Returns:
            The stored transaction.
        """
        account = make_account(db_session, household_id=household_b.household_id)
        transaction = Transaction(
            household_id=household_b.household_id,
            account_id=account.id,
            kind=TransactionKind.EXPENSE,
            amount_minor=1_000,
            occurred_on=datetime.date(2024, 3, 1),
        )
        db_session.add(transaction)
        db_session.flush()
        return transaction

    def test_reading_a_foreign_transaction_is_not_found(
        self,
        transaction_service: TransactionService,
        household_a: HouseholdContext,
        foreign_transaction: Transaction,
    ) -> None:
        """A read is scoped to the household."""
        with pytest.raises(TransactionNotFoundError):
            transaction_service.get_transaction(household=household_a, transaction_id=foreign_transaction.id)

    def test_updating_a_foreign_transaction_is_not_found(
        self,
        db_session: Session,
        transaction_service: TransactionService,
        household_a: HouseholdContext,
        foreign_transaction: Transaction,
    ) -> None:
        """An update resolves the ID the same way a read does."""
        with pytest.raises(TransactionNotFoundError):
            transaction_service.update_transaction(
                household=household_a,
                transaction_id=foreign_transaction.id,
                transaction_update=TransactionUpdate(amount_minor=1),
            )

        db_session.refresh(foreign_transaction)
        assert foreign_transaction.amount_minor == 1_000

    def test_deleting_a_foreign_transaction_is_not_found(
        self,
        db_session: Session,
        transaction_service: TransactionService,
        household_a: HouseholdContext,
        foreign_transaction: Transaction,
    ) -> None:
        """A delete cannot remove a row the household cannot see."""
        with pytest.raises(TransactionNotFoundError):
            transaction_service.delete_transaction(household=household_a, transaction_id=foreign_transaction.id)

        assert db_session.get(Transaction, foreign_transaction.id) is not None

    def test_a_transaction_cannot_be_moved_onto_a_foreign_account(
        self,
        db_session: Session,
        transaction_service: TransactionService,
        household_a: HouseholdContext,
        household_b: HouseholdContext,
    ) -> None:
        """A write that names another household's account re-resolves it."""
        own_account = make_account(db_session, household_id=household_a.household_id)
        foreign_account = make_account(db_session, household_id=household_b.household_id)
        transaction = Transaction(
            household_id=household_a.household_id,
            account_id=own_account.id,
            kind=TransactionKind.EXPENSE,
            amount_minor=2_500,
            occurred_on=datetime.date(2024, 3, 1),
        )
        db_session.add(transaction)
        db_session.flush()

        with pytest.raises(AccountNotFoundError):
            transaction_service.update_transaction(
                household=household_a,
                transaction_id=transaction.id,
                transaction_update=TransactionUpdate(account_id=foreign_account.id),
            )


class TestBudgetIsolation:
    """A budget of another household is out of reach."""

    @pytest.fixture
    def foreign_budget(self, db_session: Session, household_b: HouseholdContext) -> Budget:
        """Seed a budget owned by the other household.

        Args:
            db_session: The database session.
            household_b: The other household.

        Returns:
            The stored budget.
        """
        category = make_category(db_session, household_id=household_b.household_id)
        budget = Budget(
            household_id=household_b.household_id,
            category_id=category.id,
            period_month=datetime.date(2024, 3, 1),
            limit_minor=50_000,
        )
        db_session.add(budget)
        db_session.flush()
        return budget

    def test_reading_a_foreign_budget_is_not_found(
        self, budget_service: BudgetService, household_a: HouseholdContext, foreign_budget: Budget
    ) -> None:
        """A read is scoped to the household."""
        with pytest.raises(BudgetNotFoundError):
            budget_service.get_budget(household=household_a, budget_id=foreign_budget.id)

    def test_updating_a_foreign_budget_is_not_found(
        self,
        db_session: Session,
        budget_service: BudgetService,
        household_a: HouseholdContext,
        foreign_budget: Budget,
    ) -> None:
        """An update resolves the ID the same way a read does."""
        with pytest.raises(BudgetNotFoundError):
            budget_service.update_budget(
                household=household_a, budget_id=foreign_budget.id, budget_update=BudgetUpdate(limit_minor=1)
            )

        db_session.refresh(foreign_budget)
        assert foreign_budget.limit_minor == 50_000

    def test_deleting_a_foreign_budget_is_not_found(
        self,
        db_session: Session,
        budget_service: BudgetService,
        household_a: HouseholdContext,
        foreign_budget: Budget,
    ) -> None:
        """A delete cannot remove a row the household cannot see."""
        with pytest.raises(BudgetNotFoundError):
            budget_service.delete_budget(household=household_a, budget_id=foreign_budget.id)

        assert db_session.get(Budget, foreign_budget.id) is not None


class TestRecurringRuleIsolation:
    """A recurring rule of another household is out of reach."""

    @pytest.fixture
    def foreign_rule(self, db_session: Session, household_b: HouseholdContext) -> RecurringRule:
        """Seed a recurring rule owned by the other household.

        Args:
            db_session: The database session.
            household_b: The other household.

        Returns:
            The stored rule.
        """
        account = make_account(db_session, household_id=household_b.household_id)
        rule = RecurringRule(
            household_id=household_b.household_id,
            account_id=account.id,
            name="Rent",
            kind=TransactionKind.EXPENSE,
            amount_minor=100_000,
            start_date=datetime.date(2024, 1, 1),
            next_occurrence_on=datetime.date(2024, 4, 1),
        )
        db_session.add(rule)
        db_session.flush()
        return rule

    def test_reading_a_foreign_rule_is_not_found(
        self,
        recurring_rule_service: RecurringRuleService,
        household_a: HouseholdContext,
        foreign_rule: RecurringRule,
    ) -> None:
        """A read is scoped to the household."""
        with pytest.raises(RecurringRuleNotFoundError):
            recurring_rule_service.get_rule(household=household_a, rule_id=foreign_rule.id)

    def test_updating_a_foreign_rule_is_not_found(
        self,
        db_session: Session,
        recurring_rule_service: RecurringRuleService,
        household_a: HouseholdContext,
        foreign_rule: RecurringRule,
    ) -> None:
        """An update resolves the ID the same way a read does."""
        with pytest.raises(RecurringRuleNotFoundError):
            recurring_rule_service.update_rule(
                household=household_a, rule_id=foreign_rule.id, rule_update=RecurringRuleUpdate(name="Taken")
            )

        db_session.refresh(foreign_rule)
        assert foreign_rule.name == "Rent"

    def test_deleting_a_foreign_rule_is_not_found(
        self,
        db_session: Session,
        recurring_rule_service: RecurringRuleService,
        household_a: HouseholdContext,
        foreign_rule: RecurringRule,
    ) -> None:
        """A delete cannot remove a row the household cannot see."""
        with pytest.raises(RecurringRuleNotFoundError):
            recurring_rule_service.delete_rule(household=household_a, rule_id=foreign_rule.id)

        assert db_session.get(RecurringRule, foreign_rule.id) is not None


class TestMembershipIsolation:
    """A member of another household is out of reach.

    Membership is the highest-consequence scoped path in the domain: an
    unscoped read in ``_require_member`` would let one household change the role
    of, or detach, a user who belongs to another one.
    """

    def test_listing_members_never_shows_another_household(
        self,
        household_service: HouseholdService,
        household_a: HouseholdContext,
        household_b: HouseholdContext,
    ) -> None:
        """The list is scoped, so a foreign member is absent rather than hidden."""
        members = household_service.list_members(household=household_a)

        assert members.count == 1
        assert [member.user_id for member in members.data] == [household_a.user.id]

    def test_updating_a_foreign_member_is_not_found(
        self,
        db_session: Session,
        household_service: HouseholdService,
        household_a: HouseholdContext,
        household_b: HouseholdContext,
    ) -> None:
        """A role change resolves the user within the caller's household only."""
        with pytest.raises(HouseholdMemberNotFoundError):
            household_service.update_member(
                household=household_a,
                user_id=household_b.user.id,
                member_update=HouseholdMemberUpdate(role=HouseholdRole.MEMBER),
            )

        membership = db_session.get(HouseholdMember, household_b.membership_id)
        assert membership is not None
        assert membership.role is HouseholdRole.OWNER

    def test_removing_a_foreign_member_is_not_found(
        self,
        db_session: Session,
        household_service: HouseholdService,
        category_service: CategoryService,
        household_a: HouseholdContext,
        household_b: HouseholdContext,
    ) -> None:
        """A removal cannot detach a user the caller's household cannot see."""
        with pytest.raises(HouseholdMemberNotFoundError):
            household_service.remove_member(
                household=household_a, user_id=household_b.user.id, category_service=category_service
            )

        membership = db_session.get(HouseholdMember, household_b.membership_id)
        assert membership is not None
        assert membership.household_id == household_b.household_id


class TestInviteIsolation:
    """An invite of another household is out of reach."""

    @pytest.fixture
    def foreign_invite(self, db_session: Session, household_b: HouseholdContext) -> HouseholdInvite:
        """Seed a pending invite owned by the other household.

        Args:
            db_session: The database session.
            household_b: The other household.

        Returns:
            The stored invite.
        """
        invite = HouseholdInvite(
            household_id=household_b.household_id,
            email="guest@example.com",
            role=HouseholdRole.MEMBER,
            token=uuid.uuid4().hex,
            expires_at=datetime.datetime(2099, 1, 1, tzinfo=datetime.UTC),
        )
        db_session.add(invite)
        db_session.flush()
        return invite

    def test_listing_invites_never_shows_another_household(
        self,
        household_service: HouseholdService,
        household_a: HouseholdContext,
        foreign_invite: HouseholdInvite,
    ) -> None:
        """The list is scoped, so a foreign invite is absent rather than hidden."""
        invites = household_service.list_invites(household=household_a)

        assert invites.count == 0

    def test_revoking_a_foreign_invite_is_not_found(
        self,
        db_session: Session,
        household_service: HouseholdService,
        household_a: HouseholdContext,
        foreign_invite: HouseholdInvite,
    ) -> None:
        """A revoke resolves the ID the same way a read does."""
        with pytest.raises(HouseholdInviteNotFoundError):
            household_service.revoke_invite(household=household_a, invite_id=foreign_invite.id)

        db_session.refresh(foreign_invite)
        assert foreign_invite.status == "pending"
