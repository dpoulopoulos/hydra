import asyncio
import logging
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.core.email_dispatcher import (
    dispatch_once,
    email_dispatcher_lifespan,
    prune_once,
    prune_rate_limits_once,
    run_email_dispatcher,
    run_mail_rate_limit_pruner,
    run_outbox_pruner,
)


class TestDispatchOnce:
    """Test one round of draining the outbox."""

    def test_dispatch_once_drains_the_outbox_in_its_own_session(self) -> None:
        """The dispatcher runs outside any request, so it opens its own session."""
        # Arrange: Watch the session and the service the round builds
        with patch("app.core.email_dispatcher.Session") as mock_session_class:
            with patch("app.core.email_dispatcher.EmailOutboxService") as mock_service_class:
                mock_service_class.for_session.return_value.dispatch_due.return_value = 2

                # Act: Run one round
                delivered = dispatch_once()

        # Assert: Verify the round drained the outbox and closed its session
        assert delivered == 2
        session = mock_session_class.return_value.__enter__.return_value
        mock_service_class.for_session.assert_called_once_with(session)
        mock_session_class.return_value.__exit__.assert_called_once()


class TestRunEmailDispatcher:
    """Test the loop that keeps draining the outbox."""

    def test_the_loop_waits_before_its_first_round(self) -> None:
        """A process that exits straight away never touches the database."""
        # Arrange: Stop the loop on the first wait
        with patch("app.core.email_dispatcher.asyncio.sleep", side_effect=asyncio.CancelledError):
            with patch("app.core.email_dispatcher.dispatch_once") as mock_dispatch:
                # Act: Run the loop until it is cancelled
                with pytest.raises(asyncio.CancelledError):
                    asyncio.run(run_email_dispatcher())

        # Assert: Verify the poll interval came first
        mock_dispatch.assert_not_called()

    def test_the_loop_survives_a_failed_round(self, caplog: pytest.LogCaptureFixture) -> None:
        """A database that is briefly unreachable must not end the dispatcher."""
        # Arrange: The first round fails, the second is cancelled
        sleeps = [None, asyncio.CancelledError]

        async def sleep(_: float) -> None:
            outcome = sleeps.pop(0)
            if outcome is not None:
                raise outcome

        with patch("app.core.email_dispatcher.asyncio.sleep", side_effect=sleep):
            with patch("app.core.email_dispatcher.dispatch_once", side_effect=OSError("no route to host")):
                # Act: Run the loop until it is cancelled
                with caplog.at_level(logging.ERROR, logger="app.core.email_dispatcher"):
                    with pytest.raises(asyncio.CancelledError):
                        asyncio.run(run_email_dispatcher())

        # Assert: Verify the failure was reported and the loop went round again
        assert "no route to host" in caplog.text
        assert not sleeps


class TestEmailDispatcherLifespan:
    """Test what the application starts and stops around the dispatcher."""

    def test_the_dispatcher_runs_while_the_app_does(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The loop is started at startup and cancelled at shutdown."""
        # Arrange: Mail is configured, whatever the developer's .env happens to say
        monkeypatch.setattr(settings, "EMAILS_FROM_EMAIL", "noreply@example.com")
        monkeypatch.setattr(settings, "EMAIL_PROVIDER", "smtp")
        monkeypatch.setattr(settings, "SMTP_HOST", "localhost")

        async def exercise() -> asyncio.Task[None]:
            with patch("app.core.email_dispatcher.dispatch_once", return_value=0):
                async with email_dispatcher_lifespan(MagicMock()):
                    tasks = asyncio.all_tasks()
                    running = [task for task in tasks if task.get_name() == "email-outbox-dispatcher"]
                    assert len(running) == 1
                    return running[0]

        # Act: Enter and leave the lifespan
        task = asyncio.run(exercise())

        # Assert: Verify the loop did not outlive the application
        assert task.cancelled() or task.done()

    def test_the_dispatcher_does_not_run_without_a_provider(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """With no mail configured there is nothing to deliver."""
        # Arrange: Emails are not configured
        monkeypatch.setattr(settings, "EMAILS_FROM_EMAIL", None)

        async def exercise() -> list[asyncio.Task[None]]:
            async with email_dispatcher_lifespan(MagicMock()):
                return [task for task in asyncio.all_tasks() if task.get_name() == "email-outbox-dispatcher"]

        # Act: Enter and leave the lifespan
        with caplog.at_level(logging.INFO, logger="app.core.email_dispatcher"):
            running = asyncio.run(exercise())

        # Assert: Verify nothing was started, and the log says why
        assert running == []
        assert "disabled" in caplog.text


class TestPruneOnce:
    """Test one round of applying the retention windows."""

    def test_prune_once_prunes_the_outbox_in_its_own_session(self) -> None:
        """The pruner runs outside any request, so it opens its own session."""
        # Arrange: Watch the session and the service the round builds
        with patch("app.core.email_dispatcher.Session") as mock_session_class:
            with patch("app.core.email_dispatcher.EmailOutboxService") as mock_service_class:
                mock_service_class.for_session.return_value.prune_expired.return_value = 5

                # Act: Run one round
                removed = prune_once()

        # Assert: Verify the round pruned the outbox and closed its session
        assert removed == 5
        session = mock_session_class.return_value.__enter__.return_value
        mock_service_class.for_session.assert_called_once_with(session)
        mock_session_class.return_value.__exit__.assert_called_once()


class TestRunOutboxPruner:
    """Test the loop that keeps the outbox to its retention windows."""

    def test_the_loop_waits_before_its_first_round(self) -> None:
        """Startup is the worst moment to take a lock on the whole table."""
        # Arrange: Stop the loop on the first wait
        with patch("app.core.email_dispatcher.asyncio.sleep", side_effect=asyncio.CancelledError):
            with patch("app.core.email_dispatcher.prune_once") as mock_prune:
                # Act: Run the loop until it is cancelled
                with pytest.raises(asyncio.CancelledError):
                    asyncio.run(run_outbox_pruner())

        # Assert: Verify the interval came first
        mock_prune.assert_not_called()

    def test_the_loop_survives_a_failed_round(self, caplog: pytest.LogCaptureFixture) -> None:
        """A retention round that fails must not take the pruner with it."""
        # Arrange: The first round fails, the second is cancelled
        sleeps = [None, asyncio.CancelledError]

        async def sleep(_: float) -> None:
            outcome = sleeps.pop(0)
            if outcome is not None:
                raise outcome

        with patch("app.core.email_dispatcher.asyncio.sleep", side_effect=sleep):
            with patch("app.core.email_dispatcher.prune_once", side_effect=OSError("no route to host")):
                # Act: Run the loop until it is cancelled
                with caplog.at_level(logging.ERROR, logger="app.core.email_dispatcher"):
                    with pytest.raises(asyncio.CancelledError):
                        asyncio.run(run_outbox_pruner())

        # Assert: Verify the failure was reported and the loop went round again
        assert "no route to host" in caplog.text
        assert not sleeps


class TestPrunerLifespan:
    """Test what the application starts and stops around the pruner."""

    def test_the_pruner_runs_while_the_app_does(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Nothing else ever takes a row out of the outbox."""
        # Arrange: Mail is configured, whatever the developer's .env happens to say
        monkeypatch.setattr(settings, "EMAILS_FROM_EMAIL", "noreply@example.com")
        monkeypatch.setattr(settings, "EMAIL_PROVIDER", "smtp")
        monkeypatch.setattr(settings, "SMTP_HOST", "localhost")

        async def exercise() -> asyncio.Task[None]:
            with patch("app.core.email_dispatcher.dispatch_once", return_value=0):
                with patch("app.core.email_dispatcher.prune_once", return_value=0):
                    async with email_dispatcher_lifespan(MagicMock()):
                        running = [task for task in asyncio.all_tasks() if task.get_name() == "email-outbox-pruner"]
                        assert len(running) == 1
                        return running[0]

        # Act: Enter and leave the lifespan
        task = asyncio.run(exercise())

        # Assert: Verify the loop did not outlive the application
        assert task.cancelled() or task.done()

    def test_the_pruner_runs_even_without_a_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A deployment that turned mail off still has the rows it wrote while it was on."""
        # Arrange: Emails are not configured
        monkeypatch.setattr(settings, "EMAILS_FROM_EMAIL", None)

        async def exercise() -> list[asyncio.Task[None]]:
            with patch("app.core.email_dispatcher.prune_once", return_value=0):
                async with email_dispatcher_lifespan(MagicMock()):
                    return [task for task in asyncio.all_tasks() if task.get_name() == "email-outbox-pruner"]

        # Act: Enter and leave the lifespan
        running = asyncio.run(exercise())

        # Assert: Verify the pruner was started anyway
        assert len(running) == 1


class TestPruneRateLimitsOnce:
    """Test one round of dropping the mail budgets whose window has passed."""

    def test_the_round_prunes_the_counters_in_its_own_session(self) -> None:
        """The pruner runs outside any request, so it opens its own session."""
        # Arrange: Watch the session and the service the round builds
        with patch("app.core.email_dispatcher.Session") as mock_session_class:
            with patch("app.core.email_dispatcher.MailRateLimitService") as mock_service_class:
                mock_service_class.for_session.return_value.prune_expired.return_value = 3

                # Act: Run one round
                removed = prune_rate_limits_once()

        # Assert: Verify the round pruned the counters and closed its session
        assert removed == 3
        session = mock_session_class.return_value.__enter__.return_value
        mock_service_class.for_session.assert_called_once_with(session)
        mock_session_class.return_value.__exit__.assert_called_once()


class TestRunMailRateLimitPruner:
    """Test the loop that drops the spent mail budgets."""

    def test_the_loop_waits_before_its_first_round(self) -> None:
        """Startup is the worst moment to take a lock on the whole table."""
        # Arrange: Stop the loop on the first wait
        with patch("app.core.email_dispatcher.asyncio.sleep", side_effect=asyncio.CancelledError):
            with patch("app.core.email_dispatcher.prune_rate_limits_once") as mock_prune:
                # Act: Run the loop until it is cancelled
                with pytest.raises(asyncio.CancelledError):
                    asyncio.run(run_mail_rate_limit_pruner())

        # Assert: Verify the interval came first
        mock_prune.assert_not_called()

    def test_the_loop_survives_a_failed_round(self, caplog: pytest.LogCaptureFixture) -> None:
        """A retention round that fails must not take the pruner with it."""
        # Arrange: The first round fails, the second is cancelled
        sleeps = [None, asyncio.CancelledError]

        async def sleep(_: float) -> None:
            outcome = sleeps.pop(0)
            if outcome is not None:
                raise outcome

        with patch("app.core.email_dispatcher.asyncio.sleep", side_effect=sleep):
            with patch("app.core.email_dispatcher.prune_rate_limits_once", side_effect=OSError("no route to host")):
                # Act: Run the loop until it is cancelled
                with caplog.at_level(logging.ERROR, logger="app.core.email_dispatcher"):
                    with pytest.raises(asyncio.CancelledError):
                        asyncio.run(run_mail_rate_limit_pruner())

        # Assert: Verify the failure was reported and the loop went round again
        assert "no route to host" in caplog.text
        assert not sleeps

    def test_the_pruner_runs_even_without_a_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The budgets are counted before anything asks whether mail can be sent."""
        # Arrange: Emails are not configured
        monkeypatch.setattr(settings, "EMAILS_FROM_EMAIL", None)

        async def exercise() -> list[asyncio.Task[None]]:
            with patch("app.core.email_dispatcher.prune_once", return_value=0):
                with patch("app.core.email_dispatcher.prune_rate_limits_once", return_value=0):
                    async with email_dispatcher_lifespan(MagicMock()):
                        return [task for task in asyncio.all_tasks() if task.get_name() == "mail-rate-limit-pruner"]

        # Act: Enter and leave the lifespan
        running = asyncio.run(exercise())

        # Assert: Verify the pruner was started anyway
        assert len(running) == 1
