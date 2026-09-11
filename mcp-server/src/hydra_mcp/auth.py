import logging
import time

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.mcpserver.exceptions import ToolError

from .client import HydraClient
from .config import settings

# The prefix hydra puts on its API tokens. Anything without it is not a
# credential this server can do anything with, so it is refused without a
# round trip.
API_TOKEN_PREFIX = "hyd_"

READ_SCOPE = "hydra:read"

logger = logging.getLogger(__name__)


class HydraTokenVerifier(TokenVerifier):
    """Check a hydra API token by asking hydra.

    This server is not the authority on these tokens and deliberately holds no
    key that would let it be. It forwards the credential to the backend, which
    is the only place that can answer.

    The yes is remembered for a few seconds. An agent turn makes several tool
    calls, and checking each of them separately would be several identical
    round trips; the window is short because it is also how long a revoked
    token keeps working.
    """

    def __init__(self, client: HydraClient | None = None, cache_seconds: float | None = None) -> None:
        """Initialize the verifier.

        Args:
            client: The hydra client to check tokens with.
            cache_seconds: How long a checked token is trusted for.
        """
        self._client = client or HydraClient()
        self._cache_seconds = settings.TOKEN_CACHE_SECONDS if cache_seconds is None else cache_seconds
        self._cache: dict[str, tuple[float, AccessToken]] = {}
        self._swept_at = time.monotonic()

    async def verify_token(self, token: str) -> AccessToken | None:
        """Check a bearer token and say who it belongs to.

        Args:
            token: The bearer token the client presented.

        Returns:
            The access token to carry through the request, or None if the
            credential is not one hydra recognises.
        """
        if not token.startswith(API_TOKEN_PREFIX):
            return None

        cached = self._cached(token)
        if cached is not None:
            return cached

        try:
            user = await self._client.authenticate(token)
        except ToolError as exc:
            # hydra being unreachable is not the same as the token being bad,
            # but this runs before any tool, where there is nobody to tell:
            # the only answers available here are yes and no. Refusing is the
            # safe one, and the reason goes to the log rather than nowhere.
            # Never log the credential itself.
            logger.warning("Could not check an API token: %s", exc)
            return None

        if user is None:
            # A refusal is not cached. Somebody whose token was just minted
            # should not have to wait out a window they never benefited from.
            self._cache.pop(token, None)
            return None

        access_token = AccessToken(
            # Carried so a tool can read it back and present it to hydra. This
            # is the whole reason the credential never needs a global.
            token=token,
            client_id=str(user["id"]),
            subject=str(user["id"]),
            scopes=[READ_SCOPE],
            resource=str(settings.MCP_RESOURCE_URL),
        )
        self._sweep()
        self._cache[token] = (time.monotonic() + self._cache_seconds, access_token)
        return access_token

    def _sweep(self) -> None:
        """Drop the entries that have aged out.

        Without this a token is only ever forgotten when the same one is
        presented again, so a server that many clients reach holds every
        credential it has seen, in the clear, for as long as it runs. The
        sweep is cheap and rare: one pass, no more often than the window.
        """
        now = time.monotonic()
        if now - self._swept_at < self._cache_seconds:
            return

        self._swept_at = now
        for cached, (expires_at, _) in list(self._cache.items()):
            if now >= expires_at:
                del self._cache[cached]

    def _cached(self, token: str) -> AccessToken | None:
        """Read a token back out of the cache, if it is still fresh.

        Args:
            token: The bearer token the client presented.

        Returns:
            The remembered answer, or None if there is none or it has aged out.
        """
        entry = self._cache.get(token)
        if entry is None:
            return None

        expires_at, access_token = entry
        if time.monotonic() >= expires_at:
            del self._cache[token]
            return None

        return access_token
