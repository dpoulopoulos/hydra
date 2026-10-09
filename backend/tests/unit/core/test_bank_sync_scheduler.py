import asyncio
import datetime
import logging
from unittest.mock import MagicMock, patch

import pytest

from app.core.bank_sync_scheduler import PRUNER_TASK_NAME, SYNC_TASK_NAME, bank_sync_lifespan, prune_once, sync_due_once
from app.core.config import settings


class TestRounds:
    """Test one round of each bank sync job."""

    def test_sync_due_once_syncs_in_its_own_session(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The automatic sync runs outside any request, so it opens its own session."""
        monkeypatch.setattr(settings, "BANK_SYNC_AUTO_INTERVAL_HOURS", 24)
        with patch("app.core.bank_sync_scheduler.Session") as mock_session_class:
            with patch("app.core.bank_sync_scheduler.BankSyncService") as mock_service_class:
                mock_service_class.for_session.return_value.sync_due.return_value = 3

                synced = sync_due_once()

        assert synced == 3
        kwargs = mock_service_class.for_session.return_value.sync_due.call_args.kwargs
        assert kwargs["interval"] == datetime.timedelta(hours=24)
        assert kwargs["limit"] > 0
        mock_session_class.return_value.__exit__.assert_called_once()

    def test_prune_once_prunes_in_its_own_session(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The clean-up passes the retention windows from the settings."""
        monkeypatch.setattr(settings, "BANK_RAW_RETENTION_DAYS", 90)
        monkeypatch.setattr(settings, "BANK_PENDING_CONNECTION_TTL_MINUTES", 60)
        with patch("app.core.bank_sync_scheduler.Session"):
            with patch("app.core.bank_sync_scheduler.BankSyncService") as mock_service_class:
                mock_service_class.for_session.return_value.prune.return_value = 5

                pruned = prune_once()

        assert pruned == 5
        kwargs = mock_service_class.for_session.return_value.prune.call_args.kwargs
        assert kwargs["raw_retention"] == datetime.timedelta(days=90)
        assert kwargs["pending_ttl"] == datetime.timedelta(minutes=60)


class TestBankSyncLifespan:
    """Test what the application starts and stops around the bank sync."""

    def test_the_jobs_run_while_the_app_does(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Both loops are started at startup and cancelled at shutdown."""
        monkeypatch.setattr(settings, "ENABLE_BANKING_APP_ID", "app-id")
        monkeypatch.setattr(settings, "ENABLE_BANKING_PRIVATE_KEY", "pem")

        async def exercise() -> list[asyncio.Task[None]]:
            async with bank_sync_lifespan(MagicMock()):
                names = {SYNC_TASK_NAME, PRUNER_TASK_NAME}
                running = [task for task in asyncio.all_tasks() if task.get_name() in names]
                assert len(running) == 2
                return running

        tasks = asyncio.run(exercise())

        assert all(task.cancelled() or task.done() for task in tasks)

    def test_nothing_runs_without_bank_sync(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """With bank sync off there is nothing to sync and nothing to prune."""
        monkeypatch.setattr(settings, "ENABLE_BANKING_APP_ID", "")
        monkeypatch.setattr(settings, "ENABLE_BANKING_PRIVATE_KEY", "")

        async def exercise() -> list[asyncio.Task[None]]:
            async with bank_sync_lifespan(MagicMock()):
                return [task for task in asyncio.all_tasks() if task.get_name() in (SYNC_TASK_NAME, PRUNER_TASK_NAME)]

        with caplog.at_level(logging.INFO, logger="app.core.bank_sync_scheduler"):
            running = asyncio.run(exercise())

        assert running == []
        assert "not configured" in caplog.text
