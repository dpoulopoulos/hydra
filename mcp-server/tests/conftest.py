from collections.abc import Callable
from typing import Any

import httpx
import pytest

from hydra_mcp.client import HydraClient

TOKEN = "hyd_0123456789abcdef_aSecretNobodyElseWillEverSee"


@pytest.fixture
def responder() -> Callable[[Callable[[httpx.Request], httpx.Response]], HydraClient]:
    """Build a hydra client answered by a function rather than by a backend.

    Returns:
        A factory taking the handler and giving back a client wired to it.
    """

    def build(handler: Callable[[httpx.Request], httpx.Response]) -> HydraClient:
        return HydraClient(base_url="http://hydra.test/api/v1", transport=httpx.MockTransport(handler))

    return build


def json_response(status_code: int, payload: Any) -> httpx.Response:
    """Build a response carrying a JSON body.

    Args:
        status_code: The status to answer with.
        payload: The body to encode.

    Returns:
        The response.
    """
    return httpx.Response(status_code, json=payload)
