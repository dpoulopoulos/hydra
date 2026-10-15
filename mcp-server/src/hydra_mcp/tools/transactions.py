import datetime
import uuid
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..money import money, to_minor
from ..resolve import Named, bare_name
from ._common import READ_ONLY, as_str, current_token, household_context, hydra

Kind = Literal["expense", "income", "transfer"]

MAX_RESULTS = 200


def register(mcp: MCPServer) -> None:
    """Register the transaction tools.

    Args:
        mcp: The server to register them on.
    """

    @mcp.tool(annotations=READ_ONLY)
    async def search_transactions(
        date_from: Annotated[datetime.date | None, Field(description="Only on or after this date.")] = None,
        date_to: Annotated[datetime.date | None, Field(description="Only on or before this date.")] = None,
        account: Annotated[str | None, Field(description="Only this account, by name.")] = None,
        category: Annotated[
            str | None,
            Field(description='Only this category, by name. A child is written "Parent > Child".'),
        ] = None,
        include_subcategories: Annotated[
            bool, Field(description="When a parent category is named, also match anything filed under it.")
        ] = True,
        kind: Annotated[Kind | None, Field(description="Only expenses, only income, or only transfers.")] = None,
        min_amount: Annotated[
            str | None,
            Field(description="Only amounts at least this large, e.g. 20.00, in the currency of the account named."),
        ] = None,
        max_amount: Annotated[
            str | None,
            Field(description="Only amounts at most this large, e.g. 100.00, in the currency of the account named."),
        ] = None,
        text: Annotated[str | None, Field(description="Only where the merchant or note contains this.")] = None,
        newest_first: Annotated[bool, Field(description="Order by date, newest first.")] = True,
        limit: Annotated[int, Field(description="How many to return.", ge=1, le=MAX_RESULTS)] = 50,
    ) -> dict[str, Any]:
        """Search the household's transactions.

        Accounts and categories are named, not identified by number. Amounts
        are written in major units, as a person would: 42.50.

        Every transaction that comes back has a positive amount; which way the
        money went is in its `kind` and in the sign of `display`. The amount is
        in the currency of the account it is filed against, which is not always
        the household's. A transfer between accounts in two currencies also
        says what arrived, in `amount_received`.

        A minimum or maximum amount is compared as a number, whatever the
        currency, so it needs the account named when the household's accounts
        hold more than one currency.

        Args:
            date_from: Only on or after this date.
            date_to: Only on or before this date.
            account: Only this account, by name.
            category: Only this category, by name.
            include_subcategories: Whether a parent also matches its children.
            kind: Only one kind of transaction.
            min_amount: Only amounts at least this large, in the account's currency.
            max_amount: Only amounts at most this large, in the account's currency.
            text: Only where the merchant or note contains this.
            newest_first: Whether to order newest first.
            limit: How many to return.

        Returns:
            The matching transactions, and how many there are in total.
        """
        token = current_token()
        accounts, categories, household_currency = await household_context(token)
        account_id = accounts.id(account)

        currency = _filter_currency(accounts, account_id, household_currency, (min_amount, max_amount))

        payload = await hydra().get(
            "/transactions/",
            token=token,
            subject="transaction",
            params={
                "date_from": date_from.isoformat() if date_from else None,
                "date_to": date_to.isoformat() if date_to else None,
                "account_id": as_str(account_id),
                "category_id": as_str(categories.id(category)),
                "include_subcategories": include_subcategories,
                "kind": kind,
                "min_amount_minor": to_minor(min_amount, currency) if min_amount is not None else None,
                "max_amount_minor": to_minor(max_amount, currency) if max_amount is not None else None,
                "q": text,
                "limit": limit,
                "sort": "-date" if newest_first else "date",
            },
        )

        return {
            "transactions": [describe_transaction(t, accounts, categories) for t in payload["data"]],
            # How many match the filters, which may be more than were returned.
            "total_matching": payload["count"],
        }

    @mcp.tool(annotations=READ_ONLY)
    async def get_transaction(
        transaction_id: Annotated[str, Field(description="The id of the transaction, from a search result.")],
    ) -> dict[str, Any]:
        """Get one transaction in full, by id.

        Args:
            transaction_id: The id, as a search result reported it.

        Returns:
            The transaction.
        """
        token = current_token()
        accounts, categories, _ = await household_context(token)

        payload = await hydra().get(f"/transactions/{transaction_id}", token=token, subject="transaction")

        return describe_transaction(payload, accounts, categories)


def _filter_currency(
    accounts: Named, account_id: uuid.UUID | None, household_currency: str, amounts: tuple[str | None, ...]
) -> str:
    """Decide which currency a minimum or maximum amount is written in.

    hydra compares those as bare numbers, so 20.00 means something different
    in each currency and a filter across several would quietly mix them.

    Args:
        accounts: The household's accounts.
        account_id: The account being searched, if one was named.
        household_currency: The household currency, for a household with no accounts.
        amounts: The minimum and maximum the caller wrote.

    Returns:
        The currency to read them in.

    Raises:
        ToolError: If an amount was given, no account was named, and the
            household's accounts are in more than one currency.
    """
    if account_id is not None:
        return accounts.currency(account_id)

    held = sorted(set(accounts.currency_of.values()))
    if len(held) > 1 and any(amount is not None for amount in amounts):
        raise ToolError(
            f"The household holds {', '.join(held)}, and an amount means something different in each. "
            "Name the account to search, so the amount is read in its currency."
        )

    return held[0] if held else household_currency


def describe_transaction(transaction: dict[str, Any], accounts: Named, categories: Named) -> dict[str, Any]:
    """Describe one transaction.

    Args:
        transaction: The transaction as hydra reports it.
        accounts: The household's accounts, for naming.
        categories: The household's categories, for naming.

    Returns:
        The fields worth reading, with names rather than ids.
    """
    kind = transaction["kind"]
    received_minor = transaction.get("counter_amount_minor")

    return {
        "id": transaction["id"],
        "kind": kind,
        # In the currency of the account it is filed against, which is not
        # always the household's. A transfer is neither in nor out of the
        # household, so it is shown without a sign: the money did not go
        # anywhere, it moved.
        "amount": money(
            transaction["amount_minor"], accounts.currency(transaction["account_id"]), negative=kind == "expense"
        ),
        # What arrived, in the destination's currency, when a transfer crosses
        # two currencies. Null for everything else, where it is the amount.
        "amount_received": money(received_minor, accounts.currency(transaction["counter_account_id"]))
        if received_minor is not None
        else None,
        "occurred_on": transaction["occurred_on"],
        "account": accounts.name(transaction["account_id"]),
        "to_account": accounts.name(transaction.get("counter_account_id")),
        "category": bare_name(categories.name(transaction.get("category_id"))),
        "merchant": transaction.get("merchant"),
        "note": transaction.get("note"),
        # True when a recurring rule created it rather than a person.
        "generated": transaction.get("is_generated", False),
    }
