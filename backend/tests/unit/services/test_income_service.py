import uuid
from datetime import UTC, date, datetime
from fractions import Fraction
from unittest.mock import MagicMock

import pytest

from app.exceptions import (
    AccountArchivedError,
    AccountNotFoundError,
    CategoryNotFoundError,
    ClientCadenceError,
    IncomeClientInUseError,
    IncomeClientNotFoundError,
    IncomeClientNotOwnedError,
    IncomeSessionNotFoundError,
    IncomeVaultNotFoundError,
    SessionPaymentDateError,
    TransactionCategoryKindError,
)
from app.models import (
    Account,
    AccountType,
    Category,
    CategoryKind,
    ClientForecastRow,
    Household,
    IncomeClient,
    IncomeClientCreate,
    IncomeClientUpdate,
    IncomeSession,
    IncomeSessionCreate,
    IncomeSessionStatus,
    IncomeSessionUpdate,
    PaymentStatus,
    RecurrenceFrequency,
    Transaction,
    TransactionKind,
)
from app.repositories.rows import ClientTallyRow
from app.services import IncomeService

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def make_account(name: str = "Current", archived: bool = False) -> Account:
    """Build an account row for the tests."""
    return Account(
        household_id=HOUSEHOLD_ID,
        name=name,
        type=AccountType.CURRENT,
        currency_code="EUR",
        opening_balance_minor=0,
        opening_balance_date=date(2026, 1, 1),
        archived_at=datetime.now(UTC) if archived else None,
    )


def make_category(kind: CategoryKind = CategoryKind.INCOME) -> Category:
    """Build a category row for the tests."""
    return Category(household_id=HOUSEHOLD_ID, name="Freelance", kind=kind)


def make_household(label: str = "Session") -> Household:
    """Build a household row for the tests."""
    return Household(id=HOUSEHOLD_ID, name="Home", currency_code="EUR", session_merchant_label=label)


def make_client(
    account_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    archived: bool = False,
    owner_user_id: uuid.UUID | None = None,
) -> IncomeClient:
    """Build a client row for the tests.

    The name is ciphertext, as it always is: nothing on the server can read it.
    """
    return IncomeClient(
        household_id=HOUSEHOLD_ID,
        owner_user_id=owner_user_id or uuid.uuid4(),
        name_ct="Z0FBQUFBQm5jaXBoZXJ0ZXh0",
        default_rate_minor=50_00,
        default_account_id=account_id or uuid.uuid4(),
        default_category_id=category_id,
        archived_at=datetime.now(UTC) if archived else None,
    )


def make_session(
    client_id: uuid.UUID | None = None,
    status: IncomeSessionStatus = IncomeSessionStatus.ATTENDED,
    payment_status: PaymentStatus = PaymentStatus.PENDING,
    fee_minor: int = 50_00,
    paid_on: date | None = None,
) -> IncomeSession:
    """Build a session row for the tests."""
    return IncomeSession(
        household_id=HOUSEHOLD_ID,
        client_id=client_id or uuid.uuid4(),
        occurs_on=date(2026, 9, 8),
        fee_minor=fee_minor,
        status=status,
        payment_status=payment_status,
        paid_on=paid_on,
    )


def added_transactions(session: MagicMock) -> list[Transaction]:
    """Collect the transactions the service handed to the session."""
    return [call.args[0] for call in session.add.call_args_list if isinstance(call.args[0], Transaction)]


class TestVault:
    """Tests for the client-name key."""

    def test_a_household_without_a_pin_has_no_vault(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        mock_income_service.session.get = MagicMock(return_value=None)

        with pytest.raises(IncomeVaultNotFoundError):
            mock_income_service.get_vault(household=household_context)


class TestCreateClient:
    """Tests for create_client."""

    def test_a_client_is_stored_with_the_ciphertext_untouched(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        """The server is a post box for the name, never a reader of it."""
        account = make_account()
        category = make_category()
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.side_effect = [account, category]

        client = mock_income_service.create_client(
            household=household_context,
            client_create=IncomeClientCreate(
                name_ct="Z0FBQUFBQm5jaXBoZXJ0ZXh0",
                default_rate_minor=50_00,
                default_account_id=account.id,
                default_category_id=category.id,
            ),
        )

        assert client.name_ct == "Z0FBQUFBQm5jaXBoZXJ0ZXh0"
        mock_income_service.session.commit.assert_called_once()

    def test_an_unknown_account_is_refused(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.return_value = None

        with pytest.raises(AccountNotFoundError):
            mock_income_service.create_client(
                household=household_context,
                client_create=IncomeClientCreate(name_ct="ct", default_account_id=uuid.uuid4()),
            )

    def test_an_archived_account_is_refused(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        """Caught at the dialog, not months later while recording a payment."""
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.return_value = make_account(archived=True)

        with pytest.raises(AccountArchivedError):
            mock_income_service.create_client(
                household=household_context,
                client_create=IncomeClientCreate(name_ct="ct", default_account_id=uuid.uuid4()),
            )

    def test_an_expense_category_is_refused(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.side_effect = [
            make_account(),
            make_category(kind=CategoryKind.EXPENSE),
        ]

        with pytest.raises(TransactionCategoryKindError):
            mock_income_service.create_client(
                household=household_context,
                client_create=IncomeClientCreate(
                    name_ct="ct", default_account_id=uuid.uuid4(), default_category_id=uuid.uuid4()
                ),
            )

    def test_an_unknown_category_is_refused(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.side_effect = [make_account(), None]

        with pytest.raises(CategoryNotFoundError):
            mock_income_service.create_client(
                household=household_context,
                client_create=IncomeClientCreate(
                    name_ct="ct", default_account_id=uuid.uuid4(), default_category_id=uuid.uuid4()
                ),
            )


class TestUpdateAndDeleteClient:
    """Tests for update_client and delete_client."""

    def test_a_client_from_another_household_is_not_found(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        """404, never 403: telling a caller the ID exists is telling them too much."""
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.return_value = None

        with pytest.raises(IncomeClientNotFoundError):
            mock_income_service.update_client(
                household=household_context,
                client_id=uuid.uuid4(),
                client_update=IncomeClientUpdate(default_rate_minor=60_00),
            )

    def test_archiving_stamps_the_date(self, mock_income_service: IncomeService, household_context: MagicMock) -> None:
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.return_value = make_client(
            owner_user_id=household_context.user_id
        )

        client = mock_income_service.update_client(
            household=household_context, client_id=uuid.uuid4(), client_update=IncomeClientUpdate(is_archived=True)
        )

        assert client.archived_at is not None

    def test_unarchiving_clears_the_date(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.return_value = make_client(
            archived=True, owner_user_id=household_context.user_id
        )

        client = mock_income_service.update_client(
            household=household_context, client_id=uuid.uuid4(), client_update=IncomeClientUpdate(is_archived=False)
        )

        assert client.archived_at is None

    def test_a_client_with_sessions_cannot_be_deleted(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        """Those sessions are the record of work done and money taken."""
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.return_value = make_client(
            owner_user_id=household_context.user_id
        )
        mock_income_service.session.exec.return_value.one.return_value = 3

        with pytest.raises(IncomeClientInUseError):
            mock_income_service.delete_client(household=household_context, client_id=uuid.uuid4())

    def test_a_client_with_no_sessions_is_deleted(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.return_value = make_client(
            owner_user_id=household_context.user_id
        )
        mock_income_service.session.exec.return_value.one.return_value = 0

        mock_income_service.delete_client(household=household_context, client_id=uuid.uuid4())

        mock_income_service.session.delete.assert_called_once()
        mock_income_service.session.commit.assert_called_once()


class TestSessionsAndTheLedger:
    """Tests for the one rule: a session reaches the ledger when it is paid."""

    def test_an_attended_unpaid_session_writes_no_transaction(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        """The hour was worked. The money is not here. It is a debt, not income."""
        client = make_client()
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.side_effect = [client, None]

        mock_income_service.create_session(
            household=household_context,
            session_create=IncomeSessionCreate(
                client_id=client.id,
                occurs_on=date(2026, 9, 8),
                fee_minor=50_00,
                status=IncomeSessionStatus.ATTENDED,
                payment_status=PaymentStatus.PENDING,
            ),
        )

        assert added_transactions(mock_income_service.session) == []

    def test_a_paid_session_writes_the_income(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        account = make_account()
        category = make_category()
        client = make_client(account_id=account.id, category_id=category.id)
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.side_effect = [client, None, account]
        mock_income_service.session.get = MagicMock(return_value=make_household())

        mock_income_service.create_session(
            household=household_context,
            session_create=IncomeSessionCreate(
                client_id=client.id,
                occurs_on=date(2026, 9, 8),
                fee_minor=50_00,
                status=IncomeSessionStatus.ATTENDED,
                payment_status=PaymentStatus.PAID,
                paid_on=date(2026, 9, 8),
            ),
        )

        written = added_transactions(mock_income_service.session)
        assert len(written) == 1
        assert written[0].kind is TransactionKind.INCOME
        assert written[0].amount_minor == 50_00
        assert written[0].is_generated is True
        assert written[0].category_id == category.id

    def test_the_ledger_row_never_carries_the_client_name(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        """The whole reason the name is encrypted. The ledger says "Session"."""
        account = make_account()
        client = make_client(account_id=account.id)
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.side_effect = [client, None, account]
        mock_income_service.session.get = MagicMock(return_value=make_household())

        mock_income_service.create_session(
            household=household_context,
            session_create=IncomeSessionCreate(
                client_id=client.id,
                occurs_on=date(2026, 9, 8),
                fee_minor=50_00,
                status=IncomeSessionStatus.ATTENDED,
                payment_status=PaymentStatus.PAID,
                paid_on=date(2026, 9, 8),
            ),
        )

        written = added_transactions(mock_income_service.session)[0]
        assert written.merchant == "Session"
        assert written.merchant != client.name_ct
        assert written.note is None

    def test_the_household_label_is_used_when_it_was_changed(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        account = make_account()
        client = make_client(account_id=account.id)
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.side_effect = [client, None, account]
        mock_income_service.session.get = MagicMock(return_value=make_household(label="Consultation"))

        mock_income_service.create_session(
            household=household_context,
            session_create=IncomeSessionCreate(
                client_id=client.id,
                occurs_on=date(2026, 9, 8),
                fee_minor=50_00,
                payment_status=PaymentStatus.PAID,
                paid_on=date(2026, 9, 8),
            ),
        )

        assert added_transactions(mock_income_service.session)[0].merchant == "Consultation"

    def test_the_ledger_row_is_dated_the_day_the_money_arrived(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        """An hour in September paid in October is October's income."""
        account = make_account()
        client = make_client(account_id=account.id)
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.side_effect = [client, None, account]
        mock_income_service.session.get = MagicMock(return_value=make_household())

        mock_income_service.create_session(
            household=household_context,
            session_create=IncomeSessionCreate(
                client_id=client.id,
                occurs_on=date(2026, 9, 28),
                fee_minor=50_00,
                status=IncomeSessionStatus.ATTENDED,
                payment_status=PaymentStatus.PAID,
                paid_on=date(2026, 10, 3),
            ),
        )

        assert added_transactions(mock_income_service.session)[0].occurred_on == date(2026, 10, 3)

    def test_a_missed_session_that_was_charged_still_books(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        """A late cancellation fee is money, so it needs no special case."""
        account = make_account()
        client = make_client(account_id=account.id)
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.side_effect = [client, None, account]
        mock_income_service.session.get = MagicMock(return_value=make_household())

        mock_income_service.create_session(
            household=household_context,
            session_create=IncomeSessionCreate(
                client_id=client.id,
                occurs_on=date(2026, 9, 8),
                fee_minor=25_00,
                status=IncomeSessionStatus.MISSED,
                payment_status=PaymentStatus.PAID,
                paid_on=date(2026, 9, 8),
            ),
        )

        assert added_transactions(mock_income_service.session)[0].amount_minor == 25_00

    def test_a_free_session_writes_nothing(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        """A transaction of zero is one the ledger's own constraint forbids."""
        client = make_client()
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.side_effect = [client, None]

        mock_income_service.create_session(
            household=household_context,
            session_create=IncomeSessionCreate(
                client_id=client.id,
                occurs_on=date(2026, 9, 8),
                fee_minor=0,
                status=IncomeSessionStatus.ATTENDED,
                payment_status=PaymentStatus.PAID,
                paid_on=date(2026, 9, 8),
            ),
        )

        assert added_transactions(mock_income_service.session) == []

    def test_marking_a_session_paid_creates_the_transaction(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        account = make_account()
        client = make_client(account_id=account.id)
        existing = make_session(client_id=client.id, payment_status=PaymentStatus.PENDING)
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.side_effect = [existing, client, None, account]
        mock_income_service.session.get = MagicMock(return_value=make_household())

        updated = mock_income_service.update_session(
            household=household_context,
            session_id=existing.id,
            session_update=IncomeSessionUpdate(payment_status=PaymentStatus.PAID),
        )

        assert updated.payment_status is PaymentStatus.PAID
        # A one-click "mark paid" says nothing about when, so the hour's own
        # date is filled in rather than the request refused.
        assert updated.paid_on == date(2026, 9, 8)
        assert len(added_transactions(mock_income_service.session)) == 1

    def test_marking_a_paid_session_unpaid_removes_the_transaction(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        client = make_client()
        existing = make_session(client_id=client.id, payment_status=PaymentStatus.PAID, paid_on=date(2026, 9, 8))
        transaction = Transaction(
            household_id=HOUSEHOLD_ID,
            kind=TransactionKind.INCOME,
            amount_minor=50_00,
            occurred_on=date(2026, 9, 8),
            account_id=uuid.uuid4(),
            income_session_id=existing.id,
            is_generated=True,
        )
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.side_effect = [existing, client, transaction]

        updated = mock_income_service.update_session(
            household=household_context,
            session_id=existing.id,
            session_update=IncomeSessionUpdate(payment_status=PaymentStatus.PENDING),
        )

        assert updated.paid_on is None
        mock_income_service.session.delete.assert_called_once_with(transaction)

    def test_waiving_a_paid_session_removes_the_transaction(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        client = make_client()
        existing = make_session(client_id=client.id, payment_status=PaymentStatus.PAID, paid_on=date(2026, 9, 8))
        transaction = Transaction(
            household_id=HOUSEHOLD_ID,
            kind=TransactionKind.INCOME,
            amount_minor=50_00,
            occurred_on=date(2026, 9, 8),
            account_id=uuid.uuid4(),
            income_session_id=existing.id,
        )
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.side_effect = [existing, client, transaction]

        mock_income_service.update_session(
            household=household_context,
            session_id=existing.id,
            session_update=IncomeSessionUpdate(payment_status=PaymentStatus.WAIVED),
        )

        mock_income_service.session.delete.assert_called_once_with(transaction)

    def test_changing_the_fee_updates_the_same_transaction(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        """The same row, so anything pointing at it keeps pointing at it."""
        account = make_account()
        client = make_client(account_id=account.id)
        existing = make_session(client_id=client.id, payment_status=PaymentStatus.PAID, paid_on=date(2026, 9, 8))
        transaction = Transaction(
            household_id=HOUSEHOLD_ID,
            kind=TransactionKind.INCOME,
            amount_minor=50_00,
            occurred_on=date(2026, 9, 8),
            account_id=account.id,
            income_session_id=existing.id,
        )
        original_id = transaction.id
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.side_effect = [existing, client, transaction, account]
        mock_income_service.session.get = MagicMock(return_value=make_household())

        mock_income_service.update_session(
            household=household_context,
            session_id=existing.id,
            session_update=IncomeSessionUpdate(fee_minor=65_00),
        )

        assert transaction.amount_minor == 65_00
        assert transaction.id == original_id
        mock_income_service.session.delete.assert_not_called()

    def test_deleting_a_session_deletes_its_transaction(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        existing = make_session(payment_status=PaymentStatus.PAID, paid_on=date(2026, 9, 8))
        transaction = Transaction(
            household_id=HOUSEHOLD_ID,
            kind=TransactionKind.INCOME,
            amount_minor=50_00,
            occurred_on=date(2026, 9, 8),
            account_id=uuid.uuid4(),
            income_session_id=existing.id,
        )
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.side_effect = [existing, transaction]

        mock_income_service.delete_session(household=household_context, session_id=existing.id)

        assert mock_income_service.session.delete.call_count == 2

    def test_a_session_from_another_household_is_not_found(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.return_value = None

        with pytest.raises(IncomeSessionNotFoundError):
            mock_income_service.get_session(household=household_context, session_id=uuid.uuid4())


class TestPaymentDateShape:
    """Tests that the payment date and the payment status cannot disagree."""

    def test_a_paid_session_without_a_date_is_refused_on_create(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        client = make_client()
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.return_value = client

        with pytest.raises(SessionPaymentDateError):
            mock_income_service.create_session(
                household=household_context,
                session_create=IncomeSessionCreate(
                    client_id=client.id,
                    occurs_on=date(2026, 9, 8),
                    fee_minor=50_00,
                    payment_status=PaymentStatus.PAID,
                ),
            )

    def test_an_unpaid_session_with_a_date_is_refused_on_create(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        client = make_client()
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.return_value = client

        with pytest.raises(SessionPaymentDateError):
            mock_income_service.create_session(
                household=household_context,
                session_create=IncomeSessionCreate(
                    client_id=client.id,
                    occurs_on=date(2026, 9, 8),
                    fee_minor=50_00,
                    payment_status=PaymentStatus.PENDING,
                    paid_on=date(2026, 9, 8),
                ),
            )


class TestClientOwnership:
    """Tests that a practice belongs to one person, not to the household.

    The money is shared, so everyone sees the sessions and the figures. The
    names are not: they are under one person's key, and only that person can
    change or remove the client behind them.
    """

    def test_a_new_client_is_stamped_with_the_person_who_added_them(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        account = make_account()
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.return_value = account

        client = mock_income_service.create_client(
            household=household_context,
            client_create=IncomeClientCreate(name_ct="ct", default_account_id=account.id),
        )

        assert client.owner_user_id == household_context.user_id

    def test_another_members_client_cannot_be_edited(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        """Saving here would write a name they cannot read over one they cannot see."""
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.return_value = make_client()

        with pytest.raises(IncomeClientNotOwnedError):
            mock_income_service.update_client(
                household=household_context,
                client_id=uuid.uuid4(),
                client_update=IncomeClientUpdate(default_rate_minor=60_00),
            )

    def test_another_members_client_cannot_be_deleted(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.return_value = make_client()

        with pytest.raises(IncomeClientNotOwnedError):
            mock_income_service.delete_client(household=household_context, client_id=uuid.uuid4())

    def test_another_members_client_can_still_be_read(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        """The row and its figures are shared money. Only the name is private."""
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.return_value = make_client()

        client = mock_income_service.get_client(household=household_context, client_id=uuid.uuid4())

        assert client.owner_user_id != household_context.user_id

    def test_a_session_can_be_recorded_against_another_members_client(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        """It is household income, so anybody may record it."""
        theirs = make_client()
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.side_effect = [theirs, None]

        session = mock_income_service.create_session(
            household=household_context,
            session_create=IncomeSessionCreate(
                client_id=theirs.id,
                occurs_on=date(2026, 9, 8),
                fee_minor=50_00,
                status=IncomeSessionStatus.ATTENDED,
                payment_status=PaymentStatus.PENDING,
            ),
        )

        assert session.client_id == theirs.id

    def test_a_reset_names_the_calling_member_and_nobody_else(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        # What the service owes here is the right owner. Whether the statement
        # scopes to it correctly is the repository's promise, and is asserted
        # against a real statement in test_income_filters.
        clients = mock_income_service.income_client_repository
        clients.blank_names_for_owner = MagicMock(return_value=0)  # type: ignore[method-assign]
        mock_income_service.session.get = MagicMock(return_value=None)

        mock_income_service.reset_vault(household=household_context)
        passed = clients.blank_names_for_owner.call_args.kwargs

        assert passed["owner_user_id"] == household_context.user_id
        assert passed["household_id"] == household_context.household_id


class TestVaultIsPerUser:
    """Tests that the key belongs to a person, not to the household."""

    def test_the_vault_is_looked_up_by_the_current_user(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        mock_income_service.session.get = MagicMock(return_value=None)

        with pytest.raises(IncomeVaultNotFoundError):
            mock_income_service.get_vault(household=household_context)

        assert mock_income_service.session.get.call_args.args[1] == household_context.user_id


class TestClientCadence:
    """Tests that a client's schedule is either whole or absent.

    "Every week" says nothing without a day to pin it to, and a date pins
    nothing without a frequency. Half a schedule is refused here so it arrives
    as a message rather than as an integrity error from the database.
    """

    def test_a_client_can_be_seen_as_and_when(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        account = make_account()
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.return_value = account

        client = mock_income_service.create_client(
            household=household_context,
            client_create=IncomeClientCreate(name_ct="ct", default_account_id=account.id),
        )

        assert client.cadence_frequency is None
        assert client.cadence_anchor_on is None

    def test_a_weekly_client_keeps_the_day_it_was_pinned_to(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        account = make_account()
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.return_value = account

        client = mock_income_service.create_client(
            household=household_context,
            client_create=IncomeClientCreate(
                name_ct="ct",
                default_account_id=account.id,
                cadence_frequency=RecurrenceFrequency.WEEKLY,
                cadence_interval=2,
                # A Monday, which is what makes this "every other Monday".
                cadence_anchor_on=date(2026, 9, 7),
            ),
        )

        assert client.cadence_frequency is RecurrenceFrequency.WEEKLY
        assert client.cadence_interval == 2
        assert client.cadence_anchor_on == date(2026, 9, 7)

    def test_a_frequency_without_a_day_is_refused(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        with pytest.raises(ClientCadenceError):
            mock_income_service.create_client(
                household=household_context,
                client_create=IncomeClientCreate(
                    name_ct="ct",
                    default_account_id=uuid.uuid4(),
                    cadence_frequency=RecurrenceFrequency.WEEKLY,
                ),
            )

    def test_a_day_without_a_frequency_is_refused(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        with pytest.raises(ClientCadenceError):
            mock_income_service.create_client(
                household=household_context,
                client_create=IncomeClientCreate(
                    name_ct="ct",
                    default_account_id=uuid.uuid4(),
                    cadence_anchor_on=date(2026, 9, 7),
                ),
            )

    def test_dropping_only_the_frequency_is_refused(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        """Checked against the stored row, not only against the request."""
        stored = make_client(owner_user_id=household_context.user_id)
        stored.cadence_frequency = RecurrenceFrequency.WEEKLY
        stored.cadence_anchor_on = date(2026, 9, 7)
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.return_value = stored

        with pytest.raises(ClientCadenceError):
            mock_income_service.update_client(
                household=household_context,
                client_id=stored.id,
                client_update=IncomeClientUpdate(cadence_frequency=None),
            )

    def test_a_client_can_stop_being_a_regular(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        stored = make_client(owner_user_id=household_context.user_id)
        stored.cadence_frequency = RecurrenceFrequency.WEEKLY
        stored.cadence_anchor_on = date(2026, 9, 7)
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.return_value = stored

        client = mock_income_service.update_client(
            household=household_context,
            client_id=stored.id,
            client_update=IncomeClientUpdate(cadence_frequency=None, cadence_anchor_on=None),
        )

        assert client.cadence_frequency is None


class TestSeveralDaysAWeek:
    """Tests that a client can be seen on more than one day a week.

    A practice is not one appointment a week each. Somebody seen Monday,
    Tuesday, Thursday and Friday has one pattern, and this is what stores it.
    """

    def test_a_client_can_be_seen_four_days_a_week(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        account = make_account()
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.return_value = account

        client = mock_income_service.create_client(
            household=household_context,
            client_create=IncomeClientCreate(
                name_ct="ct",
                default_account_id=account.id,
                cadence_frequency=RecurrenceFrequency.WEEKLY,
                cadence_anchor_on=date(2026, 9, 7),
                cadence_weekdays=[0, 1, 3, 4],
            ),
        )

        assert client.cadence_weekdays == [0, 1, 3, 4]

    def test_the_days_are_sorted_and_deduplicated(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        """Stored the same way whatever order somebody clicked them in."""
        account = make_account()
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.return_value = account

        client = mock_income_service.create_client(
            household=household_context,
            client_create=IncomeClientCreate(
                name_ct="ct",
                default_account_id=account.id,
                cadence_frequency=RecurrenceFrequency.WEEKLY,
                cadence_anchor_on=date(2026, 9, 7),
                cadence_weekdays=[4, 0, 4, 3],
            ),
        )

        assert client.cadence_weekdays == [0, 3, 4]

    def test_naming_no_days_is_still_allowed(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        """The simple case stays simple: one day a week, taken from the anchor."""
        account = make_account()
        mock_income_service.session.exec = MagicMock()
        mock_income_service.session.exec.return_value.first.return_value = account

        client = mock_income_service.create_client(
            household=household_context,
            client_create=IncomeClientCreate(
                name_ct="ct",
                default_account_id=account.id,
                cadence_frequency=RecurrenceFrequency.WEEKLY,
                cadence_anchor_on=date(2026, 9, 7),
            ),
        )

        assert client.cadence_weekdays == []

    def test_a_day_outside_the_week_is_refused(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        with pytest.raises(ClientCadenceError):
            mock_income_service.create_client(
                household=household_context,
                client_create=IncomeClientCreate(
                    name_ct="ct",
                    default_account_id=uuid.uuid4(),
                    cadence_frequency=RecurrenceFrequency.WEEKLY,
                    cadence_anchor_on=date(2026, 9, 7),
                    cadence_weekdays=[0, 9],
                ),
            )

    def test_days_are_refused_on_a_monthly_schedule(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        """Storing a preference that could never apply is worse than refusing."""
        with pytest.raises(ClientCadenceError):
            mock_income_service.create_client(
                household=household_context,
                client_create=IncomeClientCreate(
                    name_ct="ct",
                    default_account_id=uuid.uuid4(),
                    cadence_frequency=RecurrenceFrequency.MONTHLY,
                    cadence_anchor_on=date(2026, 9, 7),
                    cadence_weekdays=[0, 3],
                ),
            )


class TestTheYearTotal:
    """Tests for the year-to-date figure on the summary."""

    @staticmethod
    def stub(service: IncomeService, earned: tuple[int, int]) -> MagicMock:
        """Silence every read `get_summary` makes except the one under test.

        The fixture hands over a real repository sitting on a mocked session, so
        the methods themselves are replaced rather than programmed.
        """
        sessions = service.income_session_repository
        sessions.monthly_totals = MagicMock(return_value=[])  # type: ignore[method-assign]
        sessions.booked_for_month = MagicMock(return_value=(0, 0))  # type: ignore[method-assign]
        sessions.outstanding_for_household = MagicMock(return_value=(0, 0, None))  # type: ignore[method-assign]
        sessions.earned_for_range = MagicMock(return_value=earned)  # type: ignore[method-assign]
        service.income_client_repository.count_active_for_household = MagicMock(return_value=0)  # type: ignore[method-assign]
        # The currency comes off the household row, and a MagicMock is not a
        # string as far as the response model is concerned.
        service.household_repository.get_by_id = MagicMock(return_value=make_household())  # type: ignore[method-assign]
        return sessions.earned_for_range

    def test_the_year_is_the_calendar_one_the_month_sits_in(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        # A year has a start. Rolling back twelve months from the chosen month
        # would answer a question nobody asked, least of all a tax office.
        earned_for_range = self.stub(mock_income_service, (250_000, 47))

        summary = mock_income_service.get_summary(household=household_context, month="2026-09")
        span = earned_for_range.call_args.kwargs

        assert summary.year == 2026
        assert summary.year_earned_minor == 250_000
        assert summary.year_session_count == 47
        assert (span["date_from"], span["date_to"]) == (date(2026, 1, 1), date(2027, 1, 1))

    def test_a_month_in_another_year_reports_that_year(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        self.stub(mock_income_service, (0, 0))

        summary = mock_income_service.get_summary(household=household_context, month="2025-03")

        assert summary.year == 2025

    def test_the_year_is_not_the_month(self, mock_income_service: IncomeService, household_context: MagicMock) -> None:
        # The month tile and the year tile read the same kind of figure over
        # different spans, and only one of them is moved by a quiet fortnight.
        self.stub(mock_income_service, (250_000, 47))

        summary = mock_income_service.get_summary(household=household_context, month="2026-09")

        assert summary.earned_minor == 0
        assert summary.year_earned_minor == 250_000


class TestResetVault:
    """Tests for forgetting the client-name key."""

    def test_every_name_is_blanked_not_just_the_first_page(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        # The listing is capped, so walking it would leave anybody past the cap
        # holding ciphertext no future key could decode, while the response
        # said their names had been reset.
        clients = mock_income_service.income_client_repository
        clients.blank_names_for_owner = MagicMock(return_value=0)  # type: ignore[method-assign]
        clients.list_for_household = MagicMock()  # type: ignore[method-assign]
        mock_income_service.income_vault_repository.get_for_user = MagicMock(return_value=None)  # type: ignore[method-assign]

        mock_income_service.reset_vault(household=household_context)

        clients.blank_names_for_owner.assert_called_once()
        clients.list_for_household.assert_not_called()

    def test_only_this_member_s_names_are_touched(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        # Another member's names are under another key and are none of this
        # reset's business.
        clients = mock_income_service.income_client_repository
        clients.blank_names_for_owner = MagicMock(return_value=0)  # type: ignore[method-assign]
        mock_income_service.income_vault_repository.get_for_user = MagicMock(return_value=None)  # type: ignore[method-assign]

        mock_income_service.reset_vault(household=household_context)

        assert clients.blank_names_for_owner.call_args.kwargs["owner_user_id"] == household_context.user_id


class TestTheTrialRoster:
    """Tests for which clients the estimate prices."""

    @staticmethod
    def stub(service: IncomeService, sessions: list[IncomeSession]) -> tuple[MagicMock, MagicMock]:
        """Programme the two client lookups the trial building makes."""
        clients = service.income_client_repository
        clients.list_for_household = MagicMock(return_value=([], 0))  # type: ignore[method-assign]
        clients.list_by_ids = MagicMock(return_value=[])  # type: ignore[method-assign]
        service.income_session_repository.for_month = MagicMock(return_value=sessions)  # type: ignore[method-assign]
        service.income_session_repository.client_tallies = MagicMock(return_value=[])  # type: ignore[method-assign]
        return clients.list_for_household, clients.list_by_ids

    def test_the_capped_roster_asks_only_for_active_clients(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        # The cap and the archived are the whole point. Sharing one page lets a
        # long list of finished clients push active ones out, and `list_for_household`
        # orders oldest first, so the ones pushed out are the newest — exactly
        # the clients with appointments still to come.
        listed, _ = self.stub(mock_income_service, [])

        mock_income_service._trials(
            household=household_context,
            target_month="2026-09",
            house=Fraction(1),
            churn=Fraction(0),
            date_from=date(2026, 3, 1),
            date_to=date(2026, 9, 1),
        )

        assert listed.call_args.kwargs["filters"].is_archived is False

    def test_a_client_in_the_month_s_diary_is_fetched_by_id(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        # Somebody who has stopped coming can still have an appointment left,
        # and the booked total counts it, so it has to be priced. Fetched by id
        # rather than out of the capped page, so it costs the roster nothing.
        booked = make_session(status=IncomeSessionStatus.SCHEDULED)
        _, by_ids = self.stub(mock_income_service, [booked])

        mock_income_service._trials(
            household=household_context,
            target_month="2026-09",
            house=Fraction(1),
            churn=Fraction(0),
            date_from=date(2026, 3, 1),
            date_to=date(2026, 9, 1),
        )

        assert by_ids.call_args.kwargs["client_ids"] == [booked.client_id]

    def test_the_trials_report_how_much_of_the_roster_they_walked(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        # The cap is why this is worth reporting. A practice with more active
        # clients than one page holds is estimated from the ones that fit, and
        # nothing in the figure itself says so, so the count comes back with it.
        listed, _ = self.stub(mock_income_service, [])
        listed.return_value = ([make_client(), make_client()], 2)

        _, priced = mock_income_service._trials(
            household=household_context,
            target_month="2026-09",
            house=Fraction(1),
            churn=Fraction(0),
            date_from=date(2026, 3, 1),
            date_to=date(2026, 9, 1),
        )

        assert priced == 2


def make_tally(
    client_id: uuid.UUID,
    attended: int = 0,
    missed: int = 0,
    cancelled: int = 0,
    earned_minor: int = 0,
) -> ClientTallyRow:
    """Build one grouped per-client row for the tests."""
    return ClientTallyRow(
        client_id=client_id,
        attended_count=attended,
        missed_count=missed,
        cancelled_count=cancelled,
        earned_minor=earned_minor,
        outstanding_minor=0,
        oldest_unpaid_on=None,
        last_session_on=None,
    )


class TestTheForecastTable:
    """Tests for the per-client table under the estimate."""

    @staticmethod
    def stub(
        service: IncomeService,
        tallies: list[ClientTallyRow],
        clients: list[IncomeClient],
    ) -> None:
        """Programme the tally read and the client lookup behind the table."""
        service.income_session_repository.client_tallies = MagicMock(return_value=tallies)  # type: ignore[method-assign]
        service.income_client_repository.list_for_household = MagicMock(return_value=(clients, len(clients)))  # type: ignore[method-assign]
        service.income_client_repository.list_by_ids = MagicMock(return_value=clients)  # type: ignore[method-assign]

    def rows(self, service: IncomeService, household: MagicMock, months: int = 6) -> list[ClientForecastRow]:
        """Build the table the way the forecast does."""
        return service._client_rows(
            household=household,
            date_from=date(2026, 3, 1),
            date_to=date(2026, 9, 1),
            months=months,
            target_month="2026-09",
        )

    def test_a_client_with_a_tally_gets_a_row(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        client = make_client()
        self.stub(mock_income_service, [make_tally(client.id, attended=3, earned_minor=300_00)], [client])

        rows = self.rows(mock_income_service, household_context)

        assert [row.client_id for row in rows] == [client.id]
        assert rows[0].attended_count == 3
        # The window is six months, so the average is the sixth of it.
        assert rows[0].average_monthly_minor == 50_00

    def test_a_client_with_nothing_behind_them_has_no_attendance_rate(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        # None rather than zero: a new client has not been unreliable, they are
        # simply unknown, and a zero would read as the worst record on the page.
        client = make_client()
        self.stub(mock_income_service, [make_tally(client.id, cancelled=2)], [client])

        assert self.rows(mock_income_service, household_context)[0].attendance_rate is None

    def test_a_tally_with_no_client_left_is_skipped(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        # The name lives on the client row, so a tally the lookup cannot match
        # has nothing to label it with.
        self.stub(mock_income_service, [make_tally(uuid.uuid4(), attended=1)], [])

        assert self.rows(mock_income_service, household_context) == []

    def test_an_archived_client_is_marked_as_one(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        # They still owe what they owe, so they belong in the table; the page
        # only needs to know not to expect more hours from them.
        client = make_client(archived=True)
        self.stub(mock_income_service, [make_tally(client.id, attended=1)], [client])

        assert self.rows(mock_income_service, household_context)[0].is_archived is True

    def test_the_clients_are_fetched_by_the_tallies_that_name_them(
        self, mock_income_service: IncomeService, household_context: MagicMock
    ) -> None:
        # By id rather than out of a capped page. The table is as long as the
        # window's tallies, so a practice with a roster longer than one page
        # would otherwise have had its newest clients dropped from the table
        # while their figures still counted towards the totals above it.
        first, second = make_client(), make_client()
        self.stub(
            mock_income_service,
            [make_tally(first.id, attended=1), make_tally(second.id, attended=2)],
            [first, second],
        )

        self.rows(mock_income_service, household_context)

        lookup = mock_income_service.income_client_repository.list_by_ids
        assert lookup.call_args.kwargs["client_ids"] == [first.id, second.id]  # type: ignore[attr-defined]
        mock_income_service.income_client_repository.list_for_household.assert_not_called()  # type: ignore[attr-defined]
