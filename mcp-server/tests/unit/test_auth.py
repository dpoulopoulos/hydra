from collections.abc import Callable

import httpx
import pytest

from hydra_mcp.auth import READ_SCOPE, HydraTokenVerifier
from hydra_mcp.client import HydraClient
from tests.conftest import TOKEN, json_response

OTHER_TOKEN = "hyd_fedcba9876543210_aDifferentSecretEntirelyForThisTest"

USER = {"id": "12345678-1234-5678-1234-567812345678", "email": "test@example.com"}

Responder = Callable[[Callable[[httpx.Request], httpx.Response]], HydraClient]


class TestVerifyToken:
    """Tests for checking a credential at the door."""

    async def test_accepts_a_token_hydra_recognises(self, responder: Responder) -> None:
        client = responder(lambda _: json_response(200, USER))

        access_token = await HydraTokenVerifier(client).verify_token(TOKEN)

        assert access_token is not None
        assert access_token.client_id == USER["id"]
        assert access_token.scopes == [READ_SCOPE]

    async def test_carries_the_credential_through_for_the_tools(self, responder: Responder) -> None:
        # This is the whole reason no part of this process holds a credential
        # in a global: a tool reads it back off the request it arrived on.
        client = responder(lambda _: json_response(200, USER))

        access_token = await HydraTokenVerifier(client).verify_token(TOKEN)

        assert access_token is not None
        assert access_token.token == TOKEN

    async def test_presents_the_credential_to_hydra(self, responder: Responder) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers["authorization"])
            return json_response(200, USER)

        await HydraTokenVerifier(responder(handler)).verify_token(TOKEN)

        assert seen == [f"Bearer {TOKEN}"]

    async def test_refuses_a_token_hydra_rejects(self, responder: Responder) -> None:
        client = responder(lambda _: json_response(401, {"detail": "The API token is not valid."}))

        assert await HydraTokenVerifier(client).verify_token(TOKEN) is None

    @pytest.mark.parametrize(
        "credential",
        ["", "eyJhbGciOiJIUzI1NiJ9.e30.signature", "Bearer hyd_x", "some-other-key"],
    )
    async def test_refuses_anything_without_the_prefix_without_asking(
        self, responder: Responder, credential: str
    ) -> None:
        # A session JWT is a credential hydra would accept, but not one this
        # server should take: it belongs to a browser and expires in days.
        def handler(_: httpx.Request) -> httpx.Response:
            raise AssertionError("hydra should not have been asked")

        assert await HydraTokenVerifier(responder(handler)).verify_token(credential) is None


class TestCache:
    """Tests for how long an answer is trusted."""

    async def test_asks_hydra_once_within_the_window(self, responder: Responder) -> None:
        calls: list[int] = []

        def handler(_: httpx.Request) -> httpx.Response:
            calls.append(1)
            return json_response(200, USER)

        verifier = HydraTokenVerifier(responder(handler), cache_seconds=60)
        await verifier.verify_token(TOKEN)
        await verifier.verify_token(TOKEN)

        assert len(calls) == 1

    async def test_asks_again_once_the_window_has_passed(self, responder: Responder) -> None:
        calls: list[int] = []

        def handler(_: httpx.Request) -> httpx.Response:
            calls.append(1)
            return json_response(200, USER)

        verifier = HydraTokenVerifier(responder(handler), cache_seconds=0)
        await verifier.verify_token(TOKEN)
        await verifier.verify_token(TOKEN)

        assert len(calls) == 2

    async def test_one_tokens_answer_is_not_another_tokens(self, responder: Responder) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.headers["authorization"].endswith("second"):
                return json_response(401, {"detail": "no"})
            return json_response(200, USER)

        verifier = HydraTokenVerifier(responder(handler), cache_seconds=60)

        assert await verifier.verify_token(TOKEN) is not None
        assert await verifier.verify_token("hyd_aaaaaaaaaaaaaaaa_second") is None

    async def test_a_refusal_is_not_remembered(self, responder: Responder) -> None:
        # Somebody who has just minted a token should not have to wait out a
        # window they never benefited from.
        answers = [json_response(401, {"detail": "no"}), json_response(200, USER)]

        def handler(_: httpx.Request) -> httpx.Response:
            return answers.pop(0)

        verifier = HydraTokenVerifier(responder(handler), cache_seconds=60)

        assert await verifier.verify_token(TOKEN) is None
        assert await verifier.verify_token(TOKEN) is not None


class TestNotHoldingEveryTokenForever:
    """Tests for the cache forgetting what it no longer needs."""

    async def test_drops_an_aged_out_token_without_being_shown_it_again(self, responder: Responder) -> None:
        # Otherwise a token is only ever forgotten when the same one comes
        # back, so a server many clients reach keeps every credential it has
        # seen, in the clear, for as long as it runs.
        verifier = HydraTokenVerifier(responder(lambda _: json_response(200, {"id": "a-user"})), cache_seconds=0)

        await verifier.verify_token(TOKEN)
        assert len(verifier._cache) == 1

        await verifier.verify_token(OTHER_TOKEN)

        assert list(verifier._cache) == [OTHER_TOKEN]

    async def test_leaves_a_token_that_is_still_fresh(self, responder: Responder) -> None:
        verifier = HydraTokenVerifier(responder(lambda _: json_response(200, {"id": "a-user"})), cache_seconds=60)

        await verifier.verify_token(TOKEN)
        await verifier.verify_token(OTHER_TOKEN)

        assert sorted(verifier._cache) == sorted([TOKEN, OTHER_TOKEN])


class TestHydraUnreachable:
    """Tests for what happens when the backend cannot be asked."""

    async def test_refuses_rather_than_crashing(self, responder: Responder) -> None:
        # This runs before any tool, where the only answers available are yes
        # and no. A raised error here would be a 500 on the transport rather
        # than a refusal the client can understand.
        def handler(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route")

        assert await HydraTokenVerifier(responder(handler)).verify_token(TOKEN) is None

    async def test_refuses_when_hydra_answers_badly(self, responder: Responder) -> None:
        # A 500 is not the token being wrong, but the only answers available
        # here are yes and no, so it has to be refused rather than raised.
        client = responder(lambda _: httpx.Response(500, json={"detail": "boom"}))

        assert await HydraTokenVerifier(client).verify_token(TOKEN) is None

    async def test_says_why_in_the_log_and_not_the_credential(
        self, responder: Responder, caplog: pytest.LogCaptureFixture
    ) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route")

        with caplog.at_level("WARNING"):
            await HydraTokenVerifier(responder(handler)).verify_token(TOKEN)

        assert "Could not check an API token" in caplog.text
        assert TOKEN not in caplog.text
