from mcp.server import MCPServer

from . import accounts, reports


def register_all(mcp: MCPServer) -> None:
    """Register every tool on the server.

    Args:
        mcp: The server to register them on.
    """
    accounts.register(mcp)
    reports.register(mcp)
