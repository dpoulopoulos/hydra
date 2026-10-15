import datetime
from typing import Annotated, Any

from mcp.server import MCPServer
from pydantic import Field

from ..money import money, signed_money
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
            The rules, with when each is next due, and whether an archived
            account has stalled one.
        """
        # hydra filters on is_active, where leaving it out means "either".
        token = current_token()
        accounts, categories, _ = await household_context(token)

        payload = await hydra().get(
            "/recurring-rules/",
            token=token,
            subject="recurring rule",
            params={"is_active": None if include_inactive else True},
        )

        return {
            "rules": [_rule(rule, accounts, categories) for rule in payload["data"]],
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

        Each occurrence is in the currency of the account it draws on, and the
        totals are one per currency: amounts in two currencies are never added
        together.

        Returns:
            Each occurrence that falls due, and what is leaving in each
            currency. An occurrence marked blocked is not counted in the
            totals: the account it draws on is archived, so nothing will
            record it.
        """
        token = current_token()
        accounts, categories, _ = await household_context(token)

        payload = await hydra().get(
            "/recurring-rules/upcoming",
            token=token,
            subject="recurring rule",
            params={"until": until.isoformat() if until else None},
        )

        # What is going out is summed on its own, because "what is coming out"
        # is what this tool is for; hydra's nets answer "what is left" and are
        # passed on beside it. Each currency is summed apart, since an amount
        # is in the currency of the account it draws on. A blocked occurrence
        # is left out as well: the account it draws on is archived, so nothing
        # is going to record it, and counting it would tell the household money
        # is leaving that is staying put.
        leaving: dict[str, int] = {}
        for item in payload["data"]:
            if item["kind"] == "expense" and not item.get("is_blocked"):
                leaving[item["currency_code"]] = leaving.get(item["currency_code"], 0) + item["amount_minor"]

        return {
            "upcoming": [
                {
                    "name": item["name"],
                    "kind": item["kind"],
                    "amount": money(item["amount_minor"], item["currency_code"], negative=item["kind"] == "expense"),
                    "occurs_on": item["occurs_on"],
                    "account": accounts.name(item.get("account_id")),
                    "category": bare_name(categories.name(item.get("category_id"))),
                    # Still listed, because it is what a restored account picks
                    # up, but said to be going nowhere for now.
                    "blocked": bool(item.get("is_blocked")),
                }
                for item in payload["data"]
            ],
            "total_leaving": [money(amount, code, negative=True) for code, amount in sorted(leaving.items())],
            # Income counts for, and spending against, so a salary and the rent
            # it pays do cancel here. Signed, because a net can be negative.
            "net": [signed_money(net["amount_minor"], net["currency_code"]) for net in payload["nets"]],
            "count": payload["count"],
        }


def _rule(rule: dict[str, Any], accounts: Named, categories: Named) -> dict[str, Any]:
    """Describe one standing payment.

    Args:
        rule: The rule as hydra reports it.
        accounts: The household's accounts, for naming.
        categories: The household's categories, for naming.

    Returns:
        The fields worth reading, with names rather than ids.
    """

    return {
        "name": rule["name"],
        "kind": rule["kind"],
        # In the currency of the account the rule draws on.
        "amount": money(
            rule["amount_minor"], accounts.currency(rule["account_id"]), negative=rule["kind"] == "expense"
        ),
        "how_often": _how_often(rule["frequency"], rule["interval"]),
        "next_due": rule.get("next_occurrence_on"),
        "account": accounts.name(rule.get("account_id")),
        "to_account": accounts.name(rule.get("counter_account_id")),
        "category": bare_name(categories.name(rule.get("category_id"))),
        "active": rule["is_active"],
        # An archived account has stalled the rule: it is willing, and the
        # materialization pass steps over it until the account is restored.
        "blocked": bool(rule.get("is_blocked")),
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
