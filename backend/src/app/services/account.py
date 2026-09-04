import uuid
from datetime import UTC, datetime

from sqlmodel import Session

from app.exceptions import (
    AccountExistsError,
    AccountInUseError,
    AccountNotFoundError,
    HouseholdNotFoundError,
)
from app.models import (
    Account,
    AccountCreate,
    AccountPublic,
    AccountsPublic,
    AccountType,
    AccountUpdate,
    HouseholdContext,
    Message,
)
from app.repositories.account import AccountRepository
from app.repositories.household import HouseholdRepository


class AccountService:
    """Provide services for account management."""

    def __init__(
        self,
        session: Session,
        account_repository: AccountRepository,
        household_repository: HouseholdRepository,
    ) -> None:
        """Initialize the account service.

        Args:
            session: The database session.
            account_repository: The account repository instance.
            household_repository: The household repository instance, used to read
                the household currency a new account inherits.
        """
        self.session = session
        self.account_repository = account_repository
        self.household_repository = household_repository

    def create_account(self, household: HouseholdContext, account_create: AccountCreate) -> AccountPublic:
        """Create an account.

        Args:
            household: The household context.
            account_create: The account to create.

        Returns:
            The created account.

        Raises:
            AccountExistsError: If the household already has an account with that name.
            HouseholdNotFoundError: If the household no longer exists.
        """
        self._require_name_is_free(household=household, name=account_create.name)

        entity = self.household_repository.get_by_id(household.household_id)

        if not entity:
            raise HouseholdNotFoundError from None

        account = Account.model_validate(
            account_create,
            update={"household_id": household.household_id, "currency_code": entity.currency_code},
        )
        self.account_repository.save(account)
        self.session.commit()

        return self._to_public(account=account, balance_minor=account.opening_balance_minor)

    def list_accounts(
        self,
        household: HouseholdContext,
        include_archived: bool = False,
        account_type: AccountType | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> AccountsPublic:
        """List the accounts of the household with their balances.

        Args:
            household: The household context.
            include_archived: Whether to include archived accounts.
            account_type: An optional type to filter on.
            skip: Number of records to skip.
            limit: Maximum number of records to return.

        Returns:
            The accounts, and the total of the balances returned.
        """
        accounts, count = self.account_repository.list_for_household(
            household_id=household.household_id,
            include_archived=include_archived,
            account_type=account_type,
            skip=skip,
            limit=limit,
        )
        balances = self.account_repository.balances_of(
            account_ids=[account.id for account in accounts], household_id=household.household_id
        )
        data = [self._to_public(account=account, balance_minor=balances.get(account.id, 0)) for account in accounts]

        return AccountsPublic(
            data=data,
            count=count,
            total_balance_minor=sum(account.current_balance_minor for account in data),
        )

    def get_account(self, household: HouseholdContext, account_id: uuid.UUID) -> AccountPublic:
        """Get one account of the household with its balance.

        Args:
            household: The household context.
            account_id: The ID of the account.

        Returns:
            The account.

        Raises:
            AccountNotFoundError: If the account does not exist in the household.
        """
        account = self.require_account(household=household, account_id=account_id)
        balance = self.account_repository.balance_of(account_id=account.id, household_id=household.household_id)

        return self._to_public(account=account, balance_minor=balance)

    def update_account(
        self, household: HouseholdContext, account_id: uuid.UUID, account_update: AccountUpdate
    ) -> AccountPublic:
        """Rename, re-type, archive or restore an account.

        The opening balance is deliberately not updatable. Changing it would
        silently rewrite every historical balance, so a correction belongs in an
        adjustment transaction that is visible in the ledger.

        Args:
            household: The household context.
            account_id: The ID of the account to update.
            account_update: The fields to update.

        Returns:
            The updated account.

        Raises:
            AccountNotFoundError: If the account does not exist in the household.
            AccountExistsError: If the household already has an account with the new name.
        """
        account = self.require_account(household=household, account_id=account_id)

        fields = account_update.model_dump(exclude_unset=True)
        is_archived = fields.pop("is_archived", None)

        if "name" in fields and fields["name"] != account.name:
            self._require_name_is_free(household=household, name=fields["name"])

        account.sqlmodel_update(fields)

        if is_archived is not None:
            account.archived_at = datetime.now(UTC) if is_archived else None

        self.account_repository.save(account)
        self.session.commit()

        balance = self.account_repository.balance_of(account_id=account.id, household_id=household.household_id)

        return self._to_public(account=account, balance_minor=balance)

    def delete_account(self, household: HouseholdContext, account_id: uuid.UUID) -> Message:
        """Delete an account that has no history.

        Args:
            household: The household context.
            account_id: The ID of the account to delete.

        Returns:
            A confirmation message.

        Raises:
            AccountNotFoundError: If the account does not exist in the household.
            AccountInUseError: If the account still has transactions.
        """
        account = self.require_account(household=household, account_id=account_id)

        # The foreign keys from the ledger are RESTRICT, so the database refuses
        # the delete if any transaction still points here. Translate that into
        # advice rather than a 500.
        try:
            self.account_repository.delete(account)
            self.account_repository.flush()
        except Exception as exc:
            self.session.rollback()
            raise AccountInUseError(name=account.name, exc=exc) from exc

        self.session.commit()

        return Message(message="Account deleted.")

    def require_account(self, household: HouseholdContext, account_id: uuid.UUID) -> Account:
        """Load an account of the household.

        Public because the transaction service resolves the accounts a
        transaction references through the same check.

        Args:
            household: The household context.
            account_id: The ID of the account.

        Returns:
            The account.

        Raises:
            AccountNotFoundError: If the account does not exist in the household.
        """
        account = self.account_repository.get_for_household(entity_id=account_id, household_id=household.household_id)

        if not account:
            raise AccountNotFoundError from None

        return account

    def _require_name_is_free(self, household: HouseholdContext, name: str) -> None:
        """Check that no account in the household already uses a name.

        Args:
            household: The household context.
            name: The name to check.

        Raises:
            AccountExistsError: If an account already has that name.
        """
        if self.account_repository.get_by_name(household_id=household.household_id, name=name):
            raise AccountExistsError(name=name) from None

    def _to_public(self, account: Account, balance_minor: int) -> AccountPublic:
        """Build the public representation of an account.

        Args:
            account: The account.
            balance_minor: Its current balance, in minor units.

        Returns:
            The public account.
        """
        return AccountPublic.model_validate(account, update={"current_balance_minor": balance_minor})
