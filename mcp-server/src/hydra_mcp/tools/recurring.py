import datetime
from typing import Annotated, Any

from mcp.server import MCPServer
from pydantic import Field

from ..money import money
from ..resolve import Named, bare_name
from ._common import READ_ONLY, current_token, household_context, hydra


def register(mcp: MCPServer) -> None:
    """Register the recurring rule tools.

    Args:
        mcp: The server to register them on.
    """

    @mcp.tool(annotations=READ_ONLY)
    async def list_recurring_rules(
        include_inactive: Annotated[bool, Field(description="Include rules that have been switched off.")] = False,
    ) -> dict[str, Any]:
        """List the household's standing payments.

        Rent, subscriptions, standing transfers: the things that happen again
        without anybody recording them each time.

        Args:
            include_inactive: Whether switched off rules are listed too.

        Returns:
            The rules, with when each is next due.
        """
        # hydra filters on is_active, where leaving it out means "either".
        token = current_token()
        accounts, categories, currency = await household_context(token)

        payload = await hydra().get(
            "/recurring-rules/",
            token=token,
            subject="recurring rule",
            params={"is_active": None if include_inactive else True},
        )

        return {
            "rules": [_rule(rule, accounts, categories, currency) for rule in payload["data"]],
            "count": payload["count"],
        }

    @mcp.tool(annotations=READ_ONLY)
    async def get_upcoming_recurring(
        until: Annotated[
            datetime.date | None,
            Field(description="Look ahead to this date. Leave out for hydra's own window."),
        ] = None,
    ) -> dict[str, Any]:
        """List what is due next from the standing payments.

        This is the tool for "what is coming out this month".

        Args:
            until: How far ahead to look.

        Returns:
            Each occurrence that falls due, and what is leaving in total.
        """
        token = current_token()
        accounts, categories, currency = await household_context(token)

        payload = await hydra().get(
            "/recurring-rules/upcoming",
            token=token,
            subject="recurring rule",
            params={"until": until.isoformat() if until else None},
        )

        # hydra's own total sums every kind, so a salary and the rent it pays
        # add together rather than cancel. As one unsigned figure that answers
        # no question anybody asks, and the instructions tell a model to quote
        # the display string, so it would be quoted. Only what is going out is
        # summed here, because "what is coming out" is what this tool is for.
        leaving = sum(item["amount_minor"] for item in payload["data"] if item["kind"] == "expense")

        return {
            "upcoming": [
                {
                    "name": item["name"],
                    "kind": item["kind"],
                    "amount": money(item["amount_minor"], currency, negative=item["kind"] == "expense"),
                    "occurs_on": item["occurs_on"],
                    "account": accounts.name(item.get("account_id")),
                    "category": bare_name(categories.name(item.get("category_id"))),
                }
                for item in payload["data"]
            ],
            "total_leaving": money(leaving, currency, negative=True),
            "count": payload["count"],
        }


def _rule(rule: dict[str, Any], accounts: Named, categories: Named, currency: str) -> dict[str, Any]:
    """Describe one standing payment.

    Args:
        rule: The rule as hydra reports it.
        accounts: The household's accounts, for naming.
        categories: The household's categories, for naming.
        currency: The household currency.

    Returns:
        The fields worth reading, with names rather than ids.
    """

    return {
        "name": rule["name"],
        "kind": rule["kind"],
        "amount": money(rule["amount_minor"], currency, negative=rule["kind"] == "expense"),
        "how_often": _how_often(rule["frequency"], rule["interval"]),
        "next_due": rule.get("next_occurrence_on"),
        "account": accounts.name(rule.get("account_id")),
        "to_account": accounts.name(rule.get("counter_account_id")),
        "category": bare_name(categories.name(rule.get("category_id"))),
        "active": rule["is_active"],
    }


def _how_often(frequency: str, interval: int) -> str:
    """Say how often a rule falls due, in words.

    "every 2 monthly" is what the raw fields say and not what anybody means,
    so the adjective is turned back into the noun it came from.

    Args:
        frequency: How the rule repeats: daily, weekly, monthly, yearly.
        interval: How many of those between occurrences.

    Returns:
        A readable phrase.
    """
    if interval == 1:
        return frequency

    nouns = {"daily": "days", "weekly": "weeks", "monthly": "months", "yearly": "years"}
    return f"every {interval} {nouns.get(frequency, frequency)}"
