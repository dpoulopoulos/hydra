import datetime
import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentHousehold, RecurringRuleServiceDep
from app.exceptions import (
    InvalidRecurrenceError,
    RecurringRuleNotFoundError,
    ServiceError,
)
from app.models import (
    Message,
    RecurringRuleCreate,
    RecurringRulePublic,
    RecurringRulesPublic,
    RecurringRuleUpdate,
    RecurringRunResult,
    UpcomingOccurrencesPublic,
)

router = APIRouter(prefix="/recurring-rules", tags=["recurring-rules"])


def recurring_rule_exception_mappings() -> dict[type[ServiceError], int]:
    """Map service exceptions to appropriate HTTP status codes.

    Returns:
        A dictionary mapping exception types to HTTP status codes.
    """
    return {
        RecurringRuleNotFoundError: status.HTTP_404_NOT_FOUND,
        InvalidRecurrenceError: status.HTTP_400_BAD_REQUEST,
    }


@router.post("/", response_model=RecurringRulePublic)
def create_recurring_rule(
    *,
    recurring_rule_service: RecurringRuleServiceDep,
    household: CurrentHousehold,
    rule_in: RecurringRuleCreate,
) -> RecurringRulePublic:
    """Create a recurring rule, such as rent or a subscription.

    Args:
        recurring_rule_service: The recurring rule service dependency.
        household: The current household context.
        rule_in: The rule to create.

    Returns:
        The created rule, with the date it first falls due.

    Raises:
        HTTPException: If an account or category does not exist in the household
            (404), or the rule does not match its kind or would never come due
            (400).
    """
    return recurring_rule_service.create_rule(household=household, rule_create=rule_in)


@router.get("/", response_model=RecurringRulesPublic)
def list_recurring_rules(
    *,
    recurring_rule_service: RecurringRuleServiceDep,
    household: CurrentHousehold,
    is_active: bool | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> RecurringRulesPublic:
    """List the recurring rules of the household.

    Args:
        recurring_rule_service: The recurring rule service dependency.
        household: The current household context.
        is_active: An optional active state to filter on.
        skip: Number of records to skip.
        limit: Maximum number of records to return.

    Returns:
        The rules, soonest due first.

    Raises:
        HTTPException: If the user belongs to no household (404).
    """
    return recurring_rule_service.list_rules(household=household, is_active=is_active, skip=skip, limit=limit)


# Declared before "/{rule_id}" so these words are not parsed as rule IDs.
@router.get("/upcoming", response_model=UpcomingOccurrencesPublic)
def list_upcoming_occurrences(
    *,
    recurring_rule_service: RecurringRuleServiceDep,
    household: CurrentHousehold,
    until: datetime.date | None = Query(default=None),
) -> UpcomingOccurrencesPublic:
    """Show the recurring occurrences that have not been recorded yet.

    Read only: nothing is created, so this can be used to plan ahead.

    Args:
        recurring_rule_service: The recurring rule service dependency.
        household: The current household context.
        until: The last day to look ahead to, inclusive. Defaults to two months out.

    Returns:
        The projected occurrences, soonest first, and what they add up to.

    Raises:
        HTTPException: If the user belongs to no household (404).
    """
    return recurring_rule_service.list_upcoming(household=household, until=until)


@router.post("/run", response_model=RecurringRunResult)
def run_recurring_rules(
    *,
    recurring_rule_service: RecurringRuleServiceDep,
    household: CurrentHousehold,
    until: datetime.date | None = Query(default=None),
) -> RecurringRunResult:
    """Record the transactions the rules have fallen due for.

    The read paths do this automatically, so this endpoint exists for catching
    up explicitly, or for creating occurrences ahead of today.

    Args:
        recurring_rule_service: The recurring rule service dependency.
        household: The current household context.
        until: The last day to record up to, inclusive. Defaults to today.

    Returns:
        How many transactions were created and how many rules moved on.

    Raises:
        HTTPException: If a rule points at an account that no longer exists (404).
    """
    return recurring_rule_service.materialize_due(household=household, until=until)


@router.get("/{rule_id}", response_model=RecurringRulePublic)
def get_recurring_rule(
    *,
    recurring_rule_service: RecurringRuleServiceDep,
    household: CurrentHousehold,
    rule_id: uuid.UUID,
) -> RecurringRulePublic:
    """Get one recurring rule of the household.

    Args:
        recurring_rule_service: The recurring rule service dependency.
        household: The current household context.
        rule_id: The ID of the rule.

    Returns:
        The rule.

    Raises:
        HTTPException: If the rule does not exist in the household (404).
    """
    return recurring_rule_service.get_rule(household=household, rule_id=rule_id)


@router.patch("/{rule_id}", response_model=RecurringRulePublic)
def update_recurring_rule(
    *,
    recurring_rule_service: RecurringRuleServiceDep,
    household: CurrentHousehold,
    rule_id: uuid.UUID,
    rule_in: RecurringRuleUpdate,
) -> RecurringRulePublic:
    """Edit a recurring rule, or pause it by setting is_active to false.

    Args:
        recurring_rule_service: The recurring rule service dependency.
        household: The current household context.
        rule_id: The ID of the rule to edit.
        rule_in: The fields to change.

    Returns:
        The updated rule.

    Raises:
        HTTPException: If the rule or the category does not exist in the
            household (404), or the new schedule would never come due (400).
    """
    return recurring_rule_service.update_rule(household=household, rule_id=rule_id, rule_update=rule_in)


@router.delete("/{rule_id}", response_model=Message)
def delete_recurring_rule(
    *,
    recurring_rule_service: RecurringRuleServiceDep,
    household: CurrentHousehold,
    rule_id: uuid.UUID,
) -> Message:
    """Delete a recurring rule.

    The transactions it already created are kept: they happened, and the rule
    is only the template that made them.

    Args:
        recurring_rule_service: The recurring rule service dependency.
        household: The current household context.
        rule_id: The ID of the rule to delete.

    Returns:
        A confirmation message.

    Raises:
        HTTPException: If the rule does not exist in the household (404).
    """
    return recurring_rule_service.delete_rule(household=household, rule_id=rule_id)
