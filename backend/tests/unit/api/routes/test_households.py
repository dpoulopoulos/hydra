import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db, get_household_context, get_household_service
from app.exceptions import (
    HouseholdMemberNotFoundError,
    HouseholdMembershipNotFoundError,
    HouseholdNotFoundError,
    LastHouseholdOwnerError,
)
from app.main import app
from app.models import (
    HouseholdContext,
    HouseholdMemberPublic,
    HouseholdMembersPublic,
    HouseholdPublic,
    HouseholdRole,
    Message,
    User,
)

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
MEMBERSHIP_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def owner_context(test_user: User) -> HouseholdContext:
    """Build an owner household context for the test user."""
    return HouseholdContext(
        user=test_user, household_id=HOUSEHOLD_ID, membership_id=MEMBERSHIP_ID, role=HouseholdRole.OWNER
    )


@pytest.fixture
def member_context(test_user: User) -> HouseholdContext:
    """Build a non-owner household context for the test user."""
    return HouseholdContext(
        user=test_user, household_id=HOUSEHOLD_ID, membership_id=MEMBERSHIP_ID, role=HouseholdRole.MEMBER
    )


@pytest.fixture
def household_public() -> HouseholdPublic:
    """Build a household response payload."""
    return HouseholdPublic(
        id=HOUSEHOLD_ID,
        name="Test household",
        currency_code="EUR",
        member_count=2,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def wire(mock_db_session: MagicMock, test_user: User) -> Generator[MagicMock]:
    """Override the database, the current user and the household service.

    Yields:
        A mock household service the test can program.
    """
    service = MagicMock()

    def override_get_db() -> Generator[MagicMock]:
        yield mock_db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_household_service] = lambda: service

    yield service

    app.dependency_overrides.clear()


def use_context(context: HouseholdContext) -> None:
    """Pin the household context the routes resolve to.

    Args:
        context: The context every request should see.
    """
    app.dependency_overrides[get_household_context] = lambda: context


class TestGetHouseholdMe:
    """Tests for GET /households/me."""

    def test_returns_the_household(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        owner_context: HouseholdContext,
        household_public: HouseholdPublic,
    ) -> None:
        use_context(owner_context)
        wire.get_household.return_value = household_public

        response = client.get("/api/v1/households/me", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["name"] == "Test household"
        assert response.json()["member_count"] == 2

    def test_returns_404_when_the_user_has_no_household(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        def raise_missing() -> HouseholdContext:
            raise HouseholdMembershipNotFoundError

        app.dependency_overrides[get_household_context] = raise_missing

        response = client.get("/api/v1/households/me", headers=auth_headers)

        assert response.status_code == 404

    def test_returns_404_when_the_household_is_gone(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        owner_context: HouseholdContext,
    ) -> None:
        use_context(owner_context)
        wire.get_household.side_effect = HouseholdNotFoundError

        response = client.get("/api/v1/households/me", headers=auth_headers)

        assert response.status_code == 404


class TestUpdateHouseholdMe:
    """Tests for PATCH /households/me."""

    def test_an_owner_may_rename_the_household(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        owner_context: HouseholdContext,
        household_public: HouseholdPublic,
    ) -> None:
        use_context(owner_context)
        wire.update_household.return_value = household_public

        response = client.patch("/api/v1/households/me", headers=auth_headers, json={"name": "Renamed"})

        assert response.status_code == 200
        assert wire.update_household.call_args.kwargs["household_update"].name == "Renamed"

    def test_a_member_may_not_rename_the_household(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        member_context: HouseholdContext,
    ) -> None:
        use_context(member_context)

        response = client.patch("/api/v1/households/me", headers=auth_headers, json={"name": "Renamed"})

        assert response.status_code == 403
        wire.update_household.assert_not_called()


class TestListHouseholdMembers:
    """Tests for GET /households/me/members."""

    def test_returns_the_members(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        member_context: HouseholdContext,
        test_user: User,
    ) -> None:
        use_context(member_context)
        wire.list_members.return_value = HouseholdMembersPublic(
            data=[
                HouseholdMemberPublic(
                    id=MEMBERSHIP_ID,
                    household_id=HOUSEHOLD_ID,
                    user_id=test_user.id,
                    email=test_user.email,
                    full_name=test_user.full_name,
                    role=HouseholdRole.OWNER,
                    created_at=datetime.now(UTC),
                )
            ],
            count=1,
        )

        response = client.get("/api/v1/households/me/members", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["count"] == 1
        assert response.json()["data"][0]["email"] == test_user.email


class TestLeaveHousehold:
    """Tests for DELETE /households/me/members/me."""

    def test_a_member_may_leave(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        member_context: HouseholdContext,
    ) -> None:
        use_context(member_context)
        wire.leave_household.return_value = Message(message="You have left the household.")

        response = client.delete("/api/v1/households/me/members/me", headers=auth_headers)

        assert response.status_code == 200
        wire.leave_household.assert_called_once()

    def test_the_route_is_not_parsed_as_a_user_id(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        member_context: HouseholdContext,
    ) -> None:
        """The literal "me" path must win over the {user_id} path."""
        use_context(member_context)
        wire.leave_household.return_value = Message(message="You have left the household.")

        response = client.delete("/api/v1/households/me/members/me", headers=auth_headers)

        assert response.status_code != 422
        wire.remove_member.assert_not_called()

    def test_the_last_owner_may_not_leave(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        owner_context: HouseholdContext,
    ) -> None:
        use_context(owner_context)
        wire.leave_household.side_effect = LastHouseholdOwnerError

        response = client.delete("/api/v1/households/me/members/me", headers=auth_headers)

        assert response.status_code == 400


class TestUpdateHouseholdMember:
    """Tests for PATCH /households/me/members/{user_id}."""

    def test_an_owner_may_change_a_role(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        owner_context: HouseholdContext,
        another_test_user: User,
    ) -> None:
        use_context(owner_context)
        wire.update_member.return_value = HouseholdMemberPublic(
            id=uuid.uuid4(),
            household_id=HOUSEHOLD_ID,
            user_id=another_test_user.id,
            email=another_test_user.email,
            role=HouseholdRole.OWNER,
            created_at=datetime.now(UTC),
        )

        response = client.patch(
            f"/api/v1/households/me/members/{another_test_user.id}",
            headers=auth_headers,
            json={"role": "owner"},
        )

        assert response.status_code == 200
        assert response.json()["role"] == "owner"

    def test_a_member_may_not_change_a_role(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        member_context: HouseholdContext,
        another_test_user: User,
    ) -> None:
        use_context(member_context)

        response = client.patch(
            f"/api/v1/households/me/members/{another_test_user.id}",
            headers=auth_headers,
            json={"role": "owner"},
        )

        assert response.status_code == 403

    def test_a_user_from_another_household_is_not_found(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        owner_context: HouseholdContext,
    ) -> None:
        """A user ID outside the household reads as 404, never 403."""
        use_context(owner_context)
        wire.update_member.side_effect = HouseholdMemberNotFoundError

        response = client.patch(
            f"/api/v1/households/me/members/{uuid.uuid4()}",
            headers=auth_headers,
            json={"role": "member"},
        )

        assert response.status_code == 404


class TestRemoveHouseholdMember:
    """Tests for DELETE /households/me/members/{user_id}."""

    def test_an_owner_may_remove_a_member(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        owner_context: HouseholdContext,
        another_test_user: User,
    ) -> None:
        use_context(owner_context)
        wire.remove_member.return_value = Message(message="Member removed from the household.")

        response = client.delete(
            f"/api/v1/households/me/members/{another_test_user.id}", headers=auth_headers
        )

        assert response.status_code == 200

    def test_a_member_may_not_remove_a_member(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        member_context: HouseholdContext,
        another_test_user: User,
    ) -> None:
        use_context(member_context)

        response = client.delete(
            f"/api/v1/households/me/members/{another_test_user.id}", headers=auth_headers
        )

        assert response.status_code == 403
        wire.remove_member.assert_not_called()

    def test_a_user_from_another_household_is_not_found(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        owner_context: HouseholdContext,
    ) -> None:
        """A user ID outside the household reads as 404, never 403."""
        use_context(owner_context)
        wire.remove_member.side_effect = HouseholdMemberNotFoundError

        response = client.delete(f"/api/v1/households/me/members/{uuid.uuid4()}", headers=auth_headers)

        assert response.status_code == 404
