import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_category_service, get_current_user, get_db, get_household_context
from app.exceptions import (
    CategoryDepthExceededError,
    CategoryExistsError,
    CategoryInUseError,
    CategoryLimitReachedError,
    CategoryNotFoundError,
    SystemCategoryError,
)
from app.main import app
from app.models import (
    CategoriesPublic,
    CategoryKind,
    CategoryPublic,
    CategoryTreeNode,
    CategoryTreePublic,
    HouseholdContext,
    Message,
    User,
)
from app.models.category import MAX_SORT_ORDER
from app.services.category import MAX_CATEGORIES

CATEGORY_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


def make_public(name: str = "Food & Drink", parent_id: uuid.UUID | None = None) -> CategoryPublic:
    """Build a category response payload."""
    return CategoryPublic(
        id=CATEGORY_ID,
        household_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        name=name,
        kind=CategoryKind.EXPENSE,
        parent_id=parent_id,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def wire(mock_db_session: MagicMock, test_user: User, household_context: HouseholdContext) -> Generator[MagicMock]:
    """Override the database, the current user, the household scope and the service.

    Yields:
        A mock category service the test can program.
    """
    service = MagicMock()

    def override_get_db() -> Generator[MagicMock]:
        yield mock_db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_household_context] = lambda: household_context
    app.dependency_overrides[get_category_service] = lambda: service

    yield service

    app.dependency_overrides.clear()


class TestCreateCategory:
    """Tests for POST /categories/."""

    def test_creates_a_category(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        wire.create_category.return_value = make_public(name="Boats")

        response = client.post("/api/v1/categories/", headers=auth_headers, json={"name": "Boats"})

        assert response.status_code == 200
        assert response.json()["name"] == "Boats"

    def test_reports_a_duplicate_name_as_a_conflict(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.create_category.side_effect = CategoryExistsError(name="Boats")

        response = client.post("/api/v1/categories/", headers=auth_headers, json={"name": "Boats"})

        assert response.status_code == 409

    def test_reports_a_full_category_tree_as_a_conflict(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.create_category.side_effect = CategoryLimitReachedError(limit=MAX_CATEGORIES)

        response = client.post("/api/v1/categories/", headers=auth_headers, json={"name": "Boats"})

        assert response.status_code == 409

    def test_reports_a_third_level_as_a_bad_request(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.create_category.side_effect = CategoryDepthExceededError

        response = client.post(
            "/api/v1/categories/",
            headers=auth_headers,
            json={"name": "Apples", "parent_id": str(uuid.uuid4())},
        )

        assert response.status_code == 400

    @pytest.mark.parametrize("sort_order", [MAX_SORT_ORDER + 1, -1])
    def test_rejects_an_order_outside_the_range(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str], sort_order: int
    ) -> None:
        """The column is a plain integer, so an out-of-range order is a 422, not a 500."""
        response = client.post(
            "/api/v1/categories/",
            headers=auth_headers,
            json={"name": "Boats", "sort_order": sort_order},
        )

        assert response.status_code == 422


class TestListCategories:
    """Tests for GET /categories/."""

    def test_returns_the_categories(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        wire.list_categories.return_value = CategoriesPublic(data=[make_public()], count=1)

        response = client.get("/api/v1/categories/", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["count"] == 1

    def test_passes_the_filters_through(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.list_categories.return_value = CategoriesPublic(data=[], count=0)
        parent_id = uuid.uuid4()

        response = client.get(
            "/api/v1/categories/",
            headers=auth_headers,
            params={"include_archived": "true", "kind": "income", "parent_id": str(parent_id)},
        )

        assert response.status_code == 200
        kwargs = wire.list_categories.call_args.kwargs
        assert kwargs["include_archived"] is True
        assert kwargs["kind"] is CategoryKind.INCOME
        assert kwargs["parent_id"] == parent_id

    def test_a_parent_filter_from_another_household_is_not_found(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.list_categories.side_effect = CategoryNotFoundError

        response = client.get("/api/v1/categories/", headers=auth_headers, params={"parent_id": str(uuid.uuid4())})

        assert response.status_code == 404

    def test_rejects_an_unknown_kind(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        response = client.get("/api/v1/categories/", headers=auth_headers, params={"kind": "nonsense"})

        assert response.status_code == 422


class TestGetCategoryTree:
    """Tests for GET /categories/tree."""

    def test_returns_the_tree(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        wire.get_category_tree.return_value = CategoryTreePublic(
            data=[CategoryTreeNode.model_validate(make_public(), update={"children": [make_public(name="Groceries")]})],
            count=2,
        )

        response = client.get("/api/v1/categories/tree", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["data"][0]["children"][0]["name"] == "Groceries"

    def test_tree_is_not_parsed_as_a_category_id(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        """The literal "tree" path must win over the {category_id} path."""
        wire.get_category_tree.return_value = CategoryTreePublic(data=[], count=0)

        response = client.get("/api/v1/categories/tree", headers=auth_headers)

        assert response.status_code != 422
        wire.get_category.assert_not_called()


class TestGetCategory:
    """Tests for GET /categories/{category_id}."""

    def test_returns_the_category(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        wire.get_category.return_value = make_public()

        response = client.get(f"/api/v1/categories/{CATEGORY_ID}", headers=auth_headers)

        assert response.status_code == 200

    def test_a_category_from_another_household_is_not_found(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        """A foreign ID reads as 404, never 403, so the API does not leak which IDs exist."""
        wire.get_category.side_effect = CategoryNotFoundError

        response = client.get(f"/api/v1/categories/{uuid.uuid4()}", headers=auth_headers)

        assert response.status_code == 404


class TestUpdateCategory:
    """Tests for PATCH /categories/{category_id}."""

    def test_updates_the_category(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        wire.update_category.return_value = make_public(name="Eating")

        response = client.patch(f"/api/v1/categories/{CATEGORY_ID}", headers=auth_headers, json={"name": "Eating"})

        assert response.status_code == 200
        assert wire.update_category.call_args.kwargs["category_update"].name == "Eating"

    def test_archiving_is_sent_as_a_flag(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.update_category.return_value = make_public()

        response = client.patch(f"/api/v1/categories/{CATEGORY_ID}", headers=auth_headers, json={"is_archived": True})

        assert response.status_code == 200
        assert wire.update_category.call_args.kwargs["category_update"].is_archived is True

    def test_refuses_to_change_a_system_category(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.update_category.side_effect = SystemCategoryError

        response = client.patch(f"/api/v1/categories/{CATEGORY_ID}", headers=auth_headers, json={"name": "Misc"})

        assert response.status_code == 400

    def test_rejects_an_order_beyond_the_range(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.patch(
            f"/api/v1/categories/{CATEGORY_ID}",
            headers=auth_headers,
            json={"sort_order": MAX_SORT_ORDER + 1},
        )

        assert response.status_code == 422


class TestDeleteCategory:
    """Tests for DELETE /categories/{category_id}."""

    def test_deletes_the_category(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        wire.delete_category.return_value = Message(message="Category deleted.")

        response = client.delete(f"/api/v1/categories/{CATEGORY_ID}", headers=auth_headers)

        assert response.status_code == 200

    def test_reports_a_category_still_in_use_as_a_conflict(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.delete_category.side_effect = CategoryInUseError(name="Food & Drink")

        response = client.delete(f"/api/v1/categories/{CATEGORY_ID}", headers=auth_headers)

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "still in use" in detail
        assert "already exists" not in detail
