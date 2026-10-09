from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import AuthenticatedUser, auth_context_var
from mcp.server.auth.provider import AccessToken

from hydra_mcp.client import HydraClient
from hydra_mcp.tools import _common, register_all
from tests.conftest import TOKEN
from tests.unit.test_tools import by_path
from tests.unit.test_tools_read import result_of


@pytest.fixture
def authenticated() -> Iterator[None]:
    """Put a checked token on the request, the way the verifier does.

    Yields:
        Nothing; the context is torn down afterwards.
    """
    reset = auth_context_var.set(
        AuthenticatedUser(AccessToken(token=TOKEN, client_id="a-user", scopes=["hydra:read"]))
    )
    yield
    auth_context_var.reset(reset)


@pytest.fixture
def server(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[Callable[[httpx.Request], httpx.Response]], MCPServer]:
    """Build a server whose tools talk to a handler rather than to a backend.

    Returns:
        A factory taking the handler and giving back the server.
    """

    def build(handler: Callable[[httpx.Request], httpx.Response]) -> MCPServer:
        monkeypatch.setattr(
            _common,
            "_client",
            HydraClient(base_url="http://hydra.test/api/v1", transport=httpx.MockTransport(handler)),
        )
        mcp: MCPServer = MCPServer("test")
        register_all(mcp)
        return mcp

    return build


class TestGetPortfolio:
    """Tests for valuing the holdings."""

    async def test_the_last_price_is_in_major_units(self, server: Any, authenticated: None) -> None:
        # hydra holds a price in minor units times a million: 128.4567 EUR is
        # 12_845_670_000, and reading it as plain millionths is a hundredfold out.
        portfolio = {
            "currency_code": "EUR",
            "data": [
                {
                    "symbol": "VUAA.XETRA",
                    "name": "Vanguard S&P 500",
                    "quantity_micro": 1_000_000,
                    "currency_code": "EUR",
                    "last_price_micro": 12_845_670_000,
                    "cost_basis_minor": 10_000,
                    "market_value_minor": 12_846,
                    "unrealised_gain_minor": 2_846,
                    "realised_gain_minor": 0,
                    "is_open": True,
                }
            ],
            "total_cost_basis_minor": 10_000,
            "total_market_value_minor": 12_846,
            "total_unrealised_gain_minor": 2_846,
            "total_realised_gain_minor": 0,
            "unpriced_count": 0,
        }
        mcp = server(by_path({"/investments/portfolio": portfolio}))

        result = result_of(await mcp.call_tool("get_portfolio", {}))

        assert result["holdings"][0]["last_price"] == "128.4567"
