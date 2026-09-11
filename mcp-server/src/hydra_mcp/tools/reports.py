import datetime
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from pydantic import Field

from ..money import money, signed_money
from ._common import READ_ONLY, Month, current_token, hydra, this_month


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
            "net": signed_money(payload["net_minor"], currency),
            "net_worth": {
                "total": signed_money(payload["net_worth_minor"], currency),
                "in_accounts": money(payload["bank_minor"], currency, negative=payload["bank_minor"] < 0),
                "cash_with_broker": money(payload["brokerage_minor"], currency),
                "holdings": money(payload["assets_minor"], currency),
                # Holdings with no price contribute nothing, so a total that
                # has any of these is understated rather than wrong.
                "unpriced_holdings": payload["unpriced_asset_count"],
            },
            "transaction_count": payload["transaction_count"],
            "over_budget_categories": payload["over_budget_category_count"],
            # The summary's top categories are what the month spent most on,
            # so the direction is not in question here.
            "top_categories": [_slice(entry, currency, kind="expense") for entry in payload["top_categories"]],
        }

    @mcp.tool(annotations=READ_ONLY)
    async def get_spending_by_category(
        month: Month = None,
        kind: Annotated[
            Literal["expense", "income"],
            Field(description="Break down spending or income."),
        ] = "expense",
        depth: Annotated[
            Literal["parent", "leaf"],
            Field(description='"parent" rolls children up into their parent; "leaf" keeps them apart.'),
        ] = "parent",
    ) -> dict[str, Any]:
        """Break a month down by category.

        Transfers can never appear here. Moving money between two of the
        household's own accounts is not spending, and it is its own kind.

        Args:
            month: The month to break down, or the current one.
            kind: Whether to break down spending or income.
            depth: Whether children are rolled up into their parent.

        Returns:
            Each category's share of the month.
        """
        payload = await hydra().get(
            "/reports/spend-by-category",
            token=current_token(),
            subject="month",
            params={"month": month or this_month(), "kind": kind, "depth": depth},
        )

        currency = payload["period"]["currency_code"]

        return {
            "period": payload["period"],
            "kind": payload["kind"],
            "total": money(payload["total_minor"], currency, negative=kind == "expense"),
            "categories": [_slice(entry, currency, kind=kind) for entry in payload["slices"]],
        }

    @mcp.tool(annotations=READ_ONLY)
    async def get_spending_over_time(
        date_from: Annotated[datetime.date, Field(description="The first day to include.")],
        date_to: Annotated[datetime.date, Field(description="The last day to include.")],
        granularity: Annotated[
            Literal["day", "month"], Field(description="One point per day, or one per month.")
        ] = "month",
        kind: Annotated[Literal["expense", "income"], Field(description="Track spending or income.")] = "expense",
    ) -> dict[str, Any]:
        """Track spending or income over a stretch of time.

        This is the tool for "is it going up", rather than for one month's
        total. Long ranges at day granularity may be refused as too large.

        Args:
            date_from: The first day to include.
            date_to: The last day to include.
            granularity: One point per day, or per month.
            kind: Whether to track spending or income.

        Returns:
            One point per bucket, with the total and the average.
        """
        payload = await hydra().get(
            "/reports/spend-over-time",
            token=current_token(),
            subject="date range",
            params={
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "granularity": granularity,
                "kind": kind,
            },
        )

        currency = payload["period"]["currency_code"]
        outgoing = kind == "expense"

        return {
            "period": payload["period"],
            "granularity": payload["granularity"],
            "kind": payload["kind"],
            "total": money(payload["total_minor"], currency, negative=outgoing),
            "average_per_bucket": money(payload["average_minor"], currency, negative=outgoing),
            "points": [
                {
                    "bucket": point["bucket"],
                    "amount": money(point["amount_minor"], currency, negative=outgoing),
                    "transaction_count": point["transaction_count"],
                }
                for point in payload["points"]
            ],
        }

    @mcp.tool(annotations=READ_ONLY)
    async def get_income_vs_expense(
        month_from: Month = None,
        month_to: Month = None,
    ) -> dict[str, Any]:
        """Compare money in against money out, month by month.

        This is the tool for "are we saving". The running total carries across
        the whole range, so it shows whether the household is ahead overall
        rather than only in the last month.

        Args:
            month_from: The first month, or the current one.
            month_to: The last month, or the current one.

        Returns:
            Each month's income, spending and net, plus the totals.
        """
        payload = await hydra().get(
            "/reports/income-expense",
            token=current_token(),
            subject="month range",
            params={
                "month_from": month_from or this_month(),
                "month_to": month_to or this_month(),
            },
        )

        currency = payload["period"]["currency_code"]

        return {
            "period": payload["period"],
            "months": [
                {
                    "month": flow["month"],
                    "income": money(flow["income_minor"], currency),
                    "expense": money(flow["expense_minor"], currency, negative=True),
                    "net": signed_money(flow["net_minor"], currency),
                    "running_total": signed_money(flow["cumulative_net_minor"], currency),
                    "saved": _percent(flow["savings_rate"]),
                }
                for flow in payload["months"]
            ],
            "total_income": money(payload["total_income_minor"], currency),
            "total_expense": money(payload["total_expense_minor"], currency, negative=True),
            "total_net": signed_money(payload["total_net_minor"], currency),
            "average_saved": _percent(payload["average_savings_rate"]),
        }


def _slice(entry: dict[str, Any], currency: str, *, kind: str) -> dict[str, Any]:
    """Describe one category's share of a month.

    The direction has to be carried in, because this same breakdown serves
    income as well as spending. Rendered as money going out either way, an
    income row would read "-EUR 2500.00" under a key called "spent", and the
    total beside it would say the opposite. The key is named from the kind so
    a row says what it is without the caller holding on to the question.

    Args:
        entry: The slice as hydra reports it.
        currency: The household currency the amounts are in.
        kind: Whether this breakdown is of spending or of income.

    Returns:
        The category, what it came to, and how much of the total that is.
    """
    outgoing = kind == "expense"

    return {
        "category": entry["category_name"],
        "parent": entry.get("parent_name"),
        "spent" if outgoing else "received": money(entry["amount_minor"], currency, negative=outgoing),
        "share": f"{entry['share'] * 100:.1f}%",
        "transaction_count": entry["transaction_count"],
    }


def _percent(share: float | None) -> str | None:
    """Render a proportion as a percentage.

    Args:
        share: The proportion, between 0 and 1, or None when undefined.

    Returns:
        The percentage, or None.
    """
    if share is None:
        return None

    return f"{share * 100:.1f}%"
