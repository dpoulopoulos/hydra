import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, col, select

from app.models import Account, BankAccount, BankConnection, BankConnectionStatus, BankSyncRun, BankTransaction
from app.repositories.base import HouseholdScopedRepository, table_of

# What the settings page lists. A pending login has not come back from the
# bank yet, a failed one never will, and a revoked one was disconnected.
_LISTED_STATUSES = (BankConnectionStatus.ACTIVE, BankConnectionStatus.EXPIRED)


class BankConnectionRepository(HouseholdScopedRepository[BankConnection]):
    """Repository for BankConnection database operations."""

    def __init__(self, session: Session) -> None:
        """Initialize the bank connection repository.

        Args:
            session: The database session.
        """
        super().__init__(session, BankConnection)

    def lock_by_state(self, state: str, household_id: uuid.UUID) -> BankConnection | None:
        """Get the connection a login was started with, and lock it until the transaction ends.

        Locked because a browser can deliver the same callback twice, and the
        second must wait for the first to finish rather than spend the code a
        second time.

        Args:
            state: The state token the bank handed back.
            household_id: The ID of the household that must own the connection.

        Returns:
            The connection, or None if no login in the household was started with that state.
        """
        statement = (
            select(BankConnection)
            .where(BankConnection.state == state, BankConnection.household_id == household_id)
            .with_for_update()
        )
        return self.session.exec(statement).first()

    def list_for_household(self, household_id: uuid.UUID) -> Sequence[BankConnection]:
        """List the connections of a household worth showing: active and expired.

        Args:
            household_id: The ID of the household.

        Returns:
            The connections, newest first.
        """
        statement = (
            select(BankConnection)
            .where(
                BankConnection.household_id == household_id,
                col(BankConnection.status).in_(_LISTED_STATUSES),
            )
            .order_by(col(BankConnection.created_at).desc())
        )
        return self.session.exec(statement).all()


class BankAccountRepository(HouseholdScopedRepository[BankAccount]):
    """Repository for BankAccount database operations."""

    def __init__(self, session: Session) -> None:
        """Initialize the bank account repository.

        Args:
            session: The database session.
        """
        super().__init__(session, BankAccount)

    def get_by_identity(self, household_id: uuid.UUID, identity_key: str) -> BankAccount | None:
        """Get a bank account by what recognises it across logins.

        Args:
            household_id: The ID of the household.
            identity_key: The bank's identification hash, or the IBAN.

        Returns:
            The bank account, or None if the household has not seen it before.
        """
        statement = select(BankAccount).where(
            BankAccount.household_id == household_id, BankAccount.identity_key == identity_key
        )
        return self.session.exec(statement).first()

    def get_by_account(self, account_id: uuid.UUID, household_id: uuid.UUID) -> BankAccount | None:
        """Get the bank account feeding a Hydra account.

        Args:
            account_id: The ID of the Hydra account.
            household_id: The ID of the household.

        Returns:
            The bank account, or None if nothing feeds the account.
        """
        statement = select(BankAccount).where(
            BankAccount.household_id == household_id, BankAccount.account_id == account_id
        )
        return self.session.exec(statement).first()

    def list_for_connections(
        self, connection_ids: Sequence[uuid.UUID], household_id: uuid.UUID
    ) -> Sequence[BankAccount]:
        """List the bank accounts reached through some connections.

        Args:
            connection_ids: The IDs of the connections.
            household_id: The ID of the household.

        Returns:
            The bank accounts, by name.
        """
        if not connection_ids:
            return []
        statement = (
            select(BankAccount)
            .where(BankAccount.household_id == household_id, col(BankAccount.connection_id).in_(connection_ids))
            .order_by(col(BankAccount.name), col(BankAccount.created_at))
        )
        return self.session.exec(statement).all()

    def list_syncable(self, connection_id: uuid.UUID, household_id: uuid.UUID) -> Sequence[tuple[BankAccount, Account]]:
        """List the bank accounts of a connection that a sync should fetch, with their Hydra accounts.

        An account that is not linked, is switched off, or feeds an archived
        account is left out: fetching it would spend a pull from the bank's
        daily budget on rows with nowhere to go.

        Args:
            connection_id: The ID of the connection.
            household_id: The ID of the household.

        Returns:
            Pairs of bank account and the Hydra account it feeds.
        """
        statement = (
            select(BankAccount, Account)
            .join(Account, col(BankAccount.account_id) == col(Account.id))
            .where(
                BankAccount.household_id == household_id,
                BankAccount.connection_id == connection_id,
                col(BankAccount.sync_enabled).is_(True),
                col(Account.archived_at).is_(None),
            )
            .order_by(col(BankAccount.name))
        )
        return self.session.exec(statement).all()


class BankSyncRunRepository(HouseholdScopedRepository[BankSyncRun]):
    """Repository for BankSyncRun database operations."""

    def __init__(self, session: Session) -> None:
        """Initialize the bank sync run repository.

        Args:
            session: The database session.
        """
        super().__init__(session, BankSyncRun)


class BankTransactionRepository(HouseholdScopedRepository[BankTransaction]):
    """Repository for BankTransaction database operations."""

    def __init__(self, session: Session) -> None:
        """Initialize the bank transaction repository.

        Args:
            session: The database session.
        """
        super().__init__(session, BankTransaction)

    def insert_new(self, rows: Sequence[dict[str, Any]]) -> int:
        """Insert the rows not already held, recognised by bank account and dedupe key.

        Every sync fetches days it has fetched before, so most rows of most
        syncs are already here. Skipping them in the insert, rather than looking
        them up first, also makes two syncs racing each other harmless.

        Args:
            rows: The column values of each row, with an id.

        Returns:
            How many rows were new.
        """
        if not rows:
            return 0
        table = table_of(BankTransaction)
        statement = (
            pg_insert(table)
            .values(list(rows))
            .on_conflict_do_nothing(constraint="uq_banktransaction_account_dedupe")
            .returning(table.c.id)
        )
        return len(self.session.execute(statement).all())
