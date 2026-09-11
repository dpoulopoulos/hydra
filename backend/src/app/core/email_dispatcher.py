import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.logging import get_logger
from app.services.email_outbox import EmailOutboxService

logger = get_logger(__name__)

DISPATCHER_TASK_NAME = "email-outbox-dispatcher"


def dispatch_once() -> int:
    """Run one round of the outbox: the messages that are due, up to a batch.

    Returns:
        The number of messages the provider accepted.
    """
    with Session(engine) as session:
        return EmailOutboxService.for_session(session).dispatch_due()


async def run_rounds(round_: Callable[[], int], *, interval_seconds: int, failure: str, outcome: str) -> None:
    """Run one piece of background work over and over, for as long as the app runs.

    Args:
        round_: The work to do once, returning how many rows it settled. It
            talks to the database and may talk to a mail provider, both of
            which block, so it is run in a worker thread.
        interval_seconds: How long to wait between rounds.
        failure: What to log when a round raises, as a sentence.
        outcome: What to log when a round settled something, with one ``%d``
            for the count. A round that settled nothing says nothing.
    """
    while True:
        # The wait comes first: a message queued by a request has already been
        # attempted by that request, and a process that exits immediately
        # should not have opened a session at all.
        await asyncio.sleep(interval_seconds)

        try:
            settled = await asyncio.to_thread(round_)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A round that fails must not end the loop: the reason is usually
            # the database or the provider, and both come back.
            logger.exception(failure)
            continue

        if settled:
            logger.info(outcome, settled)


async def run_email_dispatcher() -> None:
    """Drain the email outbox for as long as the application runs.

    This is what turns a queued message into a delivered one: without it the
    outbox only ever holds what the request path could not send.
    """
    await run_rounds(
        dispatch_once,
        interval_seconds=settings.EMAIL_OUTBOX_POLL_SECONDS,
        failure="Could not drain the email outbox",
        outcome="Delivered %d queued email(s)",
    )


@asynccontextmanager
async def email_dispatcher_lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Run the outbox dispatcher alongside the application.

    Args:
        _: The application being started (unused).

    Yields:
        Nothing; the application runs inside the context.
    """
    if not settings.emails_enabled:
        logger.info("Email delivery is disabled, so the outbox dispatcher was not started")
        yield
        return

    task = asyncio.create_task(run_email_dispatcher(), name=DISPATCHER_TASK_NAME)
    try:
        yield
    finally:
        task.cancel()
        # Give the task the chance to unwind before the loop closes under it.
        await asyncio.gather(task, return_exceptions=True)
