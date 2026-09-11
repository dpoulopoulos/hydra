from typing import Any

from mcp.server import MCPServer

from ..money import money, signed_money
from ..resolve import bare_name, categories_of
from ._common import READ_ONLY, Month, current_token, hydra, this_month


def register(mcp: MCPServer) -> None:
    """Register the budget tools.

    Args:
        mcp: The server to register them on.
    """

    @mcp.tool(annotations=READ_ONLY)
    async def list_budgets(month: Month = None) -> dict[str, Any]:
        """List the household's budget limits for a month.

        A limit set on a parent category covers everything filed under it.
        Nothing rolls over from one month to the next.

        Args:
            month: The month to list, or the current one.

        Returns:
            The limits, and what they come to together.
        """
        token = current_token()
        categories = await categories_of(token)
        household = await hydra().get("/households/me", token=token, subject="household")
        currency = household["currency_code"]

        payload = await hydra().get("/budgets/", token=token, subject="budget", params={"month": month or this_month()})

        return {
            "month": month or this_month(),
            "budgets": [
                {
                    "category": bare_name(categories.name(b["category_id"])),
                    "limit": money(b["limit_minor"], currency),
                }
                for b in payload["data"]
            ],
            "total_limit": money(payload["total_limit_minor"], currency),
            "count": payload["count"],
        }

    @mcp.tool(annotations=READ_ONLY)
    async def get_budget_progress(month: Month = None) -> dict[str, Any]:
        """Compare a month's spending against its budgets.

        This is the tool for "am I over budget". Remaining is signed: it goes
        negative once a category is overspent.

        Args:
            month: The month to check, or the current one.

        Returns:
            Every budgeted category with what is left, and the spending that
            fell outside any budget.
        """
        payload = await hydra().get(
            "/reports/budget-progress",
            token=current_token(),
            subject="month",
            params={"month": month or this_month()},
        )

        currency = payload["period"]["currency_code"]

        return {
            "period": payload["period"],
            "categories": [_row(row, currency) for row in payload["rows"]],
            "total_limit": money(payload["total_limit_minor"], currency),
            "total_spent": money(payload["total_spent_minor"], currency, negative=True),
            "total_remaining": signed_money(payload["total_remaining_minor"], currency),
            # Spending in categories with no limit at all. Not over budget,
            # because there is no budget, which is worth saying rather than
            # letting it silently vanish from the comparison.
            "unbudgeted_spend": money(payload["unbudgeted_spend_minor"], currency, negative=True),
        }


def _row(row: dict[str, Any], currency: str) -> dict[str, Any]:
    """Describe one category's progress against its limit.

    Args:
        row: The row as hydra reports it.
        currency: The household currency.

    Returns:
        The fields worth reading.
    """
    return {
        "category": row["category_name"],
        "limit": money(row["limit_minor"], currency),
        "spent": money(row["spent_minor"], currency, negative=True),
        "remaining": signed_money(row["remaining_minor"], currency),
        "used": f"{row['progress'] * 100:.1f}%",
        "over_budget": row["is_over_budget"],
        # Whether this limit also covers the categories filed under it.
        "covers_subcategories": row["covers_subcategories"],
    }
