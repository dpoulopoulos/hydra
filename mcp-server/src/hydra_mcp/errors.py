from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_REQUEST

# Answers to a bad credential. Raised as MCPError rather than ToolError,
# because these reach the host rather than the model: no rewording of the
# arguments makes a revoked token work, so letting the model retry would only
# cost a turn.
TOKEN_REJECTED = "The hydra API token was rejected. It may have been revoked or expired; mint a new one in hydra."
NOT_PERMITTED = "That is not something a hydra API token is allowed to do."


def raise_for_status(response: httpx.Response, *, subject: str) -> None:
    """Turn a failing hydra response into the error the caller should see.

    Args:
        response: The response hydra sent.
        subject: What was being asked for, used in the not-found message.

    Raises:
        MCPError: If the credential was refused, which retrying cannot fix.
        ToolError: If the request could be made to work, which the model may
            be able to do by trying different arguments.
    """
    if response.is_success:
        return

    if response.status_code == httpx.codes.UNAUTHORIZED:
        raise MCPError(INVALID_REQUEST, TOKEN_REJECTED)

    if response.status_code == httpx.codes.FORBIDDEN:
        raise MCPError(INVALID_REQUEST, f"{NOT_PERMITTED} {_detail(response)}".strip())

    if response.status_code == httpx.codes.NOT_FOUND:
        raise ToolError(f"No such {subject} in this household. {_detail(response)}".strip())

    if response.status_code == httpx.codes.CONFLICT:
        raise ToolError(_detail(response))

    if response.status_code in (httpx.codes.BAD_REQUEST, httpx.codes.UNPROCESSABLE_ENTITY):
        raise ToolError(f"{_detail(response)} Fix the arguments and try again.")

    raise ToolError(f"hydra answered {response.status_code} and the request did not go through.")


def unavailable(exc: httpx.HTTPError) -> ToolError:
    """Describe hydra being unreachable.

    Told apart from a 4xx on purpose: nothing is wrong with the arguments, so
    the useful next move is to wait and repeat rather than to rewrite them.

    Args:
        exc: What httpx raised.

    Returns:
        The error to raise.
    """
    return ToolError(f"hydra's API is not answering ({type(exc).__name__}). Nothing was read or changed.")


def _detail(response: httpx.Response) -> str:
    """Read hydra's own explanation out of a failing response.

    The domain errors already say what went wrong and what to do about it, so
    they are passed through rather than replaced. FastAPI's own 422 is a list
    of per-field problems, which is flattened into lines.

    Args:
        response: The response hydra sent.

    Returns:
        The explanation, or an empty string if there is none to be had.
    """
    try:
        payload: Any = response.json()
    except ValueError:
        return ""

    if not isinstance(payload, dict):
        return ""

    detail = payload.get("detail")
    if isinstance(detail, str):
        return detail

    if isinstance(detail, list):
        return " ".join(_field_error(item) for item in detail if isinstance(item, dict))

    return ""


def _field_error(item: dict[str, Any]) -> str:
    """Describe one entry of a FastAPI validation error.

    Args:
        item: The entry, with its location and message.

    Returns:
        A line naming the argument and what is wrong with it.
    """
    location = ".".join(str(part) for part in item.get("loc", []) if part not in ("body", "query"))
    message = str(item.get("msg", "is not valid"))
    return f"{location}: {message}." if location else f"{message}."
