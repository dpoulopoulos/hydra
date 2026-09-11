import uuid

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from hydra_mcp.client import HydraClient
from hydra_mcp.resolve import PAGE_SIZE, Named, accounts_of, bare_name
from hydra_mcp.tools import _common
from tests.conftest import TOKEN, json_response

FOOD = uuid.UUID("11111111-1111-1111-1111-111111111111")
GROCERIES = uuid.UUID("22222222-2222-2222-2222-222222222222")
HOME = uuid.UUID("33333333-3333-3333-3333-333333333333")
HOME_OTHER = uuid.UUID("44444444-4444-4444-4444-444444444444")
FOOD_OTHER = uuid.UUID("55555555-5555-5555-5555-555555555555")


@pytest.fixture
def categories() -> Named:
    """A household with two parents, one of which has a uniquely named child."""
    return Named(
        {
            FOOD: "Food & Drink",
            GROCERIES: "Food & Drink > Groceries",
            HOME: "Home",
            HOME_OTHER: "Home > Other",
            FOOD_OTHER: "Food & Drink > Other",
        },
        "category",
    )


class TestResolvingAName:
    """Tests for turning what a caller wrote into an id."""

    def test_finds_a_parent(self, categories: Named) -> None:
        assert categories.id("Food & Drink") == FOOD

    def test_finds_a_child_by_its_full_name(self, categories: Named) -> None:
        assert categories.id("Food & Drink > Groceries") == GROCERIES

    def test_finds_a_child_by_its_own_name(self, categories: Named) -> None:
        # A model writes "Groceries", not the path to it.
        assert categories.id("Groceries") == GROCERIES

    def test_ignores_case_and_surrounding_space(self, categories: Named) -> None:
        assert categories.id("  groceries ") == GROCERIES

    def test_accepts_an_id_it_already_has(self, categories: Named) -> None:
        assert categories.id(str(GROCERIES)) == GROCERIES

    def test_nothing_asked_for_is_not_an_error(self, categories: Named) -> None:
        assert categories.id(None) is None


class TestWhenTheNameDoesNotMatch:
    """Tests for the message a miss produces."""

    def test_a_typo_is_offered_the_thing_it_nearly_wrote(self, categories: Named) -> None:
        # "Grocerys" is nowhere near "Food & Drink > Groceries" by string
        # distance, so the suggestion has to compare the short name.
        with pytest.raises(ToolError, match="Did you mean: Food & Drink > Groceries"):
            categories.id("Grocerys")

    def test_something_unrelated_is_shown_what_exists(self, categories: Named) -> None:
        with pytest.raises(ToolError, match="Some of the category names are"):
            categories.id("Zzzzzzzz")

    def test_an_unknown_id_says_so_plainly(self, categories: Named) -> None:
        with pytest.raises(ToolError, match="no category with the id"):
            categories.id(str(uuid.uuid4()))

    def test_an_empty_household_says_it_is_empty(self) -> None:
        with pytest.raises(ToolError, match="no account at all"):
            Named({}, "account").id("Current")


class TestWhenTwoThingsShareAName:
    """Tests for a short name that could mean either of two things."""

    def test_refuses_to_pick_one(self, categories: Named) -> None:
        with pytest.raises(ToolError, match="More than one category is called 'Other'"):
            categories.id("Other")

    def test_says_which_ones_it_could_be(self, categories: Named) -> None:
        with pytest.raises(ToolError, match="Food & Drink > Other, Home > Other"):
            categories.id("Other")

    def test_the_full_name_still_works(self, categories: Named) -> None:
        assert categories.id("Home > Other") == HOME_OTHER


class TestNamingAnId:
    """Tests for the other direction, used when building a response."""

    def test_names_a_thing(self, categories: Named) -> None:
        assert categories.name(str(GROCERIES)) == "Food & Drink > Groceries"

    def test_no_id_is_no_name(self, categories: Named) -> None:
        assert categories.name(None) is None

    def test_an_id_from_elsewhere_is_no_name(self, categories: Named) -> None:
        assert categories.name(str(uuid.uuid4())) is None


class TestBareName:
    """Tests for shortening a qualified name."""

    def test_drops_the_parent(self) -> None:
        assert bare_name("Food & Drink > Groceries") == "Groceries"

    def test_leaves_a_parent_alone(self) -> None:
        assert bare_name("Food & Drink") == "Food & Drink"

    def test_passes_nothing_through(self) -> None:
        assert bare_name(None) is None


class TestReadingTheAccounts:
    """Tests for fetching the account lookup."""

    async def test_reads_past_the_first_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A household larger than one page used to lose the rest, and a name
        # in the missing part came back as "there is no account called that",
        # which reads as a wrong answer rather than as a limit.
        total = PAGE_SIZE + 3
        names = [f"Account {index}" for index in range(total)]
        ids = [str(uuid.uuid4()) for _ in names]

        def handler(request: httpx.Request) -> httpx.Response:
            skip = int(request.url.params.get("skip", 0))
            limit = int(request.url.params.get("limit", PAGE_SIZE))
            page = [{"id": ids[i], "name": names[i]} for i in range(skip, min(skip + limit, total))]
            return json_response(200, {"data": page, "count": total})

        monkeypatch.setattr(
            _common,
            "_client",
            HydraClient(base_url="http://hydra.test/api/v1", transport=httpx.MockTransport(handler)),
        )

        accounts = await accounts_of(TOKEN)

        assert len(accounts.name_of) == total
        assert accounts.id(names[-1]) == uuid.UUID(ids[-1])

    async def test_stops_when_the_page_comes_back_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A count that does not match what is served would otherwise be an
        # endless loop rather than a short answer.
        def handler(_: httpx.Request) -> httpx.Response:
            return json_response(200, {"data": [], "count": 99})

        monkeypatch.setattr(
            _common,
            "_client",
            HydraClient(base_url="http://hydra.test/api/v1", transport=httpx.MockTransport(handler)),
        )

        assert (await accounts_of(TOKEN)).name_of == {}
