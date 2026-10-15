import datetime
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..money import to_minor
from ._common import DESTRUCTIVE, WRITES, as_str, current_token, household_context, hydra
from .goals import goals_of
from .transactions import describe_transaction

Amount = Annotated[
    str,
    Field(
        description=(
            "How much, in major units and always positive, for example 42.50. "
            "In the currency of the account it is recorded against."
        )
    ),
]
AmountReceived = Annotated[
    str | None,
    Field(
        description=(
            "How much arrived, in the destination account's currency, positive, for example 54.20. "
            "Needed when the two accounts hold different currencies, and left out when they hold the same."
        )
    ),
]
Account = Annotated[str, Field(description="The account, by name.")]
Merchant = Annotated[str | None, Field(description="Who it was with.", max_length=255)]
Note = Annotated[str | None, Field(description="Anything worth remembering about it.", max_length=1024)]
Goal = Annotated[
    str | None,
    Field(description="The savings goal the money is for, by name. Only for a transfer into or out of its account."),
]


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
        It is in the currency of the account it left.

        Args:
            amount: How much, positive, in major units, in the account's currency.
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
        makes this income. It is in the currency of the account it arrived in.

        Args:
            amount: How much, positive, in major units, in the account's currency.
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
        amount_received: AmountReceived = None,
        note: Note = None,
        goal: Goal = None,
    ) -> dict[str, Any]:
        """Move money between two of the household's own accounts.

        A transfer is not spending and never appears in one. It takes no
        category for that reason: the money has not gone anywhere, so there is
        nothing to have spent it on.

        `amount` is what leaves, in the currency of `from_account`. When the
        two accounts hold different currencies, `amount_received` is needed
        as well: what arrived, in the currency of `to_account`, which is what
        the bank or the exchange actually gave and which hydra cannot work out
        from a rate. Between two accounts in the same currency, leave it out.

        Args:
            amount: How much leaves, positive, in major units.
            from_account: Where the money leaves.
            to_account: Where it arrives.
            occurred_on: The day it moved.
            amount_received: How much arrives, in the destination's currency.
                Only for a transfer between two currencies.
            note: Anything worth remembering.
            goal: The savings goal the money is for, when it moves into or
                out of that goal's savings account.

        Returns:
            The transaction as recorded.
        """
        return await _record(
            kind="transfer",
            amount=amount,
            account=from_account,
            occurred_on=occurred_on,
            to_account=to_account,
            amount_received=amount_received,
            note=note,
            goal=goal,
        )

    @mcp.tool(annotations=DESTRUCTIVE)
    async def update_transaction(
        transaction_id: Annotated[str, Field(description="The id, from a search result.")],
        amount: Annotated[
            str | None, Field(description="A new amount, positive, in the currency of the account it is filed against.")
        ] = None,
        amount_received: Annotated[
            str | None,
            Field(
                description=(
                    "A new amount received, positive, in the destination account's currency. "
                    "Only for a transfer between two currencies."
                )
            ),
        ] = None,
        occurred_on: Annotated[datetime.date | None, Field(description="A new date.")] = None,
        account: Annotated[str | None, Field(description="A different account, by name.")] = None,
        category: Annotated[str | None, Field(description="A different category, by name.")] = None,
        merchant: Merchant = None,
        note: Note = None,
        goal: Goal = None,
    ) -> dict[str, Any]:
        """Change a transaction that is already recorded.

        Only the fields given are changed; everything left out stays as it is.
        That also means nothing can be emptied here: a wrong category, merchant
        or note can be replaced with a different one, but not removed. To clear
        one, delete the transaction and record it again without it.

        The kind cannot be changed here either: an expense that should have
        been a transfer is a different shape of row, so delete it and record it
        again.

        An amount is read in the currency of the account the transaction ends
        up on. For a transfer between two currencies, `amount_received` is
        what arrived in the destination's currency. Moving such a transfer to
        another account drops the amount received, so give it again when the
        new pair of accounts still holds two currencies.

        Args:
            transaction_id: Which transaction.
            amount: A new amount, positive, in the source account's currency.
            amount_received: A new amount received, in the destination's currency.
            occurred_on: A new date.
            account: A different account.
            category: A different category.
            merchant: A different merchant.
            note: A different note.
            goal: A savings goal to tag a transfer with.

        Returns:
            The transaction as it now stands.
        """
        token = current_token()
        accounts, categories, _ = await household_context(token)
        goal_id = (await goals_of(token))[0].id(goal) if goal is not None else None
        account_id = accounts.id(account)

        amount_minor = None
        counter_amount_minor = None
        if amount is not None or amount_received is not None:
            # What the amounts are written in depends on which accounts the
            # row ends up on, so the row as it stands is needed.
            current = await hydra().get(f"/transactions/{transaction_id}", token=token, subject="transaction")
            if amount is not None:
                amount_minor = to_minor(amount, accounts.currency(account_id or current["account_id"]))
            if amount_received is not None:
                if current["kind"] != "transfer" or current.get("counter_account_id") is None:
                    raise ToolError("Only a transfer has an amount received.")
                counter_amount_minor = to_minor(amount_received, accounts.currency(current["counter_account_id"]))

        changes: dict[str, Any] = {
            "amount_minor": amount_minor,
            "counter_amount_minor": counter_amount_minor,
            "occurred_on": occurred_on.isoformat() if occurred_on else None,
            "account_id": as_str(account_id),
            "category_id": as_str(categories.id(category)),
            "merchant": merchant,
            "note": note,
            "goal_id": as_str(goal_id),
        }
        given = {field: value for field, value in changes.items() if value is not None}

        payload = await hydra().patch(f"/transactions/{transaction_id}", token=token, subject="transaction", json=given)

        return describe_transaction(payload, accounts, categories)

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
    amount_received: str | None = None,
    merchant: str | None = None,
    note: str | None = None,
    goal: str | None = None,
) -> dict[str, Any]:
    """Record one transaction of a given kind.

    Args:
        kind: expense, income or transfer.
        amount: How much, positive, in major units, in the account's currency.
        account: The account it comes out of or into.
        occurred_on: The day it happened.
        category: What it was for, where a category applies.
        to_account: Where a transfer arrives.
        amount_received: How much a transfer between two currencies delivers,
            in the destination's currency.
        merchant: Who it was with.
        note: Anything worth remembering.
        goal: The savings goal a transfer is for.

    Returns:
        The transaction as recorded.
    """
    token = current_token()
    accounts, categories, _ = await household_context(token)
    account_id = accounts.id(account)

    body: dict[str, Any] = {
        "kind": kind,
        # In the currency of the account it is filed against, not the household's.
        "amount_minor": to_minor(amount, accounts.currency(account_id)),
        "occurred_on": occurred_on.isoformat(),
        "account_id": as_str(account_id),
    }
    if to_account is not None:
        to_account_id = accounts.id(to_account)
        body["counter_account_id"] = as_str(to_account_id)
        if amount_received is not None:
            body["counter_amount_minor"] = to_minor(amount_received, accounts.currency(to_account_id))
    if category is not None:
        body["category_id"] = as_str(categories.id(category))
    if merchant is not None:
        body["merchant"] = merchant
    if note is not None:
        body["note"] = note
    if goal is not None:
        goals, _ = await goals_of(token)
        body["goal_id"] = as_str(goals.id(goal))

    payload = await hydra().post("/transactions/", token=token, subject="transaction", json=body)

    return describe_transaction(payload, accounts, categories)
