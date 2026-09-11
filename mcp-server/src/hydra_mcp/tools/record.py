import datetime
from typing import Annotated, Any

from mcp.server import MCPServer
from pydantic import Field

from ..money import to_minor
from ._common import DESTRUCTIVE, WRITES, as_str, current_token, household_context, hydra
from .transactions import describe_transaction

Amount = Annotated[
    str,
    Field(description="How much, in major units and always positive, for example 42.50."),
]
Account = Annotated[str, Field(description="The account, by name.")]
Merchant = Annotated[str | None, Field(description="Who it was with.", max_length=255)]
Note = Annotated[str | None, Field(description="Anything worth remembering about it.", max_length=1024)]


def register(mcp: MCPServer) -> None:
    """Register the tools that change the ledger.

    Args:
        mcp: The server to register them on.
    """

    @mcp.tool(annotations=WRITES)
    async def record_expense(
        amount: Amount,
        account: Account,
        occurred_on: Annotated[datetime.date, Field(description="The day the money went out.")],
        category: Annotated[str | None, Field(description="What it was for, by name.")] = None,
        merchant: Merchant = None,
        note: Note = None,
    ) -> dict[str, Any]:
        """Record money leaving the household.

        The amount is positive. That it went out is what makes this an
        expense, and is carried by calling this tool rather than by a sign.

        Args:
            amount: How much, positive, in major units.
            account: Which account it left.
            occurred_on: The day it happened.
            category: What it was for.
            merchant: Who it was with.
            note: Anything worth remembering.

        Returns:
            The transaction as recorded.
        """
        return await _record(
            kind="expense",
            amount=amount,
            account=account,
            occurred_on=occurred_on,
            category=category,
            merchant=merchant,
            note=note,
        )

    @mcp.tool(annotations=WRITES)
    async def record_income(
        amount: Amount,
        account: Account,
        occurred_on: Annotated[datetime.date, Field(description="The day the money came in.")],
        category: Annotated[str | None, Field(description="Where it came from, by name.")] = None,
        merchant: Merchant = None,
        note: Note = None,
    ) -> dict[str, Any]:
        """Record money arriving in the household.

        The amount is positive, as it is everywhere. That it came in is what
        makes this income.

        Args:
            amount: How much, positive, in major units.
            account: Which account it arrived in.
            occurred_on: The day it happened.
            category: Where it came from.
            merchant: Who it was from.
            note: Anything worth remembering.

        Returns:
            The transaction as recorded.
        """
        return await _record(
            kind="income",
            amount=amount,
            account=account,
            occurred_on=occurred_on,
            category=category,
            merchant=merchant,
            note=note,
        )

    @mcp.tool(annotations=WRITES)
    async def record_transfer(
        amount: Amount,
        from_account: Annotated[str, Field(description="The account the money leaves, by name.")],
        to_account: Annotated[str, Field(description="The account it arrives in, by name.")],
        occurred_on: Annotated[datetime.date, Field(description="The day it moved.")],
        note: Note = None,
    ) -> dict[str, Any]:
        """Move money between two of the household's own accounts.

        A transfer is not spending and never appears in one. It takes no
        category for that reason: the money has not gone anywhere, so there is
        nothing to have spent it on.

        Args:
            amount: How much, positive, in major units.
            from_account: Where the money leaves.
            to_account: Where it arrives.
            occurred_on: The day it moved.
            note: Anything worth remembering.

        Returns:
            The transaction as recorded.
        """
        return await _record(
            kind="transfer",
            amount=amount,
            account=from_account,
            occurred_on=occurred_on,
            to_account=to_account,
            note=note,
        )

    @mcp.tool(annotations=DESTRUCTIVE)
    async def update_transaction(
        transaction_id: Annotated[str, Field(description="The id, from a search result.")],
        amount: Annotated[str | None, Field(description="A new amount, positive.")] = None,
        occurred_on: Annotated[datetime.date | None, Field(description="A new date.")] = None,
        account: Annotated[str | None, Field(description="A different account, by name.")] = None,
        category: Annotated[str | None, Field(description="A different category, by name.")] = None,
        merchant: Merchant = None,
        note: Note = None,
    ) -> dict[str, Any]:
        """Change a transaction that is already recorded.

        Only the fields given are changed; everything left out stays as it is.
        That also means nothing can be emptied here: a wrong category, merchant
        or note can be replaced with a different one, but not removed. To clear
        one, delete the transaction and record it again without it.

        The kind cannot be changed here either: an expense that should have
        been a transfer is a different shape of row, so delete it and record it
        again.

        Args:
            transaction_id: Which transaction.
            amount: A new amount, positive.
            occurred_on: A new date.
            account: A different account.
            category: A different category.
            merchant: A different merchant.
            note: A different note.

        Returns:
            The transaction as it now stands.
        """
        token = current_token()
        accounts, categories, currency = await household_context(token)

        changes: dict[str, Any] = {
            "amount_minor": to_minor(amount, currency) if amount is not None else None,
            "occurred_on": occurred_on.isoformat() if occurred_on else None,
            "account_id": as_str(accounts.id(account)),
            "category_id": as_str(categories.id(category)),
            "merchant": merchant,
            "note": note,
        }
        given = {field: value for field, value in changes.items() if value is not None}

        payload = await hydra().patch(f"/transactions/{transaction_id}", token=token, subject="transaction", json=given)

        return describe_transaction(payload, accounts, categories, currency)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def delete_transaction(
        transaction_id: Annotated[str, Field(description="The id, from a search result.")],
    ) -> dict[str, Any]:
        """Delete a transaction.

        It is gone, and the balances it affected move. Check with the person
        before calling this on anything you did not just record yourself.

        Args:
            transaction_id: Which transaction.

        Returns:
            What hydra said about the deletion.
        """
        answer: dict[str, Any] = await hydra().delete(
            f"/transactions/{transaction_id}", token=current_token(), subject="transaction"
        )
        return answer


async def _record(
    *,
    kind: str,
    amount: str,
    account: str,
    occurred_on: datetime.date,
    category: str | None = None,
    to_account: str | None = None,
    merchant: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Record one transaction of a given kind.

    Args:
        kind: expense, income or transfer.
        amount: How much, positive, in major units.
        account: The account it comes out of or into.
        occurred_on: The day it happened.
        category: What it was for, where a category applies.
        to_account: Where a transfer arrives.
        merchant: Who it was with.
        note: Anything worth remembering.

    Returns:
        The transaction as recorded.
    """
    token = current_token()
    accounts, categories, currency = await household_context(token)

    body: dict[str, Any] = {
        "kind": kind,
        "amount_minor": to_minor(amount, currency),
        "occurred_on": occurred_on.isoformat(),
        "account_id": as_str(accounts.id(account)),
    }
    if to_account is not None:
        body["counter_account_id"] = as_str(accounts.id(to_account))
    if category is not None:
        body["category_id"] = as_str(categories.id(category))
    if merchant is not None:
        body["merchant"] = merchant
    if note is not None:
        body["note"] = note

    payload = await hydra().post("/transactions/", token=token, subject="transaction", json=body)

    return describe_transaction(payload, accounts, categories, currency)
