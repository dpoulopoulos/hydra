from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from .config import settings
from .errors import raise_for_status, unavailable


class HydraClient:
    """Talk to hydra's REST API on behalf of whoever presented the token.

    The client holds no credential of its own. Every call carries the token
    the caller arrived with, so the household a request can reach is decided
    by hydra, from that token, and never by this process.
    """

    def __init__(self, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """Initialize the client.

        Args:
            base_url: The API root to talk to. Defaults to the configured one.
            transport: An alternative transport, which is how the tests stand
                in for a live backend.
        """
        self.base_url = (base_url or settings.api_root).rstrip("/")
        self._transport = transport

    async def get(self, path: str, *, token: str, subject: str, params: dict[str, Any] | None = None) -> Any:
        """Make a GET request and return the decoded body.

        Args:
            path: The path below the API root, starting with a slash.
            token: The hydra API token to present.
            subject: What is being asked for, used if hydra says it is missing.
            params: Query parameters. Entries with a value of None are dropped,
                so a tool can pass its optional arguments straight through.

        Returns:
            The decoded response body.

        Raises:
            MCPError: If the token was refused.
            ToolError: If the request failed in a way that could be retried.
        """
        return await self._request("GET", path, token=token, subject=subject, params=params)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        subject: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Make a request and return the decoded body.

        Args:
            method: The HTTP method.
            path: The path below the API root, starting with a slash.
            token: The hydra API token to present.
            subject: What is being asked for, used if hydra says it is missing.
            params: Query parameters, with None valued entries dropped.
            json: A request body, if the method takes one.

        Returns:
            The decoded response body.

        Raises:
            MCPError: If the token was refused.
            ToolError: If the request failed in a way that could be retried.
        """
        async with self._client() as client:
            try:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    params=_clean(params),
                    json=json,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError as exc:
                raise unavailable(exc) from exc

        raise_for_status(response, subject=subject)
        return response.json()

    async def authenticate(self, token: str) -> dict[str, Any] | None:
        """Ask hydra who a token belongs to.

        Used to check a credential before any tool runs, so a bad token is one
        refusal at the door rather than a failure inside every tool.

        Args:
            token: The hydra API token to check.

        Returns:
            The user hydra reports, or None if it refused the token.

        Raises:
            ToolError: If hydra could not be reached, or answered something
                that is not an answer about the token. Neither is the same as
                "this token is no good", and the caller has to tell them
                apart: one refuses the client, the other is hydra being down.
        """
        async with self._client() as client:
            try:
                response = await client.get(
                    f"{self.base_url}/users/me",
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError as exc:
                raise unavailable(exc) from exc

        if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
            return None

        if not response.is_success:
            # Anything else is hydra having a bad day rather than a verdict on
            # the credential. Raised as the same ToolError an unreachable hydra
            # gives, so the one caller has one failure to handle.
            raise ToolError(f"hydra answered {response.status_code} when asked to check a token.")

        decoded: dict[str, Any] = response.json()
        return decoded

    def _client(self) -> httpx.AsyncClient:
        """Build a client for one exchange.

        Returns:
            An httpx client, using the injected transport when there is one.
        """
        return httpx.AsyncClient(
            timeout=settings.HYDRA_REQUEST_TIMEOUT_SECONDS,
            transport=self._transport,
        )


def _clean(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop the parameters that were not given.

    A tool's optional arguments default to None, and sending "?month=None"
    would be a 422 rather than the absence the caller meant.

    Args:
        params: The parameters as the tool assembled them.

    Returns:
        The parameters that were actually given, or None if there are none.
    """
    if params is None:
        return None

    return {key: value for key, value in params.items() if value is not None}
