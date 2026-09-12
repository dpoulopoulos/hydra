import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.logging import get_logger
from app.services.email_outbox import EmailOutboxService
from app.services.mail_rate_limit import MailRateLimitService

logger = get_logger(__name__)

DISPATCHER_TASK_NAME = "email-outbox-dispatcher"
PRUNER_TASK_NAME = "email-outbox-pruner"
RATE_LIMIT_PRUNER_TASK_NAME = "mail-rate-limit-pruner"


def dispatch_once() -> int:
    """Run one round of the outbox: the messages that are due, up to a batch.

    Returns:
        The number of messages the provider accepted.
    """
    with Session(engine) as session:
        return EmailOutboxService.for_session(session).dispatch_due()


def prune_once() -> int:
    """Run one round of retention: the settled rows whose window has passed.

    Returns:
        The number of rows removed.
    """
    with Session(engine) as session:
        return EmailOutboxService.for_session(session).prune_expired()


def prune_rate_limits_once() -> int:
    """Run one round of retention: the mail budgets whose window has passed.

    Returns:
        The number of rows removed.
    """
    with Session(engine) as session:
        return MailRateLimitService.for_session(session).prune_expired()


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
        # The wait comes first: a process that exits immediately should not have
        # opened a session at all. It is also what a deferred message waits
        # out, so a round that is due to a signup leaves up to one interval
        # after the request that asked for it.
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


async def run_outbox_pruner() -> None:
    """Keep the outbox to its retention windows for as long as the app runs.

    Nothing else ever takes a row out of the table, and every row holds the
    whole rendered body of its message.
    """
    await run_rounds(
        prune_once,
        interval_seconds=settings.EMAIL_OUTBOX_PRUNE_INTERVAL_SECONDS,
        failure="Could not prune the email outbox",
        outcome="Removed %d expired outbox row(s)",
    )


async def run_mail_rate_limit_pruner() -> None:
    """Drop the spent mail budgets for as long as the application runs.

    A counter is only a running total, and the request path never removes one:
    without this the table keeps a row, holding an address, for every caller
    the app has answered and every mailbox it has been asked to write to.
    """
    await run_rounds(
        prune_rate_limits_once,
        interval_seconds=settings.MAIL_RATE_LIMIT_PRUNE_INTERVAL_SECONDS,
        failure="Could not prune the mail rate limit counters",
        outcome="Removed %d expired mail rate limit counter(s)",
    )


@asynccontextmanager
async def email_dispatcher_lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Run the outbox background jobs alongside the application.

    Args:
        _: The application being started (unused).

    Yields:
        Nothing; the application runs inside the context.
    """
    # Neither pruner depends on mail being configured. A deployment that has
    # turned delivery off still holds every row it wrote while it was on, and
    # the budgets are counted before anything asks whether mail can be sent.
    tasks = [
        asyncio.create_task(run_outbox_pruner(), name=PRUNER_TASK_NAME),
        asyncio.create_task(run_mail_rate_limit_pruner(), name=RATE_LIMIT_PRUNER_TASK_NAME),
    ]

    if settings.emails_enabled:
        tasks.append(asyncio.create_task(run_email_dispatcher(), name=DISPATCHER_TASK_NAME))
    else:
        logger.info("Email delivery is disabled, so the outbox dispatcher was not started")

    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        # Give the tasks the chance to unwind before the loop closes under them.
        await asyncio.gather(*tasks, return_exceptions=True)
