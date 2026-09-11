from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth import READ_SCOPE, HydraTokenVerifier
from .config import settings

INSTRUCTIONS = """\
These tools read and record one household's finances in hydra.

Most of them only read. The ones that change anything say so, and they need a \
token that was minted with write access: with a read token they are refused, \
and the refusal says as much. Ask the person before recording, changing or \
deleting anything they did not just ask for.

How money works here, which is the one thing worth knowing before reading a \
result or writing an amount:

- Every amount comes back three ways. `amount` is the number a person would \
write, `display` is that with its currency and sign, and `amount_minor` is the \
exact integer to do arithmetic with. Quote `display`; never re-derive it.
- Every amount states its currency. Never assume one.
- A single transaction is always a positive `amount`, when read and when \
written. Which way the money went is carried by its `kind`, and by which tool \
you call to record it, never by a minus sign. An expense leaves, income \
arrives, and a transfer moves money between two of the household's own \
accounts and is not spending at all. Never pass a negative amount; it is \
refused.
- Write amounts with the precision the currency has and no more. 10.005 euros \
is not an amount, and it is refused rather than rounded.
- A total is the exception, and is genuinely signed. `net` and `net_worth` are \
negative when more went out than came in.

Dates are ISO, and a month is written as 2026-09. Where a month is optional, \
leaving it out means the current one.
"""


def build_server() -> MCPServer:
    """Build the MCP server.

    Returns:
        A server with the tools registered and the hydra token verifier
        installed, ready to be run or mounted.
    """
    mcp: MCPServer = MCPServer(
        "hydra",
        title="hydra",
        instructions=INSTRUCTIONS,
        token_verifier=HydraTokenVerifier(),
        auth=AuthSettings(
            # hydra is not an OAuth authorization server, and these tokens are
            # opaque strings rather than JWTs. AuthSettings is used here as
            # what it is at this end: the hook that hands every bearer token
            # to the verifier before any tool runs.
            issuer_url=settings.HYDRA_API_BASE_URL,
            resource_server_url=settings.MCP_RESOURCE_URL,
            required_scopes=[READ_SCOPE],
            validate_token_resource=False,
        ),
    )

    # The SDK's custom_route carries no return annotation, so mypy cannot see
    # that what it gives back is still this function.
    @mcp.custom_route("/health", methods=["GET"], include_in_schema=False)  # type: ignore[untyped-decorator]
    async def health(_: Request) -> JSONResponse:
        """Report that the process is up and serving.

        Deliberately outside the authenticated surface: it is for whoever runs
        the server, not for its callers.

        Args:
            _: The request, which carries nothing this needs.

        Returns:
            A small JSON body saying the server is up.
        """
        return JSONResponse({"status": "ok"})

    from .tools import register_all

    register_all(mcp)

    return mcp


def main() -> None:
    """Run the server over streamable HTTP.

    Streamable HTTP rather than stdio, because stdio needs the client to start
    this process on the same machine, which a service running beside the
    backend cannot be.
    """
    build_server().run(
        transport="streamable-http",
        host=settings.MCP_HOST,
        port=settings.MCP_PORT,
        streamable_http_path=settings.MCP_PATH,
        # No session state is worth keeping across requests, and a container
        # that restarts or scales would lose it anyway.
        stateless_http=True,
    )


if __name__ == "__main__":
    main()
