import math
from fractions import Fraction

import pytest

from app.models import ForecastBasis
from app.services.income_forecast import (
    CONFIDENCE_PERCENT,
    DEVIATIONS,
    MAX_LIFETIME_MONTHS,
    SHRINKAGE_SESSIONS,
    SINGLE_MONTH_SPREAD_PERCENT,
    Trial,
    expected_lifetime_months,
    history_band,
    house_rate,
    mean_minor,
    session_band,
    shrunk_rate,
    survival,
    trim_leading_empty,
)


def certain(fee_minor: int) -> Trial:
    """An appointment that always goes ahead, for testing the arithmetic alone."""
    return Trial(fee_minor=fee_minor, rate=Fraction(1))


class TestMeanMinor:
    def test_an_exact_average_is_returned_unchanged(self) -> None:
        assert mean_minor([100, 200, 300]) == 200

    def test_a_half_rounds_away_from_zero(self) -> None:
        assert mean_minor([100, 101]) == 101

    def test_a_third_rounds_down(self) -> None:
        assert mean_minor([100, 100, 101]) == 100

    def test_a_single_month_is_its_own_average(self) -> None:
        assert mean_minor([4321]) == 4321

    def test_an_empty_series_is_refused(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            mean_minor([])


class TestTrimLeadingEmpty:
    def test_months_before_the_first_client_are_dropped(self) -> None:
        assert trim_leading_empty([0, 0, 500, 600]) == [500, 600]

    def test_a_quiet_month_in_the_middle_is_kept(self) -> None:
        # A month that earned nothing is real variation, not an absence of data.
        assert trim_leading_empty([500, 0, 600]) == [500, 0, 600]

    def test_a_trailing_zero_is_kept(self) -> None:
        assert trim_leading_empty([500, 0]) == [500, 0]

    def test_an_entirely_empty_series_becomes_empty(self) -> None:
        assert trim_leading_empty([0, 0, 0]) == []

    def test_a_series_that_never_starts_empty_is_unchanged(self) -> None:
        assert trim_leading_empty([1, 2, 3]) == [1, 2, 3]


class TestHouseRate:
    def test_a_practice_nobody_cancels_on_keeps_its_whole_diary(self) -> None:
        assert house_rate(went_ahead=10, called_off=0) == Fraction(1)

    def test_cancellations_pull_the_rate_down(self) -> None:
        assert house_rate(went_ahead=9, called_off=1) == Fraction(9, 10)

    def test_no_record_is_taken_at_face_value(self) -> None:
        # Discounting by a rate nobody measured would be inventing pessimism.
        assert house_rate(went_ahead=0, called_off=0) == Fraction(1)

    def test_a_practice_that_is_always_cancelled_on_expects_nothing(self) -> None:
        assert house_rate(went_ahead=0, called_off=4) == Fraction(0)


class TestShrunkRate:
    def test_a_client_with_no_record_is_priced_like_the_practice(self) -> None:
        house = Fraction(4, 5)
        assert shrunk_rate(went_ahead=0, called_off=0, house=house) == house

    def test_one_cancellation_does_not_write_a_client_off(self) -> None:
        # Their own record says zero. Judged on that alone they would contribute
        # nothing to the month, on the strength of a single missed appointment.
        house = Fraction(9, 10)
        rate = shrunk_rate(went_ahead=0, called_off=1, house=house)

        assert rate > Fraction(1, 2)
        assert rate < house

    def test_a_long_record_outweighs_the_practice(self) -> None:
        house = Fraction(1, 2)
        rate = shrunk_rate(went_ahead=100, called_off=0, house=house)

        assert rate > Fraction(19, 20)

    def test_the_blend_is_the_documented_weighting(self) -> None:
        house = Fraction(1, 2)
        assert shrunk_rate(went_ahead=3, called_off=1, house=house) == Fraction(
            3 + SHRINKAGE_SESSIONS * house, 4 + SHRINKAGE_SESSIONS
        )

    def test_a_reliable_client_is_never_dragged_above_certainty(self) -> None:
        assert shrunk_rate(went_ahead=8, called_off=0, house=Fraction(1)) == Fraction(1)


class TestSessionBand:
    def test_nothing_in_the_month_is_worth_nothing(self) -> None:
        band = session_band([])

        assert band.likely_minor == 0
        assert band.low_minor == 0
        assert band.high_minor == 0

    def test_certain_appointments_carry_no_uncertainty(self) -> None:
        # Every fee counted, and a band of zero width, because a run of
        # certainties has nothing left to vary.
        band = session_band([certain(5_000), certain(4_000)])

        assert band.likely_minor == 9_000
        assert (band.low_minor, band.high_minor) == (9_000, 9_000)

    def test_the_middle_is_the_chance_times_the_fee(self) -> None:
        band = session_band([Trial(fee_minor=10_000, rate=Fraction(9, 10))] * 4)

        assert band.likely_minor == 36_000

    def test_the_band_is_the_documented_number_of_deviations(self) -> None:
        rate = Fraction(3, 4)
        trials = [Trial(fee_minor=8_000, rate=rate)] * 10
        variance = 10 * rate * (1 - rate) * 8_000**2
        spread = math.floor(DEVIATIONS * math.isqrt(math.floor(variance)) + Fraction(1, 2))

        band = session_band(trials)

        assert band.likely_minor == 60_000
        assert band.high_minor - band.likely_minor == spread
        assert band.likely_minor - band.low_minor == spread

    def test_more_appointments_of_the_same_size_narrow_the_band_relatively(self) -> None:
        # The whole reason to count appointments rather than average months:
        # uncertainty grows with the square root, income grows outright, so a
        # fuller roster is a proportionally surer one.
        rate = Fraction(4, 5)
        small = session_band([Trial(fee_minor=5_000, rate=rate)] * 4)
        large = session_band([Trial(fee_minor=5_000, rate=rate)] * 40)

        small_share = (small.high_minor - small.low_minor) / small.likely_minor
        large_share = (large.high_minor - large.low_minor) / large.likely_minor

        assert large_share < small_share

    def test_one_big_client_is_riskier_than_several_small_ones(self) -> None:
        # Same money, same reliability, different concentration. Variance goes
        # with the square of the fee, so the band knows the difference.
        rate = Fraction(9, 10)
        concentrated = session_band([Trial(fee_minor=40_000, rate=rate)])
        spread_out = session_band([Trial(fee_minor=10_000, rate=rate)] * 4)

        assert concentrated.likely_minor == spread_out.likely_minor
        assert concentrated.high_minor > spread_out.high_minor

    def test_strangers_add_both_money_and_doubt(self) -> None:
        booked = session_band([certain(5_000)] * 4)
        with_arrivals = session_band(
            [certain(5_000)] * 4,
            new_session_rate=Fraction(2),
            new_session_fee_minor=5_000,
        )

        assert with_arrivals.likely_minor == booked.likely_minor + 10_000
        assert with_arrivals.high_minor > with_arrivals.likely_minor

    def test_work_already_done_holds_the_bottom_of_the_range_up(self) -> None:
        # Two coin flips on a large fee: uncertain enough that the arithmetic
        # alone would put the low end under what the month has already banked.
        band = session_band(
            [Trial(fee_minor=50_000, rate=Fraction(1, 2))] * 2,
            earned_so_far_minor=40_000,
        )

        assert band.likely_minor == 90_000
        # 40,000 is in the bank. The month cannot end below it, whatever the two
        # remaining appointments do.
        assert band.low_minor == 40_000

    def test_the_estimate_converges_as_the_month_is_worked(self) -> None:
        # By the end of the month there is nothing left to guess at, so the band
        # closes onto the fact.
        trials = [Trial(fee_minor=5_000, rate=Fraction(4, 5))] * 8

        early = session_band(trials, earned_so_far_minor=0)
        late = session_band(trials[:1], earned_so_far_minor=35_000)

        assert (late.high_minor - late.low_minor) < (early.high_minor - early.low_minor)

    def test_the_expected_session_count_is_reported(self) -> None:
        band = session_band(
            [Trial(fee_minor=5_000, rate=Fraction(1, 2))] * 8,
            new_session_rate=Fraction(1),
            new_session_fee_minor=5_000,
        )

        assert band.expected_sessions == pytest.approx(5.0)

    def test_large_amounts_stay_exact(self) -> None:
        band = session_band([certain(9_999_999_999)] * 3)

        assert band.likely_minor == 29_999_999_997

    def test_the_confidence_is_the_documented_one(self) -> None:
        assert CONFIDENCE_PERCENT == 95


class TestHistoryBand:
    def test_no_history_forecasts_nothing(self) -> None:
        band = history_band([])

        assert band == (0, 0, 0, 0, ForecastBasis.INSUFFICIENT_HISTORY, None)

    def test_months_that_are_all_empty_count_as_no_history(self) -> None:
        band = history_band([0, 0, 0])

        assert band.basis is ForecastBasis.INSUFFICIENT_HISTORY
        assert band.months_used == 0

    def test_one_month_declares_a_band_around_itself(self) -> None:
        band = history_band([100_000])

        assert band.likely_minor == 100_000
        assert band.low_minor == 100_000 - 100_000 * SINGLE_MONTH_SPREAD_PERCENT // 100
        assert band.basis is ForecastBasis.SINGLE_MONTH

    def test_leading_empty_months_do_not_count_toward_the_history(self) -> None:
        assert history_band([0, 0, 100_000]).months_used == 1

    def test_a_steady_practice_gets_no_band_at_all(self) -> None:
        band = history_band([50_000] * 5)

        assert (band.low_minor, band.likely_minor, band.high_minor) == (50_000, 50_000, 50_000)
        assert band.basis is ForecastBasis.HISTORY

    def test_the_band_matches_the_mean_and_sample_deviation(self) -> None:
        values = [100_000, 120_000, 80_000, 140_000]
        mean = mean_minor(values)
        deviation = math.isqrt(sum((value - mean) ** 2 for value in values) // 3)

        band = history_band(values)

        assert band.likely_minor == mean
        assert (band.low_minor, band.high_minor) == (mean - deviation, mean + deviation)

    def test_a_quiet_month_widens_the_band(self) -> None:
        steady = history_band([100_000, 100_000, 100_000, 100_000])
        interrupted = history_band([100_000, 0, 100_000, 100_000])

        assert (interrupted.high_minor - interrupted.low_minor) > (steady.high_minor - steady.low_minor)

    def test_the_low_end_never_goes_below_zero(self) -> None:
        # A practice this erratic has a deviation wider than its own average,
        # so the arithmetic wants a negative floor. A month cannot lose money.
        band = history_band([100_000, 0, 0, 0, 400_000])

        assert band.low_minor == 0

    def test_work_already_done_holds_the_bottom_up(self) -> None:
        band = history_band([100_000] * 4, earned_so_far_minor=130_000)

        assert band.low_minor == 130_000
        assert band.likely_minor == 130_000

    def test_a_quiet_month_so_far_does_not_drag_the_estimate_down(self) -> None:
        assert history_band([100_000] * 4, earned_so_far_minor=1_000).likely_minor == 100_000


class TestSurvival:
    def test_a_practice_nobody_leaves_keeps_everybody(self) -> None:
        assert survival(Fraction(0), months_ahead=6, position=Fraction(1)) == Fraction(1)

    def test_the_start_of_this_month_is_certain(self) -> None:
        # Nothing has had time to happen yet.
        assert survival(Fraction(1, 20), months_ahead=0, position=Fraction(0)) == Fraction(1)

    def test_later_in_the_month_is_less_certain(self) -> None:
        churn = Fraction(1, 10)
        early = survival(churn, months_ahead=0, position=Fraction(1, 4))
        late = survival(churn, months_ahead=0, position=Fraction(3, 4))

        assert late < early

    def test_a_whole_month_of_waiting_compounds(self) -> None:
        # The geometric part: surviving two months is surviving one, twice.
        churn = Fraction(1, 10)

        assert survival(churn, months_ahead=2) == Fraction(81, 100)

    def test_next_month_is_worth_less_than_this_one(self) -> None:
        churn = Fraction(1, 20)
        position = Fraction(1, 2)

        assert survival(churn, 1, position) < survival(churn, 0, position)

    def test_a_client_finishing_keeps_the_sessions_before_they_did(self) -> None:
        # Somebody's last appointment is not one they missed, so a month's
        # hazard is spread across it rather than wiping the whole month out.
        assert survival(Fraction(1, 4), months_ahead=0, position=Fraction(1)) == Fraction(3, 4)


class TestExpectedLifetimeMonths:
    def test_one_in_twenty_a_month_is_twenty_months(self) -> None:
        assert expected_lifetime_months(Fraction(1, 20)) == pytest.approx(20.0)

    def test_nobody_finishing_is_not_a_measurement(self) -> None:
        # A practice six months old that has seen no endings has a short record,
        # not clients who stay for ever.
        assert expected_lifetime_months(Fraction(0)) is None

    def test_a_very_rare_ending_is_capped(self) -> None:
        assert expected_lifetime_months(Fraction(1, 10_000)) == MAX_LIFETIME_MONTHS

    def test_everybody_finishing_every_month_is_one_month(self) -> None:
        assert expected_lifetime_months(Fraction(1)) == pytest.approx(1.0)


class TestTerminationInTheBand:
    def test_endings_pull_the_estimate_down(self) -> None:
        churn = Fraction(1, 10)
        steady = [Trial(fee_minor=5_000, rate=Fraction(1))] * 8
        leaving = [Trial(fee_minor=5_000, rate=survival(churn, 0, Fraction(index, 8))) for index in range(8)]

        assert session_band(leaving).likely_minor < session_band(steady).likely_minor

    def test_endings_widen_the_band(self) -> None:
        # A certainty has no spread. Introduce a way for it not to happen and
        # the month acquires one.
        churn = Fraction(1, 5)
        leaving = [Trial(fee_minor=5_000, rate=survival(churn, 0, Fraction(index, 8))) for index in range(8)]
        band = session_band(leaving)

        assert band.high_minor > band.low_minor
