"""The automatic bank sync, and the clean-up after it, run alongside the app."""

import asyncio
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import Session

from app.api.deps import get_bank_provider
from app.core.config import settings
from app.core.db import engine
from app.core.email_dispatcher import run_rounds
from app.logging import get_logger
from app.services.bank_sync import BankSyncService

logger = get_logger(__name__)

SYNC_TASK_NAME = "bank-sync"
PRUNER_TASK_NAME = "bank-sync-pruner"

# How many connections one round syncs at most. Each takes a few seconds per
# account, and the rest are picked up by the next round.
SYNC_BATCH_SIZE = 10
PRUNE_INTERVAL_SECONDS = 3600


def _service(session: Session) -> BankSyncService:
    return BankSyncService.for_session(session, get_bank_provider(), settings.BANK_SYNC_OVERLAP_DAYS)


def sync_due_once() -> int:
    """Run one round of the automatic sync: the connections that came due, up to a batch.

    Returns:
        The number of connections synced.
    """
    with Session(engine) as session:
        return _service(session).sync_due(
            now=datetime.datetime.now(datetime.UTC),
            interval=datetime.timedelta(hours=settings.BANK_SYNC_AUTO_INTERVAL_HOURS),
            limit=SYNC_BATCH_SIZE,
        )


def prune_once() -> int:
    """Run one round of clean-up: abandoned logins, and bank data past its retention.

    Returns:
        The number of rows removed or cleared.
    """
    with Session(engine) as session:
        return _service(session).prune(
            now=datetime.datetime.now(datetime.UTC),
            pending_ttl=datetime.timedelta(minutes=settings.BANK_PENDING_CONNECTION_TTL_MINUTES),
            raw_retention=datetime.timedelta(days=settings.BANK_RAW_RETENTION_DAYS),
        )


@asynccontextmanager
async def bank_sync_lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Run the bank sync background jobs alongside the application.

    Args:
        _: The application being started (unused).

    Yields:
        Nothing; the application runs inside the context.
    """
    if not settings.bank_sync_enabled:
        logger.info("Bank sync is not configured, so the automatic sync was not started")
        yield
        return

    tasks = [
        asyncio.create_task(
            run_rounds(
                sync_due_once,
                interval_seconds=settings.BANK_SYNC_POLL_SECONDS,
                failure="Could not run the automatic bank sync",
                outcome="Synced %d bank connection(s)",
            ),
            name=SYNC_TASK_NAME,
        ),
        asyncio.create_task(
            run_rounds(
                prune_once,
                interval_seconds=PRUNE_INTERVAL_SECONDS,
                failure="Could not prune bank sync data",
                outcome="Pruned %d bank sync row(s)",
            ),
            name=PRUNER_TASK_NAME,
        ),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        # Give the tasks the chance to unwind before the loop closes under them.
        await asyncio.gather(*tasks, return_exceptions=True)
