"""Reviewing what bank sync brought in, before it reaches the ledger."""

import datetime
import uuid

from sqlmodel import Session

from app.exceptions import (
    BankAccountMappingError,
    BankTransactionKindError,
    BankTransactionNotFoundError,
    BankTransactionReviewedError,
)
from app.models import (
    BankAccount,
    BankDirection,
    BankInboxFilters,
    BankReviewStatus,
    BankTransaction,
    BankTransactionAccept,
    BankTransactionPublic,
    BankTransactionsPublic,
    HouseholdContext,
    TransactionCreate,
    TransactionKind,
)
from app.repositories.bank import BankAccountRepository, BankTransactionRepository
from app.services.transaction import TransactionService

# What each direction of money can be recorded as. Money out of the bank
# account is spending or a transfer to another account; money in is income or
# a transfer from one.
_KINDS = {
    BankDirection.DEBIT: (TransactionKind.EXPENSE, TransactionKind.TRANSFER),
    BankDirection.CREDIT: (TransactionKind.INCOME, TransactionKind.TRANSFER),
}


def to_public(row: BankTransaction, bank_account: BankAccount) -> BankTransactionPublic:
    """Build the response for an inbox row.

    Args:
        row: The bank transaction.
        bank_account: The bank account it came from.

    Returns:
        The row, with the bank account's name and the account it feeds.
    """
    return BankTransactionPublic.model_validate(
        row,
        from_attributes=True,
        update={"bank_account_name": bank_account.name, "account_id": bank_account.account_id},
    )


class BankInboxService:
    """Provide services for the bank inbox.

    Accepting a row records it in the ledger and marks it accepted in one
    commit. The amount, the date and which account it is on are the bank's;
    what is chosen is whether it is spending, income or a transfer, and how it
    is filed.
    """

    def __init__(
        self,
        session: Session,
        bank_transaction_repository: BankTransactionRepository,
        bank_account_repository: BankAccountRepository,
        transaction_service: TransactionService,
    ) -> None:
        """Initialize the bank inbox service.

        Args:
            session: The database session.
            bank_transaction_repository: The bank transaction repository instance.
            bank_account_repository: The bank account repository instance.
            transaction_service: The transaction service, which records accepted rows.
        """
        self.session = session
        self.bank_transaction_repository = bank_transaction_repository
        self.bank_account_repository = bank_account_repository
        self.transaction_service = transaction_service

    def list_inbox(self, household: HouseholdContext, filters: BankInboxFilters) -> BankTransactionsPublic:
        """List a page of the inbox.

        Args:
            household: The household context.
            filters: Which review status, which bank account, and which page.

        Returns:
            The page, newest first, and how many rows match in all.
        """
        rows, count = self.bank_transaction_repository.list_inbox(household.household_id, filters)
        return BankTransactionsPublic(data=[to_public(row, account) for row, account in rows], count=count)

    def accept(
        self, household: HouseholdContext, bank_transaction_id: uuid.UUID, accept: BankTransactionAccept
    ) -> BankTransactionPublic:
        """Record an inbox row in the ledger.

        Args:
            household: The household context.
            bank_transaction_id: The ID of the bank transaction.
            accept: How to record it.

        Returns:
            The accepted row, linked to its ledger transaction.

        Raises:
            BankTransactionNotFoundError: If the row does not exist in the household.
            BankTransactionReviewedError: If the row is not waiting in the inbox.
            BankAccountMappingError: If its bank account no longer feeds an account.
            BankTransactionKindError: If the row cannot be recorded as that kind.
        """
        row, bank_account = self._require_pending(household, bank_transaction_id)
        if bank_account.account_id is None:
            raise BankAccountMappingError(
                "The bank account this came from is not linked to an account any more. Link it first."
            ) from None
        if accept.kind not in _KINDS[row.direction]:
            allowed = " or ".join(kind.value for kind in _KINDS[row.direction])
            raise BankTransactionKindError(f"Money {_direction_word(row)} can be recorded as {allowed}.") from None

        account_id = bank_account.account_id
        counter_account_id = None
        if accept.kind == TransactionKind.TRANSFER:
            # The bank account is the side the money left from, or arrived at.
            if accept.counter_account_id is None:
                raise BankTransactionKindError("A transfer needs the other account.") from None
            if row.direction == BankDirection.DEBIT:
                counter_account_id = accept.counter_account_id
            else:
                account_id, counter_account_id = accept.counter_account_id, bank_account.account_id

        transaction = self.transaction_service.record_transaction(
            household=household,
            transaction_create=TransactionCreate(
                kind=accept.kind,
                amount_minor=row.amount_minor,
                occurred_on=row.occurred_on,
                merchant=accept.merchant or row.counterparty_name or _first_words(row.description, 255),
                note=accept.note if accept.note is not None else row.description,
                account_id=account_id,
                category_id=accept.category_id,
                counter_account_id=counter_account_id,
                goal_id=accept.goal_id,
            ),
            external_id=f"eb:{row.id}",
            import_batch_id=row.sync_run_id,
        )

        row.review_status = BankReviewStatus.ACCEPTED
        row.ledger_transaction_id = transaction.id
        self._mark_reviewed(row, household)
        self.session.commit()
        return to_public(row, bank_account)

    def skip(self, household: HouseholdContext, bank_transaction_id: uuid.UUID) -> BankTransactionPublic:
        """Leave an inbox row out of the ledger.

        Args:
            household: The household context.
            bank_transaction_id: The ID of the bank transaction.

        Returns:
            The skipped row.

        Raises:
            BankTransactionNotFoundError: If the row does not exist in the household.
            BankTransactionReviewedError: If the row is not waiting in the inbox.
        """
        row, bank_account = self._require_pending(household, bank_transaction_id)
        row.review_status = BankReviewStatus.SKIPPED
        self._mark_reviewed(row, household)
        self.session.commit()
        return to_public(row, bank_account)

    def reopen(self, household: HouseholdContext, bank_transaction_id: uuid.UUID) -> BankTransactionPublic:
        """Put a skipped row back in the inbox.

        Args:
            household: The household context.
            bank_transaction_id: The ID of the bank transaction.

        Returns:
            The row, waiting again.

        Raises:
            BankTransactionNotFoundError: If the row does not exist in the household.
            BankTransactionReviewedError: If the row was not skipped.
        """
        row, bank_account = self._require(household, bank_transaction_id)
        if row.review_status != BankReviewStatus.SKIPPED:
            raise BankTransactionReviewedError(
                "Only a skipped row can go back to the inbox. To undo an accepted one, delete its transaction."
            ) from None
        row.review_status = BankReviewStatus.PENDING
        row.reviewed_at = None
        row.reviewed_by_user_id = None
        self.bank_transaction_repository.save(row)
        self.session.commit()
        return to_public(row, bank_account)

    def _require(
        self, household: HouseholdContext, bank_transaction_id: uuid.UUID
    ) -> tuple[BankTransaction, BankAccount]:
        """Load and lock an inbox row of the household, with its bank account.

        Args:
            household: The household context.
            bank_transaction_id: The ID of the bank transaction.

        Returns:
            The row and its bank account.

        Raises:
            BankTransactionNotFoundError: If the row does not exist in the household.
        """
        row = self.bank_transaction_repository.lock_for_household(bank_transaction_id, household.household_id)
        if row is None:
            raise BankTransactionNotFoundError from None
        bank_account = self.bank_account_repository.get_for_household(row.bank_account_id, household.household_id)
        if bank_account is None:
            raise BankTransactionNotFoundError from None
        return row, bank_account

    def _require_pending(
        self, household: HouseholdContext, bank_transaction_id: uuid.UUID
    ) -> tuple[BankTransaction, BankAccount]:
        """Load and lock an inbox row that is still waiting.

        Args:
            household: The household context.
            bank_transaction_id: The ID of the bank transaction.

        Returns:
            The row and its bank account.

        Raises:
            BankTransactionReviewedError: If the row was already accepted or skipped.
        """
        row, bank_account = self._require(household, bank_transaction_id)
        if row.review_status != BankReviewStatus.PENDING:
            raise BankTransactionReviewedError(f"This row was already {row.review_status.value}.") from None
        return row, bank_account

    def _mark_reviewed(self, row: BankTransaction, household: HouseholdContext) -> None:
        """Record who settled a row and when, and save it.

        Args:
            row: The bank transaction.
            household: The household context.
        """
        row.reviewed_at = datetime.datetime.now(datetime.UTC)
        row.reviewed_by_user_id = household.user.id
        self.bank_transaction_repository.save(row)


def _direction_word(row: BankTransaction) -> str:
    return "out" if row.direction == BankDirection.DEBIT else "in"


def _first_words(text: str | None, max_length: int) -> str | None:
    return text[:max_length] if text else None
