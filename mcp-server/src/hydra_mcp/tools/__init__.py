from mcp.server import MCPServer

from . import accounts, budgets, categories, investments, recurring, reports, transactions


def register_all(mcp: MCPServer) -> None:
    """Register every tool on the server.

    Args:
        mcp: The server to register them on.
    """
    accounts.register(mcp)
    categories.register(mcp)
    transactions.register(mcp)
    budgets.register(mcp)
    reports.register(mcp)
    recurring.register(mcp)
    investments.register(mcp)
