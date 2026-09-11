import datetime
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from pydantic import Field

from ..money import money, to_minor
from ..resolve import Named, accounts_of, bare_name, categories_of
from ._common import READ_ONLY, current_token, hydra

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
        min_amount: Annotated[str | None, Field(description="Only amounts at least this large, e.g. 20.00.")] = None,
        max_amount: Annotated[str | None, Field(description="Only amounts at most this large, e.g. 100.00.")] = None,
        text: Annotated[str | None, Field(description="Only where the merchant or note contains this.")] = None,
        newest_first: Annotated[bool, Field(description="Order by date, newest first.")] = True,
        limit: Annotated[int, Field(description="How many to return.", ge=1, le=MAX_RESULTS)] = 50,
    ) -> dict[str, Any]:
        """Search the household's transactions.

        Accounts and categories are named, not identified by number. Amounts
        are written in major units, as a person would: 42.50.

        Every transaction that comes back has a positive amount; which way the
        money went is in its `kind` and in the sign of `display`.

        Args:
            date_from: Only on or after this date.
            date_to: Only on or before this date.
            account: Only this account, by name.
            category: Only this category, by name.
            include_subcategories: Whether a parent also matches its children.
            kind: Only one kind of transaction.
            min_amount: Only amounts at least this large.
            max_amount: Only amounts at most this large.
            text: Only where the merchant or note contains this.
            newest_first: Whether to order newest first.
            limit: How many to return.

        Returns:
            The matching transactions, and how many there are in total.
        """
        token = current_token()
        accounts, categories, currency = await _context(token)

        payload = await hydra().get(
            "/transactions/",
            token=token,
            subject="transaction",
            params={
                "date_from": date_from.isoformat() if date_from else None,
                "date_to": date_to.isoformat() if date_to else None,
                "account_id": _as_str(accounts.id(account)),
                "category_id": _as_str(categories.id(category)),
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
            "transactions": [_transaction(t, accounts, categories, currency) for t in payload["data"]],
            # How many match the filters, which may be more than were returned.
            "total_matching": payload["count"],
            "currency": currency,
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
        accounts, categories, currency = await _context(token)

        payload = await hydra().get(f"/transactions/{transaction_id}", token=token, subject="transaction")

        return _transaction(payload, accounts, categories, currency)


async def _context(token: str) -> tuple[Named, Named, str]:
    """Fetch what is needed to turn ids into names and back.

    Args:
        token: The hydra API token to present.

    Returns:
        The accounts, the categories, and the household currency.
    """
    accounts = await accounts_of(token)
    categories = await categories_of(token)
    household = await hydra().get("/households/me", token=token, subject="household")

    return accounts, categories, household["currency_code"]


def _as_str(value: Any) -> str | None:
    """Render a resolved id for a query string.

    Args:
        value: The id, or None.

    Returns:
        The id as text, or None.
    """
    return None if value is None else str(value)


def _transaction(transaction: dict[str, Any], accounts: Named, categories: Named, currency: str) -> dict[str, Any]:
    """Describe one transaction.

    Args:
        transaction: The transaction as hydra reports it.
        accounts: The household's accounts, for naming.
        categories: The household's categories, for naming.
        currency: The household currency.

    Returns:
        The fields worth reading, with names rather than ids.
    """
    kind = transaction["kind"]

    return {
        "id": transaction["id"],
        "kind": kind,
        # A transfer is neither in nor out of the household, so it is shown
        # without a sign: the money did not go anywhere, it moved.
        "amount": money(transaction["amount_minor"], currency, negative=kind == "expense"),
        "occurred_on": transaction["occurred_on"],
        "account": accounts.name(transaction["account_id"]),
        "to_account": accounts.name(transaction.get("counter_account_id")),
        "category": bare_name(categories.name(transaction.get("category_id"))),
        "merchant": transaction.get("merchant"),
        "note": transaction.get("note"),
        # True when a recurring rule created it rather than a person.
        "generated": transaction.get("is_generated", False),
    }
