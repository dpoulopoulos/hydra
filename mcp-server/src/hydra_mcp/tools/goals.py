import datetime
import uuid
from typing import Annotated, Any

from mcp.server import MCPServer
from pydantic import Field

from ..money import money, signed_money, to_minor
from ..resolve import Named, accounts_of
from ._common import DESTRUCTIVE, READ_ONLY, WRITES, Month, as_str, current_token, hydra

GoalName = Annotated[str, Field(description="The goal, by name.")]


async def goals_of(token: str) -> tuple[Named, dict[str, Any]]:
    """Look up the household's goals by name.

    Args:
        token: The hydra API token to present.

    Returns:
        The goals by id and name, and the listing they came from.
    """
    payload = await hydra().get("/goals/", token=token, subject="goal")
    return Named({uuid.UUID(g["id"]): g["name"] for g in payload["data"]}, "goal"), payload


def describe_goal(goal: dict[str, Any]) -> dict[str, Any]:
    """Describe one goal and how it is going.

    Args:
        goal: The goal as hydra reports it.

    Returns:
        The fields worth reading.
    """
    currency = goal["currency_code"]
    described: dict[str, Any] = {
        "id": goal["id"],
        "name": goal["name"],
        "account": goal["account_name"],
        "target": money(goal["target_minor"], currency),
        "saved": signed_money(goal["saved_minor"], currency),
        # The most it ever held. A reached goal is usually spent, so this is
        # what it got to, where "saved" is what is left of it now.
        "most_saved": money(goal["peak_saved_minor"], currency),
        "remaining": money(goal["remaining_minor"], currency),
        "progress": f"{goal['progress'] * 100:.1f}%",
        "average_saved_per_month": signed_money(goal["average_monthly_minor"], currency),
        "reached": goal.get("achieved_at") is not None,
    }
    if goal.get("target_date"):
        described["target_date"] = goal["target_date"]
        described["months_left"] = goal["months_left"]
        described["needed_per_month"] = money(goal["needed_per_month_minor"], currency)
        # None once the goal is reached, when being on track no longer means anything.
        described["on_track"] = goal["on_track"]
    return described


def register(mcp: MCPServer) -> None:
    """Register the savings goal tools.

    Args:
        mcp: The server to register them on.
    """

    @mcp.tool(annotations=READ_ONLY)
    async def list_goals() -> dict[str, Any]:
        """List the household's savings goals and how each is going.

        A goal lives in a savings account and holds the transfers tagged with
        it. Several goals can share an account; whatever no goal holds is that
        account's unassigned money, so the goals and the unassigned money of an
        account always add up to its balance.

        Returns:
            Every goal, and each savings account split into goals and unassigned.
        """
        _, payload = await goals_of(current_token())

        return {
            "goals": [describe_goal(goal) for goal in payload["data"]],
            "accounts": [
                {
                    "account": a["account_name"],
                    "balance": signed_money(a["balance_minor"], a["currency_code"]),
                    "in_goals": signed_money(a["assigned_minor"], a["currency_code"]),
                    "unassigned": signed_money(a["unassigned_minor"], a["currency_code"]),
                }
                for a in payload["accounts"]
            ],
            "count": payload["count"],
        }

    @mcp.tool(annotations=READ_ONLY)
    async def get_goal_history(
        goal: GoalName,
        month_from: Month = None,
        month_to: Month = None,
    ) -> dict[str, Any]:
        """Show what a goal saved, month by month.

        This is the tool for "how much did I put towards the car each month".

        Args:
            goal: Which goal.
            month_from: The first month. Defaults to a year before the last.
            month_to: The last month. Defaults to the current one.

        Returns:
            Each month with what went in, what came out, and the running total.
        """
        token = current_token()
        goals, payload = await goals_of(token)
        goal_id = goals.id(goal)
        currency = next(g["currency_code"] for g in payload["data"] if g["id"] == str(goal_id))

        params = {key: value for key, value in {"month_from": month_from, "month_to": month_to}.items() if value}
        history = await hydra().get(f"/goals/{goal_id}/history", token=token, subject="goal", params=params)

        return {
            "goal": goals.name(goal_id),
            "months": [
                {
                    "month": m["month"],
                    "saved_in": money(m["saved_in_minor"], currency),
                    "taken_out": money(m["saved_out_minor"], currency),
                    "net": signed_money(m["net_minor"], currency),
                    "running_total": signed_money(m["cumulative_minor"], currency),
                }
                for m in history["months"]
            ],
        }

    @mcp.tool(annotations=WRITES)
    async def create_goal(
        name: Annotated[str, Field(description="What it is for, for example New car.", max_length=100)],
        account: Annotated[str, Field(description="The savings account the money goes into, by name.")],
        target: Annotated[str, Field(description="The price, in major units, for example 20000.00.")],
        target_date: Annotated[
            datetime.date | None, Field(description="When it should be reached by, if there is a date.")
        ] = None,
    ) -> dict[str, Any]:
        """Set up something to save towards.

        The account has to be a savings account. With a date, hydra works out
        how much has to go in each month to get there.

        Args:
            name: What it is for.
            account: The savings account the money goes into.
            target: How much it costs.
            target_date: When it should be reached by.

        Returns:
            The goal as set up.
        """
        token = current_token()
        accounts = await accounts_of(token)
        account_id = accounts.id(account)
        currency = await _currency_of(token, account_id)

        payload = await hydra().post(
            "/goals/",
            token=token,
            subject="goal",
            json={
                "name": name,
                "account_id": as_str(account_id),
                "target_minor": to_minor(target, currency),
                "target_date": target_date.isoformat() if target_date else None,
            },
        )
        return describe_goal(payload)

    @mcp.tool(annotations=WRITES)
    async def update_goal(
        goal: GoalName,
        name: Annotated[str | None, Field(description="A new name.", max_length=100)] = None,
        target: Annotated[str | None, Field(description="A new price, in major units.")] = None,
        target_date: Annotated[datetime.date | None, Field(description="A new date to reach it by.")] = None,
        reached: Annotated[bool | None, Field(description="True to mark it reached, false to reopen it.")] = None,
    ) -> dict[str, Any]:
        """Change a goal, or mark it reached.

        Only the fields given are changed.

        Args:
            goal: Which goal.
            name: A new name.
            target: A new price.
            target_date: A new date.
            reached: Whether it has been reached.

        Returns:
            The goal as it now stands.
        """
        token = current_token()
        goals, payload = await goals_of(token)
        goal_id = goals.id(goal)
        currency = next(g["currency_code"] for g in payload["data"] if g["id"] == str(goal_id))

        changes: dict[str, Any] = {
            "name": name,
            "target_minor": to_minor(target, currency) if target is not None else None,
            "target_date": target_date.isoformat() if target_date else None,
            "is_achieved": reached,
        }
        given = {field: value for field, value in changes.items() if value is not None}

        updated = await hydra().patch(f"/goals/{goal_id}", token=token, subject="goal", json=given)
        return describe_goal(updated)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def delete_goal(goal: GoalName) -> dict[str, Any]:
        """Delete a goal.

        Its transfers stay in the ledger and its money becomes unassigned in
        the savings account. Check with the person first.

        Args:
            goal: Which goal.

        Returns:
            What hydra said about the deletion.
        """
        token = current_token()
        goals, _ = await goals_of(token)
        answer: dict[str, Any] = await hydra().delete(f"/goals/{goals.id(goal)}", token=token, subject="goal")
        return answer


async def _currency_of(token: str, account_id: uuid.UUID | None) -> str:
    """Read the currency an account keeps its money in.

    Args:
        token: The hydra API token to present.
        account_id: The account.

    Returns:
        Its currency code.
    """
    account = await hydra().get(f"/accounts/{account_id}", token=token, subject="account")
    currency: str = account["currency_code"]
    return currency
