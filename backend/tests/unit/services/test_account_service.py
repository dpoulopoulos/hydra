import uuid
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.exceptions import (
    AccountExistsError,
    AccountInUseError,
    AccountNotFoundError,
    HouseholdNotFoundError,
)
from app.models import (
    Account,
    AccountCreate,
    AccountType,
    AccountUpdate,
    Household,
    HouseholdContext,
    Message,
)
from app.services import AccountService

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def make_account(
    name: str = "Current",
    account_type: AccountType = AccountType.CURRENT,
    opening_balance_minor: int = 100_000,
    archived: bool = False,
) -> Account:
    """Build an account row for the tests."""
    return Account(
        household_id=HOUSEHOLD_ID,
        name=name,
        type=account_type,
        currency_code="EUR",
        opening_balance_minor=opening_balance_minor,
        opening_balance_date=date(2026, 1, 1),
        archived_at=datetime.now(UTC) if archived else None,
    )


@pytest.fixture
def household() -> Household:
    house = Household(name="Test household", currency_code="EUR")
    house.id = HOUSEHOLD_ID
    return house


class TestCreateAccount:
    """Tests for create_account."""

    def test_creates_an_account(
        self,
        mock_account_service: AccountService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.return_value = None
        mock_account_service.session.get = MagicMock(return_value=household)

        result = mock_account_service.create_account(
            household=household_context,
            account_create=AccountCreate(name="Cash", type=AccountType.CASH, opening_balance_date=date(2026, 1, 1)),
        )

        assert result.name == "Cash"
        assert result.household_id == household_context.household_id
        mock_account_service.session.commit.assert_called_once()

    def test_inherits_the_household_currency(
        self,
        mock_account_service: AccountService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        """A single currency per household, but stored on the account so it can vary later."""
        household.currency_code = "GBP"
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.return_value = None
        mock_account_service.session.get = MagicMock(return_value=household)

        result = mock_account_service.create_account(
            household=household_context,
            account_create=AccountCreate(name="Cash", type=AccountType.CASH, opening_balance_date=date(2026, 1, 1)),
        )

        assert result.currency_code == "GBP"

    def test_the_opening_balance_is_the_starting_balance(
        self,
        mock_account_service: AccountService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.return_value = None
        mock_account_service.session.get = MagicMock(return_value=household)

        result = mock_account_service.create_account(
            household=household_context,
            account_create=AccountCreate(
                name="Cash",
                type=AccountType.CASH,
                opening_balance_minor=25_000,
                opening_balance_date=date(2026, 1, 1),
            ),
        )

        assert result.current_balance_minor == 25_000

    def test_rejects_a_duplicate_name(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.return_value = make_account()

        with pytest.raises(AccountExistsError):
            mock_account_service.create_account(
                household=household_context,
                account_create=AccountCreate(
                    name="Current", type=AccountType.CURRENT, opening_balance_date=date(2026, 1, 1)
                ),
            )

    def test_raises_when_the_household_is_gone(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.return_value = None
        mock_account_service.session.get = MagicMock(return_value=None)

        with pytest.raises(HouseholdNotFoundError):
            mock_account_service.create_account(
                household=household_context,
                account_create=AccountCreate(name="Cash", type=AccountType.CASH, opening_balance_date=date(2026, 1, 1)),
            )


class TestListAccounts:
    """Tests for list_accounts."""

    def test_returns_accounts_with_balances_and_a_total(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        current = make_account(name="Current", opening_balance_minor=100_000)
        savings = make_account(name="Savings", account_type=AccountType.SAVINGS, opening_balance_minor=50_000)
        mock_account_service.session.exec = MagicMock()
        # The count is a scalar; then the page, the opening balances and the
        # ledger deltas.
        mock_account_service.session.exec.return_value.one.return_value = 2
        mock_account_service.session.exec.return_value.all.side_effect = [
            [current, savings],
            [(current.id, 100_000), (savings.id, 50_000)],
            [],
            # The household total: every matching id, then their balances.
            [current.id, savings.id],
            [(current.id, 100_000), (savings.id, 50_000)],
            [],
        ]

        result = mock_account_service.list_accounts(household=household_context)

        assert result.count == 2
        assert result.total_balance_minor == 150_000
        assert {account.name for account in result.data} == {"Current", "Savings"}

    def test_a_credit_card_in_debt_lowers_the_total(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        """Money owed on a card is a negative balance, so net worth is not overstated."""
        current = make_account(name="Current", opening_balance_minor=100_000)
        card = make_account(name="Card", account_type=AccountType.CREDIT_CARD, opening_balance_minor=-40_000)
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.one.return_value = 2
        mock_account_service.session.exec.return_value.all.side_effect = [
            [current, card],
            [(current.id, 100_000), (card.id, -40_000)],
            [],
            [current.id, card.id],
            [(current.id, 100_000), (card.id, -40_000)],
            [],
        ]

        result = mock_account_service.list_accounts(household=household_context)

        assert result.total_balance_minor == 60_000

    def test_returns_an_empty_list(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        mock_account_service.session.exec = MagicMock()
        # The count, then the page and the ids the total would cover.
        mock_account_service.session.exec.return_value.one.return_value = 0
        mock_account_service.session.exec.return_value.all.side_effect = [[], []]

        result = mock_account_service.list_accounts(household=household_context)

        assert result.count == 0
        assert result.total_balance_minor == 0

    def test_the_total_covers_every_account_not_only_the_page(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        """Net worth is the household's, so a second page must not shrink it."""
        current = make_account(name="Current", opening_balance_minor=100_000)
        savings = make_account(name="Savings", account_type=AccountType.SAVINGS, opening_balance_minor=50_000)
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.one.return_value = 2
        mock_account_service.session.exec.return_value.all.side_effect = [
            # One account on this page, both in the household.
            [current],
            [(current.id, 100_000)],
            [],
            [current.id, savings.id],
            [(current.id, 100_000), (savings.id, 50_000)],
            [],
        ]

        result = mock_account_service.list_accounts(household=household_context, limit=1)

        assert [account.name for account in result.data] == ["Current"]
        assert result.count == 2
        assert result.total_balance_minor == 150_000


class TestGetAccount:
    """Tests for get_account."""

    def test_returns_the_account_with_its_balance(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.return_value = account
        # The opening balances, then the ledger deltas.
        mock_account_service.session.exec.return_value.all.side_effect = [
            [(account.id, 100_000)],
            [(account.id, -4_250)],
        ]

        result = mock_account_service.get_account(household=household_context, account_id=account.id)

        assert result.current_balance_minor == 95_750

    def test_an_account_from_another_household_is_not_found(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        """The repository scopes the query, so a foreign ID simply is not there."""
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.return_value = None

        with pytest.raises(AccountNotFoundError):
            mock_account_service.get_account(household=household_context, account_id=uuid.uuid4())


class TestUpdateAccount:
    """Tests for update_account."""

    def test_renames_the_account(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.side_effect = [account, None]
        mock_account_service.session.exec.return_value.all.side_effect = [[(account.id, 100_000)], []]

        result = mock_account_service.update_account(
            household=household_context, account_id=account.id, account_update=AccountUpdate(name="Main")
        )

        assert result.name == "Main"
        mock_account_service.session.commit.assert_called_once()

    def test_rejects_a_name_another_account_already_uses(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.side_effect = [account, make_account("Savings")]

        with pytest.raises(AccountExistsError):
            mock_account_service.update_account(
                household=household_context,
                account_id=account.id,
                account_update=AccountUpdate(name="Savings"),
            )

    def test_archives_the_account(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.return_value = account
        mock_account_service.session.exec.return_value.all.side_effect = [[(account.id, 100_000)], []]

        result = mock_account_service.update_account(
            household=household_context,
            account_id=account.id,
            account_update=AccountUpdate(is_archived=True),
        )

        assert result.archived_at is not None

    def test_restores_the_account(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        account = make_account(archived=True)
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.return_value = account
        mock_account_service.session.exec.return_value.all.side_effect = [[(account.id, 100_000)], []]

        result = mock_account_service.update_account(
            household=household_context,
            account_id=account.id,
            account_update=AccountUpdate(is_archived=False),
        )

        assert result.archived_at is None

    def test_the_opening_balance_cannot_be_changed(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        """Changing it would silently rewrite every historical balance."""
        assert "opening_balance_minor" not in AccountUpdate.model_fields
        assert "opening_balance_date" not in AccountUpdate.model_fields


class TestDeleteAccount:
    """Tests for delete_account."""

    def test_deletes_an_account_with_no_history(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.return_value = account
        mock_account_service.session.exec.return_value.one.return_value = 0

        result = mock_account_service.delete_account(household=household_context, account_id=account.id)

        assert isinstance(result, Message)
        mock_account_service.session.delete.assert_called_once_with(account)

    @pytest.mark.parametrize(
        ("counts", "blocker"),
        [
            ([1, 0, 0], "still has transactions"),
            ([0, 1, 0], "recurring rules paid from it"),
            ([0, 0, 1], "destination of a recurring transfer"),
        ],
        ids=["transactions", "recurring rules", "recurring transfers"],
    )
    def test_refuses_to_delete_an_account_something_references(
        self,
        mock_account_service: AccountService,
        household_context: HouseholdContext,
        counts: list[int],
        blocker: str,
    ) -> None:
        """The foreign keys onto account are RESTRICT, so an unchecked delete is a 500."""
        account = make_account(name="Savings")
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.return_value = account
        mock_account_service.session.exec.return_value.one.side_effect = counts

        with pytest.raises(AccountInUseError) as excinfo:
            mock_account_service.delete_account(household=household_context, account_id=account.id)

        assert blocker in str(excinfo.value)
        mock_account_service.session.delete.assert_not_called()

    def test_reports_a_constraint_violation_as_in_use(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        """A reference created between the check and the delete still has to be translated."""
        account = make_account()
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.return_value = account
        mock_account_service.session.exec.return_value.one.return_value = 0
        mock_account_service.session.flush = MagicMock(
            side_effect=IntegrityError("DELETE", None, Exception("violates foreign key"))
        )

        with pytest.raises(AccountInUseError):
            mock_account_service.delete_account(household=household_context, account_id=account.id)

        mock_account_service.session.rollback.assert_called_once()

    def test_lets_an_unrelated_failure_surface(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        """A dropped connection is not a statement about the user's transactions."""
        account = make_account()
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.return_value = account
        mock_account_service.session.exec.return_value.one.return_value = 0
        mock_account_service.session.flush = MagicMock(side_effect=OperationalError("DELETE", None, Exception("gone")))

        with pytest.raises(OperationalError):
            mock_account_service.delete_account(household=household_context, account_id=account.id)
