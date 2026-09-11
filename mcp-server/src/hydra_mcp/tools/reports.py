from typing import Annotated, Any

from mcp.server import MCPServer
from pydantic import Field

from ..money import money, signed_display, to_major
from ._common import READ_ONLY, current_token, hydra, this_month

Month = Annotated[
    str | None,
    Field(
        default=None,
        description="The month to report on, written as 2026-09. Leave it out for the current month.",
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
    ),
]


def register(mcp: MCPServer) -> None:
    """Register the report tools.

    Args:
        mcp: The server to register them on.
    """

    @mcp.tool(annotations=READ_ONLY)
    async def get_month_summary(month: Month = None) -> dict[str, Any]:
        """Summarise a month: what came in, what went out, and what is held.

        The three parts of net worth are reported apart as well as together,
        because they move for different reasons and a single total does not
        say which one changed.

        Args:
            month: The month to summarise, or the current one.

        Returns:
            The month's income, spending, net, and where the money sits.
        """
        payload = await hydra().get(
            "/reports/summary",
            token=current_token(),
            subject="month",
            params={"month": month or this_month()},
        )

        currency = payload["period"]["currency_code"]

        return {
            "period": payload["period"],
            "income": money(payload["income_minor"], currency),
            "expense": money(payload["expense_minor"], currency, negative=True),
            # Signed on purpose: a net is genuinely negative in a month that
            # spent more than it earned, unlike a single transaction.
            "net": {
                "amount": to_major(payload["net_minor"], currency),
                "display": signed_display(payload["net_minor"], currency),
                "amount_minor": payload["net_minor"],
                "currency": currency,
            },
            "net_worth": {
                "total": {
                    "amount": to_major(payload["net_worth_minor"], currency),
                    "display": signed_display(payload["net_worth_minor"], currency),
                    "amount_minor": payload["net_worth_minor"],
                    "currency": currency,
                },
                "in_accounts": money(payload["bank_minor"], currency, negative=payload["bank_minor"] < 0),
                "cash_with_broker": money(payload["brokerage_minor"], currency),
                "holdings": money(payload["assets_minor"], currency),
                # Holdings with no price contribute nothing, so a total that
                # has any of these is understated rather than wrong.
                "unpriced_holdings": payload["unpriced_asset_count"],
            },
            "transaction_count": payload["transaction_count"],
            "over_budget_categories": payload["over_budget_category_count"],
            "top_categories": [_slice(entry, currency) for entry in payload["top_categories"]],
        }


def _slice(entry: dict[str, Any], currency: str) -> dict[str, Any]:
    """Describe one category's share of a month's spending.

    Args:
        entry: The slice as hydra reports it.
        currency: The household currency the amounts are in.

    Returns:
        The category, what was spent on it, and how much of the total that is.
    """
    return {
        "category": entry["category_name"],
        "parent": entry.get("parent_name"),
        "spent": money(entry["amount_minor"], currency, negative=True),
        "share": f"{entry['share'] * 100:.1f}%",
        "transaction_count": entry["transaction_count"],
    }
