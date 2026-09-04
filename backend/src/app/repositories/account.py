import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import case, union_all
from sqlmodel import Session, col, func, select
from sqlmodel.sql.expression import SelectOfScalar

from app.models import Account, AccountType, Transaction, TransactionKind
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
        statement = self._matching(
            household_id=household_id, include_archived=include_archived, account_type=account_type
        )

        count = len(self.session.exec(statement).all())
        page = self.session.exec(statement.order_by(col(Account.name)).offset(skip).limit(limit)).all()

        return page, count

    def total_balance(
        self,
        household_id: uuid.UUID,
        include_archived: bool = False,
        account_type: AccountType | None = None,
    ) -> int:
        """Sum the balances of every matching account, in minor units.

        Covers the whole filtered set rather than one page, so a paged list
        still reports what the household is actually worth.

        Args:
            household_id: The ID of the household.
            include_archived: Whether to include archived accounts.
            account_type: An optional type to filter on.

        Returns:
            The total balance, or zero when nothing matches.
        """
        statement = self._matching(
            household_id=household_id, include_archived=include_archived, account_type=account_type
        )
        account_ids = self.session.exec(statement.with_only_columns(col(Account.id))).all()
        if not account_ids:
            return 0

        return sum(self.balances_of(account_ids=account_ids, household_id=household_id).values())

    def _matching(
        self,
        household_id: uuid.UUID,
        include_archived: bool,
        account_type: AccountType | None,
    ) -> Any:
        """Build the query for the accounts a listing covers.

        Shared so a page and its total can never disagree about which
        accounts they are talking about.

        Args:
            household_id: The ID of the household.
            include_archived: Whether to include archived accounts.
            account_type: An optional type to filter on.

        Returns:
            The filtered query, unordered and unpaged.
        """
        statement = select(Account).where(Account.household_id == household_id)

        if not include_archived:
            statement = statement.where(col(Account.archived_at).is_(None))

        if account_type is not None:
            statement = statement.where(Account.type == account_type)

        return statement

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

        openings = select(Account.id, Account.opening_balance_minor).where(
            Account.household_id == household_id, col(Account.id).in_(account_ids)
        )
        balances = dict(self.session.exec(openings).all())

        for account_id, delta in self.session.exec(
            self._ledger_deltas(account_ids=account_ids, household_id=household_id)
        ).all():
            if account_id in balances:
                balances[account_id] += delta

        return balances

    def _ledger_deltas(self, account_ids: Sequence[uuid.UUID], household_id: uuid.UUID) -> SelectOfScalar[Any]:
        """Build the query that sums each account's transactions, in minor units.

        Amounts are stored as positive magnitudes, so the sign is applied here:
        income adds to the account, an expense or an outgoing transfer subtracts
        from it. A transfer is a single row, so the destination account is
        picked up by a second leg over counter_account_id, and the two legs
        cancel out across the household exactly as they should.

        Args:
            account_ids: The IDs of the accounts.
            household_id: The ID of the household that owns them.

        Returns:
            A query yielding (account_id, delta) pairs.
        """
        outgoing: Any = select(
            col(Transaction.account_id).label("account_id"),
            case(
                (col(Transaction.kind) == TransactionKind.INCOME, col(Transaction.amount_minor)),
                else_=-col(Transaction.amount_minor),
            ).label("delta"),
        ).where(Transaction.household_id == household_id, col(Transaction.account_id).in_(account_ids))
        incoming: Any = select(
            col(Transaction.counter_account_id).label("account_id"),
            col(Transaction.amount_minor).label("delta"),
        ).where(
            Transaction.household_id == household_id,
            col(Transaction.counter_account_id).in_(account_ids),
        )

        legs = union_all(outgoing, incoming).subquery()

        return select(legs.c.account_id, func.sum(legs.c.delta)).group_by(legs.c.account_id)  # type: ignore[return-value]
