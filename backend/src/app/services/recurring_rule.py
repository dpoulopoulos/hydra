import datetime
import uuid

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.exceptions import (
    AccountArchivedError,
    AccountNotFoundError,
    InvalidRecurrenceError,
    RecurringRuleNotFoundError,
)
from app.models import (
    RULE_OCCURRENCE_INDEX,
    HouseholdContext,
    Message,
    RecurringRule,
    RecurringRuleCreate,
    RecurringRulePublic,
    RecurringRulesPublic,
    RecurringRuleUpdate,
    RecurringRunResult,
    Transaction,
    TransactionKind,
    UpcomingOccurrence,
    UpcomingOccurrencesPublic,
)
from app.repositories.recurring_rule import RecurringRuleRepository
from app.repositories.transaction import TransactionRepository
from app.services.ledger import LedgerReferenceResolver
from app.services.recurrence import (
    MAX_OCCURRENCES_PER_RUN,
    advance,
    first_occurrence,
    occurrences_until,
)

# How far ahead the upcoming list looks when no date is given.
DEFAULT_UPCOMING_DAYS = 60


def _signed_minor(occurrence: UpcomingOccurrence) -> int:
    """Read an occurrence as the change it makes to what the household holds.

    A stored amount is a positive magnitude and the meaning lives in the kind,
    so a total that ignores the kind is not a quantity. A transfer contributes
    nothing: it moves money between the household's own accounts.

    Args:
        occurrence: The projected occurrence to read.

    Returns:
        The signed amount, in minor units.
    """
    if occurrence.kind is TransactionKind.TRANSFER:
        return 0

    if occurrence.kind is TransactionKind.INCOME:
        return occurrence.amount_minor

    return -occurrence.amount_minor


class RecurringRuleService:
    """Provide services for recurring transactions."""

    def __init__(
        self,
        session: Session,
        recurring_rule_repository: RecurringRuleRepository,
        transaction_repository: TransactionRepository,
        reference_resolver: LedgerReferenceResolver,
    ) -> None:
        """Initialize the recurring rule service.

        Args:
            session: The database session.
            recurring_rule_repository: The recurring rule repository instance.
            transaction_repository: The transaction repository instance.
            reference_resolver: The resolver for the accounts and category a rule points at.
        """
        self.session = session
        self.recurring_rule_repository = recurring_rule_repository
        self.transaction_repository = transaction_repository
        self.reference_resolver = reference_resolver

    def create_rule(self, household: HouseholdContext, rule_create: RecurringRuleCreate) -> RecurringRulePublic:
        """Create a recurring rule, such as rent or a subscription.

        Args:
            household: The household context.
            rule_create: The rule to create.

        Returns:
            The created rule, with the date it first falls due.

        Raises:
            AccountNotFoundError: If an account does not exist in the household.
            AccountArchivedError: If an account is archived.
            CategoryNotFoundError: If the category does not exist in the household.
            SameAccountTransferError: If a transfer rule names the same account twice.
            TransferShapeError: If the rule does not match its kind.
            TransactionCategoryKindError: If the category is the wrong kind.
            InvalidRecurrenceError: If the schedule would never come due.
        """
        self.reference_resolver.resolve(
            household=household,
            kind=rule_create.kind,
            account_id=rule_create.account_id,
            counter_account_id=rule_create.counter_account_id,
            category_id=rule_create.category_id,
        )
        self._validate_schedule(start_date=rule_create.start_date, end_date=rule_create.end_date)

        cursor = first_occurrence(
            start_date=rule_create.start_date,
            frequency=rule_create.frequency,
            day_of_month=rule_create.day_of_month,
        )

        if cursor is None:
            raise InvalidRecurrenceError(
                "This rule would never come due: its first occurrence falls past the end of the calendar."
            ) from None

        if rule_create.end_date and cursor > rule_create.end_date:
            raise InvalidRecurrenceError(
                "This rule would never come due: it ends before its first occurrence."
            ) from None

        rule = RecurringRule.model_validate(
            rule_create,
            update={"household_id": household.household_id, "next_occurrence_on": cursor},
        )
        self.recurring_rule_repository.save(rule)
        self.session.commit()

        return RecurringRulePublic.model_validate(rule)

    def list_rules(
        self,
        household: HouseholdContext,
        is_active: bool | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> RecurringRulesPublic:
        """List the recurring rules of the household.

        Args:
            household: The household context.
            is_active: An optional active state to filter on.
            skip: Number of records to skip.
            limit: Maximum number of records to return.

        Returns:
            The rules, soonest due first.
        """
        rules, count = self.recurring_rule_repository.list_for_household(
            household_id=household.household_id, is_active=is_active, skip=skip, limit=limit
        )
        data = [RecurringRulePublic.model_validate(rule) for rule in rules]

        return RecurringRulesPublic(data=data, count=count)

    def get_rule(self, household: HouseholdContext, rule_id: uuid.UUID) -> RecurringRulePublic:
        """Get one recurring rule of the household.

        Args:
            household: The household context.
            rule_id: The ID of the rule.

        Returns:
            The rule.

        Raises:
            RecurringRuleNotFoundError: If the rule does not exist in the household.
        """
        return RecurringRulePublic.model_validate(self._require_rule(household=household, rule_id=rule_id))

    def update_rule(
        self, household: HouseholdContext, rule_id: uuid.UUID, rule_update: RecurringRuleUpdate
    ) -> RecurringRulePublic:
        """Edit a recurring rule, or pause it.

        Editing the schedule moves the cursor to the next date the new schedule
        falls due, but never backwards past what has already been created, so
        an edit cannot duplicate a transaction that already exists.

        The whole row is re-validated after the change rather than only the
        fields that were sent, the way an edited transaction is. Which shape
        rules apply depends on the kind, so checking a field in isolation would
        let a rule through that the table itself refuses: giving a transfer
        rule a category passes a category check and then breaks on the flush.

        The kind and the accounts are read off the stored rule rather than the
        change, because no editable field carries them; a default from the
        change would read as if they could be edited, and hide the fact that
        making them editable has to be thought through here.

        The accounts are also not looked up, since the edit cannot move them.
        An account archived after the rule was made would otherwise block every
        edit of the rule, pausing included, leaving deletion as the only way to
        act on a rule whose account has gone, and taking the rule's history
        with it.

        Args:
            household: The household context.
            rule_id: The ID of the rule to edit.
            rule_update: The fields to change.

        Returns:
            The updated rule.

        Raises:
            RecurringRuleNotFoundError: If the rule does not exist in the household.
            CategoryNotFoundError: If the category does not exist in the household.
            SameAccountTransferError: If a transfer names the same account twice.
            TransferShapeError: If the change does not match the kind.
            TransactionCategoryKindError: If the category is the wrong kind.
            InvalidRecurrenceError: If the new schedule would never come due.
        """
        rule = self._require_rule(household=household, rule_id=rule_id)
        fields = rule_update.model_dump(exclude_unset=True)

        self.reference_resolver.resolve(
            household=household,
            kind=rule.kind,
            account_id=rule.account_id,
            counter_account_id=rule.counter_account_id,
            category_id=fields.get("category_id", rule.category_id),
            check_accounts=False,
        )
        self._validate_schedule(start_date=rule.start_date, end_date=fields.get("end_date", rule.end_date))
        rule.sqlmodel_update(fields)

        if {"frequency", "interval", "day_of_month"} & fields.keys():
            rule.next_occurrence_on = self._recompute_cursor(rule)

        self.recurring_rule_repository.save(rule)
        self.session.commit()

        return RecurringRulePublic.model_validate(rule)

    def delete_rule(self, household: HouseholdContext, rule_id: uuid.UUID) -> Message:
        """Delete a recurring rule.

        The transactions it already created are kept: they happened, and the
        rule is only the template that made them.

        Args:
            household: The household context.
            rule_id: The ID of the rule to delete.

        Returns:
            A confirmation message.

        Raises:
            RecurringRuleNotFoundError: If the rule does not exist in the household.
        """
        rule = self._require_rule(household=household, rule_id=rule_id)
        self.recurring_rule_repository.delete(rule)
        self.session.commit()

        return Message(message="Recurring rule deleted. The transactions it created are kept.")

    def list_upcoming(
        self, household: HouseholdContext, until: datetime.date | None = None
    ) -> UpcomingOccurrencesPublic:
        """Project the occurrences that have not been recorded yet.

        Read only: nothing is created, so this can be used to show what is
        coming without changing anything.

        Args:
            household: The household context.
            until: The last day to project to, inclusive. Defaults to two months out.

        Returns:
            The projected occurrences, soonest first, and the net they leave the
            household with: income less expenses, transfers excluded, and the
            blocked occurrences left out.
        """
        horizon = until or datetime.date.today() + datetime.timedelta(days=DEFAULT_UPCOMING_DAYS)
        upcoming: list[UpcomingOccurrence] = []
        usable: dict[uuid.UUID, bool] = {}

        for rule in self.recurring_rule_repository.list_active(household.household_id):
            if rule.next_occurrence_on is None:
                continue

            # The same question the materialization pass asks, asked here too:
            # projecting from the rule alone promises a payment that the pass
            # is going to step over for as long as the account is archived.
            is_blocked = not self._accounts_can_take_transactions(household=household, rule=rule, usable=usable)

            for occurs_on in occurrences_until(
                cursor=rule.next_occurrence_on,
                until=horizon,
                frequency=rule.frequency,
                interval=rule.interval,
                anchor_day=rule.day_of_month,
                end_date=rule.end_date,
            ):
                upcoming.append(
                    UpcomingOccurrence(
                        rule_id=rule.id,
                        name=rule.name,
                        kind=rule.kind,
                        amount_minor=rule.amount_minor,
                        occurs_on=occurs_on,
                        account_id=rule.account_id,
                        category_id=rule.category_id,
                        is_blocked=is_blocked,
                    )
                )

        upcoming.sort(key=lambda occurrence: occurrence.occurs_on)

        return UpcomingOccurrencesPublic(
            data=upcoming,
            count=len(upcoming),
            net_minor=sum(_signed_minor(occurrence) for occurrence in upcoming if not occurrence.is_blocked),
        )

    def materialize_due(self, household: HouseholdContext, until: datetime.date | None = None) -> RecurringRunResult:
        """Create the transactions the rules have fallen due for.

        Called from the read paths, so opening the app brings the ledger up to
        date. That means a GET can write, which is a deliberate trade for not
        needing a scheduler: nothing here is time critical, and correctness
        only has to hold when somebody looks. The same method is what a worker
        would call later, so adding one becomes a deployment change rather than
        a code change.

        Idempotent by the cursor on each rule, which only ever moves forward,
        and backed by a unique index on (rule, date) in case two requests race.
        Losing that race counts the occurrence as skipped: it is already in the
        ledger, written by the request that won.

        A rule whose account has since been archived, or has gone, is passed
        over rather than failing the read it runs under: its occurrences are
        counted as skipped and its cursor is left alone, so putting the account
        back picks the rule up where it stopped.

        Args:
            household: The household context.
            until: The last day to create up to, inclusive. Defaults to today.

        Returns:
            How many transactions were created, how many occurrences were
            passed over, and how many rules moved on.
        """
        horizon = until or datetime.date.today()
        rules = self.recurring_rule_repository.lock_due(household_id=household.household_id, until=horizon)

        created = 0
        skipped = 0
        advanced = 0

        for rule in rules:
            if rule.next_occurrence_on is None:
                continue

            dates = occurrences_until(
                cursor=rule.next_occurrence_on,
                until=horizon,
                frequency=rule.frequency,
                interval=rule.interval,
                anchor_day=rule.day_of_month,
                end_date=rule.end_date,
                limit=MAX_OCCURRENCES_PER_RUN,
            )

            if not dates:
                # Past its end date, so the rule is finished for good.
                rule.next_occurrence_on = None
                self.recurring_rule_repository.add(rule)
                advanced += 1
                continue

            if not self._accounts_can_take_transactions(household=household, rule=rule):
                # The ledger refuses an archived account by hand, so the rule
                # must not write one behind the user's back. Counted, and the
                # cursor stays put until the account is usable again.
                skipped += len(dates)
                continue

            for occurs_on in dates:
                if self._write_occurrence(household=household, rule=rule, occurs_on=occurs_on):
                    created += 1
                else:
                    skipped += 1

            rule.last_generated_on = dates[-1]
            rule.next_occurrence_on = self._next_after(rule=rule, last=dates[-1])
            self.recurring_rule_repository.add(rule)
            advanced += 1

        # One commit for every rule and every transaction, so a failure part
        # way leaves the cursors and the ledger consistent with each other.
        self.recurring_rule_repository.flush()
        self.session.commit()

        return RecurringRunResult(created_count=created, skipped_count=skipped, rules_advanced=advanced)

    def _write_occurrence(self, household: HouseholdContext, rule: RecurringRule, occurs_on: datetime.date) -> bool:
        """Write one occurrence of a rule, unless it is already there.

        Written inside a savepoint, because the unique index on (rule, date)
        is what stops two requests creating the same occurrence, and in
        Postgres an integrity error otherwise leaves the whole transaction
        aborted. Losing the race costs the occurrence, not the page load that
        happened to run the pass.

        Args:
            household: The household context.
            rule: The rule being materialized.
            occurs_on: The day the occurrence falls on.

        Returns:
            True if the transaction was written, False if another request had
            already written it.

        Raises:
            IntegrityError: If the insert failed for any other reason.
        """
        savepoint = self.session.begin_nested()

        try:
            self.transaction_repository.add(
                Transaction(
                    household_id=household.household_id,
                    kind=rule.kind,
                    amount_minor=rule.amount_minor,
                    occurred_on=occurs_on,
                    merchant=rule.merchant,
                    note=rule.note,
                    account_id=rule.account_id,
                    counter_account_id=rule.counter_account_id,
                    category_id=rule.category_id,
                    recurring_rule_id=rule.id,
                    is_generated=True,
                )
            )
            self.session.flush()
        except IntegrityError as error:
            savepoint.rollback()

            if RULE_OCCURRENCE_INDEX not in str(error.orig):
                raise

            return False

        savepoint.commit()

        return True

    def _accounts_can_take_transactions(
        self,
        household: HouseholdContext,
        rule: RecurringRule,
        usable: dict[uuid.UUID, bool] | None = None,
    ) -> bool:
        """Check the accounts a rule draws on are still able to take a transaction.

        Both are checked at create time, but an account can be archived, or
        removed, long after the rule was written.

        Args:
            household: The household context.
            rule: The rule being asked about.
            usable: An optional verdict per account, carried across the rules of
                one listing. A household has far fewer accounts than rules, and
                most rules draw on the same few, so asking once per account
                keeps a page of rules to a handful of lookups.

        Returns:
            True if every account the rule names exists and is not archived.
        """
        account_ids = [rule.account_id]

        if rule.counter_account_id is not None:
            account_ids.append(rule.counter_account_id)

        seen = usable if usable is not None else {}

        for account_id in account_ids:
            if account_id not in seen:
                seen[account_id] = self._account_can_take_transactions(household=household, account_id=account_id)

            if not seen[account_id]:
                return False

        return True

    def _account_can_take_transactions(self, household: HouseholdContext, account_id: uuid.UUID) -> bool:
        """Check one account is still there and still open.

        Args:
            household: The household context.
            account_id: The ID of the account.

        Returns:
            True if the account exists in the household and is not archived.
        """
        try:
            self.reference_resolver.resolve_account(household=household, account_id=account_id)
        except (AccountNotFoundError, AccountArchivedError):
            return False

        return True

    def _next_after(self, rule: RecurringRule, last: datetime.date) -> datetime.date | None:
        """Work out the cursor after an occurrence was created.

        Args:
            rule: The rule that was materialized.
            last: The most recent date created.

        Returns:
            The next date the rule falls due, or None if it is finished, which
            includes a schedule that has run past the end of the calendar.
        """
        following = advance(
            current=last,
            frequency=rule.frequency,
            interval=rule.interval,
            anchor_day=rule.day_of_month,
        )

        if following is None:
            return None

        return None if rule.end_date and following > rule.end_date else following

    def _recompute_cursor(self, rule: RecurringRule) -> datetime.date | None:
        """Place the cursor after a schedule change.

        Args:
            rule: The rule whose schedule changed.

        Returns:
            The next date the rule falls due under the new schedule.
        """
        if rule.last_generated_on is None:
            return first_occurrence(
                start_date=rule.start_date,
                frequency=rule.frequency,
                day_of_month=rule.day_of_month,
            )

        # Never move back past what already exists, so an edit cannot make the
        # next pass create a transaction twice.
        return self._next_after(rule=rule, last=rule.last_generated_on)

    def _validate_schedule(self, start_date: datetime.date, end_date: datetime.date | None) -> None:
        """Check that a schedule can come due at all.

        Args:
            start_date: The day the rule takes effect.
            end_date: The day it stops, if any.

        Raises:
            InvalidRecurrenceError: If the rule ends before it starts.
        """
        if end_date and end_date < start_date:
            raise InvalidRecurrenceError("A rule cannot end before it starts.") from None

    def _require_rule(self, household: HouseholdContext, rule_id: uuid.UUID) -> RecurringRule:
        """Load a recurring rule of the household.

        Args:
            household: The household context.
            rule_id: The ID of the rule.

        Returns:
            The rule.

        Raises:
            RecurringRuleNotFoundError: If the rule does not exist in the household.
        """
        rule = self.recurring_rule_repository.get_for_household(entity_id=rule_id, household_id=household.household_id)

        if not rule:
            raise RecurringRuleNotFoundError from None

        return rule
