from collections.abc import Callable

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError

from hydra_mcp.client import HydraClient
from tests.conftest import TOKEN, json_response

Responder = Callable[[Callable[[httpx.Request], httpx.Response]], HydraClient]


class TestGet:
    """Tests for reading from hydra."""

    async def test_returns_the_decoded_body(self, responder: Responder) -> None:
        client = responder(lambda _: json_response(200, {"count": 2}))

        assert await client.get("/accounts/", token=TOKEN, subject="account") == {"count": 2}

    async def test_forwards_the_credential_unchanged(self, responder: Responder) -> None:
        # The whole point of this process: it holds no credential, it carries
        # the caller's, and hydra decides what that reaches.
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers["authorization"])
            return json_response(200, {})

        await responder(handler).get("/accounts/", token=TOKEN, subject="account")

        assert seen == [f"Bearer {TOKEN}"]

    async def test_builds_the_url_below_the_api_root(self, responder: Responder) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return json_response(200, {})

        await responder(handler).get("/reports/summary", token=TOKEN, subject="month")

        assert seen == ["http://hydra.test/api/v1/reports/summary"]

    async def test_sends_the_parameters_that_were_given(self, responder: Responder) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.query.decode())
            return json_response(200, {})

        await responder(handler).get("/x", token=TOKEN, subject="x", params={"month": "2026-09"})

        assert seen == ["month=2026-09"]

    async def test_drops_the_parameters_that_were_not(self, responder: Responder) -> None:
        # A tool's optional arguments default to None, and "?month=None" would
        # be a 422 rather than the absence the caller meant.
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.query.decode())
            return json_response(200, {})

        await responder(handler).get("/x", token=TOKEN, subject="x", params={"month": None, "kind": "expense"})

        assert seen == ["kind=expense"]

    async def test_a_refused_credential_reaches_the_host(self, responder: Responder) -> None:
        client = responder(lambda _: json_response(401, {"detail": "no"}))

        with pytest.raises(MCPError):
            await client.get("/accounts/", token=TOKEN, subject="account")

    async def test_a_missing_thing_reaches_the_model(self, responder: Responder) -> None:
        client = responder(lambda _: json_response(404, {"detail": "Account not found."}))

        with pytest.raises(ToolError):
            await client.get("/accounts/x", token=TOKEN, subject="account")

    async def test_hydra_being_unreachable_is_its_own_answer(self, responder: Responder) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        with pytest.raises(ToolError, match="not answering"):
            await responder(handler).get("/accounts/", token=TOKEN, subject="account")


class TestAuthenticate:
    """Tests for checking a credential."""

    async def test_returns_the_user_hydra_reports(self, responder: Responder) -> None:
        client = responder(lambda _: json_response(200, {"id": "abc"}))

        assert await client.authenticate(TOKEN) == {"id": "abc"}

    @pytest.mark.parametrize("status_code", [401, 403])
    async def test_a_refusal_is_a_no_rather_than_an_error(self, responder: Responder, status_code: int) -> None:
        client = responder(lambda _: json_response(status_code, {"detail": "no"}))

        assert await client.authenticate(TOKEN) is None

    async def test_a_bad_day_at_hydra_is_not_the_same_as_a_no(self, responder: Responder) -> None:
        # Nothing here is a verdict on the credential, so it must not read as
        # one; it is also the only failure the verifier is written to catch.
        client = responder(lambda _: json_response(500, {"detail": "boom"}))

        with pytest.raises(ToolError, match="500"):
            await client.authenticate(TOKEN)

    async def test_being_unreachable_is_not_the_same_as_a_no(self, responder: Responder) -> None:
        # A token that cannot be checked has not been found wanting, and
        # saying so stops a network blip reading as a revocation.
        def handler(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        with pytest.raises(ToolError, match="not answering"):
            await responder(handler).authenticate(TOKEN)
