import datetime
import uuid

from sqlmodel import Session

from app.exceptions import (
    AccountArchivedError,
    AccountNotFoundError,
    CategoryNotFoundError,
    InvalidRecurrenceError,
    RecurringRuleNotFoundError,
    SameAccountTransferError,
    TransactionCategoryKindError,
    TransferShapeError,
)
from app.models import (
    Account,
    Category,
    CategoryKind,
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
from app.repositories.account import AccountRepository
from app.repositories.category import CategoryRepository
from app.repositories.recurring_rule import RecurringRuleRepository
from app.repositories.transaction import TransactionRepository
from app.services.recurrence import (
    MAX_OCCURRENCES_PER_RUN,
    advance,
    first_occurrence,
    occurrences_until,
)

# How far ahead the upcoming list looks when no date is given.
DEFAULT_UPCOMING_DAYS = 60

_CATEGORY_KIND_FOR: dict[TransactionKind, CategoryKind] = {
    TransactionKind.EXPENSE: CategoryKind.EXPENSE,
    TransactionKind.INCOME: CategoryKind.INCOME,
}


class RecurringRuleService:
    """Provide services for recurring transactions."""

    def __init__(
        self,
        session: Session,
        recurring_rule_repository: RecurringRuleRepository,
        transaction_repository: TransactionRepository,
        account_repository: AccountRepository,
        category_repository: CategoryRepository,
    ) -> None:
        """Initialize the recurring rule service.

        Args:
            session: The database session.
            recurring_rule_repository: The recurring rule repository instance.
            transaction_repository: The transaction repository instance.
            account_repository: The account repository instance.
            category_repository: The category repository instance.
        """
        self.session = session
        self.recurring_rule_repository = recurring_rule_repository
        self.transaction_repository = transaction_repository
        self.account_repository = account_repository
        self.category_repository = category_repository

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
        self._validate_references(
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

        Args:
            household: The household context.
            rule_id: The ID of the rule to edit.
            rule_update: The fields to change.

        Returns:
            The updated rule.

        Raises:
            RecurringRuleNotFoundError: If the rule does not exist in the household.
            CategoryNotFoundError: If the category does not exist in the household.
            TransactionCategoryKindError: If the category is the wrong kind.
            InvalidRecurrenceError: If the new schedule would never come due.
        """
        rule = self._require_rule(household=household, rule_id=rule_id)
        fields = rule_update.model_dump(exclude_unset=True)

        if fields.get("category_id") is not None:
            self._resolve_category(
                household=household,
                category_id=fields["category_id"],
                kind=fields.get("kind", rule.kind),
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
            The projected occurrences, soonest first, and what they add up to.
        """
        horizon = until or datetime.date.today() + datetime.timedelta(days=DEFAULT_UPCOMING_DAYS)
        upcoming: list[UpcomingOccurrence] = []

        for rule in self.recurring_rule_repository.list_active(household.household_id):
            if rule.next_occurrence_on is None:
                continue

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
                    )
                )

        upcoming.sort(key=lambda occurrence: occurrence.occurs_on)

        return UpcomingOccurrencesPublic(
            data=upcoming,
            count=len(upcoming),
            total_minor=sum(occurrence.amount_minor for occurrence in upcoming),
        )

    def materialize_due(self, household: HouseholdContext, until: datetime.date | None = None) -> RecurringRunResult:
        """Create the transactions the rules have fallen due for.

        The only place transactions fall out of the rules, and reached only
        through "POST /recurring-rules/run": the client calls it once when the
        app loads, so every read afterwards answers from the same ledger
        instead of the first read of the screen deciding what the rest see.
        The same method is what a scheduled worker would call, so adding one
        becomes a deployment change rather than a code change.

        Idempotent by the cursor on each rule, which only ever moves forward,
        and backed by a unique index on (rule, date) in case two requests race.

        Args:
            household: The household context.
            until: The last day to create up to, inclusive. Defaults to today.

        Returns:
            How many transactions were created, how many were already there,
            and how many rules moved on.

        Raises:
            AccountNotFoundError: If a rule points at an account that has gone.
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

            for occurs_on in dates:
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
                created += 1

            rule.last_generated_on = dates[-1]
            rule.next_occurrence_on = self._next_after(rule=rule, last=dates[-1])
            self.recurring_rule_repository.add(rule)
            advanced += 1

        # One commit for every rule and every transaction, so a failure part
        # way leaves the cursors and the ledger consistent with each other.
        self.recurring_rule_repository.flush()
        self.session.commit()

        return RecurringRunResult(created_count=created, skipped_count=skipped, rules_advanced=advanced)

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

    def _validate_references(
        self,
        household: HouseholdContext,
        kind: TransactionKind,
        account_id: uuid.UUID,
        counter_account_id: uuid.UUID | None,
        category_id: uuid.UUID | None,
    ) -> None:
        """Check the accounts and category a rule will use.

        The same rules the ledger applies, checked here so a rule cannot be
        saved that would fail every time it tried to create a transaction.

        Args:
            household: The household context.
            kind: The kind of transaction the rule creates.
            account_id: The account it draws on.
            counter_account_id: The destination account, for a transfer.
            category_id: The category, for an expense or income.

        Raises:
            AccountNotFoundError: If an account does not exist in the household.
            AccountArchivedError: If an account is archived.
            CategoryNotFoundError: If the category does not exist in the household.
            SameAccountTransferError: If a transfer names the same account twice.
            TransferShapeError: If the fields do not match the kind.
            TransactionCategoryKindError: If the category is the wrong kind.
        """
        if kind is TransactionKind.TRANSFER:
            if counter_account_id is None:
                raise TransferShapeError("A transfer rule needs a destination account.") from None

            if category_id is not None:
                raise TransferShapeError("A transfer rule has no category.") from None
        elif counter_account_id is not None:
            raise TransferShapeError("Only a transfer rule has a destination account.") from None

        self._resolve_account(household=household, account_id=account_id)

        if counter_account_id is not None:
            if counter_account_id == account_id:
                raise SameAccountTransferError from None

            self._resolve_account(household=household, account_id=counter_account_id)

        if category_id is not None:
            self._resolve_category(household=household, category_id=category_id, kind=kind)

    def _resolve_account(self, household: HouseholdContext, account_id: uuid.UUID) -> Account:
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

    def _resolve_category(self, household: HouseholdContext, category_id: uuid.UUID, kind: TransactionKind) -> Category:
        """Load a category of the household and check it suits the kind.

        Args:
            household: The household context.
            category_id: The ID of the category.
            kind: The kind of transaction the rule creates.

        Returns:
            The category.

        Raises:
            CategoryNotFoundError: If the category does not exist in the household.
            TransactionCategoryKindError: If the category is the wrong kind.
        """
        category = self.category_repository.get_for_household(
            entity_id=category_id, household_id=household.household_id
        )

        if not category:
            raise CategoryNotFoundError from None

        expected = _CATEGORY_KIND_FOR.get(kind)

        if expected is not None and category.kind is not expected:
            raise TransactionCategoryKindError from None

        return category

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
