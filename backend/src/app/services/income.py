import datetime
import uuid
from collections.abc import Sequence
from fractions import Fraction

from sqlmodel import Session

from app.exceptions import (
    AccountArchivedError,
    AccountNotFoundError,
    CategoryNotFoundError,
    ClientCadenceError,
    IncomeClientInUseError,
    IncomeClientNotFoundError,
    IncomeClientNotOwnedError,
    IncomeSessionNotFoundError,
    IncomeVaultNotFoundError,
    SessionPaymentDateError,
    TransactionCategoryKindError,
)
from app.models import (
    Account,
    Category,
    CategoryKind,
    ClientForecastRow,
    ForecastBasis,
    HouseholdContext,
    IncomeClient,
    IncomeClientCreate,
    IncomeClientFilters,
    IncomeClientPublic,
    IncomeClientsPublic,
    IncomeClientUpdate,
    IncomeForecast,
    IncomeMonth,
    IncomeSession,
    IncomeSessionCreate,
    IncomeSessionFilters,
    IncomeSessionPublic,
    IncomeSessionsPublic,
    IncomeSessionStatus,
    IncomeSessionUpdate,
    IncomeSummary,
    IncomeVault,
    IncomeVaultPublic,
    IncomeVaultUpsert,
    Message,
    PaymentStatus,
    RecurrenceFrequency,
    Transaction,
    TransactionKind,
)
from app.models.fields import month_bounds, month_key_of, month_start, next_month_start
from app.repositories.account import AccountRepository
from app.repositories.category import CategoryRepository
from app.repositories.household import HouseholdRepository
from app.repositories.income import (
    IncomeClientRepository,
    IncomeSessionRepository,
    IncomeVaultRepository,
)
from app.repositories.transaction import TransactionRepository
from app.services.cadence import expand, normalise_weekdays
from app.services.income_forecast import (
    CONFIDENCE_PERCENT,
    DEFAULT_HISTORY_MONTHS,
    MAX_HISTORY_MONTHS,
    MIN_HISTORY_MONTHS,
    ForecastBand,
    Trial,
    expected_lifetime_months,
    history_band,
    house_rate,
    session_band,
    shrunk_rate,
    survival,
)

# The statuses that mean the hour was worked. A no-show belongs here because it
# can still carry a late cancellation fee, and a fee that was charged is money
# earned whether or not anybody turned up.
_WORKED_STATUSES = (IncomeSessionStatus.ATTENDED, IncomeSessionStatus.MISSED)

# A ceiling on the roster the forecast walks. A practice with more clients than
# this has outgrown a single page of arithmetic, and an unbounded read here
# would be the one query on the page that could not be reasoned about.
_MAX_CLIENTS = 200


class IncomeService:
    """Provide services for a freelance practice: clients, sessions and payments.

    Two rules shape every method here.

    **A session reaches the ledger exactly when it has been paid.** Whether the
    client turned up says what was earned; whether they paid says what is
    actually there. Only the second is money, so only the second becomes a
    transaction, and an attended session nobody has settled is a debt this
    service reports rather than income it invents.

    **A client belongs to the person who added them.** The household shares the
    sessions, the fees and the income, because that is household money. It does
    not share the names: those are encrypted under one person's key, so a
    household member sees the row and the figures with the name blanked out, and
    only the owner can edit or remove the client.
    """

    def __init__(
        self,
        session: Session,
        income_client_repository: IncomeClientRepository,
        income_session_repository: IncomeSessionRepository,
        income_vault_repository: IncomeVaultRepository,
        transaction_repository: TransactionRepository,
        account_repository: AccountRepository,
        category_repository: CategoryRepository,
        household_repository: HouseholdRepository,
    ) -> None:
        """Initialize the income service.

        Args:
            session: The database session.
            income_client_repository: The client repository instance.
            income_session_repository: The session repository instance.
            income_vault_repository: The vault repository instance.
            transaction_repository: The transaction repository instance, used to
                write the ledger row a paid session produces.
            account_repository: The account repository instance.
            category_repository: The category repository instance.
            household_repository: The household repository instance, used for
                the currency and the ledger label.
        """
        self.session = session
        self.income_client_repository = income_client_repository
        self.income_session_repository = income_session_repository
        self.income_vault_repository = income_vault_repository
        self.transaction_repository = transaction_repository
        self.account_repository = account_repository
        self.category_repository = category_repository
        self.household_repository = household_repository

    # ----------------------------------------------------------------- vault

    def get_vault(self, household: HouseholdContext) -> IncomeVaultPublic:
        """Get the key material the browser needs to unlock this user's names.

        Args:
            household: The household context, which carries the current user.

        Returns:
            The vault.

        Raises:
            IncomeVaultNotFoundError: If this user has set up no PIN yet.
        """
        vault = self.income_vault_repository.get_for_user(household.user_id)

        if not vault:
            raise IncomeVaultNotFoundError from None

        return IncomeVaultPublic.model_validate(vault)

    def upsert_vault(self, household: HouseholdContext, vault_upsert: IncomeVaultUpsert) -> IncomeVaultPublic:
        """Set up the PIN, or re-wrap the same key under a new one.

        Changing a PIN rewrites this row and nothing else. The names were
        encrypted with the data key, not with the PIN, so re-wrapping that key
        leaves every client row exactly as it was.

        This is the current user's PIN alone. Another member of the household
        has their own, and it opens their own clients.

        Args:
            household: The household context, which carries the current user.
            vault_upsert: The key material, all of it opaque to this service.

        Returns:
            The stored vault.
        """
        vault = self.income_vault_repository.get_for_user(household.user_id)

        if vault is None:
            vault = IncomeVault.model_validate(vault_upsert, update={"user_id": household.user_id})
        else:
            vault.sqlmodel_update(vault_upsert.model_dump())

        self.income_vault_repository.save(vault)
        self.session.commit()

        return IncomeVaultPublic.model_validate(vault)

    def reset_vault(self, household: HouseholdContext) -> Message:
        """Forget the key, and with it every client name.

        Destructive and deliberately so. Without the key the stored names are
        unreadable ciphertext, so leaving them behind would be leaving rubbish
        that no future PIN could ever decode. Blanking them is what makes the
        page usable again: every fee, session and euro survives, and the names
        have to be typed in afresh.

        Only this user's own clients are touched. Another member's names are
        under another key and are none of this reset's business.

        Args:
            household: The household context, which carries the current user.

        Returns:
            A confirmation message.
        """
        self.income_client_repository.blank_names_for_owner(
            household_id=household.household_id, owner_user_id=household.user_id
        )

        vault = self.income_vault_repository.get_for_user(household.user_id)
        if vault is not None:
            self.income_vault_repository.delete(vault)

        self.session.commit()

        return Message(message="Your client name key was reset. Your names have to be entered again.")

    # --------------------------------------------------------------- clients

    def create_client(self, household: HouseholdContext, client_create: IncomeClientCreate) -> IncomeClientPublic:
        """Add a client.

        The name arrives already encrypted and is stored as it came. Nothing in
        this service can read it, which is the point.

        Args:
            household: The household context.
            client_create: The client to add.

        Returns:
            The added client.

        Raises:
            ClientCadenceError: If the schedule is only half described.
            AccountNotFoundError: If the account does not exist in the household.
            AccountArchivedError: If the account is archived.
            CategoryNotFoundError: If the category does not exist in the household.
            TransactionCategoryKindError: If the category is not an income category.
        """
        self._check_cadence(
            frequency=client_create.cadence_frequency,
            anchor_on=client_create.cadence_anchor_on,
            weekdays=client_create.cadence_weekdays,
        )
        self._resolve_account(household=household, account_id=client_create.default_account_id)

        if client_create.default_category_id is not None:
            self._resolve_income_category(household=household, category_id=client_create.default_category_id)

        client = IncomeClient.model_validate(
            client_create,
            update={
                "household_id": household.household_id,
                "owner_user_id": household.user_id,
                # Sorted and deduplicated on the way in, so two clients seen on
                # the same days are stored the same way whatever order the days
                # were clicked in.
                "cadence_weekdays": normalise_weekdays(client_create.cadence_weekdays),
            },
        )
        self.income_client_repository.save(client)
        self.session.commit()

        return IncomeClientPublic.model_validate(client)

    def list_clients(self, household: HouseholdContext, filters: IncomeClientFilters) -> IncomeClientsPublic:
        """List the clients of a household.

        Args:
            household: The household context.
            filters: The filters to apply.

        Returns:
            The matching clients, still with their names encrypted.
        """
        clients, count = self.income_client_repository.list_for_household(
            household_id=household.household_id, filters=filters
        )

        return IncomeClientsPublic(
            data=[IncomeClientPublic.model_validate(client) for client in clients],
            count=count,
        )

    def get_client(self, household: HouseholdContext, client_id: uuid.UUID) -> IncomeClientPublic:
        """Get one client.

        Args:
            household: The household context.
            client_id: The ID of the client.

        Returns:
            The client.

        Raises:
            IncomeClientNotFoundError: If the client does not exist in the household.
        """
        return IncomeClientPublic.model_validate(self._require_client(household=household, client_id=client_id))

    def update_client(
        self,
        household: HouseholdContext,
        client_id: uuid.UUID,
        client_update: IncomeClientUpdate,
    ) -> IncomeClientPublic:
        """Edit a client.

        Changing the account or the category does not touch the transactions
        past sessions already produced. Those recorded where the money actually
        went, and rewriting them now would be inventing a history that did not
        happen.

        Args:
            household: The household context.
            client_id: The ID of the client to edit.
            client_update: The fields to change.

        Returns:
            The updated client.

        Raises:
            IncomeClientNotFoundError: If the client does not exist in the household.
            IncomeClientNotOwnedError: If the client belongs to another member.
            ClientCadenceError: If the schedule is only half described.
            AccountNotFoundError: If the account does not exist in the household.
            AccountArchivedError: If the account is archived.
            CategoryNotFoundError: If the category does not exist in the household.
            TransactionCategoryKindError: If the category is not an income category.
        """
        client = self._require_own_client(household=household, client_id=client_id)
        fields = client_update.model_dump(exclude_unset=True)

        # Read against the row, not the request: changing only the frequency
        # has to be checked against the anchor already stored.
        self._check_cadence(
            frequency=fields.get("cadence_frequency", client.cadence_frequency),
            anchor_on=fields.get("cadence_anchor_on", client.cadence_anchor_on),
            weekdays=fields.get("cadence_weekdays", client.cadence_weekdays),
        )

        if "cadence_weekdays" in fields:
            fields["cadence_weekdays"] = normalise_weekdays(fields["cadence_weekdays"])

        if fields.get("default_account_id") is not None:
            self._resolve_account(household=household, account_id=fields["default_account_id"])

        if fields.get("default_category_id") is not None:
            self._resolve_income_category(household=household, category_id=fields["default_category_id"])

        is_archived = fields.pop("is_archived", None)
        if is_archived is not None:
            client.archived_at = datetime.datetime.now(datetime.UTC) if is_archived else None

        client.sqlmodel_update(fields)
        self.income_client_repository.save(client)
        self.session.commit()

        return IncomeClientPublic.model_validate(client)

    def delete_client(self, household: HouseholdContext, client_id: uuid.UUID) -> Message:
        """Delete a client who has no sessions.

        A client with sessions is refused rather than cascaded. Those sessions
        are the record of work that was done and money that was taken, and
        removing them to tidy up a list would be destroying the evidence for a
        tax return. Archiving is the way to stop seeing somebody.

        Args:
            household: The household context.
            client_id: The ID of the client to delete.

        Returns:
            A confirmation message.

        Raises:
            IncomeClientNotFoundError: If the client does not exist in the household.
            IncomeClientNotOwnedError: If the client belongs to another member.
            IncomeClientInUseError: If the client still has sessions.
        """
        client = self._require_own_client(household=household, client_id=client_id)

        if self.income_session_repository.count_for_client(client_id=client_id, household_id=household.household_id):
            raise IncomeClientInUseError from None

        self.income_client_repository.delete(client)
        self.session.commit()

        return Message(message="Client deleted.")

    # -------------------------------------------------------------- sessions

    def create_session(self, household: HouseholdContext, session_create: IncomeSessionCreate) -> IncomeSessionPublic:
        """Record a session.

        Args:
            household: The household context.
            session_create: The session to record.

        Returns:
            The recorded session.

        Raises:
            IncomeClientNotFoundError: If the client does not exist in the household.
            SessionPaymentDateError: If the payment date and status disagree.
            AccountArchivedError: If the client's account is archived.
        """
        client = self._require_client(household=household, client_id=session_create.client_id)
        self._check_payment_shape(payment_status=session_create.payment_status, paid_on=session_create.paid_on)

        income_session = IncomeSession.model_validate(
            session_create,
            update={"household_id": household.household_id, "created_by_user_id": household.user_id},
        )
        self.income_session_repository.save(income_session)
        self._sync_transaction(household=household, income_session=income_session, client=client)
        self.session.commit()

        return IncomeSessionPublic.model_validate(income_session)

    def list_sessions(self, household: HouseholdContext, filters: IncomeSessionFilters) -> IncomeSessionsPublic:
        """List the sessions of a household matching a set of filters.

        Args:
            household: The household context.
            filters: The filters to apply.

        Returns:
            The matching sessions, with the totals the table footer needs.
        """
        sessions, count, earned, outstanding = self.income_session_repository.list_for_household(
            household_id=household.household_id, filters=filters
        )

        return IncomeSessionsPublic(
            data=[IncomeSessionPublic.model_validate(row) for row in sessions],
            count=count,
            earned_total_minor=earned,
            outstanding_total_minor=outstanding,
        )

    def get_session(self, household: HouseholdContext, session_id: uuid.UUID) -> IncomeSessionPublic:
        """Get one session.

        Args:
            household: The household context.
            session_id: The ID of the session.

        Returns:
            The session.

        Raises:
            IncomeSessionNotFoundError: If the session does not exist in the household.
        """
        return IncomeSessionPublic.model_validate(self._require_session(household=household, session_id=session_id))

    def update_session(
        self,
        household: HouseholdContext,
        session_id: uuid.UUID,
        session_update: IncomeSessionUpdate,
    ) -> IncomeSessionPublic:
        """Edit a session, including marking it attended, missed or paid.

        There is no separate endpoint for a status change. A status is a field
        like any other, and one state machine behind one method is one fewer
        place for the ledger and the diary to disagree.

        Args:
            household: The household context.
            session_id: The ID of the session to edit.
            session_update: The fields to change.

        Returns:
            The updated session.

        Raises:
            IncomeSessionNotFoundError: If the session does not exist in the household.
            IncomeClientNotFoundError: If the new client does not exist in the household.
            SessionPaymentDateError: If the payment date and status disagree.
            AccountArchivedError: If the client's account is archived.
        """
        income_session = self._require_session(household=household, session_id=session_id)
        fields = session_update.model_dump(exclude_unset=True)

        payment_status = fields.get("payment_status", income_session.payment_status)
        # `paid_on` has to be read out of the update rather than defaulted from
        # the row, because clearing it is a legitimate change and an unset field
        # is not the same as one explicitly set to None.
        paid_on = fields["paid_on"] if "paid_on" in fields else income_session.paid_on

        # Marking a session paid without saying when is the common case from a
        # one-click "mark paid" button, so it is filled in rather than refused:
        # the hour's own date is the only sensible guess, and it is editable.
        if payment_status is PaymentStatus.PAID and paid_on is None:
            paid_on = fields.get("occurs_on", income_session.occurs_on)
        # Moving off paid clears the date, so the two can never contradict.
        elif payment_status is not PaymentStatus.PAID:
            paid_on = None

        fields["paid_on"] = paid_on
        self._check_payment_shape(payment_status=payment_status, paid_on=paid_on)

        client_id = fields.get("client_id", income_session.client_id)
        client = self._require_client(household=household, client_id=client_id)

        income_session.sqlmodel_update(fields)
        self.income_session_repository.save(income_session)
        self._sync_transaction(household=household, income_session=income_session, client=client)
        self.session.commit()

        return IncomeSessionPublic.model_validate(income_session)

    def delete_session(self, household: HouseholdContext, session_id: uuid.UUID) -> Message:
        """Delete a session, and the ledger row it produced.

        The session is the source of truth for this money, so the transaction
        goes with it. Leaving the transaction behind would leave income in the
        ledger that nothing in the app could explain or edit.

        Args:
            household: The household context.
            session_id: The ID of the session to delete.

        Returns:
            A confirmation message.

        Raises:
            IncomeSessionNotFoundError: If the session does not exist in the household.
        """
        income_session = self._require_session(household=household, session_id=session_id)

        transaction = self.transaction_repository.get_for_income_session(
            session_id=income_session.id, household_id=household.household_id
        )
        if transaction is not None:
            self.transaction_repository.delete(transaction)

        self.income_session_repository.delete(income_session)
        self.session.commit()

        return Message(message="Session deleted.")

    # ------------------------------------------------------------- reporting

    def get_summary(self, household: HouseholdContext, month: str | None = None) -> IncomeSummary:
        """Get the figures for one month, plus what is owed across all of them.

        Args:
            household: The household context.
            month: The month in "YYYY-MM" form. Defaults to the current one.

        Returns:
            The summary.
        """
        month = month or month_key_of(datetime.date.today())
        rows = self.income_session_repository.monthly_totals(
            household_id=household.household_id,
            date_from=month_start(month),
            date_to=next_month_start(month),
        )
        row = rows[0] if rows else None

        booked_minor, booked_count = self.income_session_repository.booked_for_month(
            household_id=household.household_id, month=month
        )
        total_outstanding, unpaid_count, oldest_unpaid = self.income_session_repository.outstanding_for_household(
            household.household_id
        )

        # The calendar year the month sits in, not the twelve months before it.
        # A year is a thing with a start, and it is the one a tax return asks
        # about; a rolling window would answer a question nobody asked.
        year = month_start(month).year
        year_earned, year_sessions = self.income_session_repository.earned_for_range(
            household_id=household.household_id,
            date_from=datetime.date(year, 1, 1),
            date_to=datetime.date(year + 1, 1, 1),
        )

        return IncomeSummary(
            month=month,
            currency_code=self._currency_of(household),
            earned_minor=row.earned_minor if row else 0,
            received_minor=row.received_minor if row else 0,
            outstanding_minor=(row.earned_minor - row.received_minor) if row else 0,
            total_outstanding_minor=total_outstanding,
            oldest_unpaid_on=oldest_unpaid,
            attended_count=row.attended_count if row else 0,
            unpaid_count=unpaid_count,
            scheduled_minor=booked_minor,
            scheduled_count=booked_count,
            missed_count=row.missed_count if row else 0,
            cancelled_count=row.cancelled_count if row else 0,
            active_client_count=self.income_client_repository.count_active_for_household(household.household_id),
            year=year,
            year_earned_minor=year_earned,
            year_session_count=year_sessions,
        )

    def get_forecast(
        self,
        household: HouseholdContext,
        month: str | None = None,
        months: int = DEFAULT_HISTORY_MONTHS,
    ) -> IncomeForecast:
        """Estimate what a month will bring, from the complete months before it.

        Works for the month in progress as well as the one after it. History
        always stops at the month before the target and never includes the
        target itself: a month one week old is a fraction of itself, and
        including it would pull the average down in exactly the week the
        estimate is worth reading.

        What the month itself is known to hold is then layered on, and the two
        kinds of knowledge are kept apart. Work already done is certain, so it
        becomes a floor the estimate can never fall below. The diary is not
        certain — an appointment can be missed or called off — so it is
        discounted by how much of a diary has historically turned into work,
        and is only allowed to move the likely figure. For the month in
        progress the floor grows until the estimate has converged on the truth.

        Args:
            household: The household context.
            month: The month to forecast, in "YYYY-MM" form. Defaults to next.
            months: How many complete months of history to average over.

        Returns:
            The forecast, its band, and the history behind it.
        """
        months = max(1, min(months, MAX_HISTORY_MONTHS))
        today = datetime.date.today()
        target = month or month_key_of(next_month_start(month_key_of(today)))

        # The window ends at the last month that is both complete and before the
        # target, so a forecast asked for a month in the past is not built from
        # the months after it.
        history_end = min(month_start(target), month_start(month_key_of(today)))
        history_start = self._months_before(history_end, months)

        rows = self.income_session_repository.monthly_totals(
            household_id=household.household_id, date_from=history_start, date_to=history_end
        )
        by_month = {month_key_of(row.month): row for row in rows}

        # A running debt balance, which is a different question from what any
        # one month is owed. It rises with work that goes unpaid and falls when
        # somebody settles, so the line it draws answers "is this getting better
        # or worse" rather than "how much has gone unpaid, ever", which can only
        # ever climb.
        settled = self.income_session_repository.settled_monthly(
            household_id=household.household_id, date_from=history_start, date_to=history_end
        )
        # What was already owed before the window opened. Without it the line
        # would start at zero and climb out of a debt that was always there.
        owed = self.income_session_repository.debt_before(household_id=household.household_id, on=history_start)

        history: list[IncomeMonth] = []
        cursor = history_start
        while cursor < history_end:
            key = month_key_of(cursor)
            row = by_month.get(key)
            owed += (row.earned_minor if row else 0) - settled.get(cursor, 0)
            history.append(
                IncomeMonth(
                    month=key,
                    earned_minor=row.earned_minor if row else 0,
                    received_minor=row.received_minor if row else 0,
                    outstanding_minor=(row.earned_minor - row.received_minor) if row else 0,
                    attended_count=row.attended_count if row else 0,
                    missed_count=row.missed_count if row else 0,
                    cancelled_count=row.cancelled_count if row else 0,
                    unpaid_count=row.unpaid_count if row else 0,
                    client_count=row.client_count if row else 0,
                    # Never negative: a payment straddling the edge of the window
                    # must not be able to draw a debt that is owed to somebody.
                    owed_balance_minor=max(0, owed),
                )
            )
            cursor = next_month_start(key)

        booked_minor, booked_count = self.income_session_repository.booked_for_month(
            household_id=household.household_id, month=target
        )
        # What the target month has already earned. Zero for a month still to
        # come; the bulk of the answer for one nearly over. Disjoint from
        # `booked_minor`, which counts only sessions still scheduled, so the two
        # never describe the same hour.
        target_rows = self.income_session_repository.monthly_totals(
            household_id=household.household_id,
            date_from=month_start(target),
            date_to=next_month_start(target),
        )
        earned_so_far = target_rows[0].earned_minor if target_rows else 0

        # How much of a diary has historically become work, read from the same
        # window the rest of the estimate comes from. Each client is then priced
        # on their own record, blended towards this until they have one.
        went_ahead = sum(point.attended_count + point.missed_count for point in history)
        called_off = sum(point.cancelled_count for point in history)
        house = house_rate(went_ahead=went_ahead, called_off=called_off)

        # How often a client stops coming. Read from archived clients,
        # because archiving one is what saying "we finished" looks like here.
        # Kept apart from the cancellation rate on purpose: a client who has
        # finished is not a client who called off, and only one of the two takes
        # every future appointment with them.
        churn = self._churn(household=household, date_from=history_start, date_to=history_end, history=history)

        trials, priced_clients = self._trials(
            household=household,
            target_month=target,
            house=house,
            churn=churn,
            date_from=history_start,
            date_to=history_end,
        )
        new_rate, new_fee = self._new_client_rate(
            household=household, date_from=history_start, date_to=history_end, months=len(history)
        )

        band = self._band(
            trials=trials,
            new_rate=new_rate,
            new_fee=new_fee,
            earned_so_far=earned_so_far,
            history=history,
        )

        return IncomeForecast(
            month=target,
            currency_code=self._currency_of(household),
            likely_minor=band.likely_minor,
            low_minor=band.low_minor,
            high_minor=band.high_minor,
            basis=band.basis,
            months_used=band.months_used,
            history=history,
            booked_minor=booked_minor,
            booked_session_count=booked_count,
            earned_so_far_minor=earned_so_far,
            # Everything the estimate expects the rest of the month to add:
            # standing appointments, the diary, and the strangers who have not
            # rung up yet. Always the middle figure less what is already banked.
            expected_from_diary_minor=max(0, band.likely_minor - earned_so_far),
            # None rather than 1.0 when nothing was ever scheduled, so a
            # practice with no record is not shown a rate it did not earn.
            diary_realisation_rate=float(house) if (went_ahead + called_off) else None,
            trial_count=len(trials),
            expected_session_count=band.expected_sessions,
            new_client_session_rate=float(new_rate) if history else None,
            confidence_percent=CONFIDENCE_PERCENT,
            monthly_churn_rate=float(churn) if history else None,
            expected_client_months=expected_lifetime_months(churn),
            client_lifetime_value_minor=self._lifetime_value(churn=churn, history=history),
            average_sessions_per_month=self._average_sessions(history),
            # How much of the practice the estimate actually walked. The roster
            # read is capped, so a practice with more active clients than the
            # cap has the ones past it projecting nothing — while the booked
            # total, one aggregate over the whole month, counts them regardless.
            # Reporting both figures is what lets the page say so, instead of
            # leaving a number that simply reads low.
            active_client_count=self.income_client_repository.count_active_for_household(household.household_id),
            priced_client_count=priced_clients,
            clients=self._client_rows(
                household=household,
                date_from=history_start,
                date_to=history_end,
                months=max(1, band.months_used),
                target_month=target,
            ),
        )

    # --------------------------------------------------------------- helpers

    def _sync_transaction(
        self,
        household: HouseholdContext,
        income_session: IncomeSession,
        client: IncomeClient,
    ) -> None:
        """Make the ledger agree with the session, in the same transaction.

        The rule is one line and the status plays no part in it: a transaction
        exists exactly when the session has been paid and the fee is not zero.
        A late cancellation fee therefore books like any other payment, and a
        free session books like nothing at all, both without a special case.

        The row is dated `paid_on` rather than the day of the hour, because the
        ledger records when money moved and that is the date a bank statement
        would agree with.

        Args:
            household: The household context.
            income_session: The session, already updated.
            client: The client the session belongs to.

        Raises:
            AccountArchivedError: If the client's account is archived.
        """
        existing = self.transaction_repository.get_for_income_session(
            session_id=income_session.id, household_id=household.household_id
        )
        should_exist = income_session.payment_status is PaymentStatus.PAID and income_session.fee_minor > 0

        if not should_exist:
            if existing is not None:
                self.transaction_repository.delete(existing)
            return

        account = self._resolve_account(household=household, account_id=client.default_account_id)
        # The client's name must never appear here. It is encrypted precisely so
        # that the ledger cannot say who somebody's clients are, and a merchant
        # field is the most visible place in the app.
        label = self._session_label(household)

        if existing is not None:
            existing.sqlmodel_update(
                {
                    "amount_minor": income_session.fee_minor,
                    "occurred_on": income_session.paid_on,
                    "account_id": account.id,
                    "category_id": client.default_category_id,
                    "merchant": label,
                }
            )
            self.transaction_repository.save(existing)
            return

        transaction = Transaction(
            household_id=household.household_id,
            kind=TransactionKind.INCOME,
            amount_minor=income_session.fee_minor,
            occurred_on=income_session.paid_on,
            account_id=account.id,
            category_id=client.default_category_id,
            merchant=label,
            income_session_id=income_session.id,
            is_generated=True,
            created_by_user_id=household.user_id,
        )
        self.transaction_repository.save(transaction)

    def _check_cadence(
        self,
        frequency: RecurrenceFrequency | None,
        anchor_on: datetime.date | None,
        weekdays: Sequence[int] | None = None,
    ) -> None:
        """Check that a client's schedule is whole and means something.

        Args:
            frequency: How often the client is seen, if a pattern is set.
            anchor_on: The date the pattern is pinned to.
            weekdays: The days of the week it falls on, Monday as 0.

        Raises:
            ClientCadenceError: If the schedule is half described, or names
                days that are not days of the week, or names days for a
                schedule that is not weekly.
        """
        if (frequency is None) != (anchor_on is None):
            raise ClientCadenceError from None

        if not weekdays:
            return

        # Named days only mean something to a weekly schedule. Accepting them
        # elsewhere would store a preference that silently never applied.
        if frequency is not RecurrenceFrequency.WEEKLY:
            raise ClientCadenceError(
                "Days of the week can only be chosen for a schedule that repeats weekly."
            ) from None

        try:
            normalise_weekdays(weekdays)
        except ValueError as exc:
            raise ClientCadenceError(str(exc)) from None

    def _check_payment_shape(self, payment_status: PaymentStatus, paid_on: datetime.date | None) -> None:
        """Check that the payment date and the payment status agree.

        The database enforces the same rule, so this exists to turn it into a
        clear message rather than an integrity error.

        Args:
            payment_status: The payment state.
            paid_on: The date the money arrived, if any.

        Raises:
            SessionPaymentDateError: If the two disagree.
        """
        if payment_status is PaymentStatus.PAID and paid_on is None:
            raise SessionPaymentDateError("A paid session needs the date the money arrived.") from None

        if payment_status is not PaymentStatus.PAID and paid_on is not None:
            raise SessionPaymentDateError("A session that has not been paid cannot have a payment date.") from None

    def _band(
        self,
        trials: Sequence[Trial],
        new_rate: Fraction,
        new_fee: int,
        earned_so_far: int,
        history: list[IncomeMonth],
    ) -> ForecastBand:
        """Choose between counting the appointments and averaging the months.

        Counting wins whenever there is anything to count. It reads this
        month's actual roster, so it moves the moment a client is taken on or
        let go, where an average of past months would take half a year to
        notice. Averaging is the fallback for a practice that keeps no
        schedules and books nothing ahead, which would otherwise be told to
        expect nothing at all.

        Args:
            trials: The appointments the month holds.
            new_rate: Sessions per month from clients never seen before.
            new_fee: What one of those sessions has typically earned.
            earned_so_far: What the month has already earned.
            history: The complete months behind the rates.

        Returns:
            The band, from whichever estimator had something to work with.
        """
        if not trials and not new_rate:
            return history_band([point.earned_minor for point in history], earned_so_far_minor=earned_so_far)

        return session_band(
            trials=trials,
            new_session_rate=new_rate,
            new_session_fee_minor=new_fee,
            earned_so_far_minor=earned_so_far,
            months_used=len(history),
            basis=self._basis(len(history)),
        )

    @staticmethod
    def _basis(months: int) -> ForecastBasis:
        """Say how much history the rates behind an estimate were measured over.

        Args:
            months: How many complete months the window held.

        Returns:
            The basis to report.
        """
        if months >= MIN_HISTORY_MONTHS:
            return ForecastBasis.HISTORY

        return ForecastBasis.SINGLE_MONTH if months == 1 else ForecastBasis.INSUFFICIENT_HISTORY

    def _churn(
        self,
        household: HouseholdContext,
        date_from: datetime.date,
        date_to: datetime.date,
        history: list[IncomeMonth],
    ) -> Fraction:
        """Measure how much of a caseload stops coming in a month.

        Endings over caseload, both summed across the window rather than
        averaged month by month, so a quiet month with two clients on the books
        does not count for as much as a busy one with twenty.

        Args:
            household: The household context.
            date_from: First day of the history window.
            date_to: First day after the history window.
            history: The complete months in that window, for the caseload.

        Returns:
            The share of the caseload that stops coming in a month, 0 to 1.
            Zero when nobody has left yet, which reads as "no evidence" rather
            than as "nobody ever leaves".
        """
        caseload = sum(point.client_count for point in history)

        if caseload == 0:
            return Fraction(0)

        endings = self.income_client_repository.endings_monthly(
            household_id=household.household_id, date_from=date_from, date_to=date_to
        )
        # Cannot exceed one: a caseload cannot lose more clients than it has,
        # and a short window with an odd shape should not be able to say so.
        return min(Fraction(sum(endings.values()), caseload), Fraction(1))

    @staticmethod
    def _lifetime_value(churn: Fraction, history: list[IncomeMonth]) -> int | None:
        """What one client is worth over the whole time they are with you.

        The monthly fee a client brings, multiplied by how many months they
        typically stay. It is the figure that says whether it is worth the
        effort of taking somebody new on, which a monthly total never does.

        Args:
            churn: The share of the caseload that stops coming in a month.
            history: The complete months in the window.

        Returns:
            The value in minor units, or None when no client has left yet
            and there is therefore no lifetime to measure.
        """
        months = expected_lifetime_months(churn)
        caseload = sum(point.client_count for point in history)

        if months is None or caseload == 0:
            return None

        earned = sum(point.earned_minor for point in history)
        # Earned per client-month, which is what the lifetime is counted in.
        return int(months * earned / caseload)

    def _trials(
        self,
        household: HouseholdContext,
        target_month: str,
        house: Fraction,
        churn: Fraction,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> tuple[list[Trial], int]:
        """List every appointment the target month could hold, and price each one.

        Two sources, and the order between them matters. The diary comes first
        and wins: a session somebody actually entered carries its own fee, which
        may not be the client's usual one. A client's standing schedule then
        fills in the days the diary has not reached yet, at their usual rate.
        Any day that already carries a session of any kind is skipped, so an
        hour that has been worked, missed or called off can never be counted a
        second time as one still to come.

        Only the remainder of the month is projected. Yesterday's standing
        appointment either happened, in which case it is already earned, or it
        was never recorded, in which case inventing it now would be optimism.

        Every appointment is then discounted by the chance the client is still
        on the books when it comes round. That is what makes a schedule an
        estimate rather than a promise: a standing Monday appointment is worth
        less in the fourth week of next month than in the first, because
        they might have stopped coming in between.

        Args:
            household: The household context.
            target_month: The month being forecast, in "YYYY-MM" form.
            house: The practice-wide rate, for clients with no record of their own.
            churn: The share of a caseload that stops coming in a month.
            date_from: First day of the history window the rates come from.
            date_to: First day after that window.

        Returns:
            Tuple of (one trial per appointment, unordered; how many active
            clients the roster read returned). The second figure is what the
            page needs to say the estimate covers part of a practice: the read
            is capped, and a roster longer than the cap projects nothing for
            the clients past it.
        """
        # Two lookups, because the two groups are needed for different things
        # and must not compete for the same budget.
        #
        # The roster is the clients still being seen, capped, and it is the only
        # group whose schedule projects appointments.
        active, _ = self.income_client_repository.list_for_household(
            household_id=household.household_id,
            filters=IncomeClientFilters(is_archived=False, limit=_MAX_CLIENTS),
        )
        sessions = self.income_session_repository.for_month(household_id=household.household_id, month=target_month)

        # Then whoever the month's diary actually names. Somebody who has
        # stopped coming can still have an appointment left in it, and the
        # booked total counts that appointment, so leaving them unpriced would
        # show money booked for the month that the estimate ignores. Fetched by
        # id rather than by page: this set is the size of one month's diary, so
        # it cannot crowd the roster out the way sharing a page would.
        known = {client.id for client in active}
        extra = self.income_client_repository.list_by_ids(
            household_id=household.household_id,
            client_ids=[
                income_session.client_id for income_session in sessions if income_session.client_id not in known
            ],
        )
        clients = [*active, *extra]
        tallies = {
            tally.client_id: tally
            for tally in self.income_session_repository.client_tallies(
                household_id=household.household_id, date_from=date_from, date_to=date_to
            )
        }

        rates = {
            client.id: shrunk_rate(
                went_ahead=(tally.attended_count + tally.missed_count) if (tally := tallies.get(client.id)) else 0,
                called_off=tally.cancelled_count if tally else 0,
                house=house,
            )
            for client in clients
        }

        today = datetime.date.today()
        first_day, last_day = month_bounds(target_month)
        # Today itself is still ahead: an appointment this afternoon has not
        # been missed yet.
        window_from = max(first_day, today)
        # Whole months of waiting before the target month even begins. Each one
        # is a month in which a client might stop coming, so it compounds.
        months_ahead = max(0, (first_day.year * 12 + first_day.month) - (today.year * 12 + today.month))
        span = max(1, (last_day - window_from).days)

        def priced(client_id: uuid.UUID, fee_minor: int, day: datetime.date) -> Trial | None:
            """Price one appointment by who it is with and how far off it is.

            Args:
                client_id: The client the appointment is with.
                fee_minor: What the appointment is billed at, in minor units.
                day: The date the appointment falls on.

            Returns:
                The appointment as a trial, or None when the client has no attendance rate.
            """
            attends = rates.get(client_id)

            if attends is None:
                return None

            position = Fraction(max(0, (day - window_from).days), span)
            return Trial(fee_minor=fee_minor, rate=attends * survival(churn, months_ahead, position))

        taken: dict[uuid.UUID, set[datetime.date]] = {}
        trials: list[Trial] = []

        for income_session in sessions:
            taken.setdefault(income_session.client_id, set()).add(income_session.occurs_on)

            if (
                income_session.status is IncomeSessionStatus.SCHEDULED
                and income_session.fee_minor > 0
                # Already written off, so it is in the diary but not in the
                # money. The booked total leaves it out for the same reason.
                and income_session.payment_status is not PaymentStatus.WAIVED
            ):
                trial = priced(income_session.client_id, income_session.fee_minor, income_session.occurs_on)
                if trial is not None:
                    trials.append(trial)

        # The roster only. Nobody who has stopped coming gets a new appointment
        # projected for them; what is already in their diary is all they count.
        for client in active:
            if (
                client.cadence_frequency is None
                or client.cadence_anchor_on is None
                or client.default_rate_minor <= 0
                or window_from > last_day
            ):
                continue

            occupied = taken.get(client.id, set())

            for day in expand(
                frequency=client.cadence_frequency,
                interval=client.cadence_interval,
                anchor_on=client.cadence_anchor_on,
                date_from=window_from,
                date_to=last_day,
                weekdays=client.cadence_weekdays,
            ):
                trial = priced(client.id, client.default_rate_minor, day)

                if day not in occupied and trial is not None:
                    trials.append(trial)

        return trials, len(active)

    def _new_client_rate(
        self,
        household: HouseholdContext,
        date_from: datetime.date,
        date_to: datetime.date,
        months: int,
    ) -> tuple[Fraction, int]:
        """Work out how much work arrives each month from people never seen before.

        Nobody knows who will ring up next month, and no schedule can say. What
        the practice's own record can say is the rate they have been arriving
        at, and a rate is all a Poisson estimate needs.

        Args:
            household: The household context.
            date_from: First day of the history window.
            date_to: First day after the history window.
            months: How many complete months the window spans.

        Returns:
            Tuple of (sessions per month, the typical fee of one of them). Both
            zero when the window holds no history at all.
        """
        if months <= 0:
            return Fraction(0), 0

        rows = self.income_session_repository.new_client_monthly(
            household_id=household.household_id, date_from=date_from, date_to=date_to
        )
        count = sum(row.session_count for row in rows)

        if count == 0:
            return Fraction(0), 0

        earned = sum(row.earned_minor for row in rows)
        return Fraction(count, months), earned // count

    def _client_rows(
        self,
        household: HouseholdContext,
        date_from: datetime.date,
        date_to: datetime.date,
        months: int,
        target_month: str,
    ) -> list[ClientForecastRow]:
        """Build the per-client table behind the forecast.

        Args:
            household: The household context.
            date_from: First day of the history window.
            date_to: First day after the history window.
            months: How many months the window spans, for the monthly average.
            target_month: The month being forecast.

        Returns:
            One row per client, names still encrypted.
        """
        tallies = self.income_session_repository.client_tallies(
            household_id=household.household_id, date_from=date_from, date_to=date_to
        )
        # Fetched by id rather than by page. The table is exactly as long as
        # the window's tallies, so that is the bound it should carry; reading a
        # page of the roster instead would drop whoever fell past it while
        # their figures still counted towards the totals above the table.
        clients = self.income_client_repository.list_by_ids(
            household_id=household.household_id,
            client_ids=[tally.client_id for tally in tallies],
        )
        by_id = {client.id: client for client in clients}

        rows: list[ClientForecastRow] = []
        for tally in tallies:
            client = by_id.get(tally.client_id)
            if client is None:
                continue

            seen = tally.attended_count + tally.missed_count
            rows.append(
                ClientForecastRow(
                    client_id=tally.client_id,
                    name_ct=client.name_ct,
                    attended_count=tally.attended_count,
                    missed_count=tally.missed_count,
                    # None rather than zero when nothing has happened yet: a new
                    # client has not been unreliable, they are simply unknown.
                    attendance_rate=(tally.attended_count / seen) if seen else None,
                    outstanding_minor=tally.outstanding_minor,
                    oldest_unpaid_on=tally.oldest_unpaid_on,
                    average_monthly_minor=tally.earned_minor // months,
                    booked_minor=0,
                    last_session_on=tally.last_session_on,
                    is_archived=client.archived_at is not None,
                )
            )

        return rows

    @staticmethod
    def _average_sessions(history: list[IncomeMonth]) -> float | None:
        """Average how many hours were worked per month.

        Args:
            history: The complete months in the window.

        Returns:
            The average, or None when there is no history to average.
        """
        if not history:
            return None

        worked = sum(point.attended_count + point.missed_count for point in history)
        return worked / len(history)

    @staticmethod
    def _months_before(start: datetime.date, months: int) -> datetime.date:
        """Step back a number of whole months from the first of a month.

        Args:
            start: The first day of a month.
            months: How many months to step back.

        Returns:
            The first day of the month that many months earlier.
        """
        month_index = start.year * 12 + (start.month - 1) - months
        return datetime.date(month_index // 12, month_index % 12 + 1, 1)

    def _currency_of(self, household: HouseholdContext) -> str:
        """Get the household's currency.

        Args:
            household: The household context.

        Returns:
            The ISO 4217 code.
        """
        entity = self.household_repository.get_by_id(household.household_id)
        return entity.currency_code if entity else "EUR"

    def _session_label(self, household: HouseholdContext) -> str:
        """Get what a paid session is called in the ledger.

        Args:
            household: The household context.

        Returns:
            The household's label for a session.
        """
        entity = self.household_repository.get_by_id(household.household_id)
        return entity.session_merchant_label if entity else "Session"

    def _require_client(self, household: HouseholdContext, client_id: uuid.UUID) -> IncomeClient:
        """Load a client of the household.

        Args:
            household: The household context.
            client_id: The ID of the client.

        Returns:
            The client.

        Raises:
            IncomeClientNotFoundError: If the client does not exist in the household.
        """
        client = self.income_client_repository.get_for_household(
            entity_id=client_id, household_id=household.household_id
        )

        if not client:
            raise IncomeClientNotFoundError from None

        return client

    def _require_own_client(self, household: HouseholdContext, client_id: uuid.UUID) -> IncomeClient:
        """Load a client of the household and check the caller owns them.

        A member of the household who did not add this client can see the row
        and record sessions against it, because the money is shared. They cannot
        edit or remove it: the name is under somebody else's key, so saving from
        their screen would write a name they could not read over one they could
        not see.

        Args:
            household: The household context.
            client_id: The ID of the client.

        Returns:
            The client.

        Raises:
            IncomeClientNotFoundError: If the client does not exist in the household.
            IncomeClientNotOwnedError: If the client belongs to another member.
        """
        client = self._require_client(household=household, client_id=client_id)

        if client.owner_user_id != household.user_id:
            raise IncomeClientNotOwnedError from None

        return client

    def _require_session(self, household: HouseholdContext, session_id: uuid.UUID) -> IncomeSession:
        """Load a session of the household.

        Args:
            household: The household context.
            session_id: The ID of the session.

        Returns:
            The session.

        Raises:
            IncomeSessionNotFoundError: If the session does not exist in the household.
        """
        income_session = self.income_session_repository.get_for_household(
            entity_id=session_id, household_id=household.household_id
        )

        if not income_session:
            raise IncomeSessionNotFoundError from None

        return income_session

    def _resolve_account(self, household: HouseholdContext, account_id: uuid.UUID) -> Account:
        """Load an account of the household and check it is still open.

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

    def _resolve_income_category(self, household: HouseholdContext, category_id: uuid.UUID) -> Category:
        """Load a category of the household and check it is an income category.

        Checked when the client is saved, not when a payment is recorded, so a
        wrong category is a message in the dialog rather than a failure months
        later in the middle of marking somebody paid.

        Args:
            household: The household context.
            category_id: The ID of the category.

        Returns:
            The category.

        Raises:
            CategoryNotFoundError: If the category does not exist in the household.
            TransactionCategoryKindError: If the category is not an income category.
        """
        category = self.category_repository.get_for_household(
            entity_id=category_id, household_id=household.household_id
        )

        if not category:
            raise CategoryNotFoundError from None

        if category.kind is not CategoryKind.INCOME:
            raise TransactionCategoryKindError from None

        return category
