import datetime
from typing import Annotated

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from ..client import HydraClient

# Every tool in this phase only reads. The hint is what lets a client tell its
# user that, rather than asking them to take it on trust.
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

# The month a report covers. Checked against the schema before the tool runs,
# so a month hydra would reject never becomes a request.
Month = Annotated[
    str | None,
    Field(
        default=None,
        description="The month, written as 2026-09. Leave it out for the current month.",
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
    ),
]

_client = HydraClient()


def hydra() -> HydraClient:
    """Get the client the tools read hydra through.

    Reached through a function rather than imported by name, so one client is
    shared by every tool and a test can still put its own in place of it.

    Returns:
        The client.
    """
    return _client


def use_client(client: HydraClient) -> None:
    """Replace the client the tools read hydra through.

    Args:
        client: The client to use from now on.
    """
    global _client
    _client = client


def current_token() -> str:
    """Get the hydra token this request arrived with.

    The verifier put it here, so a tool reads it back rather than this process
    holding a credential of its own.

    Returns:
        The token to present to hydra.

    Raises:
        ToolError: If the request somehow reached a tool unauthenticated.
    """
    access_token = get_access_token()
    if access_token is None:
        raise ToolError("This request carried no hydra API token.")

    return access_token.token


def this_month() -> str:
    """The month to use when a caller does not name one.

    Computed here rather than left to the caller, because hydra rejects a
    malformed month and a model guessing today's date is how one arises.

    Returns:
        The current month, as hydra writes them.
    """
    return datetime.date.today().strftime("%Y-%m")
