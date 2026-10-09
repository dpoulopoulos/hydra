import datetime
import uuid
from unittest.mock import MagicMock

import pytest

from app.exceptions import (
    BankAccountMappingError,
    BankTransactionKindError,
    BankTransactionNotFoundError,
    BankTransactionReviewedError,
)
from app.models import (
    BankAccount,
    BankDirection,
    BankInboxFilters,
    BankReviewStatus,
    BankTransaction,
    BankTransactionAccept,
    HouseholdContext,
    Transaction,
    TransactionKind,
)
from app.services import BankInboxService

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
LINKED_ACCOUNT = uuid.uuid4()
OTHER_ACCOUNT = uuid.uuid4()


def make_bank_account(account_id: uuid.UUID | None = LINKED_ACCOUNT) -> BankAccount:
    return BankAccount(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        connection_id=uuid.uuid4(),
        provider_account_uid="u",
        identity_key="k",
        name="Main",
        account_id=account_id,
    )


def make_row(
    bank_account: BankAccount,
    direction: BankDirection = BankDirection.DEBIT,
    status: BankReviewStatus = BankReviewStatus.PENDING,
    **fields: object,
) -> BankTransaction:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "household_id": HOUSEHOLD_ID,
        "bank_account_id": bank_account.id,
        "sync_run_id": uuid.uuid4(),
        "dedupe_key": "ref:1",
        "direction": direction,
        "amount_minor": 1250,
        "currency_code": "EUR",
        "occurred_on": datetime.date(2026, 10, 1),
        "counterparty_name": "Coffee Island",
        "description": "CARD 1234",
        "review_status": status,
        "created_at": datetime.datetime.now(datetime.UTC),
    }
    values.update(fields)
    return BankTransaction(**values)


@pytest.fixture
def service(mock_db_session: MagicMock) -> BankInboxService:
    service = BankInboxService(
        session=mock_db_session,
        bank_transaction_repository=MagicMock(),
        bank_account_repository=MagicMock(),
        transaction_service=MagicMock(),
    )
    service.transaction_service.record_transaction.side_effect = lambda **kwargs: Transaction(
        id=uuid.uuid4(),
        household_id=HOUSEHOLD_ID,
        **kwargs["transaction_create"].model_dump(),
    )
    return service


def program(service: BankInboxService, row: BankTransaction, bank_account: BankAccount) -> None:
    service.bank_transaction_repository.lock_for_household.return_value = row
    service.bank_account_repository.get_for_household.return_value = bank_account


class TestList:
    """Tests for listing the inbox."""

    def test_adds_the_bank_account_to_each_row(
        self, service: BankInboxService, household_context: HouseholdContext
    ) -> None:
        bank_account = make_bank_account()
        service.bank_transaction_repository.list_inbox.return_value = (
            [(make_row(bank_account), bank_account)],
            7,
        )

        result = service.list_inbox(household_context, BankInboxFilters())

        assert result.count == 7
        assert result.data[0].bank_account_name == "Main"
        assert result.data[0].account_id == LINKED_ACCOUNT


class TestAccept:
    """Tests for accepting an inbox row."""

    def test_records_spending_and_links_it(
        self, service: BankInboxService, household_context: HouseholdContext
    ) -> None:
        bank_account = make_bank_account()
        row = make_row(bank_account)
        program(service, row, bank_account)
        category_id = uuid.uuid4()

        result = service.accept(
            household_context, row.id, BankTransactionAccept(kind=TransactionKind.EXPENSE, category_id=category_id)
        )

        kwargs = service.transaction_service.record_transaction.call_args.kwargs
        create = kwargs["transaction_create"]
        assert create.kind == TransactionKind.EXPENSE
        assert create.amount_minor == 1250
        assert create.occurred_on == datetime.date(2026, 10, 1)
        assert create.account_id == LINKED_ACCOUNT
        assert create.category_id == category_id
        assert create.merchant == "Coffee Island"
        assert create.note == "CARD 1234"
        assert kwargs["external_id"] == f"eb:{row.id}"
        assert kwargs["import_batch_id"] == row.sync_run_id
        assert result.review_status == BankReviewStatus.ACCEPTED
        assert result.ledger_transaction_id is not None
        assert row.reviewed_by_user_id == household_context.user.id
        service.session.commit.assert_called_once()

    def test_merchant_and_note_can_be_given(
        self, service: BankInboxService, household_context: HouseholdContext
    ) -> None:
        bank_account = make_bank_account()
        row = make_row(bank_account, counterparty_name=None)
        program(service, row, bank_account)

        service.accept(
            household_context, row.id, BankTransactionAccept(kind=TransactionKind.EXPENSE, merchant="Cafe", note="")
        )

        create = service.transaction_service.record_transaction.call_args.kwargs["transaction_create"]
        assert create.merchant == "Cafe"
        assert create.note == ""

    def test_money_out_as_a_transfer_goes_to_the_chosen_account(
        self, service: BankInboxService, household_context: HouseholdContext
    ) -> None:
        bank_account = make_bank_account()
        row = make_row(bank_account, BankDirection.DEBIT)
        program(service, row, bank_account)

        service.accept(
            household_context,
            row.id,
            BankTransactionAccept(kind=TransactionKind.TRANSFER, counter_account_id=OTHER_ACCOUNT),
        )

        create = service.transaction_service.record_transaction.call_args.kwargs["transaction_create"]
        assert (create.account_id, create.counter_account_id) == (LINKED_ACCOUNT, OTHER_ACCOUNT)

    def test_money_in_as_a_transfer_comes_from_the_chosen_account(
        self, service: BankInboxService, household_context: HouseholdContext
    ) -> None:
        bank_account = make_bank_account()
        row = make_row(bank_account, BankDirection.CREDIT)
        program(service, row, bank_account)

        service.accept(
            household_context,
            row.id,
            BankTransactionAccept(kind=TransactionKind.TRANSFER, counter_account_id=OTHER_ACCOUNT),
        )

        create = service.transaction_service.record_transaction.call_args.kwargs["transaction_create"]
        assert (create.account_id, create.counter_account_id) == (OTHER_ACCOUNT, LINKED_ACCOUNT)

    def test_a_transfer_needs_the_other_account(
        self, service: BankInboxService, household_context: HouseholdContext
    ) -> None:
        bank_account = make_bank_account()
        row = make_row(bank_account)
        program(service, row, bank_account)

        with pytest.raises(BankTransactionKindError, match="other account"):
            service.accept(household_context, row.id, BankTransactionAccept(kind=TransactionKind.TRANSFER))

    @pytest.mark.parametrize(
        ("direction", "kind"),
        [(BankDirection.DEBIT, TransactionKind.INCOME), (BankDirection.CREDIT, TransactionKind.EXPENSE)],
    )
    def test_the_kind_must_fit_the_direction(
        self,
        service: BankInboxService,
        household_context: HouseholdContext,
        direction: BankDirection,
        kind: TransactionKind,
    ) -> None:
        bank_account = make_bank_account()
        row = make_row(bank_account, direction)
        program(service, row, bank_account)

        with pytest.raises(BankTransactionKindError):
            service.accept(household_context, row.id, BankTransactionAccept(kind=kind))

        service.transaction_service.record_transaction.assert_not_called()

    def test_an_unlinked_bank_account_is_refused(
        self, service: BankInboxService, household_context: HouseholdContext
    ) -> None:
        bank_account = make_bank_account(account_id=None)
        row = make_row(bank_account)
        program(service, row, bank_account)

        with pytest.raises(BankAccountMappingError):
            service.accept(household_context, row.id, BankTransactionAccept(kind=TransactionKind.EXPENSE))

    @pytest.mark.parametrize("status", [BankReviewStatus.ACCEPTED, BankReviewStatus.SKIPPED])
    def test_a_reviewed_row_is_refused(
        self, service: BankInboxService, household_context: HouseholdContext, status: BankReviewStatus
    ) -> None:
        bank_account = make_bank_account()
        row = make_row(bank_account, status=status)
        program(service, row, bank_account)

        with pytest.raises(BankTransactionReviewedError, match=status.value):
            service.accept(household_context, row.id, BankTransactionAccept(kind=TransactionKind.EXPENSE))

    def test_an_unknown_row_is_refused(self, service: BankInboxService, household_context: HouseholdContext) -> None:
        service.bank_transaction_repository.lock_for_household.return_value = None

        with pytest.raises(BankTransactionNotFoundError):
            service.accept(household_context, uuid.uuid4(), BankTransactionAccept(kind=TransactionKind.EXPENSE))

    def test_a_row_whose_bank_account_is_gone_is_refused(
        self, service: BankInboxService, household_context: HouseholdContext
    ) -> None:
        row = make_row(make_bank_account())
        service.bank_transaction_repository.lock_for_household.return_value = row
        service.bank_account_repository.get_for_household.return_value = None

        with pytest.raises(BankTransactionNotFoundError):
            service.accept(household_context, row.id, BankTransactionAccept(kind=TransactionKind.EXPENSE))


class TestSkipAndReopen:
    """Tests for skipping a row and putting it back."""

    def test_skip(self, service: BankInboxService, household_context: HouseholdContext) -> None:
        bank_account = make_bank_account()
        row = make_row(bank_account)
        program(service, row, bank_account)

        result = service.skip(household_context, row.id)

        assert result.review_status == BankReviewStatus.SKIPPED
        assert row.reviewed_at is not None

    def test_reopen_a_skipped_row(self, service: BankInboxService, household_context: HouseholdContext) -> None:
        bank_account = make_bank_account()
        row = make_row(bank_account, status=BankReviewStatus.SKIPPED, reviewed_at=datetime.datetime.now(datetime.UTC))
        program(service, row, bank_account)

        result = service.reopen(household_context, row.id)

        assert result.review_status == BankReviewStatus.PENDING
        assert row.reviewed_at is None

    @pytest.mark.parametrize("status", [BankReviewStatus.PENDING, BankReviewStatus.ACCEPTED])
    def test_only_a_skipped_row_can_be_reopened(
        self, service: BankInboxService, household_context: HouseholdContext, status: BankReviewStatus
    ) -> None:
        bank_account = make_bank_account()
        program(service, make_row(bank_account, status=status), bank_account)

        with pytest.raises(BankTransactionReviewedError):
            service.reopen(household_context, uuid.uuid4())
