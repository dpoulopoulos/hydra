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
    TransactionFromSessionError,
    TransactionNotFoundError,
    TransferShapeError,
)
from app.models import (
    Account,
    AccountType,
    Category,
    CategoryKind,
    HouseholdContext,
    Message,
    Transaction,
    TransactionCreate,
    TransactionFilters,
    TransactionKind,
    TransactionUpdate,
)
from app.services import TransactionService

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


def make_transaction(
    kind: TransactionKind = TransactionKind.EXPENSE,
    amount_minor: int = 4250,
    account_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    counter_account_id: uuid.UUID | None = None,
) -> Transaction:
    """Build a transaction row for the tests."""
    return Transaction(
        household_id=HOUSEHOLD_ID,
        kind=kind,
        amount_minor=amount_minor,
        occurred_on=date(2026, 3, 4),
        account_id=account_id or uuid.uuid4(),
        category_id=category_id,
        counter_account_id=counter_account_id,
    )


class TestCreateTransaction:
    """Tests for create_transaction."""

    def test_records_an_expense(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        category = make_category()
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.side_effect = [account, category]

        result = mock_transaction_service.create_transaction(
            household=household_context,
            transaction_create=TransactionCreate(
                kind=TransactionKind.EXPENSE,
                amount_minor=4250,
                occurred_on=date(2026, 3, 4),
                account_id=account.id,
                category_id=category.id,
            ),
        )

        assert result.amount_minor == 4250
        assert result.kind is TransactionKind.EXPENSE
        mock_transaction_service.session.commit.assert_called_once()

    def test_records_income(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        category = make_category(name="Salary", kind=CategoryKind.INCOME)
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.side_effect = [account, category]

        result = mock_transaction_service.create_transaction(
            household=household_context,
            transaction_create=TransactionCreate(
                kind=TransactionKind.INCOME,
                amount_minor=250_000,
                occurred_on=date(2026, 3, 1),
                account_id=account.id,
                category_id=category.id,
            ),
        )

        assert result.kind is TransactionKind.INCOME

    def test_records_a_transfer_as_a_single_row(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        """One row with a counter account, so there is no pair that can fall out of step."""
        source = make_account("Current")
        destination = make_account("Savings")
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.side_effect = [source, destination]

        result = mock_transaction_service.create_transaction(
            household=household_context,
            transaction_create=TransactionCreate(
                kind=TransactionKind.TRANSFER,
                amount_minor=20_000,
                occurred_on=date(2026, 3, 5),
                account_id=source.id,
                counter_account_id=destination.id,
            ),
        )

        assert result.counter_account_id == destination.id
        assert result.category_id is None
        assert mock_transaction_service.session.add.call_count == 1

    def test_records_who_entered_it(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.return_value = account

        mock_transaction_service.create_transaction(
            household=household_context,
            transaction_create=TransactionCreate(
                kind=TransactionKind.EXPENSE,
                amount_minor=100,
                occurred_on=date(2026, 3, 4),
                account_id=account.id,
            ),
        )

        added = mock_transaction_service.session.add.call_args.args[0]
        assert added.created_by_user_id == household_context.user_id

    def test_rejects_a_zero_amount(self) -> None:
        """The magnitude carries no sign, so zero and negatives are meaningless."""
        with pytest.raises(ValueError):
            TransactionCreate(
                kind=TransactionKind.EXPENSE,
                amount_minor=0,
                occurred_on=date(2026, 3, 4),
                account_id=uuid.uuid4(),
            )

    def test_rejects_a_negative_amount(self) -> None:
        with pytest.raises(ValueError):
            TransactionCreate(
                kind=TransactionKind.EXPENSE,
                amount_minor=-100,
                occurred_on=date(2026, 3, 4),
                account_id=uuid.uuid4(),
            )

    def test_rejects_a_transfer_with_no_destination(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        with pytest.raises(TransferShapeError):
            mock_transaction_service.create_transaction(
                household=household_context,
                transaction_create=TransactionCreate(
                    kind=TransactionKind.TRANSFER,
                    amount_minor=100,
                    occurred_on=date(2026, 3, 4),
                    account_id=uuid.uuid4(),
                ),
            )

    def test_rejects_a_transfer_with_a_category(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        """Otherwise moving money to savings would show up as spending."""
        with pytest.raises(TransferShapeError):
            mock_transaction_service.create_transaction(
                household=household_context,
                transaction_create=TransactionCreate(
                    kind=TransactionKind.TRANSFER,
                    amount_minor=100,
                    occurred_on=date(2026, 3, 4),
                    account_id=uuid.uuid4(),
                    counter_account_id=uuid.uuid4(),
                    category_id=uuid.uuid4(),
                ),
            )

    def test_rejects_an_expense_with_a_destination(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        with pytest.raises(TransferShapeError):
            mock_transaction_service.create_transaction(
                household=household_context,
                transaction_create=TransactionCreate(
                    kind=TransactionKind.EXPENSE,
                    amount_minor=100,
                    occurred_on=date(2026, 3, 4),
                    account_id=uuid.uuid4(),
                    counter_account_id=uuid.uuid4(),
                ),
            )

    def test_rejects_a_transfer_to_the_same_account(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.return_value = account

        with pytest.raises(SameAccountTransferError):
            mock_transaction_service.create_transaction(
                household=household_context,
                transaction_create=TransactionCreate(
                    kind=TransactionKind.TRANSFER,
                    amount_minor=100,
                    occurred_on=date(2026, 3, 4),
                    account_id=account.id,
                    counter_account_id=account.id,
                ),
            )

    def test_rejects_an_account_from_another_household(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        """The repository scopes the query, so a foreign ID simply is not there."""
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.return_value = None

        with pytest.raises(AccountNotFoundError):
            mock_transaction_service.create_transaction(
                household=household_context,
                transaction_create=TransactionCreate(
                    kind=TransactionKind.EXPENSE,
                    amount_minor=100,
                    occurred_on=date(2026, 3, 4),
                    account_id=uuid.uuid4(),
                ),
            )

    def test_rejects_an_archived_account(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        account = make_account(archived=True)
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.return_value = account

        with pytest.raises(AccountArchivedError):
            mock_transaction_service.create_transaction(
                household=household_context,
                transaction_create=TransactionCreate(
                    kind=TransactionKind.EXPENSE,
                    amount_minor=100,
                    occurred_on=date(2026, 3, 4),
                    account_id=account.id,
                ),
            )

    def test_rejects_a_category_from_another_household(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.side_effect = [account, None]

        with pytest.raises(CategoryNotFoundError):
            mock_transaction_service.create_transaction(
                household=household_context,
                transaction_create=TransactionCreate(
                    kind=TransactionKind.EXPENSE,
                    amount_minor=100,
                    occurred_on=date(2026, 3, 4),
                    account_id=account.id,
                    category_id=uuid.uuid4(),
                ),
            )

    def test_rejects_an_income_category_on_an_expense(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        category = make_category(name="Salary", kind=CategoryKind.INCOME)
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.side_effect = [account, category]

        with pytest.raises(TransactionCategoryKindError):
            mock_transaction_service.create_transaction(
                household=household_context,
                transaction_create=TransactionCreate(
                    kind=TransactionKind.EXPENSE,
                    amount_minor=100,
                    occurred_on=date(2026, 3, 4),
                    account_id=account.id,
                    category_id=category.id,
                ),
            )


class TestListTransactions:
    """Tests for list_transactions."""

    def test_returns_the_matches_and_the_total(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.one.return_value = 7
        mock_transaction_service.session.exec.return_value.all.return_value = [make_transaction()]

        result = mock_transaction_service.list_transactions(
            household=household_context, filters=TransactionFilters()
        )

        assert result.count == 7
        assert len(result.data) == 1

    def test_a_parent_category_filter_includes_its_subcategories(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        parent = make_category(name="Food & Drink")
        child_id = uuid.uuid4()
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.return_value = parent
        mock_transaction_service.session.exec.return_value.all.side_effect = [[child_id], []]
        mock_transaction_service.session.exec.return_value.one.return_value = 0

        mock_transaction_service.list_transactions(
            household=household_context, filters=TransactionFilters(category_id=parent.id)
        )

        # The expanded set reaches the query, so spending filed under Groceries
        # is counted against a filter on Food & Drink.
        statements = [str(call.args[0]) for call in mock_transaction_service.session.exec.call_args_list]
        assert any("category.parent_id = " in statement for statement in statements)
        assert "category_id IN" in statements[-1]

    def test_subcategories_can_be_excluded(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        parent = make_category(name="Food & Drink")
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.return_value = parent
        mock_transaction_service.session.exec.return_value.all.return_value = []
        mock_transaction_service.session.exec.return_value.one.return_value = 0

        mock_transaction_service.list_transactions(
            household=household_context,
            filters=TransactionFilters(category_id=parent.id, include_subcategories=False),
        )

        # No descendant lookup ran, so only the category itself is matched:
        # the scoped lookup, the count and the page, and nothing more.
        statements = [str(call.args[0]) for call in mock_transaction_service.session.exec.call_args_list]
        assert len(statements) == 3
        assert all("category.parent_id = " not in statement for statement in statements)

    def test_a_category_filter_from_another_household_is_not_found(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        """A foreign category reads as 404 rather than quietly returning an empty page."""
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.return_value = None

        with pytest.raises(CategoryNotFoundError):
            mock_transaction_service.list_transactions(
                household=household_context, filters=TransactionFilters(category_id=uuid.uuid4())
            )

    def test_rejects_an_unknown_filter(self) -> None:
        """A mistyped filter must fail, not be ignored and return more data than asked for."""
        with pytest.raises(ValueError):
            TransactionFilters(catgory_id=uuid.uuid4())


class TestGetTransaction:
    """Tests for get_transaction."""

    def test_returns_the_transaction(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        transaction = make_transaction()
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.return_value = transaction

        assert (
            mock_transaction_service.get_transaction(
                household=household_context, transaction_id=transaction.id
            ).id
            == transaction.id
        )

    def test_a_transaction_from_another_household_is_not_found(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.return_value = None

        with pytest.raises(TransactionNotFoundError):
            mock_transaction_service.get_transaction(
                household=household_context, transaction_id=uuid.uuid4()
            )


class TestUpdateTransaction:
    """Tests for update_transaction."""

    def test_changes_the_amount(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        transaction = make_transaction(account_id=account.id)
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.side_effect = [transaction, account]

        result = mock_transaction_service.update_transaction(
            household=household_context,
            transaction_id=transaction.id,
            transaction_update=TransactionUpdate(amount_minor=5000),
        )

        assert result.amount_minor == 5000
        mock_transaction_service.session.commit.assert_called_once()

    def test_turning_an_expense_into_a_transfer_drops_the_category(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        """The new kind cannot carry a category, so it is cleared rather than refused."""
        account = make_account("Current")
        destination = make_account("Savings")
        transaction = make_transaction(account_id=account.id, category_id=uuid.uuid4())
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.side_effect = [
            transaction,
            account,
            destination,
        ]

        result = mock_transaction_service.update_transaction(
            household=household_context,
            transaction_id=transaction.id,
            transaction_update=TransactionUpdate(
                kind=TransactionKind.TRANSFER, counter_account_id=destination.id
            ),
        )

        assert result.kind is TransactionKind.TRANSFER
        assert result.category_id is None

    def test_turning_a_transfer_into_an_expense_drops_the_destination(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        account = make_account("Current")
        transaction = make_transaction(
            kind=TransactionKind.TRANSFER, account_id=account.id, counter_account_id=uuid.uuid4()
        )
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.side_effect = [transaction, account]

        result = mock_transaction_service.update_transaction(
            household=household_context,
            transaction_id=transaction.id,
            transaction_update=TransactionUpdate(kind=TransactionKind.EXPENSE),
        )

        assert result.kind is TransactionKind.EXPENSE
        assert result.counter_account_id is None

    def test_rejects_an_edit_that_points_a_transfer_at_its_own_account(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        transaction = make_transaction(
            kind=TransactionKind.TRANSFER, account_id=account.id, counter_account_id=uuid.uuid4()
        )
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.side_effect = [transaction, account]

        with pytest.raises(SameAccountTransferError):
            mock_transaction_service.update_transaction(
                household=household_context,
                transaction_id=transaction.id,
                transaction_update=TransactionUpdate(counter_account_id=account.id),
            )

    def test_rejects_moving_a_transaction_to_a_foreign_account(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        transaction = make_transaction()
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.side_effect = [transaction, None]

        with pytest.raises(AccountNotFoundError):
            mock_transaction_service.update_transaction(
                household=household_context,
                transaction_id=transaction.id,
                transaction_update=TransactionUpdate(account_id=uuid.uuid4()),
            )


class TestDeleteTransaction:
    """Tests for delete_transaction."""

    def test_deletes_the_transaction(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        transaction = make_transaction()
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.return_value = transaction

        result = mock_transaction_service.delete_transaction(
            household=household_context, transaction_id=transaction.id
        )

        assert isinstance(result, Message)
        mock_transaction_service.session.delete.assert_called_once_with(transaction)

    def test_a_transaction_from_another_household_is_not_found(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.return_value = None

        with pytest.raises(TransactionNotFoundError):
            mock_transaction_service.delete_transaction(
                household=household_context, transaction_id=uuid.uuid4()
            )




class TestSessionGeneratedTransactions:
    """Tests that a session's income cannot be edited from the ledger.

    The session holds the fee and the Income page reads it from there. If this
    row could be changed here the two would drift apart, and nothing afterwards
    could say which figure was the real one.
    """

    def test_a_session_transaction_cannot_be_edited(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        transaction = make_transaction(kind=TransactionKind.INCOME)
        transaction.income_session_id = uuid.uuid4()
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.return_value = transaction

        with pytest.raises(TransactionFromSessionError):
            mock_transaction_service.update_transaction(
                household=household_context,
                transaction_id=transaction.id,
                transaction_update=TransactionUpdate(amount_minor=9999),
            )

    def test_a_session_transaction_cannot_be_deleted(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        transaction = make_transaction(kind=TransactionKind.INCOME)
        transaction.income_session_id = uuid.uuid4()
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.return_value = transaction

        with pytest.raises(TransactionFromSessionError):
            mock_transaction_service.delete_transaction(household=household_context, transaction_id=transaction.id)

    def test_ordinary_income_is_left_alone(
        self, mock_transaction_service: TransactionService, household_context: HouseholdContext
    ) -> None:
        """The guard must not catch income somebody typed in by hand."""
        transaction = make_transaction(kind=TransactionKind.INCOME)
        mock_transaction_service.session.exec = MagicMock()
        mock_transaction_service.session.exec.return_value.first.return_value = transaction

        message = mock_transaction_service.delete_transaction(
            household=household_context, transaction_id=transaction.id
        )

        assert message.message == "Transaction deleted."
