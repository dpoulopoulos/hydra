import logging
from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.models import MailRateLimitKind
from app.repositories import MailRateLimitRepository
from app.services import MailRateLimitService


@pytest.fixture
def mock_mail_rate_limit_repository(mock_db_session: MagicMock) -> MailRateLimitRepository:
    """Create a MailRateLimitRepository instance with a mocked session.

    Args:
        mock_db_session: The mock database session.

    Returns:
        A MailRateLimitRepository instance with a mocked session.
    """
    return MailRateLimitRepository(session=mock_db_session)


@pytest.fixture
def mock_mail_rate_limit_service(
    mock_db_session: MagicMock, mock_mail_rate_limit_repository: MailRateLimitRepository
) -> MailRateLimitService:
    """Create a MailRateLimitService instance with a mocked session and repository.

    Args:
        mock_db_session: The mock database session.
        mock_mail_rate_limit_repository: The mock mail rate limit repository.

    Returns:
        A MailRateLimitService instance with a mocked session and repository.
    """
    return MailRateLimitService(session=mock_db_session, mail_rate_limit_repository=mock_mail_rate_limit_repository)


class TestAllowsMail:
    """Test the two budgets a request is counted against."""

    def test_a_first_request_is_allowed(self, mock_mail_rate_limit_service: MailRateLimitService) -> None:
        """The limits bound abuse, so the ordinary request must not notice them."""
        # Arrange: Nobody has asked for anything yet
        mock_mail_rate_limit_service.mail_rate_limit_repository.count_attempt = MagicMock(return_value=1)

        # Act: Ask whether a signup may send its verification email
        allowed = mock_mail_rate_limit_service.allows_mail(source="203.0.113.7", recipient="new@example.com")

        # Assert: Verify it may, having spent one of each budget
        assert allowed is True
        assert mock_mail_rate_limit_service.mail_rate_limit_repository.count_attempt.call_count == 2

    def test_the_request_that_reaches_the_limit_still_sends(
        self, mock_mail_rate_limit_service: MailRateLimitService
    ) -> None:
        """The budget is what the window allows, not what it stops one short of."""
        # Arrange: This attempt is the last the recipient's budget covers
        mock_mail_rate_limit_service.mail_rate_limit_repository.count_attempt = MagicMock(
            return_value=settings.MAIL_RATE_LIMIT_PER_RECIPIENT
        )

        # Act: Ask whether it may send
        allowed = mock_mail_rate_limit_service.allows_mail(source="203.0.113.7", recipient="victim@example.com")

        # Assert: Verify it may
        assert allowed is True

    def test_a_spent_recipient_budget_stops_the_mail(self, mock_mail_rate_limit_service: MailRateLimitService) -> None:
        """One mailbox cannot be flooded by however many callers name it."""
        # Arrange: The address has already had everything its window allows
        mock_mail_rate_limit_service.mail_rate_limit_repository.count_attempt = MagicMock(
            return_value=settings.MAIL_RATE_LIMIT_PER_RECIPIENT + 1
        )

        # Act: Ask whether one more may be sent to it
        allowed = mock_mail_rate_limit_service.allows_mail(source="203.0.113.7", recipient="victim@example.com")

        # Assert: Verify it may not
        assert allowed is False

    def test_a_spent_source_budget_leaves_the_recipient_untouched(
        self, mock_mail_rate_limit_service: MailRateLimitService
    ) -> None:
        """A caller that is already over must not spend the budget of every address it names."""
        # Arrange: The caller has spent its own budget
        count_attempt = MagicMock(return_value=settings.MAIL_RATE_LIMIT_PER_SOURCE + 1)
        mock_mail_rate_limit_service.mail_rate_limit_repository.count_attempt = count_attempt

        # Act: Ask whether it may send to an address that has asked for nothing
        allowed = mock_mail_rate_limit_service.allows_mail(source="203.0.113.7", recipient="victim@example.com")

        # Assert: Verify it may not, and that only the caller was counted
        assert allowed is False
        count_attempt.assert_called_once()
        assert count_attempt.call_args.kwargs["kind"] is MailRateLimitKind.SOURCE

    def test_a_recipient_is_counted_in_one_case(self, mock_mail_rate_limit_service: MailRateLimitService) -> None:
        """An address is the same mailbox however it is capitalised."""
        # Arrange: Watch what the recipient's budget is counted against
        count_attempt = MagicMock(return_value=1)
        mock_mail_rate_limit_service.mail_rate_limit_repository.count_attempt = count_attempt

        # Act: Name the address in capitals, with the whitespace a form leaves
        mock_mail_rate_limit_service.allows_mail(source=None, recipient="  Victim@Example.COM ")

        # Assert: Verify the budget belongs to the address, not to its spelling
        count_attempt.assert_called_once()
        assert count_attempt.call_args.kwargs["subject"] == "victim@example.com"

    def test_a_request_with_no_source_still_spends_the_recipient_budget(
        self, mock_mail_rate_limit_service: MailRateLimitService
    ) -> None:
        """A caller whose address is unknown must not be a way past both budgets."""
        # Arrange: Watch which budgets are counted
        count_attempt = MagicMock(return_value=1)
        mock_mail_rate_limit_service.mail_rate_limit_repository.count_attempt = count_attempt

        # Act: Ask on behalf of a request whose source could not be worked out
        allowed = mock_mail_rate_limit_service.allows_mail(source=None, recipient="new@example.com")

        # Assert: Verify the recipient was still counted
        assert allowed is True
        count_attempt.assert_called_once()
        assert count_attempt.call_args.kwargs["kind"] is MailRateLimitKind.RECIPIENT

    def test_a_refusal_is_logged(
        self, mock_mail_rate_limit_service: MailRateLimitService, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Nothing else says that mail was refused: the caller is told the usual thing."""
        # Arrange: A budget that is spent
        mock_mail_rate_limit_service.mail_rate_limit_repository.count_attempt = MagicMock(
            return_value=settings.MAIL_RATE_LIMIT_PER_RECIPIENT + 10
        )

        # Act: Ask whether it may send
        with caplog.at_level(logging.WARNING):
            mock_mail_rate_limit_service.allows_mail(source=None, recipient="victim@example.com")

        # Assert: Verify whoever runs the deployment can see it happening
        assert "victim@example.com" in caplog.text


class TestPruneExpired:
    """Test dropping the counters whose window has passed."""

    def test_prune_reports_what_it_removed(self, mock_mail_rate_limit_service: MailRateLimitService) -> None:
        """The count is what the background loop logs when it did something."""
        # Arrange: Two counters have run out
        mock_mail_rate_limit_service.mail_rate_limit_repository.delete_expired = MagicMock(return_value=2)

        # Act: Run one round of retention
        removed = mock_mail_rate_limit_service.prune_expired()

        # Assert: Verify the removal is reported and committed
        assert removed == 2
        mock_mail_rate_limit_service.session.commit.assert_called_once()
