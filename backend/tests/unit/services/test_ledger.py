import uuid
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest

from app.exceptions import (
    AccountArchivedError,
    AccountNotFoundError,
    CategoryNotFoundError,
    SameAccountTransferError,
    TransactionCategoryKindError,
    TransferShapeError,
)
from app.models import (
    Account,
    AccountType,
    Category,
    CategoryKind,
    HouseholdContext,
    TransactionKind,
)
from app.repositories.account import AccountRepository
from app.repositories.category import CategoryRepository
from app.services.ledger import LedgerReferenceResolver

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def make_account(name: str = "Current", archived: bool = False) -> Account:
    """Build an account row for the tests."""
    return Account(
        household_id=HOUSEHOLD_ID,
        name=name,
        type=AccountType.CURRENT,
        currency_code="EUR",
        opening_balance_minor=0,
        opening_balance_date=date(2026, 1, 1),
        archived_at=datetime.now(UTC) if archived else None,
    )


def make_category(name: str = "Groceries", kind: CategoryKind = CategoryKind.EXPENSE) -> Category:
    """Build a category row for the tests."""
    return Category(household_id=HOUSEHOLD_ID, name=name, kind=kind)


@pytest.fixture
def resolver(
    mock_account_repository: AccountRepository, mock_category_repository: CategoryRepository
) -> LedgerReferenceResolver:
    """Build a resolver over repositories backed by a mocked session."""
    return LedgerReferenceResolver(
        account_repository=mock_account_repository,
        category_repository=mock_category_repository,
    )


class TestCheckShape:
    """The shape rules a kind imposes on the rest of the row."""

    def test_accepts_an_expense_with_a_category(self, resolver: LedgerReferenceResolver) -> None:
        resolver.check_shape(
            kind=TransactionKind.EXPENSE,
            counter_account_id=None,
            category_id=uuid.uuid4(),
        )

    def test_accepts_a_transfer_between_two_accounts(self, resolver: LedgerReferenceResolver) -> None:
        resolver.check_shape(
            kind=TransactionKind.TRANSFER,
            counter_account_id=uuid.uuid4(),
            category_id=None,
        )

    def test_rejects_a_transfer_with_no_destination(self, resolver: LedgerReferenceResolver) -> None:
        with pytest.raises(TransferShapeError):
            resolver.check_shape(
                kind=TransactionKind.TRANSFER,
                counter_account_id=None,
                category_id=None,
            )

    def test_rejects_a_transfer_with_a_category(self, resolver: LedgerReferenceResolver) -> None:
        """Otherwise moving money to savings would show up as spending."""
        with pytest.raises(TransferShapeError):
            resolver.check_shape(
                kind=TransactionKind.TRANSFER,
                counter_account_id=uuid.uuid4(),
                category_id=uuid.uuid4(),
            )

    def test_rejects_a_destination_on_anything_else(self, resolver: LedgerReferenceResolver) -> None:
        with pytest.raises(TransferShapeError):
            resolver.check_shape(
                kind=TransactionKind.INCOME,
                counter_account_id=uuid.uuid4(),
                category_id=None,
            )

    def test_explains_a_transfer_without_naming_a_rule(self, resolver: LedgerReferenceResolver) -> None:
        """One wording for both services, so the same mistake reads the same everywhere."""
        with pytest.raises(TransferShapeError) as error:
            resolver.check_shape(
                kind=TransactionKind.TRANSFER,
                counter_account_id=uuid.uuid4(),
                category_id=uuid.uuid4(),
            )

        assert "moves money between your own accounts" in str(error.value)


class TestResolveAccount:
    """Loading an account that can take a transaction."""

    def test_returns_the_account(
        self, resolver: LedgerReferenceResolver, household_context: HouseholdContext, mock_db_session: MagicMock
    ) -> None:
        account = make_account()
        mock_db_session.exec.return_value.first.return_value = account

        assert resolver.resolve_account(household=household_context, account_id=account.id) is account

    def test_rejects_an_account_of_another_household(
        self, resolver: LedgerReferenceResolver, household_context: HouseholdContext, mock_db_session: MagicMock
    ) -> None:
        mock_db_session.exec.return_value.first.return_value = None

        with pytest.raises(AccountNotFoundError):
            resolver.resolve_account(household=household_context, account_id=uuid.uuid4())

    def test_rejects_an_archived_account(
        self, resolver: LedgerReferenceResolver, household_context: HouseholdContext, mock_db_session: MagicMock
    ) -> None:
        account = make_account(archived=True)
        mock_db_session.exec.return_value.first.return_value = account

        with pytest.raises(AccountArchivedError):
            resolver.resolve_account(household=household_context, account_id=account.id)


class TestResolveCategory:
    """Loading a category that suits the kind it is used for."""

    def test_returns_the_category(
        self, resolver: LedgerReferenceResolver, household_context: HouseholdContext, mock_db_session: MagicMock
    ) -> None:
        category = make_category()
        mock_db_session.exec.return_value.first.return_value = category

        resolved = resolver.resolve_category(
            household=household_context, category_id=category.id, kind=TransactionKind.EXPENSE
        )

        assert resolved is category

    def test_rejects_a_category_of_another_household(
        self, resolver: LedgerReferenceResolver, household_context: HouseholdContext, mock_db_session: MagicMock
    ) -> None:
        mock_db_session.exec.return_value.first.return_value = None

        with pytest.raises(CategoryNotFoundError):
            resolver.resolve_category(
                household=household_context, category_id=uuid.uuid4(), kind=TransactionKind.EXPENSE
            )

    def test_rejects_an_income_category_on_an_expense(
        self, resolver: LedgerReferenceResolver, household_context: HouseholdContext, mock_db_session: MagicMock
    ) -> None:
        category = make_category(name="Salary", kind=CategoryKind.INCOME)
        mock_db_session.exec.return_value.first.return_value = category

        with pytest.raises(TransactionCategoryKindError):
            resolver.resolve_category(
                household=household_context, category_id=category.id, kind=TransactionKind.EXPENSE
            )

    def test_require_category_ignores_the_kind(
        self, resolver: LedgerReferenceResolver, household_context: HouseholdContext, mock_db_session: MagicMock
    ) -> None:
        """Filtering by a category is not tied to a kind, so only existence is checked."""
        category = make_category(name="Salary", kind=CategoryKind.INCOME)
        mock_db_session.exec.return_value.first.return_value = category

        assert resolver.require_category(household=household_context, category_id=category.id) is category


class TestResolve:
    """The whole post-change tuple, which is what both create and update paths pass."""

    def test_resolves_an_expense(
        self, resolver: LedgerReferenceResolver, household_context: HouseholdContext, mock_db_session: MagicMock
    ) -> None:
        account = make_account()
        category = make_category()
        mock_db_session.exec.return_value.first.side_effect = [account, category]

        resolver.resolve(
            household=household_context,
            kind=TransactionKind.EXPENSE,
            account_id=account.id,
            counter_account_id=None,
            category_id=category.id,
        )

    def test_resolves_both_accounts_of_a_transfer(
        self, resolver: LedgerReferenceResolver, household_context: HouseholdContext, mock_db_session: MagicMock
    ) -> None:
        source = make_account("Current")
        destination = make_account("Savings")
        mock_db_session.exec.return_value.first.side_effect = [source, destination]

        resolver.resolve(
            household=household_context,
            kind=TransactionKind.TRANSFER,
            account_id=source.id,
            counter_account_id=destination.id,
            category_id=None,
        )

        assert mock_db_session.exec.call_count == 2

    def test_rejects_an_archived_destination(
        self, resolver: LedgerReferenceResolver, household_context: HouseholdContext, mock_db_session: MagicMock
    ) -> None:
        source = make_account("Current")
        destination = make_account("Savings", archived=True)
        mock_db_session.exec.return_value.first.side_effect = [source, destination]

        with pytest.raises(AccountArchivedError):
            resolver.resolve(
                household=household_context,
                kind=TransactionKind.TRANSFER,
                account_id=source.id,
                counter_account_id=destination.id,
                category_id=None,
            )

    def test_rejects_a_transfer_to_the_same_account(
        self, resolver: LedgerReferenceResolver, household_context: HouseholdContext, mock_db_session: MagicMock
    ) -> None:
        account = make_account()
        mock_db_session.exec.return_value.first.return_value = account

        with pytest.raises(SameAccountTransferError):
            resolver.resolve(
                household=household_context,
                kind=TransactionKind.TRANSFER,
                account_id=account.id,
                counter_account_id=account.id,
                category_id=None,
            )

    def test_reports_an_account_that_is_not_there_as_missing(
        self, resolver: LedgerReferenceResolver, household_context: HouseholdContext, mock_db_session: MagicMock
    ) -> None:
        """Naming an unknown account twice is still a missing reference, not a bad shape."""
        account_id = uuid.uuid4()
        mock_db_session.exec.return_value.first.return_value = None

        with pytest.raises(AccountNotFoundError):
            resolver.resolve(
                household=household_context,
                kind=TransactionKind.TRANSFER,
                account_id=account_id,
                counter_account_id=account_id,
                category_id=None,
            )

    def test_checks_the_shape_before_touching_the_database(
        self, resolver: LedgerReferenceResolver, household_context: HouseholdContext, mock_db_session: MagicMock
    ) -> None:
        with pytest.raises(TransferShapeError):
            resolver.resolve(
                household=household_context,
                kind=TransactionKind.EXPENSE,
                account_id=uuid.uuid4(),
                counter_account_id=uuid.uuid4(),
                category_id=None,
            )

        mock_db_session.exec.assert_not_called()
