import datetime
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Date, case
from sqlalchemy import and_ as sa_and
from sqlalchemy import or_ as sa_or
from sqlmodel import Session, col, func, select, update

from app.models import (
    IncomeClient,
    IncomeClientFilters,
    IncomeSession,
    IncomeSessionFilters,
    IncomeSessionSort,
    IncomeSessionStatus,
    IncomeVault,
    PaymentStatus,
)
from app.models.fields import month_start, next_month_start
from app.repositories.base import BaseRepository, HouseholdScopedRepository
from app.repositories.rows import ClientTallyRow, NewClientMonthRow, SessionMonthRow

# A session earns money when the hour was worked and the fee was not written
# off. A no-show that carried a late cancellation fee earns exactly like an
# attended hour, which is why the status alone never decides this.
_WORKED_STATUSES = (IncomeSessionStatus.ATTENDED, IncomeSessionStatus.MISSED)


def _is_billable() -> tuple[Any, ...]:
    """Build the condition that marks a session as one that carries a fee.

    Says nothing about whether the hour has happened, so it applies equally to
    an appointment still in the diary. Waived sessions are excluded whatever
    their status, because the decision not to charge is the whole meaning of
    the word, and a fee of zero is a free session by another route.

    Returns:
        A SQLAlchemy condition usable in a WHERE clause or a CASE.
    """
    return (
        col(IncomeSession.payment_status) != PaymentStatus.WAIVED,
        col(IncomeSession.fee_minor) > 0,
    )


def _is_chargeable() -> tuple[Any, ...]:
    """Build the condition that marks a session as money the practice is owed.

    Billable, and the hour actually happened. A missed session usually earns
    nothing, but it does when a late cancellation fee was charged.

    Returns:
        A SQLAlchemy condition usable in a WHERE clause or a CASE.
    """
    return (*_is_billable(), col(IncomeSession.status).in_(_WORKED_STATUSES))


class IncomeVaultRepository(BaseRepository[IncomeVault]):
    """Repository for one person's client-name key.

    Not household scoped, and deliberately so: a vault belongs to a user, not to
    the household they are in. Two people sharing a household share their money,
    not their client lists.
    """

    def __init__(self, session: Session) -> None:
        """Initialize the vault repository.

        Args:
            session: The database session.
        """
        super().__init__(session, IncomeVault)

    def get_for_user(self, user_id: uuid.UUID) -> IncomeVault | None:
        """Get the key material a user stored, if they have any.

        Args:
            user_id: The ID of the user.

        Returns:
            The vault row, or None when that user has set up no PIN yet.
        """
        return self.session.get(IncomeVault, user_id)


class IncomeClientRepository(HouseholdScopedRepository[IncomeClient]):
    """Repository for IncomeClient database operations."""

    def __init__(self, session: Session) -> None:
        """Initialize the client repository.

        Args:
            session: The database session.
        """
        super().__init__(session, IncomeClient)

    def list_for_household(
        self,
        household_id: uuid.UUID,
        filters: IncomeClientFilters,
    ) -> tuple[Sequence[IncomeClient], int]:
        """List the clients of a household.

        Ordered by creation rather than by name, because the name is encrypted
        and sorting ciphertext would produce an order with no meaning. The page
        sorts by name after decrypting, which is the only place it can.

        Args:
            household_id: The ID of the household.
            filters: The filters to apply.

        Returns:
            Tuple of (clients, total_count).
        """
        conditions: list[Any] = [col(IncomeClient.household_id) == household_id]

        if filters.is_archived is not None:
            if filters.is_archived:
                conditions.append(col(IncomeClient.archived_at).is_not(None))
            else:
                conditions.append(col(IncomeClient.archived_at).is_(None))

        count_statement = select(func.count()).select_from(IncomeClient).where(*conditions)
        count = self.session.exec(count_statement).one()

        statement = self._paginate(
            select(IncomeClient).where(*conditions).order_by(col(IncomeClient.created_at).asc()),
            skip=filters.skip,
            limit=filters.limit,
        )

        return self.session.exec(statement).all(), count

    def endings_monthly(
        self,
        household_id: uuid.UUID,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> dict[datetime.date, int]:
        """Count, per month, the clients who finished.

        Archiving a client is what says they have stopped coming, so it is read as
        the ending itself rather than as bookkeeping. A client is counted in the
        month they were archived in.

        Args:
            household_id: The ID of the household.
            date_from: First day to include.
            date_to: First day to exclude, so the range is half open.

        Returns:
            The number of endings against the first of each month that had any.
        """
        month = func.cast(func.date_trunc("month", col(IncomeClient.archived_at)), Date)

        columns: list[Any] = [month.label("month"), func.count()]
        statement: Any = (
            select(*columns)
            .where(
                col(IncomeClient.household_id) == household_id,
                col(IncomeClient.archived_at).is_not(None),
                col(IncomeClient.archived_at) >= date_from,
                col(IncomeClient.archived_at) < date_to,
            )
            .group_by(month)
        )

        return {row[0]: row[1] for row in self.session.exec(statement).all()}

    def blank_names_for_owner(self, household_id: uuid.UUID, owner_user_id: uuid.UUID) -> int:
        """Wipe the stored name and note of every client one member added.

        One statement rather than a walk over rows, because the alternative is
        a page: the listing is capped, and anybody past the cap would keep
        ciphertext that no future key could ever decode while being told their
        names had been reset.

        Args:
            household_id: The ID of the household.
            owner_user_id: The member whose clients to blank. Another member's
                names are under another key and are none of this reset's
                business.

        Returns:
            The number of clients blanked.
        """
        statement = (
            update(IncomeClient)
            .where(
                col(IncomeClient.household_id) == household_id,
                col(IncomeClient.owner_user_id) == owner_user_id,
            )
            .values(name_ct="", note_ct=None)
        )
        return int(self.session.exec(statement).rowcount)

    def list_by_ids(self, household_id: uuid.UUID, client_ids: Sequence[uuid.UUID]) -> Sequence[IncomeClient]:
        """Fetch named clients, whatever state they are in.

        Bounded by the caller's own list rather than by a page, which is the
        point of it: the forecast needs whoever appears in one month's diary,
        and that set is the size of a month rather than the size of a roster.

        Args:
            household_id: The ID of the household.
            client_ids: The clients to fetch. An empty list fetches nothing.

        Returns:
            The clients that exist in the household.
        """
        if not client_ids:
            return []

        statement = select(IncomeClient).where(
            col(IncomeClient.household_id) == household_id,
            col(IncomeClient.id).in_(client_ids),
        )
        return self.session.exec(statement).all()

    def count_for_default_account(self, account_id: uuid.UUID, household_id: uuid.UUID) -> int:
        """Count the clients whose earnings are paid into an account.

        Archived clients count too. Archiving hides a client from the user but
        leaves its foreign key onto the account in place, so the database would
        still refuse the delete.

        Args:
            account_id: The ID of the account.
            household_id: The ID of the household.

        Returns:
            The number of clients that name the account as their default.
        """
        statement = (
            select(func.count())
            .select_from(IncomeClient)
            .where(
                col(IncomeClient.household_id) == household_id,
                col(IncomeClient.default_account_id) == account_id,
            )
        )
        return self.session.exec(statement).one()

    def count_active_for_household(self, household_id: uuid.UUID) -> int:
        """Count the clients a household still sees.

        Args:
            household_id: The ID of the household.

        Returns:
            The number of clients that are not archived.
        """
        statement = (
            select(func.count())
            .select_from(IncomeClient)
            .where(
                col(IncomeClient.household_id) == household_id,
                col(IncomeClient.archived_at).is_(None),
            )
        )
        return self.session.exec(statement).one()


class IncomeSessionRepository(HouseholdScopedRepository[IncomeSession]):
    """Repository for IncomeSession database operations."""

    def __init__(self, session: Session) -> None:
        """Initialize the session repository.

        Args:
            session: The database session.
        """
        super().__init__(session, IncomeSession)

    def list_for_household(
        self,
        household_id: uuid.UUID,
        filters: IncomeSessionFilters,
    ) -> tuple[Sequence[IncomeSession], int, int, int]:
        """List the sessions of a household matching a set of filters.

        The two totals come back with the page because the table footer needs
        them, and a second request for a number already summed here would be
        one more chance for the two to disagree.

        Args:
            household_id: The ID of the household.
            filters: The filters to apply.

        Returns:
            Tuple of (sessions, total_count, earned_total_minor, outstanding_total_minor).
        """
        conditions = self._conditions(household_id=household_id, filters=filters)

        count_statement = select(func.count()).select_from(IncomeSession).where(*conditions)
        count = self.session.exec(count_statement).one()

        chargeable = _is_chargeable()
        earned_case = case((sa_and(*chargeable), col(IncomeSession.fee_minor)), else_=0)
        outstanding_case = case(
            (
                sa_and(*chargeable, col(IncomeSession.payment_status) == PaymentStatus.PENDING),
                col(IncomeSession.fee_minor),
            ),
            else_=0,
        )

        totals_statement = select(
            func.coalesce(func.sum(earned_case), 0),
            func.coalesce(func.sum(outstanding_case), 0),
        ).where(*conditions)
        earned_total, outstanding_total = self.session.exec(totals_statement).one()

        statement = self._paginate(
            select(IncomeSession).where(*conditions).order_by(*self._ordering(filters.sort)),
            skip=filters.skip,
            limit=filters.limit,
        )

        # Postgres sums a BigInteger into a numeric, which arrives as a
        # Decimal. Money is an int everywhere in this app, and the forecast
        # does integer arithmetic on these, so the conversion belongs here at
        # the boundary rather than in every caller.
        return self.session.exec(statement).all(), count, int(earned_total), int(outstanding_total)

    def count_for_client(self, client_id: uuid.UUID, household_id: uuid.UUID) -> int:
        """Count the sessions recorded against a client.

        Args:
            client_id: The ID of the client.
            household_id: The ID of the household.

        Returns:
            The number of sessions referencing the client.
        """
        statement = (
            select(func.count())
            .select_from(IncomeSession)
            .where(
                col(IncomeSession.household_id) == household_id,
                col(IncomeSession.client_id) == client_id,
            )
        )
        return self.session.exec(statement).one()

    def monthly_totals(
        self,
        household_id: uuid.UUID,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> Sequence[SessionMonthRow]:
        """Aggregate sessions by the month the hour was worked in.

        Grouped on `occurs_on`, not on `paid_on`: this feeds the forecast, and
        the forecast describes the practice rather than how promptly people pay.

        Args:
            household_id: The ID of the household.
            date_from: First day to include.
            date_to: First day to exclude, so the range is half open.

        Returns:
            One row per month that had any session at all, oldest first.
        """
        chargeable = _is_chargeable()
        month = func.cast(func.date_trunc("month", col(IncomeSession.occurs_on)), Date)

        # Gathered into a list because the select is wider than the overloads
        # the type checker knows about. The order here is the order
        # SessionMonthRow unpacks below.
        columns: list[Any] = [
            month.label("month"),
            func.coalesce(func.sum(case((sa_and(*chargeable), col(IncomeSession.fee_minor)), else_=0)), 0),
            func.coalesce(
                func.sum(
                    case(
                        (
                            sa_and(*chargeable, col(IncomeSession.payment_status) == PaymentStatus.PAID),
                            col(IncomeSession.fee_minor),
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.count(case((col(IncomeSession.status) == IncomeSessionStatus.ATTENDED, 1))),
            func.count(case((col(IncomeSession.status) == IncomeSessionStatus.MISSED, 1))),
            func.count(case((col(IncomeSession.status) == IncomeSessionStatus.CANCELLED, 1))),
            func.count(
                case(
                    (
                        sa_and(*chargeable, col(IncomeSession.payment_status) == PaymentStatus.PENDING),
                        1,
                    )
                )
            ),
            func.count(func.distinct(col(IncomeSession.client_id))),
        ]

        statement: Any = (
            select(*columns)
            .where(
                col(IncomeSession.household_id) == household_id,
                col(IncomeSession.occurs_on) >= date_from,
                col(IncomeSession.occurs_on) < date_to,
            )
            .group_by(month)
            .order_by(month)
        )

        return [
            SessionMonthRow(
                month=row[0],
                earned_minor=int(row[1]),
                received_minor=int(row[2]),
                attended_count=row[3],
                missed_count=row[4],
                cancelled_count=row[5],
                unpaid_count=row[6],
                client_count=row[7],
            )
            for row in self.session.exec(statement).all()
        ]

    def settled_monthly(
        self,
        household_id: uuid.UUID,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> dict[datetime.date, int]:
        """Sum, per month, the money that actually arrived.

        Grouped on `paid_on` rather than on `occurs_on`, which is the whole
        point of it: an hour worked in March and settled in June is money that
        left the debtors list in June. Grouping it under March would say the
        debt had never been there.

        Args:
            household_id: The ID of the household.
            date_from: First day to include.
            date_to: First day to exclude, so the range is half open.

        Returns:
            The amount settled, against the first of each month that saw any.
        """
        month = func.cast(func.date_trunc("month", col(IncomeSession.paid_on)), Date)

        columns: list[Any] = [month.label("month"), func.coalesce(func.sum(col(IncomeSession.fee_minor)), 0)]
        statement: Any = (
            select(*columns)
            .where(
                col(IncomeSession.household_id) == household_id,
                col(IncomeSession.paid_on).is_not(None),
                col(IncomeSession.paid_on) >= date_from,
                col(IncomeSession.paid_on) < date_to,
                *_is_chargeable(),
            )
            .group_by(month)
        )

        return {row[0]: int(row[1]) for row in self.session.exec(statement).all()}

    def debt_before(self, household_id: uuid.UUID, on: datetime.date) -> int:
        """Sum what was still owed on the eve of a date.

        The opening balance a running debt line has to start from. Without it a
        window that begins mid-practice would show the debt starting at zero and
        climbing, when in truth it was already there.

        A session counts as owed on that date if the work was done before it and
        the money had not arrived yet — either it still has not, or it arrived
        later.

        Args:
            household_id: The ID of the household.
            on: The day to measure at, exclusive.

        Returns:
            The amount outstanding at that moment, in minor units.
        """
        statement = select(func.coalesce(func.sum(col(IncomeSession.fee_minor)), 0)).where(
            col(IncomeSession.household_id) == household_id,
            col(IncomeSession.occurs_on) < on,
            sa_or(col(IncomeSession.paid_on).is_(None), col(IncomeSession.paid_on) >= on),
            *_is_chargeable(),
        )
        return int(self.session.exec(statement).one())

    def booked_for_month(self, household_id: uuid.UUID, month: str) -> tuple[int, int]:
        """Sum the sessions already in the diary for a month.

        Only `SCHEDULED` rows count. A session already marked attended is
        history, not a booking, and adding it here would double count it
        against the month it is already in.

        A booking that has already been waived is left out, so this figure
        cannot promise money the estimate knows will never arrive.

        Args:
            household_id: The ID of the household.
            month: The month in "YYYY-MM" form.

        Returns:
            Tuple of (total_minor, session_count).
        """
        statement = select(
            func.coalesce(func.sum(col(IncomeSession.fee_minor)), 0),
            func.count(),
        ).where(
            col(IncomeSession.household_id) == household_id,
            col(IncomeSession.status) == IncomeSessionStatus.SCHEDULED,
            col(IncomeSession.occurs_on) >= month_start(month),
            col(IncomeSession.occurs_on) < next_month_start(month),
            *_is_billable(),
        )
        total, count = self.session.exec(statement).one()
        return int(total), count

    def earned_for_range(
        self,
        household_id: uuid.UUID,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> tuple[int, int]:
        """Sum the chargeable work done in a span of dates.

        Grouped by nothing at all, unlike `monthly_totals`: the caller wants one
        figure for the whole span, and asking for twelve rows to add up would be
        the same query wearing a disguise.

        Args:
            household_id: The ID of the household.
            date_from: First day to include.
            date_to: First day to exclude, so the range is half open.

        Returns:
            Tuple of (earned_minor, session_count).
        """
        statement = select(
            func.coalesce(func.sum(col(IncomeSession.fee_minor)), 0),
            func.count(),
        ).where(
            col(IncomeSession.household_id) == household_id,
            col(IncomeSession.occurs_on) >= date_from,
            col(IncomeSession.occurs_on) < date_to,
            *_is_chargeable(),
        )
        total, count = self.session.exec(statement).one()
        return int(total), count

    def outstanding_for_household(self, household_id: uuid.UUID) -> tuple[int, int, datetime.date | None]:
        """Sum everything the household is still owed, across every month.

        Deliberately not scoped to a month. A debt from March is still a debt in
        September, and a figure that reset each month would quietly hide the
        ones actually worth chasing.

        Args:
            household_id: The ID of the household.

        Returns:
            Tuple of (total_minor, session_count, oldest_unpaid_on).
        """
        statement = select(
            func.coalesce(func.sum(col(IncomeSession.fee_minor)), 0),
            func.count(),
            func.min(col(IncomeSession.occurs_on)),
        ).where(
            col(IncomeSession.household_id) == household_id,
            col(IncomeSession.payment_status) == PaymentStatus.PENDING,
            col(IncomeSession.status).in_(_WORKED_STATUSES),
            col(IncomeSession.fee_minor) > 0,
        )
        total, count, oldest = self.session.exec(statement).one()
        return int(total), count, oldest

    def client_tallies(
        self,
        household_id: uuid.UUID,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> Sequence[ClientTallyRow]:
        """Aggregate sessions per client over a window.

        The outstanding figures are deliberately *not* limited to the window:
        what somebody owes is owed whenever the hour was, and a debtors list
        that forgot anything older than six months would be the wrong list.

        Args:
            household_id: The ID of the household.
            date_from: First day of the window.
            date_to: First day after the window.

        Returns:
            One row per client that has any session at all.
        """
        chargeable = _is_chargeable()
        in_window = (
            col(IncomeSession.occurs_on) >= date_from,
            col(IncomeSession.occurs_on) < date_to,
        )
        owed = sa_and(*chargeable, col(IncomeSession.payment_status) == PaymentStatus.PENDING)

        # The order here is the order ClientTallyRow unpacks below.
        columns: list[Any] = [
            col(IncomeSession.client_id),
            func.count(case((sa_and(col(IncomeSession.status) == IncomeSessionStatus.ATTENDED, *in_window), 1))),
            func.count(case((sa_and(col(IncomeSession.status) == IncomeSessionStatus.MISSED, *in_window), 1))),
            func.count(case((sa_and(col(IncomeSession.status) == IncomeSessionStatus.CANCELLED, *in_window), 1))),
            func.coalesce(
                func.sum(case((sa_and(*chargeable, *in_window), col(IncomeSession.fee_minor)), else_=0)),
                0,
            ),
            func.coalesce(func.sum(case((owed, col(IncomeSession.fee_minor)), else_=0)), 0),
            func.min(case((owed, col(IncomeSession.occurs_on)))),
            func.max(
                case(
                    (
                        col(IncomeSession.status).in_(_WORKED_STATUSES),
                        col(IncomeSession.occurs_on),
                    )
                )
            ),
        ]

        statement: Any = (
            select(*columns)
            .where(col(IncomeSession.household_id) == household_id)
            .group_by(col(IncomeSession.client_id))
        )

        return [
            ClientTallyRow(
                client_id=row[0],
                attended_count=row[1],
                missed_count=row[2],
                cancelled_count=row[3],
                earned_minor=int(row[4]),
                outstanding_minor=int(row[5]),
                oldest_unpaid_on=row[6],
                last_session_on=row[7],
            )
            for row in self.session.exec(statement).all()
        ]

    def for_month(self, household_id: uuid.UUID, month: str) -> Sequence[IncomeSession]:
        """List every session recorded against a month, whatever its state.

        The forecast needs the whole month rather than a filtered slice: the
        booked ones are the appointments it prices, and the rest are the days a
        client's schedule must not be allowed to project a second session onto.

        Args:
            household_id: The ID of the household.
            month: The month in "YYYY-MM" form.

        Returns:
            Every session dated in that month.
        """
        statement = select(IncomeSession).where(
            col(IncomeSession.household_id) == household_id,
            col(IncomeSession.occurs_on) >= month_start(month),
            col(IncomeSession.occurs_on) < next_month_start(month),
        )
        return self.session.exec(statement).all()

    def new_client_monthly(
        self,
        household_id: uuid.UUID,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> Sequence[NewClientMonthRow]:
        """Aggregate, per month, the work brought by clients seen for the first time.

        A client belongs to the month of their earliest session ever, which is
        taken over all of time rather than over the window: somebody first seen
        two years ago is not a new arrival just because the window starts after
        them.

        Args:
            household_id: The ID of the household.
            date_from: First day to include.
            date_to: First day to exclude, so the range is half open.

        Returns:
            One row per month that saw a new client, oldest first.
        """
        started = (
            select(
                col(IncomeSession.client_id).label("client_id"),
                func.min(col(IncomeSession.occurs_on)).label("started_on"),
            )
            .where(col(IncomeSession.household_id) == household_id)
            .group_by(col(IncomeSession.client_id))
            .subquery()
        )

        month = func.cast(func.date_trunc("month", col(IncomeSession.occurs_on)), Date)
        first_month = func.cast(func.date_trunc("month", started.c.started_on), Date)

        columns: list[Any] = [
            month.label("month"),
            func.count(),
            func.coalesce(func.sum(col(IncomeSession.fee_minor)), 0),
        ]

        statement: Any = (
            select(*columns)
            .join(started, started.c.client_id == col(IncomeSession.client_id))
            .where(
                col(IncomeSession.household_id) == household_id,
                col(IncomeSession.occurs_on) >= date_from,
                col(IncomeSession.occurs_on) < date_to,
                first_month == month,
                *_is_chargeable(),
            )
            .group_by(month)
            .order_by(month)
        )

        return [
            NewClientMonthRow(month=row[0], session_count=row[1], earned_minor=int(row[2]))
            for row in self.session.exec(statement).all()
        ]

    def _conditions(self, household_id: uuid.UUID, filters: IncomeSessionFilters) -> list[Any]:
        """Build the WHERE clause for a session listing.

        Args:
            household_id: The ID of the household.
            filters: The filters to apply.

        Returns:
            The conditions to apply.
        """
        conditions: list[Any] = [col(IncomeSession.household_id) == household_id]

        if filters.client_id is not None:
            conditions.append(col(IncomeSession.client_id) == filters.client_id)

        # `month` is shorthand for the two dates, and it wins over them: a
        # caller sending both has contradicted itself, and the narrower, more
        # explicit intent is the one to honour.
        if filters.month is not None:
            conditions.append(col(IncomeSession.occurs_on) >= month_start(filters.month))
            conditions.append(col(IncomeSession.occurs_on) < next_month_start(filters.month))
        else:
            if filters.date_from is not None:
                conditions.append(col(IncomeSession.occurs_on) >= filters.date_from)
            if filters.date_to is not None:
                conditions.append(col(IncomeSession.occurs_on) <= filters.date_to)

        if filters.status is not None:
            conditions.append(col(IncomeSession.status) == filters.status)

        if filters.payment_status is not None:
            conditions.append(col(IncomeSession.payment_status) == filters.payment_status)

        # The same definition the "owed to you" total uses, so the list and the
        # figure above it can never disagree.
        if filters.owed_only:
            conditions.extend(_is_chargeable())

        return conditions

    @staticmethod
    def _ordering(sort: IncomeSessionSort) -> list[Any]:
        """Build the ORDER BY clause for a session listing.

        The ID is the tie break, so a page boundary in the middle of a busy day
        cannot show the same session twice or skip one.

        Args:
            sort: The requested order.

        Returns:
            The ordering to apply.
        """
        if sort is IncomeSessionSort.DATE_ASC:
            return [col(IncomeSession.occurs_on).asc(), col(IncomeSession.id).asc()]
        return [col(IncomeSession.occurs_on).desc(), col(IncomeSession.id).desc()]
