import difflib
import uuid
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

# How close a name has to be before it is offered as "did you mean". Loose
# enough to catch a typo, tight enough not to suggest an unrelated category.
SUGGESTION_CUTOFF = 0.5
MAX_SUGGESTIONS = 3

# The largest page the API will serve. Asking for more is a 422, so a
# household with more than this is read a page at a time.
PAGE_SIZE = 200


class Named:
    """The named things of one household, looked up by name or by id.

    A model has "Groceries", not a UUID, so every tool takes names. Holding the
    lookup in one object means one fetch serves a whole tool call, and a miss
    can say what the household actually has rather than returning a bare 404.
    """

    def __init__(self, entries: dict[uuid.UUID, str], noun: str) -> None:
        """Initialize the lookup.

        Args:
            entries: The id of each thing, and what it is called.
            noun: What these are, for the error message: "account", "category".
        """
        self.noun = noun
        self.name_of = entries
        self._by_lowered = {name.lower(): entity_id for entity_id, name in entries.items()}

        # A child is held as "Parent > Child", but a caller will write
        # "Groceries". That is accepted whenever exactly one thing ends that
        # way; when two parents each have one, it stays ambiguous and the
        # caller is asked which, rather than being handed either.
        bare: dict[str, list[uuid.UUID]] = {}
        for entity_id, name in entries.items():
            bare.setdefault(name.rsplit(" > ", 1)[-1].lower(), []).append(entity_id)
        self._by_bare = {key: ids[0] for key, ids in bare.items() if len(ids) == 1}
        self._ambiguous = {key: ids for key, ids in bare.items() if len(ids) > 1}

    def name(self, entity_id: Any) -> str | None:
        """Get the name of a thing, for a response.

        Args:
            entity_id: The id as hydra reported it, or None.

        Returns:
            The name, or None if there is no id or it is not one of these.
        """
        if entity_id is None:
            return None

        return self.name_of.get(uuid.UUID(str(entity_id)))

    def id(self, name: str | None) -> uuid.UUID | None:
        """Resolve what a caller wrote into an id.

        Matching ignores case, and a UUID is accepted as itself, for a caller
        that already has one from an earlier result.

        Args:
            name: The name, or a UUID, or None.

        Returns:
            The id, or None if nothing was asked for.

        Raises:
            ToolError: If there is no such thing, naming the near misses.
        """
        if name is None:
            return None

        try:
            as_uuid = uuid.UUID(name)
        except ValueError:
            pass
        else:
            if as_uuid in self.name_of:
                return as_uuid
            raise ToolError(f"There is no {self.noun} with the id {name} in this household.")

        wanted = name.strip().lower()

        found = self._by_lowered.get(wanted) or self._by_bare.get(wanted)
        if found is not None:
            return found

        clashing = self._ambiguous.get(wanted)
        if clashing is not None:
            options = ", ".join(sorted(self.name_of[entity_id] for entity_id in clashing))
            raise ToolError(f"More than one {self.noun} is called '{name}'. Say which one: {options}.")

        raise ToolError(self._no_such(name))

    def _no_such(self, name: str) -> str:
        """Explain that a name matched nothing, helpfully.

        Args:
            name: What the caller wrote.

        Returns:
            A message naming the closest things, or everything if there are few.
        """
        known = list(self.name_of.values())
        if not known:
            return f"This household has no {self.noun} at all."

        # Compare against the short name as well as the qualified one. A
        # caller writing "Grocerys" is nowhere near "Food & Drink > Groceries"
        # by string distance, but it is one letter from "Groceries".
        by_bare = {full.rsplit(" > ", 1)[-1]: full for full in known}
        close = difflib.get_close_matches(name, list(by_bare), n=MAX_SUGGESTIONS, cutoff=SUGGESTION_CUTOFF)
        suggestions = [by_bare[match] for match in close] or sorted(known)[:MAX_SUGGESTIONS]
        lead = "Did you mean" if close else f"Some of the {self.noun} names are"

        return f"There is no {self.noun} called '{name}' in this household. {lead}: {', '.join(suggestions)}."


async def accounts_of(token: str) -> Named:
    """Look up the household's accounts by name.

    Args:
        token: The hydra API token to present.

    Returns:
        The accounts, by id and name.
    """
    from .tools._common import hydra

    # Paged through to the end rather than taking one large page. A household
    # over the page size would otherwise lose the rest silently, and a name in
    # the missing part would come back as "there is no account called that",
    # which reads as a wrong answer instead of a limit.
    entries: dict[uuid.UUID, str] = {}
    skip = 0
    while True:
        payload = await hydra().get(
            "/accounts/",
            token=token,
            subject="account",
            params={"include_archived": True, "skip": skip, "limit": PAGE_SIZE},
        )
        page = payload["data"]
        entries.update({uuid.UUID(a["id"]): a["name"] for a in page})
        skip += len(page)
        if not page or skip >= payload["count"]:
            break

    return Named(entries, "account")


async def categories_of(token: str) -> Named:
    """Look up the household's categories by name.

    A child is also reachable as "Parent > Child", because two parents may each
    have a child called the same thing and a bare name could then mean either.

    Args:
        token: The hydra API token to present.

    Returns:
        The categories, by id and name.
    """
    from .tools._common import hydra

    payload = await hydra().get("/categories/tree", token=token, subject="category", params={"include_archived": True})

    entries: dict[uuid.UUID, str] = {}
    for parent in payload["data"]:
        entries[uuid.UUID(parent["id"])] = parent["name"]
        for child in parent.get("children", []):
            entries[uuid.UUID(child["id"])] = f"{parent['name']} > {child['name']}"

    return Named(entries, "category")


def bare_name(qualified: str | None) -> str | None:
    """Take the child's own name out of a "Parent > Child" name.

    Args:
        qualified: The name as the lookup holds it, or None.

    Returns:
        The last part of it, or None.
    """
    if qualified is None:
        return None

    return qualified.rsplit(" > ", 1)[-1]
