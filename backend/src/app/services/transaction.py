import uuid
from typing import TYPE_CHECKING

from sqlmodel import Session

from app.exceptions import (
    AccountArchivedError,
    AccountNotFoundError,
    CategoryNotFoundError,
    SameAccountTransferError,
    TransactionCategoryKindError,
    TransactionNotFoundError,
    TransferShapeError,
)
from app.models import (
    Account,
    Category,
    CategoryKind,
    HouseholdContext,
    Message,
    Transaction,
    TransactionCreate,
    TransactionFilters,
    TransactionKind,
    TransactionPublic,
    TransactionsPublic,
    TransactionUpdate,
)
from app.repositories.account import AccountRepository
from app.repositories.category import CategoryRepository
from app.repositories.transaction import TransactionRepository

if TYPE_CHECKING:
    from app.services.recurring_rule import RecurringRuleService

# Which category kind each transaction kind needs. A transfer takes none.
_CATEGORY_KIND_FOR: dict[TransactionKind, CategoryKind] = {
    TransactionKind.EXPENSE: CategoryKind.EXPENSE,
    TransactionKind.INCOME: CategoryKind.INCOME,
}


class TransactionService:
    """Provide services for the transaction ledger."""

    def __init__(
        self,
        session: Session,
        transaction_repository: TransactionRepository,
        account_repository: AccountRepository,
        category_repository: CategoryRepository,
    ) -> None:
        """Initialize the transaction service.

        Args:
            session: The database session.
            transaction_repository: The transaction repository instance.
            account_repository: The account repository instance.
            category_repository: The category repository instance.
        """
        self.session = session
        self.transaction_repository = transaction_repository
        self.account_repository = account_repository
        self.category_repository = category_repository

    def create_transaction(
        self, household: HouseholdContext, transaction_create: TransactionCreate
    ) -> TransactionPublic:
        """Record an expense, some income, or a transfer between accounts.

        A transfer is one row with a counter account, not two mirrored rows, so
        there is no pair of rows that could fall out of step.

        Args:
            household: The household context.
            transaction_create: The transaction to record.

        Returns:
            The recorded transaction.

        Raises:
            AccountNotFoundError: If an account does not exist in the household.
            AccountArchivedError: If an account is archived.
            CategoryNotFoundError: If the category does not exist in the household.
            SameAccountTransferError: If a transfer names the same account twice.
            TransferShapeError: If the transaction does not match its kind.
            TransactionCategoryKindError: If the category is the wrong kind.
        """
        self._check_shape(
            kind=transaction_create.kind,
            category_id=transaction_create.category_id,
            counter_account_id=transaction_create.counter_account_id,
        )
        self._resolve_account(household=household, account_id=transaction_create.account_id)

        if transaction_create.counter_account_id is not None:
            if transaction_create.counter_account_id == transaction_create.account_id:
                raise SameAccountTransferError from None

            self._resolve_account(household=household, account_id=transaction_create.counter_account_id)

        if transaction_create.category_id is not None:
            self._resolve_category(
                household=household,
                category_id=transaction_create.category_id,
                kind=transaction_create.kind,
            )

        transaction = Transaction.model_validate(
            transaction_create,
            update={"household_id": household.household_id, "created_by_user_id": household.user_id},
        )
        self.transaction_repository.save(transaction)
        self.session.commit()

        return TransactionPublic.model_validate(transaction)

    def list_transactions(
        self,
        household: HouseholdContext,
        filters: TransactionFilters,
        recurring_rule_service: "RecurringRuleService | None" = None,
    ) -> TransactionsPublic:
        """List the transactions of the household matching a set of filters.

        Args:
            household: The household context.
            filters: The filters to apply.
            recurring_rule_service: Optional recurring rule service. When given,
                any recurring transactions that have fallen due are recorded
                first, so the ledger is up to date before it is read.

        Returns:
            The matching transactions and the total number of matches.

        Raises:
            CategoryNotFoundError: If the category filter names a category
                outside the household.
        """
        if recurring_rule_service:
            recurring_rule_service.materialize_due(household=household)

        category_ids = None

        if filters.category_id is not None:
            # Resolved through the scoped repository, so filtering by another
            # household's category is a 404 rather than an empty page.
            self._require_category(household=household, category_id=filters.category_id)

            category_ids = (
                self.transaction_repository.descendant_category_ids(
                    category_id=filters.category_id, household_id=household.household_id
                )
                if filters.include_subcategories
                else [filters.category_id]
            )

        transactions, count = self.transaction_repository.list_for_household(
            household_id=household.household_id, filters=filters, category_ids=category_ids
        )
        data = [TransactionPublic.model_validate(transaction) for transaction in transactions]

        return TransactionsPublic(data=data, count=count)

    def get_transaction(self, household: HouseholdContext, transaction_id: uuid.UUID) -> TransactionPublic:
        """Get one transaction of the household.

        Args:
            household: The household context.
            transaction_id: The ID of the transaction.

        Returns:
            The transaction.

        Raises:
            TransactionNotFoundError: If the transaction does not exist in the household.
        """
        return TransactionPublic.model_validate(
            self._require_transaction(household=household, transaction_id=transaction_id)
        )

    def update_transaction(
        self,
        household: HouseholdContext,
        transaction_id: uuid.UUID,
        transaction_update: TransactionUpdate,
    ) -> TransactionPublic:
        """Edit a transaction.

        The whole row is re-validated after the change rather than only the
        fields that were sent. Switching an expense to a transfer, or moving a
        transfer to a different account, changes which shape rules apply, so
        checking the fields in isolation would let an invalid row through.

        Args:
            household: The household context.
            transaction_id: The ID of the transaction to edit.
            transaction_update: The fields to change.

        Returns:
            The updated transaction.

        Raises:
            TransactionNotFoundError: If the transaction does not exist in the household.
            AccountNotFoundError: If an account does not exist in the household.
            AccountArchivedError: If an account is archived.
            CategoryNotFoundError: If the category does not exist in the household.
            SameAccountTransferError: If a transfer names the same account twice.
            TransferShapeError: If the change does not match the kind.
            TransactionCategoryKindError: If the category is the wrong kind.
        """
        transaction = self._require_transaction(household=household, transaction_id=transaction_id)

        fields = transaction_update.model_dump(exclude_unset=True)
        kind = fields.get("kind", transaction.kind)
        account_id = fields.get("account_id", transaction.account_id)
        counter_account_id = fields.get("counter_account_id", transaction.counter_account_id)
        category_id = fields.get("category_id", transaction.category_id)

        # Changing to a transfer means the category has to go, and changing away
        # from one means the counter account has to. Rather than reject the
        # combination, clear whichever field the new kind cannot carry, unless
        # the caller set it explicitly in the same request.
        if kind is TransactionKind.TRANSFER and "category_id" not in fields:
            category_id = None

        if kind is not TransactionKind.TRANSFER and "counter_account_id" not in fields:
            counter_account_id = None

        self._check_shape(kind=kind, category_id=category_id, counter_account_id=counter_account_id)
        self._resolve_account(household=household, account_id=account_id)

        if counter_account_id is not None:
            if counter_account_id == account_id:
                raise SameAccountTransferError from None

            self._resolve_account(household=household, account_id=counter_account_id)

        if category_id is not None:
            self._resolve_category(household=household, category_id=category_id, kind=kind)

        transaction.sqlmodel_update(
            {
                **fields,
                "kind": kind,
                "account_id": account_id,
                "counter_account_id": counter_account_id,
                "category_id": category_id,
            }
        )
        self.transaction_repository.save(transaction)
        self.session.commit()

        return TransactionPublic.model_validate(transaction)

    def delete_transaction(self, household: HouseholdContext, transaction_id: uuid.UUID) -> Message:
        """Delete a transaction.

        Balances are derived from the ledger, so removing the row is all that is
        needed. There is no stored total to correct and therefore nothing that
        can drift.

        Args:
            household: The household context.
            transaction_id: The ID of the transaction to delete.

        Returns:
            A confirmation message.

        Raises:
            TransactionNotFoundError: If the transaction does not exist in the household.
        """
        transaction = self._require_transaction(household=household, transaction_id=transaction_id)
        self.transaction_repository.delete(transaction)
        self.session.commit()

        return Message(message="Transaction deleted.")

    def _check_shape(
        self,
        kind: TransactionKind,
        category_id: uuid.UUID | None,
        counter_account_id: uuid.UUID | None,
    ) -> None:
        """Check that a transaction matches the shape its kind requires.

        The database enforces the same rule, so this exists to turn it into a
        clear message rather than an integrity error.

        Args:
            kind: The kind of transaction.
            category_id: The category, if any.
            counter_account_id: The destination account, if any.

        Raises:
            TransferShapeError: If the fields do not match the kind.
        """
        if kind is TransactionKind.TRANSFER:
            if counter_account_id is None:
                raise TransferShapeError("A transfer needs a destination account.") from None

            if category_id is not None:
                raise TransferShapeError(
                    "A transfer has no category: it moves money between your own accounts rather than spending it."
                ) from None
        elif counter_account_id is not None:
            raise TransferShapeError(
                "Only a transfer has a destination account. Set the kind to transfer, or remove it."
            ) from None

    def _resolve_account(self, household: HouseholdContext, account_id: uuid.UUID) -> Account:
        """Load an account of the household and check it can take transactions.

        Args:
            household: The household context.
            account_id: The ID of the account.

        Returns:
            The account.

        Raises:
            AccountNotFoundError: If the account does not exist in the household.
            AccountArchivedError: If the account is archived.
        """
        account = self.account_repository.get_for_household(entity_id=account_id, household_id=household.household_id)

        if not account:
            raise AccountNotFoundError from None

        if account.archived_at is not None:
            raise AccountArchivedError(name=account.name) from None

        return account

    def _resolve_category(self, household: HouseholdContext, category_id: uuid.UUID, kind: TransactionKind) -> Category:
        """Load a category of the household and check it suits the kind.

        Args:
            household: The household context.
            category_id: The ID of the category.
            kind: The kind of transaction it is being used for.

        Returns:
            The category.

        Raises:
            CategoryNotFoundError: If the category does not exist in the household.
            TransactionCategoryKindError: If the category is the wrong kind.
        """
        category = self._require_category(household=household, category_id=category_id)
        expected = _CATEGORY_KIND_FOR.get(kind)

        if expected is not None and category.kind is not expected:
            raise TransactionCategoryKindError from None

        return category

    def _require_category(self, household: HouseholdContext, category_id: uuid.UUID) -> Category:
        """Load a category of the household.

        Args:
            household: The household context.
            category_id: The ID of the category.

        Returns:
            The category.

        Raises:
            CategoryNotFoundError: If the category does not exist in the household.
        """
        category = self.category_repository.get_for_household(
            entity_id=category_id, household_id=household.household_id
        )

        if not category:
            raise CategoryNotFoundError from None

        return category

    def _require_transaction(self, household: HouseholdContext, transaction_id: uuid.UUID) -> Transaction:
        """Load a transaction of the household.

        Args:
            household: The household context.
            transaction_id: The ID of the transaction.

        Returns:
            The transaction.

        Raises:
            TransactionNotFoundError: If the transaction does not exist in the household.
        """
        transaction = self.transaction_repository.get_for_household(
            entity_id=transaction_id, household_id=household.household_id
        )

        if not transaction:
            raise TransactionNotFoundError from None

        return transaction
