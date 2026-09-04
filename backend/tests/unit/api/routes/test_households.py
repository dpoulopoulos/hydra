import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import (
    get_category_service,
    get_current_user,
    get_db,
    get_household_context,
    get_household_service,
)
from app.exceptions import (
    HouseholdInviteEmailMismatchError,
    HouseholdInviteExistsError,
    HouseholdInviteExpiredError,
    HouseholdInviteNotFoundError,
    HouseholdInviteUnclaimedError,
    HouseholdInviteUsedError,
    HouseholdMemberNotFoundError,
    HouseholdMembershipNotFoundError,
    HouseholdNotEmptyError,
    HouseholdNotFoundError,
    LastHouseholdOwnerError,
)
from app.main import app
from app.models import (
    HouseholdContext,
    HouseholdInvitePreview,
    HouseholdInvitePublic,
    HouseholdInvitesPublic,
    HouseholdInviteStatus,
    HouseholdMemberPublic,
    HouseholdMembersPublic,
    HouseholdPublic,
    HouseholdRole,
    Message,
    User,
)

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
MEMBERSHIP_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
INVITE_ID = uuid.UUID("88888888-8888-8888-8888-888888888888")


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


@pytest.fixture
def category_wire(wire: MagicMock) -> MagicMock:
    """Override the category service the detaching routes have to pass on.

    Args:
        wire: The household service override, whose teardown clears this one.

    Returns:
        A mock category service the test can assert on.
    """
    service = MagicMock()
    app.dependency_overrides[get_category_service] = lambda: service

    return service


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

    def test_hands_the_category_service_over(
        self,
        client: TestClient,
        wire: MagicMock,
        category_wire: MagicMock,
        auth_headers: dict[str, str],
        member_context: HouseholdContext,
    ) -> None:
        """Without it the replacement household is created with no categories."""
        use_context(member_context)
        wire.leave_household.return_value = Message(message="You have left the household.")

        client.delete("/api/v1/households/me/members/me", headers=auth_headers)

        assert wire.leave_household.call_args.kwargs["category_service"] is category_wire

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

    def test_hands_the_category_service_over(
        self,
        client: TestClient,
        wire: MagicMock,
        category_wire: MagicMock,
        auth_headers: dict[str, str],
        owner_context: HouseholdContext,
        another_test_user: User,
    ) -> None:
        """Without it the removed member is left with no categories."""
        use_context(owner_context)
        wire.remove_member.return_value = Message(message="Member removed from the household.")

        client.delete(f"/api/v1/households/me/members/{another_test_user.id}", headers=auth_headers)

        assert wire.remove_member.call_args.kwargs["category_service"] is category_wire

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


def make_invite_public(
    email: str = "partner@example.com", status: HouseholdInviteStatus = HouseholdInviteStatus.PENDING
) -> HouseholdInvitePublic:
    """Build an invite response payload."""
    return HouseholdInvitePublic(
        id=INVITE_ID,
        household_id=HOUSEHOLD_ID,
        email=email,
        role=HouseholdRole.MEMBER,
        status=status,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        created_at=datetime.now(UTC),
    )


class TestCreateHouseholdInvite:
    """Tests for POST /households/me/invites."""

    def test_an_owner_may_invite(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        owner_context: HouseholdContext,
    ) -> None:
        use_context(owner_context)
        wire.create_invite.return_value = make_invite_public()

        response = client.post(
            "/api/v1/households/me/invites",
            headers=auth_headers,
            json={"email": "partner@example.com"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "pending"

    def test_a_member_may_not_invite(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        member_context: HouseholdContext,
    ) -> None:
        use_context(member_context)

        response = client.post(
            "/api/v1/households/me/invites",
            headers=auth_headers,
            json={"email": "partner@example.com"},
        )

        assert response.status_code == 403
        wire.create_invite.assert_not_called()

    def test_reports_a_duplicate_invite_as_a_conflict(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        owner_context: HouseholdContext,
    ) -> None:
        use_context(owner_context)
        wire.create_invite.side_effect = HouseholdInviteExistsError(email="partner@example.com")

        response = client.post(
            "/api/v1/households/me/invites",
            headers=auth_headers,
            json={"email": "partner@example.com"},
        )

        assert response.status_code == 409

    def test_rejects_an_address_that_is_not_an_address(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        owner_context: HouseholdContext,
    ) -> None:
        use_context(owner_context)

        response = client.post(
            "/api/v1/households/me/invites", headers=auth_headers, json={"email": "not-an-email"}
        )

        assert response.status_code == 422


class TestListHouseholdInvites:
    """Tests for GET /households/me/invites."""

    def test_returns_the_invites(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        member_context: HouseholdContext,
    ) -> None:
        use_context(member_context)
        wire.list_invites.return_value = HouseholdInvitesPublic(data=[make_invite_public()], count=1)

        response = client.get("/api/v1/households/me/invites", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["count"] == 1

    def test_can_filter_by_status(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        member_context: HouseholdContext,
    ) -> None:
        use_context(member_context)
        wire.list_invites.return_value = HouseholdInvitesPublic(data=[], count=0)

        client.get(
            "/api/v1/households/me/invites", headers=auth_headers, params={"status": "accepted"}
        )

        assert wire.list_invites.call_args.kwargs["status"] is HouseholdInviteStatus.ACCEPTED


class TestRevokeHouseholdInvite:
    """Tests for DELETE /households/me/invites/{invite_id}."""

    def test_an_owner_may_revoke(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        owner_context: HouseholdContext,
    ) -> None:
        use_context(owner_context)
        wire.revoke_invite.return_value = Message(message="Invitation withdrawn.")

        response = client.delete(
            f"/api/v1/households/me/invites/{INVITE_ID}", headers=auth_headers
        )

        assert response.status_code == 200

    def test_a_member_may_not_revoke(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        member_context: HouseholdContext,
    ) -> None:
        use_context(member_context)

        response = client.delete(
            f"/api/v1/households/me/invites/{INVITE_ID}", headers=auth_headers
        )

        assert response.status_code == 403

    def test_reports_an_already_used_invite_as_a_bad_request(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        owner_context: HouseholdContext,
    ) -> None:
        use_context(owner_context)
        wire.revoke_invite.side_effect = HouseholdInviteUsedError

        response = client.delete(
            f"/api/v1/households/me/invites/{INVITE_ID}", headers=auth_headers
        )

        assert response.status_code == 400


class TestPreviewHouseholdInvite:
    """Tests for GET /households/invites/{token}."""

    def test_is_public(self, client: TestClient, wire: MagicMock) -> None:
        """The recipient may not have an account yet, so no token is required."""
        wire.preview_invite.return_value = HouseholdInvitePreview(
            household_name="Test household",
            invited_by="owner@example.com",
            masked_email="p*****@example.com",
            role=HouseholdRole.MEMBER,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )

        response = client.get("/api/v1/households/invites/a-token")

        assert response.status_code == 200
        assert response.json()["household_name"] == "Test household"
        assert response.json()["masked_email"] == "p*****@example.com"

    def test_an_unknown_token_is_not_found(self, client: TestClient, wire: MagicMock) -> None:
        wire.preview_invite.side_effect = HouseholdInviteNotFoundError

        response = client.get("/api/v1/households/invites/nonsense")

        assert response.status_code == 404

    def test_an_expired_invite_is_a_bad_request(
        self, client: TestClient, wire: MagicMock
    ) -> None:
        wire.preview_invite.side_effect = HouseholdInviteExpiredError

        response = client.get("/api/v1/households/invites/a-token")

        assert response.status_code == 400


class TestAcceptHouseholdInvite:
    """Tests for POST /households/invites/accept."""

    def test_joins_the_household(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        household_public: HouseholdPublic,
    ) -> None:
        wire.accept_invite.return_value = household_public

        response = client.post(
            "/api/v1/households/invites/accept", headers=auth_headers, json={"token": "a-token"}
        )

        assert response.status_code == 200
        assert response.json()["name"] == "Test household"

    def test_accept_is_not_parsed_as_a_token(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        household_public: HouseholdPublic,
    ) -> None:
        """The literal "accept" path must win over the {token} path."""
        wire.accept_invite.return_value = household_public

        response = client.post(
            "/api/v1/households/invites/accept", headers=auth_headers, json={"token": "a-token"}
        )

        assert response.status_code == 200
        wire.preview_invite.assert_not_called()

    def test_an_invite_for_a_different_address_is_forbidden(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.accept_invite.side_effect = HouseholdInviteEmailMismatchError

        response = client.post(
            "/api/v1/households/invites/accept", headers=auth_headers, json={"token": "a-token"}
        )

        assert response.status_code == 403

    def test_an_unconfirmed_invite_is_forbidden(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.accept_invite.side_effect = HouseholdInviteUnclaimedError

        response = client.post(
            "/api/v1/households/invites/accept", headers=auth_headers, json={"token": "a-token"}
        )

        assert response.status_code == 403
        assert "waiting for its address to be confirmed" in response.json()["detail"]

    def test_a_household_with_data_is_a_conflict(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.accept_invite.side_effect = HouseholdNotEmptyError

        response = client.post(
            "/api/v1/households/invites/accept", headers=auth_headers, json={"token": "a-token"}
        )

        assert response.status_code == 409
        assert "accounts or transactions" in response.json()["detail"]
