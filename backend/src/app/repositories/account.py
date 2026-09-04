import uuid
from collections.abc import Sequence

from sqlmodel import Session, col, select

from app.models import Account, AccountType
from app.repositories.base import HouseholdScopedRepository


class AccountRepository(HouseholdScopedRepository[Account]):
    """Repository for Account database operations.

    Balances are derived from the ledger on every read rather than stored. A
    stored balance is a cache with no invalidation story that survives
    back-dated edits, re-pointed transfers and recurring runs, and a balance
    that has silently drifted is the most damaging bug a finance app can have.
    At a few thousand transactions a year the sum is cheap.
    """

    def __init__(self, session: Session) -> None:
        """Initialize the account repository.

        Args:
            session: The database session.
        """
        super().__init__(session, Account)

    def list_for_household(
        self,
        household_id: uuid.UUID,
        include_archived: bool = False,
        account_type: AccountType | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[Account], int]:
        """List the accounts of a household.

        Args:
            household_id: The ID of the household.
            include_archived: Whether to include archived accounts.
            account_type: An optional type to filter on.
            skip: Number of records to skip.
            limit: Maximum number of records to return.

        Returns:
            Tuple of (accounts, total_count), ordered by name.
        """
        statement = select(Account).where(Account.household_id == household_id)

        if not include_archived:
            statement = statement.where(col(Account.archived_at).is_(None))

        if account_type is not None:
            statement = statement.where(Account.type == account_type)

        count = len(self.session.exec(statement).all())
        page = self.session.exec(statement.order_by(col(Account.name)).offset(skip).limit(limit)).all()

        return page, count

    def get_by_name(self, household_id: uuid.UUID, name: str) -> Account | None:
        """Get an account by name within a household.

        Args:
            household_id: The ID of the household.
            name: The account name.

        Returns:
            The account if one exists with that name, None otherwise.
        """
        statement = select(Account).where(Account.household_id == household_id, Account.name == name)
        return self.session.exec(statement).first()

    def balance_of(self, account_id: uuid.UUID, household_id: uuid.UUID) -> int:
        """Compute the current balance of an account, in minor units.

        Args:
            account_id: The ID of the account.
            household_id: The ID of the household that owns it.

        Returns:
            The balance, or zero if the account does not exist in the household.
        """
        return self.balances_of(account_ids=[account_id], household_id=household_id).get(account_id, 0)

    def balances_of(self, account_ids: Sequence[uuid.UUID], household_id: uuid.UUID) -> dict[uuid.UUID, int]:
        """Compute the current balance of several accounts, in minor units.

        Batched so listing accounts costs one query rather than one per account.

        Args:
            account_ids: The IDs of the accounts.
            household_id: The ID of the household that owns them.

        Returns:
            A mapping of account ID to balance. Accounts that do not exist in
            the household are absent.
        """
        if not account_ids:
            return {}

        statement = select(Account.id, Account.opening_balance_minor).where(
            Account.household_id == household_id, col(Account.id).in_(account_ids)
        )

        # Until the ledger exists, an account's balance is what it opened with.
        # The transaction legs are added to this sum in the ledger slice.
        return dict(self.session.exec(statement).all())
