import uuid
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest

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
            account_create=AccountCreate(
                name="Cash", type=AccountType.CASH, opening_balance_date=date(2026, 1, 1)
            ),
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
            account_create=AccountCreate(
                name="Cash", type=AccountType.CASH, opening_balance_date=date(2026, 1, 1)
            ),
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
                account_create=AccountCreate(
                    name="Cash", type=AccountType.CASH, opening_balance_date=date(2026, 1, 1)
                ),
            )


class TestListAccounts:
    """Tests for list_accounts."""

    def test_returns_accounts_with_balances_and_a_total(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        current = make_account(name="Current", opening_balance_minor=100_000)
        savings = make_account(name="Savings", account_type=AccountType.SAVINGS, opening_balance_minor=50_000)
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.all.side_effect = [
            [current, savings],
            [current, savings],
            [(current.id, 100_000), (savings.id, 50_000)],
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
        card = make_account(
            name="Card", account_type=AccountType.CREDIT_CARD, opening_balance_minor=-40_000
        )
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.all.side_effect = [
            [current, card],
            [current, card],
            [(current.id, 100_000), (card.id, -40_000)],
        ]

        result = mock_account_service.list_accounts(household=household_context)

        assert result.total_balance_minor == 60_000

    def test_returns_an_empty_list(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.all.side_effect = [[], []]

        result = mock_account_service.list_accounts(household=household_context)

        assert result.count == 0
        assert result.total_balance_minor == 0


class TestGetAccount:
    """Tests for get_account."""

    def test_returns_the_account_with_its_balance(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.return_value = account
        mock_account_service.session.exec.return_value.all.return_value = [(account.id, 100_000)]

        result = mock_account_service.get_account(household=household_context, account_id=account.id)

        assert result.current_balance_minor == 100_000

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
        mock_account_service.session.exec.return_value.all.return_value = [(account.id, 100_000)]

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
        mock_account_service.session.exec.return_value.all.return_value = [(account.id, 100_000)]

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
        mock_account_service.session.exec.return_value.all.return_value = [(account.id, 100_000)]

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

        result = mock_account_service.delete_account(household=household_context, account_id=account.id)

        assert isinstance(result, Message)
        mock_account_service.session.delete.assert_called_once_with(account)

    def test_reports_an_account_with_history_as_in_use(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        """The ledger foreign keys are RESTRICT, so the database refuses the delete."""
        account = make_account()
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.return_value = account
        mock_account_service.session.flush = MagicMock(side_effect=RuntimeError("violates foreign key"))

        with pytest.raises(AccountInUseError):
            mock_account_service.delete_account(household=household_context, account_id=account.id)

        mock_account_service.session.rollback.assert_called_once()
