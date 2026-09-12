import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.exceptions import (
    AccountExistsError,
    AccountInUseError,
    AccountNotFoundError,
    HouseholdNotFoundError,
)
from app.logging import get_logger
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
from app.repositories.income import IncomeClientRepository
from app.repositories.investment import TradeRepository
from app.repositories.recurring_rule import RecurringRuleRepository
from app.repositories.transaction import TransactionRepository

logger = get_logger(__name__)


class AccountService:
    """Provide services for account management."""

    def __init__(
        self,
        session: Session,
        account_repository: AccountRepository,
        household_repository: HouseholdRepository,
        transaction_repository: TransactionRepository,
        recurring_rule_repository: RecurringRuleRepository,
        income_client_repository: IncomeClientRepository,
        trade_repository: TradeRepository,
    ) -> None:
        """Initialize the account service.

        Args:
            session: The database session.
            account_repository: The account repository instance.
            household_repository: The household repository instance, used to read
                the household currency a new account inherits.
            transaction_repository: The transaction repository instance, used to see
                what still references an account being deleted.
            recurring_rule_repository: The recurring rule repository instance, used to
                see what still references an account being deleted.
            income_client_repository: The income client repository instance, used to
                see what still references an account being deleted.
            trade_repository: The trade repository instance, used to see what still
                references an account being deleted.
        """
        self.session = session
        self.account_repository = account_repository
        self.household_repository = household_repository
        self.transaction_repository = transaction_repository
        self.recurring_rule_repository = recurring_rule_repository
        self.income_client_repository = income_client_repository
        self.trade_repository = trade_repository

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
            The accounts on the page, and the household's total balance.
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
            # Asked for separately: summing the page would report a smaller
            # net worth the moment a second page exists.
            total_balance_minor=self.account_repository.total_balance(
                household_id=household.household_id,
                include_archived=include_archived,
                account_type=account_type,
            ),
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
            AccountInUseError: If anything still references the account.
        """
        account = self.require_account(household=household, account_id=account_id)

        self._require_nothing_references(household=household, account=account)

        # The checks above run in the same transaction as the delete, but a
        # concurrent request can still file a transaction against the account
        # between them. Translate that constraint violation into the same
        # advice, and let anything else surface as a 500 with a traceback.
        try:
            self.account_repository.delete(account)
            self.account_repository.flush()
        except IntegrityError as exc:
            self.session.rollback()
            logger.warning("Delete of account %s refused by the database: %s", account.id, exc)
            raise AccountInUseError(name=account.name, exc=exc) from exc

        self.session.commit()

        return Message(message="Account deleted.")

    def _require_nothing_references(self, household: HouseholdContext, account: Account) -> None:
        """Check that an account can be deleted without breaking a reference to it.

        Six foreign keys point at account and every one of them is RESTRICT,
        yet only two are about transactions. Ask for each reference up front,
        in the order the user is likeliest to be able to act on, so the refusal
        names what is actually holding the account. A blocker left unasked
        reaches the database instead, which refuses the delete without saying
        why, and the user is told about transactions the account does not have.

        Five checks, not six: a transaction holds an account from either side,
        and one count covers both.

        Args:
            household: The household context.
            account: The account about to be deleted.

        Raises:
            AccountInUseError: If anything still references the account.
        """
        household_id = household.household_id

        if self.transaction_repository.count_for_account(account_id=account.id, household_id=household_id):
            raise AccountInUseError(name=account.name, reason="still has transactions") from None

        if self.recurring_rule_repository.count_for_account(account_id=account.id, household_id=household_id):
            raise AccountInUseError(name=account.name, reason="still has recurring rules paid from it") from None

        if self.recurring_rule_repository.count_for_counter_account(account_id=account.id, household_id=household_id):
            raise AccountInUseError(name=account.name, reason="is the destination of a recurring transfer") from None

        if self.income_client_repository.count_for_default_account(account_id=account.id, household_id=household_id):
            raise AccountInUseError(name=account.name, reason="is where an income client is paid") from None

        if self.trade_repository.count_for_brokerage_account(account_id=account.id, household_id=household_id):
            raise AccountInUseError(name=account.name, reason="has investment trades settled through it") from None

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
