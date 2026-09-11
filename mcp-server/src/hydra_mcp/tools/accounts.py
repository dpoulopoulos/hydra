from typing import Annotated, Any

from mcp.server import MCPServer
from pydantic import Field

from ..money import money
from ._common import READ_ONLY, current_token, hydra


def register(mcp: MCPServer) -> None:
    """Register the account and identity tools.

    Args:
        mcp: The server to register them on.
    """

    @mcp.tool(annotations=READ_ONLY)
    async def whoami() -> dict[str, Any]:
        """Say whose hydra household these tools are reading.

        Worth calling first in a conversation: everything else is scoped to
        this household, and the currency it reports is the one every amount
        will be in.

        Returns:
            The signed in person, their household and its currency.
        """
        token = current_token()
        user = await hydra().get("/users/me", token=token, subject="user")
        household = await hydra().get("/households/me", token=token, subject="household")

        return {
            "email": user["email"],
            "name": user.get("full_name"),
            "household": household["name"],
            "currency": household["currency_code"],
            "member_count": household["member_count"],
        }

    @mcp.tool(annotations=READ_ONLY)
    async def list_accounts(
        include_archived: Annotated[
            bool, Field(description="Include accounts that have been archived but kept for their history.")
        ] = False,
    ) -> dict[str, Any]:
        """List the household's accounts with what is currently in each.

        Balances are worked out from the ledger every time they are asked for,
        so they are never stale.

        Args:
            include_archived: Whether archived accounts are listed too.

        Returns:
            The accounts, and what they hold in total.
        """
        token = current_token()
        payload = await hydra().get(
            "/accounts/",
            token=token,
            subject="account",
            params={"include_archived": include_archived},
        )

        # From the household, not from the first account. The total is in the
        # household currency whatever the accounts are in, so reading it off
        # an account labels a mixed-currency household by whichever one
        # happened to come first, and an empty one by a guess.
        household = await hydra().get("/households/me", token=token, subject="household")
        currency = household["currency_code"]

        return {
            "accounts": [_account(account) for account in payload["data"]],
            "total": money(payload["total_balance_minor"], currency, negative=payload["total_balance_minor"] < 0),
            "count": payload["count"],
        }


def _account(account: dict[str, Any]) -> dict[str, Any]:
    """Describe one account.

    Args:
        account: The account as hydra reports it.

    Returns:
        The fields worth reading, with the balance in every useful form.
    """
    balance_minor = account["current_balance_minor"]
    currency = account["currency_code"]

    return {
        "id": account["id"],
        "name": account["name"],
        "type": account["type"],
        "balance": money(balance_minor, currency, negative=balance_minor < 0),
        "institution": account.get("institution"),
        "archived": account.get("archived_at") is not None,
    }
