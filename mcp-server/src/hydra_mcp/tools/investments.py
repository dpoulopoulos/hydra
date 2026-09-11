from decimal import Decimal
from typing import Annotated, Any

from mcp.server import MCPServer
from pydantic import Field

from ..money import money, signed_money
from ._common import READ_ONLY, current_token, hydra

# Quantities and prices are stored as millionths, the way money is stored as
# minor units: an exact integer rather than a float that drifts.
MICRO = Decimal(1_000_000)


def register(mcp: MCPServer) -> None:
    """Register the investment tools.

    Args:
        mcp: The server to register them on.
    """

    @mcp.tool(annotations=READ_ONLY)
    async def get_portfolio(
        include_closed: Annotated[
            bool, Field(description="Include holdings that have been sold off entirely.")
        ] = False,
    ) -> dict[str, Any]:
        """Value the household's investments.

        Everything is converted into the household currency. A holding with no
        recent price contributes nothing, so a total with any of those is an
        understatement rather than an error, which is why they are counted.

        Args:
            include_closed: Whether fully sold holdings are listed too.

        Returns:
            Each holding and what the portfolio is worth.
        """
        payload = await hydra().get(
            "/investments/portfolio",
            token=current_token(),
            subject="portfolio",
            params={"include_closed": include_closed},
        )

        currency = payload["currency_code"]

        return {
            "currency": currency,
            "holdings": [_position(position, currency) for position in payload["data"]],
            "cost_basis": money(payload["total_cost_basis_minor"], currency),
            "market_value": money(payload["total_market_value_minor"], currency),
            "unrealised_gain": signed_money(payload["total_unrealised_gain_minor"], currency),
            "realised_gain": signed_money(payload["total_realised_gain_minor"], currency),
            # Holdings with no price or no exchange rate. They are worth
            # nothing in the totals above, so any of these means the portfolio
            # is worth more than it says.
            "unpriced_holdings": payload["unpriced_count"],
            "priced_as_of": payload.get("priced_as_of"),
        }


def _position(position: dict[str, Any], currency: str) -> dict[str, Any]:
    """Describe one holding.

    Args:
        position: The position as hydra reports it.
        currency: The household currency the values are in.

    Returns:
        The fields worth reading.
    """
    return {
        "symbol": position["symbol"],
        "name": position.get("name"),
        "quantity": _from_micro(position["quantity_micro"]),
        "currency": position["currency_code"],
        "last_price": _from_micro(position.get("last_price_micro")),
        "last_price_at": position.get("last_price_at"),
        # A hand-entered price is only as fresh as whoever typed it.
        "price_is_manual": position.get("last_price_is_manual", False),
        "cost_basis": money(position["cost_basis_minor"], currency),
        "market_value": money(position["market_value_minor"], currency),
        "unrealised_gain": signed_money(position["unrealised_gain_minor"], currency),
        "realised_gain": signed_money(position["realised_gain_minor"], currency),
        "open": position["is_open"],
    }


def _from_micro(value: int | None) -> str | None:
    """Render a quantity or price held as millionths.

    Args:
        value: The stored integer, or None when there is no price.

    Returns:
        The number as text, with trailing zeroes trimmed, or None.
    """
    if value is None:
        return None

    exact = (Decimal(value) / MICRO).normalize()
    return f"{exact:f}"
