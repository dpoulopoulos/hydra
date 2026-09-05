import uuid

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
    Category,
    CategoryKind,
    HouseholdContext,
    TransactionKind,
)
from app.repositories.account import AccountRepository
from app.repositories.category import CategoryRepository

# Which category kind each transaction kind needs. Every kind is listed, and a
# transfer maps to None rather than being left out: an absent key would read as
# "no constraint", which is how a category slipped onto a transfer before.
CATEGORY_KIND_FOR: dict[TransactionKind, CategoryKind | None] = {
    TransactionKind.EXPENSE: CategoryKind.EXPENSE,
    TransactionKind.INCOME: CategoryKind.INCOME,
    TransactionKind.TRANSFER: None,
}

_TRANSFER_HAS_NO_CATEGORY = (
    "A transfer has no category: it moves money between your own accounts rather than spending it."
)


class LedgerReferenceResolver:
    """Resolve and check the accounts and category a ledger entry points at.

    A transaction and the recurring rule that creates one carry the same
    references and obey the same shape rules, so both are defined here once.
    Keeping them in one place is what stops a fix landing on only one of the
    two callers, which is how the rules drifted apart before.
    """

    def __init__(self, account_repository: AccountRepository, category_repository: CategoryRepository) -> None:
        """Initialize the resolver.

        Args:
            account_repository: The account repository instance.
            category_repository: The category repository instance.
        """
        self.account_repository = account_repository
        self.category_repository = category_repository

    def resolve(
        self,
        household: HouseholdContext,
        kind: TransactionKind,
        account_id: uuid.UUID,
        counter_account_id: uuid.UUID | None,
        category_id: uuid.UUID | None,
        check_accounts: bool = True,
    ) -> None:
        """Check every reference of an entry, as it will stand once written.

        The whole tuple is passed rather than only the fields that changed:
        switching an expense to a transfer, or moving a transfer to a different
        account, changes which rules apply, so checking fields in isolation
        would let an invalid row through.

        Args:
            household: The household context.
            kind: The kind of entry.
            account_id: The account it draws on.
            counter_account_id: The destination account, for a transfer.
            category_id: The category, for an expense or income.
            check_accounts: Whether to look the accounts up and check they can
                still take transactions. An edit that names no account leaves
                this off, so an unrelated change still saves once an account
                the entry already points at has been archived.

        Raises:
            AccountNotFoundError: If an account does not exist in the household.
            AccountArchivedError: If an account is archived.
            CategoryNotFoundError: If the category does not exist in the household.
            SameAccountTransferError: If a transfer names the same account twice.
            TransferShapeError: If the fields do not match the kind.
            TransactionCategoryKindError: If the category is the wrong kind.
        """
        self.check_shape(
            kind=kind,
            counter_account_id=counter_account_id,
            category_id=category_id,
        )

        if check_accounts:
            self.resolve_account(household=household, account_id=account_id)

            if counter_account_id is not None:
                self.resolve_account(household=household, account_id=counter_account_id)

        # After the lookups rather than before: an account that is not there is
        # a missing reference first and a badly shaped transfer second, so
        # naming it twice must not turn that 404 into a 400.
        if counter_account_id is not None and counter_account_id == account_id:
            raise SameAccountTransferError from None

        if category_id is not None:
            self.resolve_category(household=household, category_id=category_id, kind=kind)

    def check_shape(
        self,
        kind: TransactionKind,
        counter_account_id: uuid.UUID | None,
        category_id: uuid.UUID | None,
    ) -> None:
        """Check which fields a kind requires and which it forbids.

        The database enforces the same rules, so this exists to turn them into
        a clear message rather than an integrity error.

        Only whether a field is set is judged here, never the account it names:
        whether a transfer names the same account twice is decided in `resolve`,
        once both accounts have been looked up, so a reference that is not there
        is reported as missing rather than as a badly shaped transfer.

        Args:
            kind: The kind of entry.
            counter_account_id: The destination account, if any.
            category_id: The category, if any.

        Raises:
            TransferShapeError: If the fields do not match the kind.
        """
        if kind is TransactionKind.TRANSFER:
            if counter_account_id is None:
                raise TransferShapeError("A transfer needs a destination account.") from None

            if category_id is not None:
                raise TransferShapeError(_TRANSFER_HAS_NO_CATEGORY) from None
        elif counter_account_id is not None:
            raise TransferShapeError(
                "Only a transfer has a destination account. Set the kind to transfer, or remove it."
            ) from None

    def resolve_account(self, household: HouseholdContext, account_id: uuid.UUID) -> Account:
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

    def resolve_category(self, household: HouseholdContext, category_id: uuid.UUID, kind: TransactionKind) -> Category:
        """Load a category of the household and check it suits the kind.

        Args:
            household: The household context.
            category_id: The ID of the category.
            kind: The kind of entry it is being used for.

        Returns:
            The category.

        Raises:
            CategoryNotFoundError: If the category does not exist in the household.
            TransferShapeError: If the kind takes no category at all.
            TransactionCategoryKindError: If the category is the wrong kind.
        """
        expected = CATEGORY_KIND_FOR[kind]

        if expected is None:
            raise TransferShapeError(_TRANSFER_HAS_NO_CATEGORY) from None

        category = self.require_category(household=household, category_id=category_id)

        if category.kind is not expected:
            raise TransactionCategoryKindError from None

        return category

    def require_account(self, household: HouseholdContext, account_id: uuid.UUID) -> None:
        """Check that an account filter names an account of the household.

        Unlike `resolve_account` this accepts an archived account, because
        reading the entries already filed against one is still allowed.

        Args:
            household: The household context.
            account_id: The ID of the account.

        Raises:
            AccountNotFoundError: If the account does not exist in the household.
        """
        if not self.account_repository.exists_for_household(entity_id=account_id, household_id=household.household_id):
            raise AccountNotFoundError from None

    def require_category(self, household: HouseholdContext, category_id: uuid.UUID) -> Category:
        """Load a category of the household, whatever kind it is.

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
