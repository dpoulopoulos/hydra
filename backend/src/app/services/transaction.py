import uuid
from typing import TYPE_CHECKING

from sqlmodel import Session

from app.exceptions import TransactionFromSessionError, TransactionNotFoundError
from app.models import (
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
from app.repositories.transaction import TransactionRepository
from app.services.ledger import LedgerReferenceResolver

if TYPE_CHECKING:
    from app.services.recurring_rule import RecurringRuleService


class TransactionService:
    """Provide services for the transaction ledger."""

    def __init__(
        self,
        session: Session,
        transaction_repository: TransactionRepository,
        reference_resolver: LedgerReferenceResolver,
    ) -> None:
        """Initialize the transaction service.

        Args:
            session: The database session.
            transaction_repository: The transaction repository instance.
            reference_resolver: The resolver for the accounts and category a transaction points at.
        """
        self.session = session
        self.transaction_repository = transaction_repository
        self.reference_resolver = reference_resolver

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
        self.reference_resolver.resolve(
            household=household,
            kind=transaction_create.kind,
            account_id=transaction_create.account_id,
            counter_account_id=transaction_create.counter_account_id,
            category_id=transaction_create.category_id,
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
            AccountNotFoundError: If the account filter names an account
                outside the household.
            CategoryNotFoundError: If the category filter names a category
                outside the household.
        """
        if recurring_rule_service:
            recurring_rule_service.materialize_due(household=household)

        if filters.account_id is not None:
            # Resolved through the scoped repository, so filtering by another
            # household's account is a 404 rather than an empty page. An
            # archived account still passes: it is hidden from new entries,
            # not from its own history.
            self.reference_resolver.require_account(household=household, account_id=filters.account_id)

        category_ids = None

        if filters.category_id is not None:
            # Resolved through the scoped repository, so filtering by another
            # household's category is a 404 rather than an empty page.
            self.reference_resolver.require_category(household=household, category_id=filters.category_id)

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

        The archived check is the exception: it only applies to an account the
        edit moves the row onto. An account archived after the transaction was
        recorded would otherwise block every edit of it, correcting a typo
        included, leaving deletion as the only way to act on the row.

        Args:
            household: The household context.
            transaction_id: The ID of the transaction to edit.
            transaction_update: The fields to change.

        Returns:
            The updated transaction.

        Raises:
            TransactionNotFoundError: If the transaction does not exist in the household.
            AccountNotFoundError: If an account does not exist in the household.
            AccountArchivedError: If an account the edit moves the row onto is archived.
            CategoryNotFoundError: If the category does not exist in the household.
            SameAccountTransferError: If a transfer names the same account twice.
            TransferShapeError: If the change does not match the kind.
            TransactionCategoryKindError: If the category is the wrong kind.
        """
        transaction = self._require_transaction(household=household, transaction_id=transaction_id)
        self._check_not_from_session(transaction)

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

        # An account the row already draws on is looked up, but not held to
        # being open: an edit that leaves the row where it is adds nothing to
        # that account, so archiving an account must not freeze the history it
        # already holds. Only an account the edit moves the row onto is gated.
        self.reference_resolver.resolve(
            household=household,
            kind=kind,
            account_id=account_id,
            counter_account_id=counter_account_id,
            category_id=category_id,
            settled_account_ids=self._accounts_already_used(transaction),
        )

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
        self._check_not_from_session(transaction)
        self.transaction_repository.delete(transaction)
        self.session.commit()

        return Message(message="Transaction deleted.")

    def _check_not_from_session(self, transaction: Transaction) -> None:
        """Refuse to edit a row a paid session generated.

        The session holds the fee, and the Income page reads it from there. If
        this row could be changed here the two would drift apart, and afterwards
        nothing in the app could say which of the two figures was real. One
        writer per number is what keeps the ledger and the diary equal.

        Args:
            transaction: The transaction about to be changed.

        Raises:
            TransactionFromSessionError: If a session generated the transaction.
        """
        if transaction.income_session_id is not None:
            raise TransactionFromSessionError from None

    def _accounts_already_used(self, transaction: Transaction) -> frozenset[uuid.UUID]:
        """Collect the accounts a stored transaction already draws on.

        Args:
            transaction: The stored transaction, before the edit is applied.

        Returns:
            The IDs of the accounts the row names today.
        """
        return frozenset(
            account_id
            for account_id in (transaction.account_id, transaction.counter_account_id)
            if account_id is not None
        )

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
