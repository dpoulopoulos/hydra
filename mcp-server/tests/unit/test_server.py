import pytest
from mcp.server import MCPServer

from hydra_mcp.auth import READ_SCOPE, HydraTokenVerifier
from hydra_mcp.server import build_server

READS = {
    "whoami",
    "list_accounts",
    "list_categories",
    "search_transactions",
    "get_transaction",
    "list_budgets",
    "get_budget_progress",
    "get_month_summary",
    "get_spending_by_category",
    "get_spending_over_time",
    "get_income_vs_expense",
    "list_recurring_rules",
    "get_upcoming_recurring",
    "get_portfolio",
}

WRITES = {
    "record_expense",
    "record_income",
    "record_transfer",
    "update_transaction",
    "delete_transaction",
    "set_budget",
}

# The subset of the writes that change or remove something already recorded,
# rather than only adding to it.
DESTRUCTIVE = {"update_transaction", "delete_transaction"}


@pytest.fixture(scope="module")
def server() -> MCPServer:
    """Build the server once, the way main() does."""
    return build_server()


class TestBuildServer:
    """Tests for the wiring, which only fails over the wire otherwise."""

    async def test_registers_the_tools(self, server: MCPServer) -> None:
        names = {tool.name for tool in await server.list_tools()}

        assert names == READS | WRITES

    async def test_a_reading_tool_says_it_only_reads(self, server: MCPServer) -> None:
        # Which is how a client tells its user that nothing will change.
        for tool in await server.list_tools():
            if tool.name in READS:
                assert tool.annotations is not None, tool.name
                assert tool.annotations.read_only_hint is True, tool.name

    async def test_a_writing_tool_never_claims_otherwise(self, server: MCPServer) -> None:
        # A write hinted as read-only is the one mislabelling that matters: a
        # client would stop asking before running it.
        for tool in await server.list_tools():
            if tool.name in WRITES:
                assert tool.annotations is not None, tool.name
                assert tool.annotations.read_only_hint is False, tool.name

    async def test_changing_or_deleting_is_marked_destructive(self, server: MCPServer) -> None:
        for tool in await server.list_tools():
            if tool.name in DESTRUCTIVE:
                assert tool.annotations is not None, tool.name
                assert tool.annotations.destructive_hint is True, tool.name

    def test_installs_the_hydra_token_verifier(self, server: MCPServer) -> None:
        # Without it the server would serve every caller as if authenticated.
        assert isinstance(server._token_verifier, HydraTokenVerifier)

    def test_requires_the_read_scope(self, server: MCPServer) -> None:
        assert server.settings.auth is not None
        assert server.settings.auth.required_scopes == [READ_SCOPE]

    def test_does_not_check_a_resource_the_tokens_do_not_carry(self, server: MCPServer) -> None:
        # hydra's tokens are opaque strings with no audience claim, so asking
        # the middleware to match one would refuse every request.
        assert server.settings.auth is not None
        assert server.settings.auth.validate_token_resource is False

    def test_tells_the_model_how_money_is_reported(self, server: MCPServer) -> None:
        assert server.instructions is not None
        assert "positive" in server.instructions
        assert "currency" in server.instructions

    def test_serves_an_unauthenticated_health_check(self, server: MCPServer) -> None:
        # Compose and Railway need it, and neither carries a token.
        paths = {getattr(route, "path", None) for route in server.streamable_http_app().routes}

        assert "/health" in paths
