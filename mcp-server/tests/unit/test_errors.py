import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError

from hydra_mcp.errors import raise_for_status, unavailable


def response(status_code: int, payload: object = None) -> httpx.Response:
    """Build a response with an optional JSON body."""
    if payload is None:
        return httpx.Response(status_code)
    return httpx.Response(status_code, json=payload)


class TestCredentialRefused:
    """A bad credential is the host's problem, not the model's."""

    def test_a_401_is_a_protocol_error(self) -> None:
        # Raised so the model never sees it: no rewording of the arguments
        # makes a revoked token work, so a retry would only cost a turn.
        with pytest.raises(MCPError, match="revoked or expired"):
            raise_for_status(response(401), subject="account")

    def test_a_403_is_a_protocol_error(self) -> None:
        with pytest.raises(MCPError, match="not something a hydra API token is allowed to do"):
            raise_for_status(response(403, {"detail": "This API token is read only."}), subject="account")

    def test_the_credential_never_appears_in_the_message(self) -> None:
        with pytest.raises(MCPError) as caught:
            raise_for_status(response(401), subject="account")

        assert "hyd_" not in str(caught.value)


class TestRecoverable:
    """Everything the model could fix comes back as a tool error."""

    def test_a_404_names_what_was_missing(self) -> None:
        with pytest.raises(ToolError, match="No such account"):
            raise_for_status(response(404, {"detail": "Account not found."}), subject="account")

    def test_a_409_passes_hydras_own_explanation_through(self) -> None:
        # The domain messages already say what the invariant is and what to do
        # about it, so replacing them would only lose information.
        with pytest.raises(ToolError, match="still has transactions"):
            raise_for_status(response(409, {"detail": "Account 'Current' still has transactions."}), subject="account")

    def test_a_422_is_flattened_into_lines_and_says_what_to_do(self) -> None:
        with pytest.raises(ToolError, match=r"month: string does not match.*Fix the arguments"):
            raise_for_status(
                response(
                    422,
                    {"detail": [{"loc": ["query", "month"], "msg": "string does not match pattern"}]},
                ),
                subject="month",
            )

    def test_a_500_says_the_request_did_not_go_through(self) -> None:
        with pytest.raises(ToolError, match="did not go through"):
            raise_for_status(response(500), subject="account")

    def test_a_body_that_is_not_json_is_survivable(self) -> None:
        with pytest.raises(ToolError):
            raise_for_status(httpx.Response(404, text="<html>nope</html>"), subject="account")

    def test_being_unreachable_is_told_apart_from_being_refused(self) -> None:
        # A different answer, because the useful next move is to wait and
        # repeat rather than to rewrite the arguments.
        error = unavailable(httpx.ConnectError("refused"))

        assert "not answering" in str(error)
        assert "Nothing was read or changed" in str(error)


class TestSuccess:
    """A good response raises nothing."""

    @pytest.mark.parametrize("status_code", [200, 201, 204])
    def test_passes_a_success_through(self, status_code: int) -> None:
        raise_for_status(httpx.Response(status_code), subject="account")
