"""Pure date arithmetic for recurring rules.

Kept free of the database and the models so it can be tested directly. It is
the only real algorithm in the app, and the place where a mistake would quietly
create a transaction on the wrong day, so every case has a test.
"""

import calendar
from datetime import date, timedelta

from app.models import RecurrenceFrequency

DAYS_IN_WEEK = 7

# How many occurrences one pass may create for a single rule. A rule whose
# start date is decades in the past would otherwise insert thousands of rows
# the first time anybody opened the app.
MAX_OCCURRENCES_PER_RUN = 500


def days_in_month(year: int, month: int) -> int:
    """Get the number of days in a month.

    Args:
        year: The year.
        month: The month, 1 to 12.

    Returns:
        The number of days in that month.
    """
    return calendar.monthrange(year, month)[1]


def _on_day(year: int, month: int, day: int) -> date:
    """Build a date, pulling the day back to the end of a short month.

    Args:
        year: The year.
        month: The month, 1 to 12.
        day: The intended day of the month.

    Returns:
        The date, with the day clamped to the last day of that month.
    """
    return date(year, month, min(day, days_in_month(year, month)))


def first_occurrence(start_date: date, frequency: RecurrenceFrequency, day_of_month: int | None = None) -> date:
    """Work out when a rule first falls due.

    Args:
        start_date: The day the rule takes effect.
        frequency: How often the rule repeats.
        day_of_month: For a monthly or yearly rule, the day it falls on.
            Ignored for a weekly rule, which keeps the weekday of the start date.

    Returns:
        The first date the rule falls due, never before the start date.
    """
    if day_of_month is None or frequency is RecurrenceFrequency.WEEKLY:
        return start_date

    candidate = _on_day(start_date.year, start_date.month, day_of_month)

    if candidate >= start_date:
        return candidate

    # The day has already gone by this month, so the rule waits a period.
    return advance(current=candidate, frequency=frequency, interval=1, anchor_day=day_of_month)


def advance(
    current: date,
    frequency: RecurrenceFrequency,
    interval: int,
    anchor_day: int | None = None,
) -> date:
    """Move a date on by one period of a rule.

    Args:
        current: The date to move on from.
        frequency: How often the rule repeats.
        interval: How many periods to move. Every second week is interval 2.
        anchor_day: The day of the month the rule is anchored to. Given
            separately from `current`, because a rule on the 31st that was
            pulled back to 28 February must return to the 31st in March rather
            than staying on the 28th.

    Returns:
        The next date the rule falls due.

    Raises:
        ValueError: If the interval would not move the date forward.
    """
    if interval < 1:
        raise ValueError("A recurrence interval must be at least 1.")

    day = anchor_day or current.day

    if frequency is RecurrenceFrequency.WEEKLY:
        return current + timedelta(days=DAYS_IN_WEEK * interval)

    if frequency is RecurrenceFrequency.YEARLY:
        return _on_day(current.year + interval, current.month, day)

    # Monthly. Count months from zero so the year rolls over by division.
    months = current.year * 12 + (current.month - 1) + interval

    return _on_day(months // 12, months % 12 + 1, day)


def occurrences_until(
    cursor: date,
    until: date,
    frequency: RecurrenceFrequency,
    interval: int,
    anchor_day: int | None = None,
    end_date: date | None = None,
    limit: int = MAX_OCCURRENCES_PER_RUN,
) -> list[date]:
    """List the dates a rule has fallen due on, up to and including a day.

    Args:
        cursor: The next date the rule is due, which has not been created yet.
        until: The last day to create up to, inclusive.
        frequency: How often the rule repeats.
        interval: How many periods lie between occurrences.
        anchor_day: The day of the month the rule is anchored to.
        end_date: The day the rule stops, inclusive. None means it never stops.
        limit: The most occurrences to return in one pass.

    Returns:
        The due dates, oldest first, at most `limit` of them.

    Raises:
        ValueError: If the interval would not move the date forward.
    """
    if interval < 1:
        raise ValueError("A recurrence interval must be at least 1.")

    last = min(until, end_date) if end_date else until
    dates: list[date] = []
    current = cursor

    while current <= last and len(dates) < limit:
        dates.append(current)
        current = advance(current=current, frequency=frequency, interval=interval, anchor_day=anchor_day)

    return dates
