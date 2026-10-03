import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentHousehold, GoalServiceDep
from app.exceptions import (
    GoalAccountLockedError,
    GoalAccountNotSavingsError,
    GoalExistsError,
    GoalNotFoundError,
    GoalTransferMismatchError,
    ServiceError,
)
from app.models import GoalCreate, GoalHistory, GoalPublic, GoalsPublic, GoalUpdate, Message
from app.models.fields import MONTH_KEY_PATTERN

router = APIRouter(prefix="/goals", tags=["goals"])


def goal_exception_mappings() -> dict[type[ServiceError], int]:
    """Map service exceptions to appropriate HTTP status codes.

    Returns:
        A dictionary mapping exception types to HTTP status codes.
    """
    return {
        GoalNotFoundError: status.HTTP_404_NOT_FOUND,
        GoalExistsError: status.HTTP_409_CONFLICT,
        GoalAccountLockedError: status.HTTP_409_CONFLICT,
        GoalAccountNotSavingsError: status.HTTP_400_BAD_REQUEST,
        GoalTransferMismatchError: status.HTTP_400_BAD_REQUEST,
    }


@router.post("/", response_model=GoalPublic)
def create_goal(*, goal_service: GoalServiceDep, household: CurrentHousehold, goal_in: GoalCreate) -> GoalPublic:
    """Set up a goal to save towards.

    Args:
        goal_service: The goal service dependency.
        household: The current household context.
        goal_in: The name, savings account, target and optional date.

    Returns:
        The created goal.

    Raises:
        HTTPException: If the account does not exist in the household (404),
            another goal has the name (409), or the account is archived or not a
            savings account (400).
    """
    return goal_service.create_goal(household=household, goal_create=goal_in)


@router.get("/", response_model=GoalsPublic)
def list_goals(*, goal_service: GoalServiceDep, household: CurrentHousehold) -> GoalsPublic:
    """List the goals of the household with their progress.

    Each savings account holding a goal is summed up as well, splitting its
    balance into what the goals hold and what is unassigned.

    Args:
        goal_service: The goal service dependency.
        household: The current household context.

    Returns:
        The goals, and one summary per account.
    """
    return goal_service.list_goals(household=household)


@router.get("/{goal_id}", response_model=GoalPublic)
def get_goal(*, goal_service: GoalServiceDep, household: CurrentHousehold, goal_id: uuid.UUID) -> GoalPublic:
    """Get one goal of the household with its progress.

    Args:
        goal_service: The goal service dependency.
        household: The current household context.
        goal_id: The ID of the goal.

    Returns:
        The goal.

    Raises:
        HTTPException: If the goal does not exist in the household (404).
    """
    return goal_service.get_goal(household=household, goal_id=goal_id)


@router.get("/{goal_id}/history", response_model=GoalHistory)
def get_goal_history(
    *,
    goal_service: GoalServiceDep,
    household: CurrentHousehold,
    goal_id: uuid.UUID,
    month_from: str | None = Query(default=None, pattern=MONTH_KEY_PATTERN),
    month_to: str | None = Query(default=None, pattern=MONTH_KEY_PATTERN),
) -> GoalHistory:
    """Show what a goal saved, month by month.

    Args:
        goal_service: The goal service dependency.
        household: The current household context.
        goal_id: The ID of the goal.
        month_from: The first month, "YYYY-MM". Defaults to a year before the last.
        month_to: The last month, "YYYY-MM". Defaults to the current month.

    Returns:
        Every month of the range, with what went in, what came out, and the
        running total.

    Raises:
        HTTPException: If the goal does not exist in the household (404), or
            the range is backwards or longer than ten years (400).
    """
    return goal_service.history(household=household, goal_id=goal_id, month_from=month_from, month_to=month_to)


@router.patch("/{goal_id}", response_model=GoalPublic)
def update_goal(
    *, goal_service: GoalServiceDep, household: CurrentHousehold, goal_id: uuid.UUID, goal_in: GoalUpdate
) -> GoalPublic:
    """Edit a goal, or mark it reached.

    Args:
        goal_service: The goal service dependency.
        household: The current household context.
        goal_id: The ID of the goal.
        goal_in: The fields to change.

    Returns:
        The updated goal.

    Raises:
        HTTPException: If the goal or the new account does not exist in the
            household (404), the name is taken or the account changes while
            transfers are tagged with the goal (409), or the new account is
            archived or not a savings account (400).
    """
    return goal_service.update_goal(household=household, goal_id=goal_id, goal_update=goal_in)


@router.delete("/{goal_id}", response_model=Message)
def delete_goal(*, goal_service: GoalServiceDep, household: CurrentHousehold, goal_id: uuid.UUID) -> Message:
    """Delete a goal.

    Its transfers stay in the ledger. Their money becomes unassigned.

    Args:
        goal_service: The goal service dependency.
        household: The current household context.
        goal_id: The ID of the goal.

    Returns:
        A confirmation message.

    Raises:
        HTTPException: If the goal does not exist in the household (404).
    """
    return goal_service.delete_goal(household=household, goal_id=goal_id)
