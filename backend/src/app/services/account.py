import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.exceptions import (
    AccountCurrencyLockedError,
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
    CurrencyTotal,
    HouseholdContext,
    Message,
)
from app.models.fields import minor_digits
from app.repositories.account import AccountRepository
from app.repositories.bank import BankAccountRepository
from app.repositories.goal import GoalRepository
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
        goal_repository: GoalRepository,
        bank_account_repository: BankAccountRepository,
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
            goal_repository: The goal repository instance, used to see what still
                references an account being deleted.
            bank_account_repository: The bank account repository instance, used to
                see which currency the bank feeding an account reports in.
        """
        self.session = session
        self.account_repository = account_repository
        self.household_repository = household_repository
        self.transaction_repository = transaction_repository
        self.recurring_rule_repository = recurring_rule_repository
        self.income_client_repository = income_client_repository
        self.trade_repository = trade_repository
        self.goal_repository = goal_repository
        self.bank_account_repository = bank_account_repository

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
            update={
                "household_id": household.household_id,
                "currency_code": account_create.currency_code or entity.currency_code,
            },
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

        # Asked for separately: summing the page would report a smaller net
        # worth the moment a second page exists.
        totals = self.account_repository.totals_by_currency(
            household_id=household.household_id,
            include_archived=include_archived,
            account_type=account_type,
        )

        return AccountsPublic(
            data=data,
            count=count,
            totals=[CurrencyTotal(currency_code=code, amount_minor=total) for code, total in sorted(totals.items())],
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
        """Rename, re-type, archive or restore an account, or change its currency.

        The opening balance is deliberately not updatable. Changing it would
        silently rewrite every historical balance, so a correction belongs in an
        adjustment transaction that is visible in the ledger.

        The currency can change only while nothing is filed against the
        account. Every amount already there was written in the old currency,
        and neither relabelling it nor converting it at today's rate would
        leave it saying what happened.

        Args:
            household: The household context.
            account_id: The ID of the account to update.
            account_update: The fields to update.

        Returns:
            The updated account.

        Raises:
            AccountNotFoundError: If the account does not exist in the household.
            AccountExistsError: If the household already has an account with the new name.
            AccountCurrencyLockedError: If the currency changes while something is
                filed against the account.
        """
        account = self.require_account(household=household, account_id=account_id)

        fields = account_update.model_dump(exclude_unset=True)
        is_archived = fields.pop("is_archived", None)
        currency_code = fields.pop("currency_code", None)

        if "name" in fields and fields["name"] != account.name:
            self._require_name_is_free(household=household, name=fields["name"])

        if currency_code is not None and currency_code != account.currency_code:
            self._change_currency(household=household, account=account, currency_code=currency_code)

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

    def _change_currency(self, household: HouseholdContext, account: Account, currency_code: str) -> None:
        """Move an account that nothing is filed against to another currency.

        The opening balance comes along as the same written amount, which is
        what changing the currency of an account just opened means. A currency
        with a different number of decimal places stores that amount as a
        different number of minor units, so it is rescaled.

        Args:
            household: The household context.
            account: The account, before the change.
            currency_code: The currency it is to hold.

        Raises:
            AccountCurrencyLockedError: If anything is filed against the account,
                its bank reports another currency, or the opening balance has
                more decimal places than the new currency can hold.
        """
        reason = self._first_reference(household=household, account=account)

        if reason is not None:
            raise AccountCurrencyLockedError(name=account.name, reason=reason) from None

        bank_account = self.bank_account_repository.get_by_account(account.id, household.household_id)

        if bank_account is not None and bank_account.currency_code and bank_account.currency_code != currency_code:
            raise AccountCurrencyLockedError(
                name=account.name,
                reason=f"is linked to a bank account in {bank_account.currency_code}",
                advice="Unlink it under Settings first.",
            ) from None

        shift = minor_digits(currency_code) - minor_digits(account.currency_code)

        if shift < 0 and account.opening_balance_minor % 10**-shift:
            raise AccountCurrencyLockedError(
                name=account.name, reason=f"opens with a fraction {currency_code} does not have"
            ) from None

        account.opening_balance_minor = (
            account.opening_balance_minor * 10**shift if shift >= 0 else account.opening_balance_minor // 10**-shift
        )
        account.currency_code = currency_code

    def _require_nothing_references(self, household: HouseholdContext, account: Account) -> None:
        """Check that an account can be deleted without breaking a reference to it.

        Args:
            household: The household context.
            account: The account about to be deleted.

        Raises:
            AccountInUseError: If anything still references the account.
        """
        reason = self._first_reference(household=household, account=account)

        if reason is not None:
            raise AccountInUseError(name=account.name, reason=reason) from None

    def _first_reference(self, household: HouseholdContext, account: Account) -> str | None:
        """Find the first thing that still references an account.

        Seven foreign keys point at account and every one of them is RESTRICT,
        yet only two are about transactions. Ask for each reference up front,
        in the order the user is likeliest to be able to act on, so a refusal
        names what is actually holding the account. A blocker left unasked
        reaches the database instead, which refuses a delete without saying
        why, and the user is told about transactions the account does not have.

        Six checks, not seven: a transaction holds an account from either side,
        and one count covers both.

        Args:
            household: The household context.
            account: The account.

        Returns:
            What references the account, phrased to follow its name, or None
            when nothing does.
        """
        household_id = household.household_id

        if self.transaction_repository.count_for_account(account_id=account.id, household_id=household_id):
            return "still has transactions"

        if self.recurring_rule_repository.count_for_account(account_id=account.id, household_id=household_id):
            return "still has recurring rules paid from it"

        if self.recurring_rule_repository.count_for_counter_account(account_id=account.id, household_id=household_id):
            return "is the destination of a recurring transfer"

        if self.income_client_repository.count_for_default_account(account_id=account.id, household_id=household_id):
            return "is where an income client is paid"

        if self.trade_repository.count_for_brokerage_account(account_id=account.id, household_id=household_id):
            return "has investment trades settled through it"

        if self.goal_repository.count_for_account(account_id=account.id, household_id=household_id):
            return "holds a savings goal"

        return None

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
