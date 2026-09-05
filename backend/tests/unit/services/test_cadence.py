from datetime import date

import pytest

from app.models import RecurrenceFrequency
from app.services.cadence import expand, normalise_weekdays

MONDAY = 0
TUESDAY = 1
THURSDAY = 3
FRIDAY = 4

# 7 September 2026 is a Monday, which is what makes these cases readable.
ANCHOR_MONDAY = date(2026, 9, 7)


class TestNormaliseWeekdays:
    """Tests for normalise_weekdays."""

    def test_days_are_sorted(self) -> None:
        """Two clients seen on the same days should be stored the same way."""
        assert normalise_weekdays([FRIDAY, MONDAY, THURSDAY]) == [MONDAY, THURSDAY, FRIDAY]

    def test_duplicates_are_dropped(self) -> None:
        assert normalise_weekdays([MONDAY, MONDAY]) == [MONDAY]

    def test_nothing_named_is_an_empty_list(self) -> None:
        assert normalise_weekdays(None) == []
        assert normalise_weekdays([]) == []

    @pytest.mark.parametrize("day", [-1, 7, 99])
    def test_a_day_outside_the_week_is_refused(self, day: int) -> None:
        """An out-of-range day would silently never match, which is worse."""
        with pytest.raises(ValueError):
            normalise_weekdays([day])


class TestSeveralDaysAWeek:
    """Tests for a weekly schedule that names its days."""

    def test_four_days_a_week_lands_on_all_four(self) -> None:
        days = expand(
            frequency=RecurrenceFrequency.WEEKLY,
            interval=1,
            anchor_on=ANCHOR_MONDAY,
            date_from=ANCHOR_MONDAY,
            date_to=date(2026, 9, 13),
            weekdays=[MONDAY, TUESDAY, THURSDAY, FRIDAY],
        )

        assert days == [date(2026, 9, 7), date(2026, 9, 8), date(2026, 9, 10), date(2026, 9, 11)]

    def test_the_days_come_back_in_date_order(self) -> None:
        days = expand(
            frequency=RecurrenceFrequency.WEEKLY,
            interval=1,
            anchor_on=ANCHOR_MONDAY,
            date_from=ANCHOR_MONDAY,
            date_to=date(2026, 9, 20),
            weekdays=[FRIDAY, MONDAY],
        )

        assert days == sorted(days)

    def test_an_interval_skips_whole_weeks_not_days(self) -> None:
        """Every other week means both days of that week, then a week off."""
        days = expand(
            frequency=RecurrenceFrequency.WEEKLY,
            interval=2,
            anchor_on=ANCHOR_MONDAY,
            date_from=ANCHOR_MONDAY,
            date_to=date(2026, 9, 27),
            weekdays=[MONDAY, THURSDAY],
        )

        assert days == [date(2026, 9, 7), date(2026, 9, 10), date(2026, 9, 21), date(2026, 9, 24)]

    def test_naming_no_days_keeps_the_weekday_it_was_pinned_to(self) -> None:
        days = expand(
            frequency=RecurrenceFrequency.WEEKLY,
            interval=1,
            anchor_on=ANCHOR_MONDAY,
            date_from=ANCHOR_MONDAY,
            date_to=date(2026, 9, 28),
        )

        assert days == [date(2026, 9, 7), date(2026, 9, 14), date(2026, 9, 21), date(2026, 9, 28)]

    def test_nothing_before_the_day_the_pattern_started(self) -> None:
        """The anchor's own week counts, but not the days before it began."""
        days = expand(
            frequency=RecurrenceFrequency.WEEKLY,
            interval=1,
            anchor_on=date(2026, 9, 10),
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 13),
            weekdays=[MONDAY, THURSDAY],
        )

        assert days == [date(2026, 9, 10)]

    def test_a_window_years_later_still_lines_up(self) -> None:
        """Counted in whole weeks, not walked one week at a time."""
        days = expand(
            frequency=RecurrenceFrequency.WEEKLY,
            interval=2,
            anchor_on=ANCHOR_MONDAY,
            date_from=date(2028, 9, 4),
            date_to=date(2028, 9, 17),
            weekdays=[MONDAY],
        )

        # Whole fortnights from the anchor, so a Monday two years on still
        # falls in an "on" week rather than drifting.
        assert all((day - ANCHOR_MONDAY).days % 14 == 0 for day in days)

    def test_the_window_is_inclusive_at_both_ends(self) -> None:
        days = expand(
            frequency=RecurrenceFrequency.WEEKLY,
            interval=1,
            anchor_on=ANCHOR_MONDAY,
            date_from=ANCHOR_MONDAY,
            date_to=date(2026, 9, 14),
            weekdays=[MONDAY],
        )

        assert days == [date(2026, 9, 7), date(2026, 9, 14)]

    def test_the_list_is_bounded(self) -> None:
        days = expand(
            frequency=RecurrenceFrequency.WEEKLY,
            interval=1,
            anchor_on=ANCHOR_MONDAY,
            date_from=ANCHOR_MONDAY,
            date_to=date(2030, 1, 1),
            weekdays=[MONDAY, TUESDAY, THURSDAY, FRIDAY],
            limit=10,
        )

        assert len(days) == 10


class TestTheOtherFrequencies:
    """Tests that everything without named days is left to `recurrence`."""

    def test_a_daily_schedule_lands_every_day(self) -> None:
        days = expand(
            frequency=RecurrenceFrequency.DAILY,
            interval=1,
            anchor_on=date(2026, 9, 1),
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 4),
        )

        assert days == [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3), date(2026, 9, 4)]

    def test_a_monthly_schedule_keeps_its_day_of_the_month(self) -> None:
        days = expand(
            frequency=RecurrenceFrequency.MONTHLY,
            interval=1,
            anchor_on=date(2026, 1, 15),
            date_from=date(2026, 1, 1),
            date_to=date(2026, 3, 31),
        )

        assert days == [date(2026, 1, 15), date(2026, 2, 15), date(2026, 3, 15)]

    def test_a_monthly_schedule_on_the_31st_comes_back_after_february(self) -> None:
        """Pulled back to the 28th, not stuck there: the anchor is remembered."""
        days = expand(
            frequency=RecurrenceFrequency.MONTHLY,
            interval=1,
            anchor_on=date(2026, 1, 31),
            date_from=date(2026, 1, 1),
            date_to=date(2026, 3, 31),
        )

        assert days == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)]

    def test_named_days_are_ignored_when_the_schedule_is_not_weekly(self) -> None:
        # The service refuses this combination outright; here it simply must
        # not change the dates.
        with_days = expand(
            frequency=RecurrenceFrequency.MONTHLY,
            interval=1,
            anchor_on=date(2026, 1, 15),
            date_from=date(2026, 1, 1),
            date_to=date(2026, 3, 31),
            weekdays=[MONDAY, FRIDAY],
        )

        assert with_days == [date(2026, 1, 15), date(2026, 2, 15), date(2026, 3, 15)]
