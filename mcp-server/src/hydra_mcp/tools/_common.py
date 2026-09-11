import datetime
from typing import TYPE_CHECKING, Annotated, NamedTuple

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from ..client import HydraClient

if TYPE_CHECKING:
    from ..resolve import Named

# Every tool in this phase only reads. The hint is what lets a client tell its
# user that, rather than asking them to take it on trust.
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

# Adds a row. Not destructive, because nothing that was there is lost, but
# calling it twice makes two of them.
WRITES = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)

# Changes or removes a row that already exists. A client is expected to ask
# before running one of these without being told to.
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False)

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


class HouseholdContext(NamedTuple):
    """The household's names and currency, for one tool call."""

    accounts: "Named"
    categories: "Named"
    currency: str


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


async def household_context(token: str) -> "HouseholdContext":
    """Fetch what a tool needs to turn names into ids and back.

    Almost every tool needs the same three things, and fetching them together
    means one place decides how often that happens.

    Args:
        token: The hydra API token to present.

    Returns:
        The accounts, the categories, and the household currency.
    """
    from ..resolve import accounts_of, categories_of

    accounts = await accounts_of(token)
    categories = await categories_of(token)
    household = await hydra().get("/households/me", token=token, subject="household")

    return HouseholdContext(accounts=accounts, categories=categories, currency=household["currency_code"])


def as_str(value: object) -> str | None:
    """Render a resolved id for a query string or a request body.

    Args:
        value: The id, or None.

    Returns:
        The id as text, or None.
    """
    return None if value is None else str(value)


def this_month() -> str:
    """The month to use when a caller does not name one.

    Computed here rather than left to the caller, because hydra rejects a
    malformed month and a model guessing today's date is how one arises.

    Returns:
        The current month, as hydra writes them.
    """
    return datetime.date.today().strftime("%Y-%m")
