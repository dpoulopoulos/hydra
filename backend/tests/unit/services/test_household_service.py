import logging
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.core.config import settings

from app.exceptions import (
    HouseholdInviteEmailMismatchError,
    HouseholdInviteExistsError,
    HouseholdInviteExpiredError,
    HouseholdInviteNotFoundError,
    HouseholdInviteUsedError,
    HouseholdMemberExistsError,
    HouseholdMemberNotFoundError,
    HouseholdMembershipNotFoundError,
    HouseholdNotEmptyError,
    HouseholdNotFoundError,
    LastHouseholdOwnerError,
)
from app.models import (
    EmailVerification,
    EmailVerificationStatus,
    Household,
    HouseholdContext,
    HouseholdInvite,
    HouseholdInviteCreate,
    HouseholdInviteStatus,
    HouseholdMember,
    HouseholdMemberUpdate,
    HouseholdPublic,
    HouseholdRole,
    HouseholdUpdate,
    Message,
    User,
)
from app.services import HouseholdService
from app.services.household import default_household_name


@pytest.fixture
def household() -> Household:
    house = Household(name="Test household")
    house.id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    return house


@pytest.fixture
def membership(household: Household, test_user: User) -> HouseholdMember:
    member = HouseholdMember(household_id=household.id, user_id=test_user.id, role=HouseholdRole.OWNER)
    member.id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    return member


@pytest.fixture
def context(test_user: User, household: Household, membership: HouseholdMember) -> HouseholdContext:
    return HouseholdContext(
        user=test_user,
        household_id=household.id,
        membership_id=membership.id,
        role=HouseholdRole.OWNER,
    )


class TestDefaultHouseholdName:
    """Tests for the default household name."""

    def test_uses_the_full_name_when_present(self, test_user: User) -> None:
        assert default_household_name(test_user) == "Test User's household"

    def test_falls_back_to_the_email(self, test_user: User) -> None:
        test_user.full_name = None
        assert default_household_name(test_user) == "test@example.com's household"


class TestGetContext:
    """Tests for get_context."""

    def test_returns_the_context(
        self, mock_household_service: HouseholdService, test_user: User, membership: HouseholdMember
    ) -> None:
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = membership

        context = mock_household_service.get_context(user=test_user)

        assert context.household_id == membership.household_id
        assert context.membership_id == membership.id
        assert context.role is HouseholdRole.OWNER
        assert context.user_id == test_user.id
        assert context.is_owner is True

    def test_raises_when_the_user_has_no_household(
        self, mock_household_service: HouseholdService, test_user: User
    ) -> None:
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = None

        with pytest.raises(HouseholdMembershipNotFoundError):
            mock_household_service.get_context(user=test_user)


class TestProvisionForUser:
    """Tests for provision_for_user."""

    def test_creates_a_household_and_an_owner_membership(
        self, mock_household_service: HouseholdService, test_user: User
    ) -> None:
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = None

        result = mock_household_service.provision_for_user(user=test_user, category_service=MagicMock())

        assert isinstance(result, HouseholdPublic)
        assert result.name == "Test User's household"
        assert result.member_count == 1
        mock_household_service.session.commit.assert_called_once()

        added = [call.args[0] for call in mock_household_service.session.add.call_args_list]
        households = [entity for entity in added if isinstance(entity, Household)]
        members = [entity for entity in added if isinstance(entity, HouseholdMember)]
        assert len(households) == 1
        assert len(members) == 1
        assert members[0].role is HouseholdRole.OWNER
        assert members[0].user_id == test_user.id
        assert members[0].household_id == households[0].id

    def test_accepts_an_explicit_name(self, mock_household_service: HouseholdService, test_user: User) -> None:
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = None

        result = mock_household_service.provision_for_user(
            user=test_user, name="The Flat", category_service=MagicMock()
        )

        assert result.name == "The Flat"

    def test_raises_when_the_user_already_has_a_household(
        self, mock_household_service: HouseholdService, test_user: User, membership: HouseholdMember
    ) -> None:
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = membership

        with pytest.raises(HouseholdMemberExistsError):
            mock_household_service.provision_for_user(user=test_user, category_service=MagicMock())

        mock_household_service.session.commit.assert_not_called()

    def test_seeds_the_categories_of_the_household(
        self, mock_household_service: HouseholdService, test_user: User
    ) -> None:
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = None
        category_service = MagicMock()

        mock_household_service.provision_for_user(user=test_user, category_service=category_service)

        category_service.seed_defaults.assert_called_once()


class TestGetHousehold:
    """Tests for get_household."""

    def test_returns_the_household_with_its_member_count(
        self, mock_household_service: HouseholdService, context: HouseholdContext, household: Household
    ) -> None:
        mock_household_service.session.get = MagicMock(return_value=household)
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.one.return_value = 2

        result = mock_household_service.get_household(household=context)

        assert result.id == household.id
        assert result.member_count == 2

    def test_raises_when_the_household_is_gone(
        self, mock_household_service: HouseholdService, context: HouseholdContext
    ) -> None:
        mock_household_service.session.get = MagicMock(return_value=None)

        with pytest.raises(HouseholdNotFoundError):
            mock_household_service.get_household(household=context)


class TestUpdateHousehold:
    """Tests for update_household."""

    def test_renames_the_household(
        self, mock_household_service: HouseholdService, context: HouseholdContext, household: Household
    ) -> None:
        mock_household_service.session.get = MagicMock(return_value=household)
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.one.return_value = 1

        result = mock_household_service.update_household(
            household=context, household_update=HouseholdUpdate(name="Renamed")
        )

        assert result.name == "Renamed"
        mock_household_service.session.commit.assert_called_once()

    def test_ignores_unset_fields(
        self, mock_household_service: HouseholdService, context: HouseholdContext, household: Household
    ) -> None:
        mock_household_service.session.get = MagicMock(return_value=household)
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.one.return_value = 1

        result = mock_household_service.update_household(household=context, household_update=HouseholdUpdate())

        assert result.name == "Test household"


class TestListMembers:
    """Tests for list_members."""

    def test_returns_members_with_their_user_details(
        self,
        mock_household_service: HouseholdService,
        context: HouseholdContext,
        membership: HouseholdMember,
        test_user: User,
    ) -> None:
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.all.return_value = [(membership, test_user)]

        result = mock_household_service.list_members(household=context)

        assert result.count == 1
        assert result.data[0].email == test_user.email
        assert result.data[0].full_name == test_user.full_name
        assert result.data[0].role is HouseholdRole.OWNER


class TestUpdateMember:
    """Tests for update_member."""

    def test_promotes_a_member(
        self,
        mock_household_service: HouseholdService,
        context: HouseholdContext,
        another_test_user: User,
    ) -> None:
        target = HouseholdMember(
            household_id=context.household_id, user_id=another_test_user.id, role=HouseholdRole.MEMBER
        )
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.side_effect = [(target, another_test_user)]

        result = mock_household_service.update_member(
            household=context,
            user_id=another_test_user.id,
            member_update=HouseholdMemberUpdate(role=HouseholdRole.OWNER),
        )

        assert result.role is HouseholdRole.OWNER
        mock_household_service.session.commit.assert_called_once()

    def test_raises_when_the_member_is_not_in_the_household(
        self, mock_household_service: HouseholdService, context: HouseholdContext
    ) -> None:
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = None

        with pytest.raises(HouseholdMemberNotFoundError):
            mock_household_service.update_member(
                household=context,
                user_id=uuid.uuid4(),
                member_update=HouseholdMemberUpdate(role=HouseholdRole.MEMBER),
            )

    def test_refuses_to_demote_the_last_owner(
        self,
        mock_household_service: HouseholdService,
        context: HouseholdContext,
        membership: HouseholdMember,
        test_user: User,
    ) -> None:
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = (membership, test_user)
        mock_household_service.session.exec.return_value.one.return_value = 1

        with pytest.raises(LastHouseholdOwnerError):
            mock_household_service.update_member(
                household=context,
                user_id=membership.user_id,
                member_update=HouseholdMemberUpdate(role=HouseholdRole.MEMBER),
            )


class TestRemoveMember:
    """Tests for remove_member."""

    def test_removes_the_member_and_gives_them_a_fresh_household(
        self,
        mock_household_service: HouseholdService,
        context: HouseholdContext,
        another_test_user: User,
    ) -> None:
        target = HouseholdMember(
            household_id=context.household_id, user_id=another_test_user.id, role=HouseholdRole.MEMBER
        )
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.side_effect = [(target, another_test_user), None]
        mock_household_service.session.exec.return_value.one.return_value = 1

        result = mock_household_service.remove_member(
            household=context, user_id=another_test_user.id, category_service=MagicMock()
        )

        assert isinstance(result, Message)
        mock_household_service.session.delete.assert_called_once_with(target)

        added = [call.args[0] for call in mock_household_service.session.add.call_args_list]
        assert any(isinstance(entity, Household) for entity in added)
        assert any(isinstance(entity, HouseholdMember) and entity.user_id == another_test_user.id for entity in added)

    def test_seeds_the_categories_of_the_fresh_household(
        self,
        mock_household_service: HouseholdService,
        context: HouseholdContext,
        another_test_user: User,
    ) -> None:
        """The removed member must land in a household they can use."""
        target = HouseholdMember(
            household_id=context.household_id, user_id=another_test_user.id, role=HouseholdRole.MEMBER
        )
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.side_effect = [(target, another_test_user), None]
        mock_household_service.session.exec.return_value.one.return_value = 1
        category_service = MagicMock()

        mock_household_service.remove_member(
            household=context, user_id=another_test_user.id, category_service=category_service
        )

        added = [call.args[0] for call in mock_household_service.session.add.call_args_list]
        fresh = next(entity for entity in added if isinstance(entity, Household))
        category_service.seed_defaults.assert_called_once_with(household_id=fresh.id)

    def test_refuses_to_remove_the_last_owner(
        self,
        mock_household_service: HouseholdService,
        context: HouseholdContext,
        membership: HouseholdMember,
        test_user: User,
    ) -> None:
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = (membership, test_user)
        mock_household_service.session.exec.return_value.one.return_value = 1

        with pytest.raises(LastHouseholdOwnerError):
            mock_household_service.remove_member(
                household=context, user_id=membership.user_id, category_service=MagicMock()
            )


class TestLeaveHousehold:
    """Tests for leave_household."""

    def test_a_member_may_leave(
        self, mock_household_service: HouseholdService, test_user: User, household: Household
    ) -> None:
        member_context = HouseholdContext(
            user=test_user,
            household_id=household.id,
            membership_id=uuid.uuid4(),
            role=HouseholdRole.MEMBER,
        )
        target = HouseholdMember(household_id=household.id, user_id=test_user.id, role=HouseholdRole.MEMBER)
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.side_effect = [(target, test_user), None]
        mock_household_service.session.exec.return_value.one.return_value = 1

        result = mock_household_service.leave_household(household=member_context, category_service=MagicMock())

        assert isinstance(result, Message)
        mock_household_service.session.delete.assert_called_once_with(target)

    def test_seeds_the_categories_of_the_fresh_household(
        self, mock_household_service: HouseholdService, test_user: User, household: Household
    ) -> None:
        """Leaving must not strand the caller in a household with no categories."""
        member_context = HouseholdContext(
            user=test_user,
            household_id=household.id,
            membership_id=uuid.uuid4(),
            role=HouseholdRole.MEMBER,
        )
        target = HouseholdMember(household_id=household.id, user_id=test_user.id, role=HouseholdRole.MEMBER)
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.side_effect = [(target, test_user), None]
        mock_household_service.session.exec.return_value.one.return_value = 1
        category_service = MagicMock()

        mock_household_service.leave_household(household=member_context, category_service=category_service)

        added = [call.args[0] for call in mock_household_service.session.add.call_args_list]
        fresh = next(entity for entity in added if isinstance(entity, Household))
        category_service.seed_defaults.assert_called_once_with(household_id=fresh.id)

    def test_the_last_owner_may_not_leave(
        self, mock_household_service: HouseholdService, context: HouseholdContext
    ) -> None:
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.one.return_value = 1

        with pytest.raises(LastHouseholdOwnerError):
            mock_household_service.leave_household(household=context, category_service=MagicMock())


class TestReleaseForUser:
    """Tests for release_for_user."""

    def test_deletes_the_household_the_last_member_leaves_behind(
        self,
        mock_household_service: HouseholdService,
        test_user: User,
        household: Household,
        membership: HouseholdMember,
    ) -> None:
        """Nobody could reach it again, so it goes with them."""
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = membership
        mock_household_service.session.exec.return_value.one.return_value = 0
        mock_household_service.session.get = MagicMock(return_value=household)

        mock_household_service.release_for_user(user=test_user)

        deleted = [call.args[0] for call in mock_household_service.session.delete.call_args_list]
        assert membership in deleted
        assert household in deleted

    def test_keeps_a_household_that_still_has_members(
        self,
        mock_household_service: HouseholdService,
        test_user: User,
        household: Household,
        membership: HouseholdMember,
    ) -> None:
        """The other members' accounts and transactions are still theirs."""
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = membership
        mock_household_service.session.exec.return_value.one.return_value = 1
        mock_household_service.session.get = MagicMock(return_value=household)

        mock_household_service.release_for_user(user=test_user)

        deleted = [call.args[0] for call in mock_household_service.session.delete.call_args_list]
        assert membership in deleted
        assert household not in deleted

    def test_does_nothing_when_the_user_has_no_household(
        self, mock_household_service: HouseholdService, test_user: User
    ) -> None:
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = None

        mock_household_service.release_for_user(user=test_user)

        mock_household_service.session.delete.assert_not_called()

    def test_promotes_a_member_when_the_last_owner_goes(
        self,
        mock_household_service: HouseholdService,
        test_user: User,
        another_test_user: User,
        household: Household,
        membership: HouseholdMember,
    ) -> None:
        """A household with no owner has no working settings and can be stranded again."""
        successor = HouseholdMember(household_id=household.id, user_id=another_test_user.id, role=HouseholdRole.MEMBER)
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.side_effect = [membership, successor]
        mock_household_service.session.exec.return_value.one.side_effect = [1, 0]
        mock_household_service.session.get = MagicMock(return_value=household)

        mock_household_service.release_for_user(user=test_user)

        assert successor.role is HouseholdRole.OWNER
        assert household not in [call.args[0] for call in mock_household_service.session.delete.call_args_list]

    def test_leaves_the_roles_alone_when_an_owner_remains(
        self,
        mock_household_service: HouseholdService,
        test_user: User,
        another_test_user: User,
        household: Household,
        membership: HouseholdMember,
    ) -> None:
        successor = HouseholdMember(household_id=household.id, user_id=another_test_user.id, role=HouseholdRole.MEMBER)
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.side_effect = [membership, successor]
        mock_household_service.session.exec.return_value.one.side_effect = [2, 1]
        mock_household_service.session.get = MagicMock(return_value=household)

        mock_household_service.release_for_user(user=test_user)

        assert successor.role is HouseholdRole.MEMBER

    def test_locks_the_household_before_counting_its_members(
        self,
        mock_household_service: HouseholdService,
        test_user: User,
        household: Household,
        membership: HouseholdMember,
    ) -> None:
        """Two members leaving at once would otherwise both see the other in place."""
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = membership
        mock_household_service.session.exec.return_value.one.return_value = 0
        mock_household_service.session.get = MagicMock(return_value=household)

        mock_household_service.release_for_user(user=test_user)

        assert mock_household_service.session.get.call_args.kwargs["with_for_update"] is True

    def test_does_not_commit(
        self,
        mock_household_service: HouseholdService,
        test_user: User,
        household: Household,
        membership: HouseholdMember,
    ) -> None:
        """The caller deletes the user in the same transaction."""
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = membership
        mock_household_service.session.exec.return_value.one.return_value = 0
        mock_household_service.session.get = MagicMock(return_value=household)

        mock_household_service.release_for_user(user=test_user)

        mock_household_service.session.commit.assert_not_called()


class TestEnsureEveryUserHasAHousehold:
    """Tests for ensure_every_user_has_a_household."""

    def test_provisions_for_each_user_without_one(
        self, mock_household_service: HouseholdService, test_user: User, another_test_user: User
    ) -> None:
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.all.return_value = [test_user, another_test_user]
        mock_household_service.session.exec.return_value.first.return_value = None

        assert mock_household_service.ensure_every_user_has_a_household(category_service=MagicMock()) == 2

    def test_does_nothing_when_every_user_has_one(self, mock_household_service: HouseholdService) -> None:
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.all.return_value = []

        assert mock_household_service.ensure_every_user_has_a_household(category_service=MagicMock()) == 0
        mock_household_service.session.commit.assert_not_called()


def make_invite(
    household_id: uuid.UUID,
    email: str = "partner@example.com",
    role: HouseholdRole = HouseholdRole.MEMBER,
    status: HouseholdInviteStatus = HouseholdInviteStatus.PENDING,
    expires_in_hours: int = 24,
) -> HouseholdInvite:
    """Build an invite row for the tests."""
    return HouseholdInvite(
        household_id=household_id,
        email=email,
        role=role,
        status=status,
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=expires_in_hours),
        token="a-token",
    )


def make_verification(user_id: uuid.UUID, email: str) -> EmailVerification:
    """Build the proof that an account holds an address."""
    return EmailVerification(
        email=email,
        user_id=user_id,
        status=EmailVerificationStatus.VERIFIED,
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24),
        token="a-verification-token",
    )


def saved_invite(service: HouseholdService) -> HouseholdInvite:
    """Return the invite the service handed to the session."""
    saved = [
        call.args[0]
        for call in service.session.add.call_args_list  # type: ignore[attr-defined]
        if isinstance(call.args[0], HouseholdInvite)
    ]
    return saved[0]


class TestCreateInvite:
    """Tests for create_invite."""

    def test_creates_a_pending_invite(
        self,
        mock_household_service: HouseholdService,
        context: HouseholdContext,
        household: Household,
    ) -> None:
        mock_household_service.session.get = MagicMock(return_value=household)
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = None
        mock_household_service.session.exec.return_value.all.return_value = []

        result = mock_household_service.create_invite(
            household=context,
            invite_create=HouseholdInviteCreate(email="Partner@Example.com"),
        )

        assert result.status is HouseholdInviteStatus.PENDING
        # Stored lower case, so a differently cased reply still matches.
        assert result.email == "partner@example.com"
        mock_household_service.session.commit.assert_called_once()

    def test_creates_the_invite_even_when_the_mail_does_not_go_out(
        self,
        mock_household_service: HouseholdService,
        context: HouseholdContext,
        household: Household,
        monkeypatch,
        caplog,
    ) -> None:
        mock_household_service.session.get = MagicMock(return_value=household)
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = None
        mock_household_service.session.exec.return_value.all.return_value = []

        # Turn mail on, then have the provider refuse the message.
        monkeypatch.setattr(settings, "EMAIL_PROVIDER", "resend")
        monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test_key")
        monkeypatch.setattr(settings, "EMAILS_FROM_EMAIL", "from@example.com")

        request = httpx.Request("POST", "https://api.resend.com/emails")
        rate_limited = httpx.HTTPStatusError("429", request=request, response=httpx.Response(429))

        with patch("app.utils.email_utils.send_email", side_effect=rate_limited):
            with caplog.at_level(logging.ERROR, logger="app.utils.email_utils"):
                result = mock_household_service.create_invite(
                    household=context,
                    invite_create=HouseholdInviteCreate(email="partner@example.com"),
                )

        # The invite is real and reported as such, so the owner is not told to
        # retry an invitation that the pending guard would then reject.
        assert result.status is HouseholdInviteStatus.PENDING
        mock_household_service.session.commit.assert_called_once()
        assert "partner@example.com" in caplog.text
        assert "HTTPStatusError" in caplog.text

    def test_binds_the_invite_to_the_account_that_proved_the_address(
        self,
        mock_household_service: HouseholdService,
        context: HouseholdContext,
        household: Household,
        another_test_user: User,
    ) -> None:
        """The invitation names an account, not a piece of text anybody can adopt."""
        mock_household_service.session.get = MagicMock(return_value=household)
        mock_household_service.session.exec = MagicMock()
        # No outstanding invite, then the account holding the invited address,
        # then its verification of that address.
        mock_household_service.session.exec.return_value.first.side_effect = [
            None,
            another_test_user,
            make_verification(user_id=another_test_user.id, email=another_test_user.email),
        ]
        mock_household_service.session.exec.return_value.all.return_value = []

        mock_household_service.create_invite(
            household=context,
            invite_create=HouseholdInviteCreate(email=another_test_user.email),
        )

        assert saved_invite(mock_household_service).invited_user_id == another_test_user.id

    def test_leaves_the_invite_unbound_when_the_address_was_never_proved(
        self,
        mock_household_service: HouseholdService,
        context: HouseholdContext,
        household: Household,
        another_test_user: User,
    ) -> None:
        """An address on a profile is a claim: `PATCH /users/me` takes any unclaimed one.

        Binding on that alone would record whoever squatted the address ahead
        of the invitation as the account it was issued to.
        """
        mock_household_service.session.get = MagicMock(return_value=household)
        mock_household_service.session.exec = MagicMock()
        # No outstanding invite, the account holding the address, no proof of it.
        mock_household_service.session.exec.return_value.first.side_effect = [None, another_test_user, None]
        mock_household_service.session.exec.return_value.all.return_value = []

        mock_household_service.create_invite(
            household=context,
            invite_create=HouseholdInviteCreate(email=another_test_user.email),
        )

        assert saved_invite(mock_household_service).invited_user_id is None

    def test_leaves_the_invite_unbound_when_the_address_has_no_account(
        self,
        mock_household_service: HouseholdService,
        context: HouseholdContext,
        household: Household,
    ) -> None:
        """The ordinary case of inviting somebody new: there is no identity yet."""
        mock_household_service.session.get = MagicMock(return_value=household)
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.side_effect = [None, None]
        mock_household_service.session.exec.return_value.all.return_value = []

        mock_household_service.create_invite(
            household=context,
            invite_create=HouseholdInviteCreate(email="nobody@example.com"),
        )

        assert saved_invite(mock_household_service).invited_user_id is None

    def test_rejects_a_second_invite_to_the_same_address(
        self,
        mock_household_service: HouseholdService,
        context: HouseholdContext,
        household: Household,
    ) -> None:
        mock_household_service.session.get = MagicMock(return_value=household)
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = make_invite(
            household_id=household.id
        )

        with pytest.raises(HouseholdInviteExistsError):
            mock_household_service.create_invite(
                household=context, invite_create=HouseholdInviteCreate(email="partner@example.com")
            )

    def test_rejects_inviting_an_existing_member(
        self,
        mock_household_service: HouseholdService,
        context: HouseholdContext,
        household: Household,
        membership: HouseholdMember,
        test_user: User,
    ) -> None:
        mock_household_service.session.get = MagicMock(return_value=household)
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = None
        mock_household_service.session.exec.return_value.all.return_value = [(membership, test_user)]

        with pytest.raises(HouseholdMemberExistsError):
            mock_household_service.create_invite(
                household=context, invite_create=HouseholdInviteCreate(email=test_user.email)
            )


class TestRevokeInvite:
    """Tests for revoke_invite."""

    def test_marks_the_invite_revoked(
        self, mock_household_service: HouseholdService, context: HouseholdContext
    ) -> None:
        """The row is kept, so an old link says it was withdrawn rather than never existed."""
        invite = make_invite(household_id=context.household_id)
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = invite

        result = mock_household_service.revoke_invite(household=context, invite_id=invite.id)

        assert isinstance(result, Message)
        assert invite.status is HouseholdInviteStatus.REVOKED
        mock_household_service.session.delete.assert_not_called()

    def test_refuses_to_revoke_an_accepted_invite(
        self, mock_household_service: HouseholdService, context: HouseholdContext
    ) -> None:
        invite = make_invite(
            household_id=context.household_id, status=HouseholdInviteStatus.ACCEPTED
        )
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = invite

        with pytest.raises(HouseholdInviteUsedError):
            mock_household_service.revoke_invite(household=context, invite_id=invite.id)

    def test_an_invite_from_another_household_is_not_found(
        self, mock_household_service: HouseholdService, context: HouseholdContext
    ) -> None:
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = None

        with pytest.raises(HouseholdInviteNotFoundError):
            mock_household_service.revoke_invite(household=context, invite_id=uuid.uuid4())


class TestPreviewInvite:
    """Tests for preview_invite."""

    def test_describes_the_invite(
        self,
        mock_household_service: HouseholdService,
        household: Household,
        test_user: User,
    ) -> None:
        invite = make_invite(household_id=household.id)
        invite.invited_by_user_id = test_user.id
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = invite
        mock_household_service.session.get = MagicMock(side_effect=[household, test_user])

        result = mock_household_service.preview_invite(token="a-token")

        assert result.household_name == "Test household"
        assert result.invited_by == test_user.email
        assert result.email == "partner@example.com"

    def test_an_unknown_token_is_not_found(
        self, mock_household_service: HouseholdService
    ) -> None:
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = None

        with pytest.raises(HouseholdInviteNotFoundError):
            mock_household_service.preview_invite(token="nonsense")

    def test_an_expired_invite_is_reported_and_marked(
        self, mock_household_service: HouseholdService, household: Household
    ) -> None:
        invite = make_invite(household_id=household.id, expires_in_hours=-1)
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = invite

        with pytest.raises(HouseholdInviteExpiredError):
            mock_household_service.preview_invite(token="a-token")

        assert invite.status is HouseholdInviteStatus.EXPIRED


class TestAcceptInvite:
    """Tests for accept_invite."""

    def test_joins_the_household(
        self,
        mock_household_service: HouseholdService,
        household: Household,
        another_test_user: User,
    ) -> None:
        invite = make_invite(household_id=household.id, email=another_test_user.email)
        mock_household_service.session.exec = MagicMock()
        # The invite, then no existing membership for the user.
        mock_household_service.session.exec.return_value.first.side_effect = [invite, None]
        mock_household_service.session.exec.return_value.one.return_value = 2
        mock_household_service.session.get = MagicMock(return_value=household)

        result = mock_household_service.accept_invite(user=another_test_user, token="a-token")

        assert result.id == household.id
        assert invite.status is HouseholdInviteStatus.ACCEPTED
        added = [call.args[0] for call in mock_household_service.session.add.call_args_list]
        assert any(
            isinstance(entity, HouseholdMember) and entity.household_id == household.id
            for entity in added
        )

    def test_gives_the_role_the_invite_named(
        self,
        mock_household_service: HouseholdService,
        household: Household,
        another_test_user: User,
    ) -> None:
        invite = make_invite(
            household_id=household.id, email=another_test_user.email, role=HouseholdRole.OWNER
        )
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.side_effect = [invite, None]
        mock_household_service.session.exec.return_value.one.return_value = 2
        mock_household_service.session.get = MagicMock(return_value=household)

        mock_household_service.accept_invite(user=another_test_user, token="a-token")

        members = [
            call.args[0]
            for call in mock_household_service.session.add.call_args_list
            if isinstance(call.args[0], HouseholdMember)
        ]
        assert members[0].role is HouseholdRole.OWNER

    def test_refuses_an_invite_sent_to_someone_else(
        self,
        mock_household_service: HouseholdService,
        household: Household,
        another_test_user: User,
    ) -> None:
        """Otherwise a leaked link would hand a stranger the household's finances."""
        invite = make_invite(household_id=household.id, email="someone.else@example.com")
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = invite

        with pytest.raises(HouseholdInviteEmailMismatchError):
            mock_household_service.accept_invite(user=another_test_user, token="a-token")

    def test_matches_the_address_regardless_of_case(
        self,
        mock_household_service: HouseholdService,
        household: Household,
        another_test_user: User,
    ) -> None:
        invite = make_invite(household_id=household.id, email=another_test_user.email.upper())
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.side_effect = [invite, None]
        mock_household_service.session.exec.return_value.one.return_value = 2
        mock_household_service.session.get = MagicMock(return_value=household)

        result = mock_household_service.accept_invite(user=another_test_user, token="a-token")

        assert result.id == household.id

    def test_discards_an_empty_household_the_user_is_leaving(
        self,
        mock_household_service: HouseholdService,
        household: Household,
        another_test_user: User,
    ) -> None:
        """It held nothing but seeded categories, so nothing is lost."""
        invite = make_invite(household_id=household.id, email=another_test_user.email)
        old_household = Household(name="Their own household")
        old_membership = HouseholdMember(
            household_id=old_household.id, user_id=another_test_user.id, role=HouseholdRole.OWNER
        )
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.side_effect = [
            invite,
            old_membership,
        ]
        # No accounts, transactions, budgets or rules, then no members left.
        mock_household_service.session.exec.return_value.one.side_effect = [0, 0, 0, 0, 0, 2]
        mock_household_service.session.get = MagicMock(side_effect=[household, old_household])

        mock_household_service.accept_invite(user=another_test_user, token="a-token")

        deleted = [call.args[0] for call in mock_household_service.session.delete.call_args_list]
        assert old_membership in deleted
        assert old_household in deleted

    def test_promotes_an_owner_in_the_household_the_user_is_leaving(
        self,
        mock_household_service: HouseholdService,
        household: Household,
        test_user: User,
        another_test_user: User,
    ) -> None:
        """Moving out as its last owner would otherwise strand the household."""
        invite = make_invite(household_id=household.id, email=another_test_user.email)
        old_household = Household(name="Their own household")
        old_membership = HouseholdMember(
            household_id=old_household.id, user_id=another_test_user.id, role=HouseholdRole.OWNER
        )
        successor = HouseholdMember(
            household_id=old_household.id, user_id=test_user.id, role=HouseholdRole.MEMBER
        )
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.side_effect = [
            invite,
            old_membership,
            successor,
        ]
        # No financial data, then a member left behind, then no owner among them.
        mock_household_service.session.exec.return_value.one.side_effect = [0, 0, 0, 0, 1, 0, 2]
        mock_household_service.session.get = MagicMock(side_effect=[household, old_household])

        mock_household_service.accept_invite(user=another_test_user, token="a-token")

        assert successor.role is HouseholdRole.OWNER
        assert old_household not in [
            call.args[0] for call in mock_household_service.session.delete.call_args_list
        ]

    def test_locks_the_household_the_user_is_leaving(
        self,
        mock_household_service: HouseholdService,
        household: Household,
        another_test_user: User,
    ) -> None:
        """Its members are counted, so a member going at the same time has to queue up."""
        invite = make_invite(household_id=household.id, email=another_test_user.email)
        old_household = Household(name="Their own household")
        old_membership = HouseholdMember(
            household_id=old_household.id, user_id=another_test_user.id, role=HouseholdRole.OWNER
        )
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.side_effect = [
            invite,
            old_membership,
        ]
        mock_household_service.session.exec.return_value.one.side_effect = [0, 0, 0, 0, 0, 2]
        mock_household_service.session.get = MagicMock(side_effect=[household, old_household])

        mock_household_service.accept_invite(user=another_test_user, token="a-token")

        assert mock_household_service.session.get.call_args.kwargs["with_for_update"] is True

    def test_refuses_when_the_users_household_holds_data(
        self,
        mock_household_service: HouseholdService,
        household: Household,
        another_test_user: User,
    ) -> None:
        """Joining would leave their accounts and transactions behind."""
        invite = make_invite(household_id=household.id, email=another_test_user.email)
        old_membership = HouseholdMember(
            household_id=uuid.uuid4(), user_id=another_test_user.id, role=HouseholdRole.OWNER
        )
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.side_effect = [
            invite,
            old_membership,
        ]
        mock_household_service.session.exec.return_value.one.return_value = 3
        mock_household_service.session.get = MagicMock(return_value=household)

        with pytest.raises(HouseholdNotEmptyError):
            mock_household_service.accept_invite(user=another_test_user, token="a-token")

    def test_refuses_when_the_user_is_already_in_that_household(
        self,
        mock_household_service: HouseholdService,
        household: Household,
        another_test_user: User,
    ) -> None:
        invite = make_invite(household_id=household.id, email=another_test_user.email)
        existing = HouseholdMember(
            household_id=household.id, user_id=another_test_user.id, role=HouseholdRole.MEMBER
        )
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.side_effect = [invite, existing]
        mock_household_service.session.get = MagicMock(return_value=household)

        with pytest.raises(HouseholdMemberExistsError):
            mock_household_service.accept_invite(user=another_test_user, token="a-token")


class TestCreateForUserWithInvite:
    """Tests for create_for_user when a registration carries an invite token."""

    def test_joins_the_inviting_household_instead_of_making_one(
        self,
        mock_household_service: HouseholdService,
        household: Household,
        another_test_user: User,
    ) -> None:
        """Saves creating a household only to discard it a moment later."""
        invite = make_invite(household_id=household.id, email=another_test_user.email)
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = invite
        mock_household_service.session.get = MagicMock(return_value=household)

        result = mock_household_service.create_for_user(
            user=another_test_user, invite_token="a-token", category_service=MagicMock()
        )

        assert result.id == household.id
        added = [call.args[0] for call in mock_household_service.session.add.call_args_list]
        assert not [entity for entity in added if isinstance(entity, Household)]
        assert invite.status is HouseholdInviteStatus.ACCEPTED

    def test_does_not_commit(
        self,
        mock_household_service: HouseholdService,
        household: Household,
        another_test_user: User,
    ) -> None:
        """It runs inside the transaction that is creating the user."""
        invite = make_invite(household_id=household.id, email=another_test_user.email)
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = invite
        mock_household_service.session.get = MagicMock(return_value=household)

        mock_household_service.create_for_user(
            user=another_test_user, invite_token="a-token", category_service=MagicMock()
        )

        mock_household_service.session.commit.assert_not_called()

    def test_refuses_a_token_sent_to_a_different_address(
        self,
        mock_household_service: HouseholdService,
        household: Household,
        another_test_user: User,
    ) -> None:
        invite = make_invite(household_id=household.id, email="someone.else@example.com")
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = invite

        with pytest.raises(HouseholdInviteEmailMismatchError):
            mock_household_service.create_for_user(
                user=another_test_user, invite_token="a-token", category_service=MagicMock()
            )
