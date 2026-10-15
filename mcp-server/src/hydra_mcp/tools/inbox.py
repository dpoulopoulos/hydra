import datetime
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from pydantic import BaseModel, Field

from ..money import to_minor
from ..resolve import accounts_of
from ._common import WRITES, as_str, current_token, hydra

# What hydra calls each way the money can move, from the account's side.
_DIRECTIONS = {"out": "debit", "in": "credit"}


class InboxLine(BaseModel):
    """One line of a statement, as it is printed."""

    direction: Literal["in", "out"] = Field(
        description="'out' for money that left the account, 'in' for money that arrived in it."
    )
    amount: str = Field(
        description="How much, in major units and always positive, for example 42.50. In the account's currency."
    )
    occurred_on: datetime.date = Field(description="The day the statement gives for it.")
    counterparty: str | None = Field(default=None, description="Who it was with, as printed.", max_length=255)
    description: str | None = Field(default=None, description="The statement's text for it.", max_length=1024)
    reference: str | None = Field(
        default=None,
        description="The statement's own id for the line, when it prints one.",
        min_length=1,
        max_length=200,
    )


def register(mcp: MCPServer) -> None:
    """Register the tools that fill the inbox.

    Args:
        mcp: The server to register them on.
    """

    @mcp.tool(annotations=WRITES)
    async def add_to_inbox(
        account: Annotated[str, Field(description="The account the statement is for, by name.")],
        lines: Annotated[
            list[InboxLine],
            Field(description="The statement's lines, in the order it prints them.", min_length=1, max_length=500),
        ],
    ) -> dict[str, Any]:
        """Put the lines of a statement in the inbox, for a person to review.

        Nothing reaches the ledger here. Each line waits in the inbox of the
        web app, where a person accepts it as an expense, income or a
        transfer, files it, or skips it. Use this rather than the record
        tools when the person wants to check each line themselves.

        Every amount is positive and in the account's currency. Which way the
        money went is `direction`, never a sign.

        Adding the same statement again is safe: a line already in the inbox
        is recognised and not added twice. A line is recognised by its
        reference when it has one, and otherwise by what it says and its place
        among identical lines, so keep the statement's order.

        Args:
            account: The account the statement is for.
            lines: Its lines, in statement order.

        Returns:
            How many lines were sent, how many were new, and how many were in
            the inbox already.
        """
        token = current_token()
        accounts = await accounts_of(token)
        account_id = accounts.id(account)
        currency = accounts.currency(account_id)

        entries = [
            {
                "direction": _DIRECTIONS[line.direction],
                "amount_minor": to_minor(line.amount, currency),
                "occurred_on": line.occurred_on.isoformat(),
                "counterparty_name": line.counterparty,
                "description": line.description,
                "reference": line.reference,
            }
            for line in lines
        ]

        answer = await hydra().post(
            "/bank/inbox", token=token, subject="account", json={"account_id": as_str(account_id), "entries": entries}
        )

        return {
            "account": accounts.name(account_id),
            "sent": answer["received"],
            "added": answer["added"],
            "already_in_inbox": answer["received"] - answer["added"],
        }
