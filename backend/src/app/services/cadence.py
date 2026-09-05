"""Turning a client's schedule into the days it actually falls on.

A practice is mostly standing appointments, and they are not all one a week.
Somebody seen on Monday, Tuesday, Thursday and Friday has one pattern, not
four, and this is the module that knows how to read it.

Kept apart from `recurrence`, which serves recurring rules and knows nothing
about weekday sets. Everything a weekday set does not touch is delegated there
rather than written twice, so the awkward parts — a monthly schedule on the
31st landing in February, running off the end of the calendar — keep the one
implementation that is already tested.
"""

import datetime
from collections.abc import Iterable, Sequence

from app.models import RecurrenceFrequency
from app.models.income import MONDAY, SUNDAY
from app.services.recurrence import DAYS_IN_WEEK, occurrences_until

# The same ceiling recurrence uses, for the same reason: a schedule anchored
# decades ago must not be able to build an unbounded list.
MAX_OCCURRENCES = 500


def normalise_weekdays(weekdays: Iterable[int] | None) -> list[int]:
    """Put a set of weekdays into a stable, duplicate-free order.

    Stored sorted so that two clients seen on the same days compare equal, and
    so the page can render them in the order a week runs rather than the order
    somebody happened to click them.

    Args:
        weekdays: Days of the week, Monday as 0. None or empty means the
            pattern simply keeps the weekday it was pinned to.

    Returns:
        The days, sorted and deduplicated.

    Raises:
        ValueError: If a value is not a day of the week.
    """
    days = sorted(set(weekdays or []))

    if any(day < MONDAY or day > SUNDAY for day in days):
        raise ValueError("A weekday must be between 0 (Monday) and 6 (Sunday).")

    return days


def expand(
    frequency: RecurrenceFrequency,
    interval: int,
    anchor_on: datetime.date,
    date_from: datetime.date,
    date_to: datetime.date,
    weekdays: Sequence[int] | None = None,
    limit: int = MAX_OCCURRENCES,
) -> list[datetime.date]:
    """List the days a client's schedule falls on within a window.

    A weekly schedule with named days is the only case handled here. The anchor
    stops meaning "the weekday" and starts meaning "which week", so a
    fortnightly pattern on Monday and Thursday lands on both days of every
    second week counted from the anchor's own week.

    Args:
        frequency: How often the client is seen.
        interval: How many periods lie between occurrences.
        anchor_on: The date the pattern is pinned to.
        date_from: First day to include.
        date_to: Last day to include, inclusive.
        weekdays: For a weekly schedule, the days it falls on, Monday as 0.
        limit: The most dates to return.

    Returns:
        The days, oldest first.
    """
    days = normalise_weekdays(weekdays)

    if frequency is not RecurrenceFrequency.WEEKLY or not days:
        # Nothing here that `recurrence` does not already do, including running
        # off the end of the calendar and short months.
        return [
            day
            for day in occurrences_until(
                cursor=anchor_on,
                until=date_to,
                frequency=frequency,
                interval=interval,
                # Without this, a monthly schedule on the 31st that February
                # pulled back to the 28th would stay on the 28th for ever.
                anchor_day=anchor_on.day,
                limit=limit,
            )
            if day >= date_from
        ]

    # Count from the Monday of the anchor's week, so "every second week" means
    # the same thing whichever day of that week the anchor happens to be.
    first_monday = anchor_on - datetime.timedelta(days=anchor_on.weekday())
    step = datetime.timedelta(days=DAYS_IN_WEEK * interval)

    dates: list[datetime.date] = []
    week = first_monday

    # Skip whole weeks rather than stepping a day at a time: a window years
    # after the anchor would otherwise walk every week in between.
    if week < date_from:
        weeks_behind = (date_from - week).days // (DAYS_IN_WEEK * interval)
        week += step * weeks_behind

    while week <= date_to and len(dates) < limit:
        for day in days:
            occurrence = week + datetime.timedelta(days=day)

            if date_from <= occurrence <= date_to and occurrence >= anchor_on:
                dates.append(occurrence)

        week += step

    return sorted(dates)[:limit]
