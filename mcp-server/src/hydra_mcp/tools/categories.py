from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from pydantic import Field

from ._common import READ_ONLY, current_token, hydra


def register(mcp: MCPServer) -> None:
    """Register the category tools.

    Args:
        mcp: The server to register them on.
    """

    @mcp.tool(annotations=READ_ONLY)
    async def list_categories(
        kind: Annotated[
            Literal["expense", "income"] | None,
            Field(description="Only categories of this kind. Leave out for both."),
        ] = None,
        include_archived: Annotated[bool, Field(description="Include categories that have been archived.")] = False,
    ) -> dict[str, Any]:
        """List the household's spending and income categories.

        Categories are two levels deep. A child is written "Parent > Child",
        and that is the name every other tool accepts, so two parents can each
        have a "Other" without the name being ambiguous.

        Args:
            kind: Only categories of that kind, or both.
            include_archived: Whether archived categories are listed too.

        Returns:
            The categories, as a flat list of names.
        """
        payload = await hydra().get(
            "/categories/tree",
            token=current_token(),
            subject="category",
            params={"kind": kind, "include_archived": include_archived},
        )

        categories = []
        for parent in payload["data"]:
            categories.append(_category(parent, name=parent["name"]))
            for child in parent.get("children", []):
                categories.append(_category(child, name=f"{parent['name']} > {child['name']}"))

        return {"categories": categories, "count": len(categories)}


def _category(category: dict[str, Any], *, name: str) -> dict[str, Any]:
    """Describe one category.

    Args:
        category: The category as hydra reports it.
        name: The name other tools accept for it.

    Returns:
        The fields worth reading.
    """
    return {
        "name": name,
        "kind": category["kind"],
        "archived": category.get("archived_at") is not None,
    }
