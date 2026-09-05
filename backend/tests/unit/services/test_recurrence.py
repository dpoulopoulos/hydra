from datetime import date

import pytest

from app.models import RecurrenceFrequency
from app.models.recurring_rule import MAX_RECURRENCE_INTERVAL
from app.services.recurrence import advance, first_occurrence, occurrences_until


class TestFirstOccurrence:
    """Tests for first_occurrence."""

    def test_a_monthly_rule_starts_on_its_start_date(self) -> None:
        assert first_occurrence(start_date=date(2026, 3, 4), frequency=RecurrenceFrequency.MONTHLY) == date(2026, 3, 4)

    def test_an_explicit_day_moves_the_first_occurrence_forward(self) -> None:
        """A rule that starts on the 4th but bills on the 15th first falls due on the 15th."""
        assert first_occurrence(
            start_date=date(2026, 3, 4), frequency=RecurrenceFrequency.MONTHLY, day_of_month=15
        ) == date(2026, 3, 15)

    def test_an_explicit_day_already_passed_moves_to_the_next_month(self) -> None:
        assert first_occurrence(
            start_date=date(2026, 3, 20), frequency=RecurrenceFrequency.MONTHLY, day_of_month=15
        ) == date(2026, 4, 15)

    def test_a_day_beyond_the_month_is_clamped(self) -> None:
        assert first_occurrence(
            start_date=date(2026, 2, 1), frequency=RecurrenceFrequency.MONTHLY, day_of_month=31
        ) == date(2026, 2, 28)

    def test_a_weekly_rule_starts_on_its_start_date(self) -> None:
        assert first_occurrence(start_date=date(2026, 3, 4), frequency=RecurrenceFrequency.WEEKLY) == date(2026, 3, 4)

    def test_the_day_of_month_is_ignored_for_a_weekly_rule(self) -> None:
        assert first_occurrence(
            start_date=date(2026, 3, 4), frequency=RecurrenceFrequency.WEEKLY, day_of_month=15
        ) == date(2026, 3, 4)


class TestAdvanceMonthly:
    """Tests for advancing a monthly rule."""

    def test_moves_on_one_month(self) -> None:
        assert advance(current=date(2026, 3, 4), frequency=RecurrenceFrequency.MONTHLY, interval=1) == date(2026, 4, 4)

    def test_rolls_the_year_over(self) -> None:
        assert advance(current=date(2026, 12, 4), frequency=RecurrenceFrequency.MONTHLY, interval=1) == date(2027, 1, 4)

    def test_an_interval_of_two_skips_a_month(self) -> None:
        assert advance(current=date(2026, 3, 4), frequency=RecurrenceFrequency.MONTHLY, interval=2) == date(2026, 5, 4)

    def test_an_interval_of_three_rolls_the_year_over(self) -> None:
        assert advance(current=date(2026, 11, 4), frequency=RecurrenceFrequency.MONTHLY, interval=3) == date(2027, 2, 4)

    def test_the_31st_is_clamped_to_the_end_of_a_short_month(self) -> None:
        assert advance(
            current=date(2026, 1, 31),
            frequency=RecurrenceFrequency.MONTHLY,
            interval=1,
            anchor_day=31,
        ) == date(2026, 2, 28)

    def test_the_31st_returns_after_being_clamped(self) -> None:
        """The anchor day, not the clamped date, is what the next step is measured from."""
        assert advance(
            current=date(2026, 2, 28),
            frequency=RecurrenceFrequency.MONTHLY,
            interval=1,
            anchor_day=31,
        ) == date(2026, 3, 31)

    def test_the_29th_is_clamped_in_a_common_year(self) -> None:
        assert advance(
            current=date(2026, 1, 29),
            frequency=RecurrenceFrequency.MONTHLY,
            interval=1,
            anchor_day=29,
        ) == date(2026, 2, 28)

    def test_the_29th_survives_a_leap_year(self) -> None:
        assert advance(
            current=date(2028, 1, 29),
            frequency=RecurrenceFrequency.MONTHLY,
            interval=1,
            anchor_day=29,
        ) == date(2028, 2, 29)

    def test_the_30th_is_clamped_only_in_february(self) -> None:
        assert advance(
            current=date(2026, 2, 28),
            frequency=RecurrenceFrequency.MONTHLY,
            interval=1,
            anchor_day=30,
        ) == date(2026, 3, 30)


class TestAdvanceWeekly:
    """Tests for advancing a weekly rule."""

    def test_moves_on_seven_days(self) -> None:
        assert advance(current=date(2026, 3, 4), frequency=RecurrenceFrequency.WEEKLY, interval=1) == date(2026, 3, 11)

    def test_an_interval_of_two_is_a_fortnight(self) -> None:
        assert advance(current=date(2026, 3, 4), frequency=RecurrenceFrequency.WEEKLY, interval=2) == date(2026, 3, 18)

    def test_keeps_the_same_weekday(self) -> None:
        start = date(2026, 3, 4)
        moved = advance(current=start, frequency=RecurrenceFrequency.WEEKLY, interval=1)
        assert moved.weekday() == start.weekday()

    def test_crosses_a_month_boundary(self) -> None:
        assert advance(current=date(2026, 3, 30), frequency=RecurrenceFrequency.WEEKLY, interval=1) == date(2026, 4, 6)


class TestAdvanceYearly:
    """Tests for advancing a yearly rule."""

    def test_moves_on_one_year(self) -> None:
        assert advance(current=date(2026, 3, 4), frequency=RecurrenceFrequency.YEARLY, interval=1) == date(2027, 3, 4)

    def test_an_interval_of_two_skips_a_year(self) -> None:
        assert advance(current=date(2026, 3, 4), frequency=RecurrenceFrequency.YEARLY, interval=2) == date(2028, 3, 4)

    def test_the_29th_of_february_is_clamped_in_a_common_year(self) -> None:
        assert advance(current=date(2028, 2, 29), frequency=RecurrenceFrequency.YEARLY, interval=1) == date(2029, 2, 28)

    def test_the_29th_of_february_returns_in_the_next_leap_year(self) -> None:
        assert advance(
            current=date(2028, 2, 29),
            frequency=RecurrenceFrequency.YEARLY,
            interval=4,
            anchor_day=29,
        ) == date(2032, 2, 29)


class TestAdvanceInterval:
    """Tests for the intervals advance accepts."""

    @pytest.mark.parametrize("interval", [0, -1])
    def test_rejects_an_interval_that_would_not_move_the_date_on(self, interval: int) -> None:
        with pytest.raises(ValueError):
            advance(current=date(2026, 3, 4), frequency=RecurrenceFrequency.YEARLY, interval=interval)

    def test_accepts_the_largest_interval(self) -> None:
        assert advance(
            current=date(2026, 3, 4),
            frequency=RecurrenceFrequency.YEARLY,
            interval=MAX_RECURRENCE_INTERVAL,
        ) == date(3226, 3, 4)


class TestAdvancePastTheCalendar:
    """A step that would leave the calendar ends the schedule instead of raising."""

    @pytest.mark.parametrize(
        ("frequency", "interval"),
        [
            (RecurrenceFrequency.YEARLY, 1),
            (RecurrenceFrequency.MONTHLY, 1),
            (RecurrenceFrequency.WEEKLY, 1),
        ],
    )
    def test_returns_none_at_the_end_of_the_calendar(self, frequency: RecurrenceFrequency, interval: int) -> None:
        assert advance(current=date.max, frequency=frequency, interval=interval) is None

    def test_returns_none_for_a_stored_interval_above_the_cap(self) -> None:
        """A rule saved before the cap must not raise from the arithmetic on a read."""
        assert (
            advance(
                current=date(2026, 3, 4),
                frequency=RecurrenceFrequency.YEARLY,
                interval=MAX_RECURRENCE_INTERVAL * 10,
            )
            is None
        )

    def test_the_last_step_that_still_fits_is_taken(self) -> None:
        assert advance(current=date(9998, 12, 31), frequency=RecurrenceFrequency.YEARLY, interval=1) == date(
            9999, 12, 31
        )


class TestFirstOccurrencePastTheCalendar:
    """A first occurrence that cannot be placed on the calendar."""

    def test_returns_none_when_the_first_occurrence_leaves_the_calendar(self) -> None:
        assert first_occurrence(start_date=date.max, frequency=RecurrenceFrequency.MONTHLY, day_of_month=1) is None


class TestOccurrencesUntil:
    """Tests for occurrences_until."""

    def test_lists_the_dates_that_have_fallen_due(self) -> None:
        assert occurrences_until(
            cursor=date(2026, 1, 15),
            until=date(2026, 4, 1),
            frequency=RecurrenceFrequency.MONTHLY,
            interval=1,
            anchor_day=15,
        ) == [date(2026, 1, 15), date(2026, 2, 15), date(2026, 3, 15)]

    def test_includes_a_date_falling_exactly_on_the_boundary(self) -> None:
        assert occurrences_until(
            cursor=date(2026, 3, 15),
            until=date(2026, 3, 15),
            frequency=RecurrenceFrequency.MONTHLY,
            interval=1,
            anchor_day=15,
        ) == [date(2026, 3, 15)]

    def test_returns_nothing_when_nothing_is_due_yet(self) -> None:
        assert (
            occurrences_until(
                cursor=date(2026, 5, 15),
                until=date(2026, 3, 1),
                frequency=RecurrenceFrequency.MONTHLY,
                interval=1,
            )
            == []
        )

    def test_stops_at_the_end_date(self) -> None:
        assert occurrences_until(
            cursor=date(2026, 1, 15),
            until=date(2026, 6, 1),
            frequency=RecurrenceFrequency.MONTHLY,
            interval=1,
            anchor_day=15,
            end_date=date(2026, 2, 20),
        ) == [date(2026, 1, 15), date(2026, 2, 15)]

    def test_returns_nothing_when_the_rule_has_already_ended(self) -> None:
        assert (
            occurrences_until(
                cursor=date(2026, 1, 15),
                until=date(2026, 6, 1),
                frequency=RecurrenceFrequency.MONTHLY,
                interval=1,
                end_date=date(2025, 12, 1),
            )
            == []
        )

    def test_caps_a_runaway_rule(self) -> None:
        """A rule starting decades ago must not create thousands of rows in one go."""
        dates = occurrences_until(
            cursor=date(1990, 1, 1),
            until=date(2026, 1, 1),
            frequency=RecurrenceFrequency.WEEKLY,
            interval=1,
            limit=10,
        )

        assert len(dates) == 10

    def test_month_ends_stay_anchored_across_several_steps(self) -> None:
        """February must not permanently pull a 31st rule back to the 28th."""
        assert occurrences_until(
            cursor=date(2026, 1, 31),
            until=date(2026, 5, 1),
            frequency=RecurrenceFrequency.MONTHLY,
            interval=1,
            anchor_day=31,
        ) == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]

    @pytest.mark.parametrize("interval", [0, -1])
    def test_rejects_an_interval_that_would_not_move_the_date_on(self, interval: int) -> None:
        """The loop would otherwise never end."""
        with pytest.raises(ValueError):
            occurrences_until(
                cursor=date(2026, 1, 1),
                until=date(2026, 6, 1),
                frequency=RecurrenceFrequency.MONTHLY,
                interval=interval,
            )

    @pytest.mark.parametrize(
        ("frequency", "interval"),
        [(RecurrenceFrequency.YEARLY, MAX_RECURRENCE_INTERVAL), (RecurrenceFrequency.WEEKLY, 1)],
    )
    def test_stops_when_the_schedule_runs_off_the_calendar(self, frequency: RecurrenceFrequency, interval: int) -> None:
        """Asking to look ahead to the last day there is must not raise."""
        dates = occurrences_until(
            cursor=date(9990, 1, 1),
            until=date.max,
            frequency=frequency,
            interval=interval,
        )

        assert dates
        assert dates[0] == date(9990, 1, 1)
        assert dates[-1] <= date.max


class TestAdvanceDaily:
    """Tests for advancing a daily rule."""

    def test_moves_on_one_day(self) -> None:
        assert advance(current=date(2026, 3, 4), frequency=RecurrenceFrequency.DAILY, interval=1) == date(2026, 3, 5)

    def test_an_interval_moves_on_that_many_days(self) -> None:
        assert advance(current=date(2026, 3, 4), frequency=RecurrenceFrequency.DAILY, interval=3) == date(2026, 3, 7)

    def test_rolls_over_the_end_of_a_month(self) -> None:
        assert advance(current=date(2026, 2, 28), frequency=RecurrenceFrequency.DAILY, interval=1) == date(2026, 3, 1)

    def test_the_day_of_month_is_ignored(self) -> None:
        """A daily rule is led by its date, so an anchor day means nothing."""
        assert advance(
            current=date(2026, 3, 4), frequency=RecurrenceFrequency.DAILY, interval=1, anchor_day=15
        ) == date(2026, 3, 5)

    def test_a_daily_rule_starts_on_its_start_date(self) -> None:
        assert first_occurrence(
            start_date=date(2026, 3, 4), frequency=RecurrenceFrequency.DAILY, day_of_month=15
        ) == date(2026, 3, 4)

    def test_lists_every_day_up_to_the_limit(self) -> None:
        assert occurrences_until(
            cursor=date(2026, 3, 1), until=date(2026, 3, 4), frequency=RecurrenceFrequency.DAILY, interval=1
        ) == [date(2026, 3, 1), date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4)]
