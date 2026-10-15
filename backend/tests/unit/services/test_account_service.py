import uuid
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.exceptions import (
    AccountCurrencyLockedError,
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
    currency_code: str = "EUR",
) -> Account:
    """Build an account row for the tests."""
    return Account(
        household_id=HOUSEHOLD_ID,
        name=name,
        type=account_type,
        currency_code=currency_code,
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
        """An account that names no currency holds the household's."""
        household.currency_code = "GBP"
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.return_value = None
        mock_account_service.session.get = MagicMock(return_value=household)

        result = mock_account_service.create_account(
            household=household_context,
            account_create=AccountCreate(name="Cash", type=AccountType.CASH, opening_balance_date=date(2026, 1, 1)),
        )

        assert result.currency_code == "GBP"

    def test_takes_the_currency_it_is_given(
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
                name="Dollars", type=AccountType.CURRENT, opening_balance_date=date(2026, 1, 1), currency_code="usd"
            ),
        )

        assert result.currency_code == "USD"

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
            [(current.id, "EUR"), (savings.id, "EUR")],
            [(current.id, 100_000), (savings.id, 50_000)],
            [],
        ]

        result = mock_account_service.list_accounts(household=household_context)

        assert result.count == 2
        assert [(total.currency_code, total.amount_minor) for total in result.totals] == [("EUR", 150_000)]
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
            [(current.id, "EUR"), (card.id, "EUR")],
            [(current.id, 100_000), (card.id, -40_000)],
            [],
        ]

        result = mock_account_service.list_accounts(household=household_context)

        assert [(total.currency_code, total.amount_minor) for total in result.totals] == [("EUR", 60_000)]

    def test_each_currency_is_totalled_apart(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        """Dollars and euros are not added together at a rate nobody chose."""
        current = make_account(name="Current", opening_balance_minor=100_000)
        dollars = make_account(name="Dollars", opening_balance_minor=30_000, currency_code="USD")
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.one.return_value = 2
        mock_account_service.session.exec.return_value.all.side_effect = [
            [current, dollars],
            [(current.id, 100_000), (dollars.id, 30_000)],
            [],
            [(current.id, "EUR"), (dollars.id, "USD")],
            [(current.id, 100_000), (dollars.id, 30_000)],
            [],
        ]

        result = mock_account_service.list_accounts(household=household_context)

        assert [(total.currency_code, total.amount_minor) for total in result.totals] == [
            ("EUR", 100_000),
            ("USD", 30_000),
        ]

    def test_returns_an_empty_list(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        mock_account_service.session.exec = MagicMock()
        # The count, then the page and the ids the total would cover.
        mock_account_service.session.exec.return_value.one.return_value = 0
        mock_account_service.session.exec.return_value.all.side_effect = [[], []]

        result = mock_account_service.list_accounts(household=household_context)

        assert result.count == 0
        assert result.totals == []

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
            [(current.id, "EUR"), (savings.id, "EUR")],
            [(current.id, 100_000), (savings.id, 50_000)],
            [],
        ]

        result = mock_account_service.list_accounts(household=household_context, limit=1)

        assert [account.name for account in result.data] == ["Current"]
        assert result.count == 2
        assert [(total.currency_code, total.amount_minor) for total in result.totals] == [("EUR", 150_000)]


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


class TestChangeCurrency:
    """Tests for changing an account's currency through update_account."""

    def test_an_empty_account_changes_currency(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        account = make_account(opening_balance_minor=25_000)
        mock_account_service.session.exec = MagicMock()
        # The account, then the bank account feeding it: none.
        mock_account_service.session.exec.return_value.first.side_effect = [account, None]
        mock_account_service.session.exec.return_value.one.return_value = 0
        mock_account_service.session.exec.return_value.all.side_effect = [[(account.id, 25_000)], []]

        result = mock_account_service.update_account(
            household=household_context, account_id=account.id, account_update=AccountUpdate(currency_code="USD")
        )

        assert result.currency_code == "USD"
        assert result.opening_balance_minor == 25_000
        mock_account_service.session.commit.assert_called_once()

    @pytest.mark.parametrize(
        ("counts", "blocker"),
        [
            ([1, 0, 0, 0, 0, 0], "still has transactions"),
            ([0, 0, 0, 0, 0, 1], "holds a savings goal"),
        ],
        ids=["transactions", "goals"],
    )
    def test_an_account_with_anything_filed_against_it_keeps_its_currency(
        self,
        mock_account_service: AccountService,
        household_context: HouseholdContext,
        counts: list[int],
        blocker: str,
    ) -> None:
        """Every amount there was written in the old currency."""
        account = make_account()
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.return_value = account
        mock_account_service.session.exec.return_value.one.side_effect = counts

        with pytest.raises(AccountCurrencyLockedError, match=blocker):
            mock_account_service.update_account(
                household=household_context, account_id=account.id, account_update=AccountUpdate(currency_code="USD")
            )

        assert account.currency_code == "EUR"
        mock_account_service.session.commit.assert_not_called()

    def test_the_same_currency_is_not_a_change(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        """Sending the currency it already holds is what a form does, and is no change."""
        account = make_account()
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.return_value = account
        mock_account_service.session.exec.return_value.one.return_value = 1
        mock_account_service.session.exec.return_value.all.side_effect = [[(account.id, 100_000)], []]

        result = mock_account_service.update_account(
            household=household_context, account_id=account.id, account_update=AccountUpdate(currency_code="eur")
        )

        assert result.currency_code == "EUR"

    def test_a_linked_bank_decides_the_currency(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        account = make_account()
        bank_account = MagicMock(currency_code="EUR")
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.side_effect = [account, bank_account]
        mock_account_service.session.exec.return_value.one.return_value = 0

        with pytest.raises(AccountCurrencyLockedError, match="linked to a bank account in EUR"):
            mock_account_service.update_account(
                household=household_context, account_id=account.id, account_update=AccountUpdate(currency_code="USD")
            )

    def test_the_opening_balance_is_rescaled_to_the_new_decimal_places(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        """A thousand yen is a thousand minor units, and ten euros is a thousand cents."""
        account = make_account(opening_balance_minor=1_000, currency_code="JPY")
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.side_effect = [account, None]
        mock_account_service.session.exec.return_value.one.return_value = 0
        mock_account_service.session.exec.return_value.all.side_effect = [[(account.id, 100_000)], []]

        result = mock_account_service.update_account(
            household=household_context, account_id=account.id, account_update=AccountUpdate(currency_code="EUR")
        )

        assert result.opening_balance_minor == 100_000

    def test_a_fraction_the_new_currency_lacks_is_refused(
        self, mock_account_service: AccountService, household_context: HouseholdContext
    ) -> None:
        account = make_account(opening_balance_minor=1_050)
        mock_account_service.session.exec = MagicMock()
        mock_account_service.session.exec.return_value.first.side_effect = [account, None]
        mock_account_service.session.exec.return_value.one.return_value = 0

        with pytest.raises(AccountCurrencyLockedError, match="fraction JPY does not have"):
            mock_account_service.update_account(
                household=household_context, account_id=account.id, account_update=AccountUpdate(currency_code="JPY")
            )

    def test_a_code_that_is_not_three_letters_is_refused(self) -> None:
        with pytest.raises(ValueError, match="three-letter"):
            AccountUpdate(currency_code="EURO")


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
            ([1, 0, 0, 0, 0, 0], "still has transactions"),
            ([0, 1, 0, 0, 0, 0], "recurring rules paid from it"),
            ([0, 0, 1, 0, 0, 0], "destination of a recurring transfer"),
            ([0, 0, 0, 1, 0, 0], "is where an income client is paid"),
            ([0, 0, 0, 0, 1, 0], "has investment trades settled through it"),
            ([0, 0, 0, 0, 0, 1], "holds a savings goal"),
        ],
        ids=["transactions", "recurring rules", "recurring transfers", "income clients", "trades", "goals"],
    )
    def test_refuses_to_delete_an_account_something_references(
        self,
        mock_account_service: AccountService,
        household_context: HouseholdContext,
        counts: list[int],
        blocker: str,
    ) -> None:
        """Every foreign key onto account is RESTRICT, so an unchecked delete is a 500.

        Every one of them has to be asked about up front. A blocker the service
        does not name reaches the database instead, which refuses the delete
        without a reason and leaves the user reading about transactions the
        account does not have.
        """
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
