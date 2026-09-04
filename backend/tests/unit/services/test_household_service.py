import uuid
from unittest.mock import MagicMock

import pytest

from app.exceptions import (
    HouseholdMemberExistsError,
    HouseholdMemberNotFoundError,
    HouseholdMembershipNotFoundError,
    HouseholdNotFoundError,
    LastHouseholdOwnerError,
)
from app.models import (
    Household,
    HouseholdContext,
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

        result = mock_household_service.provision_for_user(user=test_user)

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

        result = mock_household_service.provision_for_user(user=test_user, name="The Flat")

        assert result.name == "The Flat"

    def test_raises_when_the_user_already_has_a_household(
        self, mock_household_service: HouseholdService, test_user: User, membership: HouseholdMember
    ) -> None:
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.first.return_value = membership

        with pytest.raises(HouseholdMemberExistsError):
            mock_household_service.provision_for_user(user=test_user)

        mock_household_service.session.commit.assert_not_called()

    def test_seeds_categories_when_a_category_service_is_given(
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

        result = mock_household_service.remove_member(household=context, user_id=another_test_user.id)

        assert isinstance(result, Message)
        mock_household_service.session.delete.assert_called_once_with(target)

        added = [call.args[0] for call in mock_household_service.session.add.call_args_list]
        assert any(isinstance(entity, Household) for entity in added)
        assert any(isinstance(entity, HouseholdMember) and entity.user_id == another_test_user.id for entity in added)

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
            mock_household_service.remove_member(household=context, user_id=membership.user_id)


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

        result = mock_household_service.leave_household(household=member_context)

        assert isinstance(result, Message)
        mock_household_service.session.delete.assert_called_once_with(target)

    def test_the_last_owner_may_not_leave(
        self, mock_household_service: HouseholdService, context: HouseholdContext
    ) -> None:
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.one.return_value = 1

        with pytest.raises(LastHouseholdOwnerError):
            mock_household_service.leave_household(household=context)


class TestEnsureEveryUserHasAHousehold:
    """Tests for ensure_every_user_has_a_household."""

    def test_provisions_for_each_user_without_one(
        self, mock_household_service: HouseholdService, test_user: User, another_test_user: User
    ) -> None:
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.all.return_value = [test_user, another_test_user]
        mock_household_service.session.exec.return_value.first.return_value = None

        assert mock_household_service.ensure_every_user_has_a_household() == 2

    def test_does_nothing_when_every_user_has_one(self, mock_household_service: HouseholdService) -> None:
        mock_household_service.session.exec = MagicMock()
        mock_household_service.session.exec.return_value.all.return_value = []

        assert mock_household_service.ensure_every_user_has_a_household() == 0
        mock_household_service.session.commit.assert_not_called()
