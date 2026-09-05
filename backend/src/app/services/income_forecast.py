"""Pure arithmetic for the income forecast.

Kept free of the database and of every model except the one enum it reports, so
it can be tested directly. It answers one question — what is this month likely
to bring, and how sure is that — and it answers it exactly, in integers and
rationals, because these numbers are money and money never touches a float.

There are two ways to answer it, and which one applies depends on what the
practice has told us.

**Counting the appointments.** When clients have a schedule, next month is not a
mystery to be averaged: it is a known list of appointments, each of which either
goes ahead or does not. That is a run of independent yes/no trials, so the
number that go ahead follows a binomial distribution, and the handful of
strangers who ring up out of the blue follow a Poisson one. Add the two, and
both the middle and the spread fall out of the arithmetic rather than being
guessed at. This is the estimator to use whenever there is a diary to read.

**Clients who finish.** Clients move on, and a client who has stopped coming is not a
client who cancelled — they are gone, and so is every appointment after them.
That is a third outcome alongside attending and missing, which makes each month
a multinomial rather than a binomial draw. For the *money* the distinction
collapses again, because an appointment either earns its fee or it does not, and
what changes is only the chance it survives: an appointment three weeks out
needs the client still to be there when it comes round. The extra outcome earns
its keep elsewhere — it says how long clients stay, and therefore what one is
worth over the whole time they are with you.

**Averaging the months.** When there is no schedule and nothing booked, all
that is left is what the last few months came to. The mean is the estimate and
the spread of those months is the band. It is the weaker answer — it describes a
practice's past shape rather than its current roster — and it exists so that
somebody who logs sessions as they happen still gets a figure.

Both answers carry a band, never a bare number, because a single figure invites
a freelancer to plan against an average they will miss half the time.
"""

import math
from collections.abc import Sequence
from fractions import Fraction
from typing import NamedTuple

from app.models import ForecastBasis

# Six months is long enough for a quiet August and a busy September to cancel
# out, and short enough that a practice which has changed shape is not judged
# by what it looked like two years ago.
DEFAULT_HISTORY_MONTHS = 6
MIN_HISTORY_MONTHS = 2
MAX_HISTORY_MONTHS = 24

# With one month of history there is no spread to measure, so the band is
# declared instead. A quarter either way is wide enough to be honest about how
# little is known and narrow enough to still be worth reading.
SINGLE_MONTH_SPREAD_PERCENT = 25

# How many standard deviations the band reaches, as an exact fraction so the
# module stays free of floating point. 1.96 either way is the textbook 95%
# interval under a normal approximation: the month lands inside it about
# nineteen times in twenty.
CONFIDENCE_PERCENT = 95
DEVIATIONS = Fraction(196, 100)

# How much of somebody else's record a client borrows while building their own.
# A client with four sessions behind them sits halfway between their personal
# attendance and the practice's; by twenty sessions they are judged almost
# entirely on themselves. Without this, one client who cancelled their only
# appointment would be permanently written off as never turning up.
SHRINKAGE_SESSIONS = 4

# Beyond this, "how long does a client stay" stops being a useful sentence. A
# practice that has never seen anybody finish would otherwise be told its
# clients stay for ever, which is a statement about a short record rather than
# about the clients.
MAX_LIFETIME_MONTHS = 120


class Trial(NamedTuple):
    """One appointment that may or may not happen, and what it is worth.

    Attributes:
        fee_minor: What the session earns if it goes ahead, in minor units.
        rate: The chance it goes ahead, as an exact fraction between 0 and 1.
    """

    fee_minor: int
    rate: Fraction


class ForecastBand(NamedTuple):
    """A likely figure, the usual range around it, and how much to trust it."""

    likely_minor: int
    low_minor: int
    high_minor: int
    months_used: int
    basis: ForecastBasis
    # How many sessions the middle figure assumes, for the page to explain
    # itself with. None when the estimate came from monthly totals, which do
    # not know how many hours went into them.
    expected_sessions: float | None = None


def mean_minor(values: Sequence[int]) -> int:
    """Average a series of amounts in minor units.

    Done in integers, rounding half away from zero, which is the same rule the
    rest of the app rounds money by. Amounts here are never negative, so the
    doubling trick below is the whole of it.

    Args:
        values: The amounts to average, in minor units. Must not be empty.

    Returns:
        The mean, in minor units.

    Raises:
        ValueError: If there is nothing to average.
    """
    if not values:
        raise ValueError("Cannot average an empty series.")

    total = sum(values)
    count = len(values)
    return (total * 2 + count) // (2 * count)


def trim_leading_empty(values: Sequence[int]) -> list[int]:
    """Drop the empty months before the practice started.

    A practice that took its first client in March must not be judged on
    January and February, which were empty because it did not exist yet. Zeros
    *inside* the series are left alone on purpose: a genuinely quiet June
    between two busy months is real, and it is exactly the variation the band
    exists to show.

    Args:
        values: Monthly totals in minor units, oldest first.

    Returns:
        The series with the leading zeros removed.
    """
    first_earning = next((i for i, value in enumerate(values) if value > 0), len(values))
    return list(values[first_earning:])


def _round_half_up(value: Fraction) -> int:
    """Round a rational amount to whole minor units.

    Args:
        value: The amount, which is never negative here, so rounding half up
            and rounding half away from zero are the same rule.

    Returns:
        The amount as a whole number of minor units.
    """
    return math.floor(value + Fraction(1, 2))


def house_rate(went_ahead: int, called_off: int) -> Fraction:
    """How much of this practice's diary has historically turned into work.

    An appointment is not money. Some are missed, some are called off, and only
    the ones that go ahead earn anything. This counts sessions rather than
    fees, which is an approximation — a no-show charged a late fee counts as
    having gone ahead — but it is built from the practice's own record rather
    than from a number somebody guessed.

    Args:
        went_ahead: Sessions that were attended or charged as no-shows.
        called_off: Sessions that were cancelled.

    Returns:
        The rate, exactly, between 0 and 1. One when there is no record either
        way: discounting by a rate that does not exist would be inventing
        pessimism, and the basis on the result is what warns the reader.
    """
    total = went_ahead + called_off

    if total == 0:
        return Fraction(1)

    return Fraction(went_ahead, total)


def shrunk_rate(went_ahead: int, called_off: int, house: Fraction) -> Fraction:
    """Blend one client's attendance with the practice's, by how much is known.

    A client seen twice tells you almost nothing about themselves, and treating
    their record as fact would let a single cancellation halve what the month is
    expected to bring. So a client starts out judged by the practice around them
    and earns their own rate as their history accumulates.

    Args:
        went_ahead: That client's sessions that went ahead.
        called_off: That client's sessions that were called off.
        house: The practice-wide rate, from `house_rate`.

    Returns:
        The blended rate, exactly, between 0 and 1.
    """
    total = went_ahead + called_off
    return (went_ahead + SHRINKAGE_SESSIONS * house) / (total + SHRINKAGE_SESSIONS)


def survival(churn: Fraction, months_ahead: int, position: Fraction = Fraction(0)) -> Fraction:
    """The chance a client is still on the books when an appointment comes round.

    Clients leaving is treated as a constant hazard: each month a client is on
    the books, some fixed share of them stop coming. The number of months they stay
    is then geometrically distributed, and the chance of still being here after
    a whole month is simply the chance of not finishing, raised to the number of
    months waited.

    Inside the month the same hazard is spread evenly across it rather than
    applied in one lump, because a client who stops in the third week keeps
    the first two weeks of appointments. Somebody's last session is not a
    session they missed.

    Args:
        churn: The share of the caseload that stops coming in a month, 0 to 1.
        months_ahead: Whole months between now and the month in question.
        position: How far into that month the appointment falls, 0 to 1.

    Returns:
        The chance the client is still there, exactly.
    """
    return (1 - churn) ** months_ahead * (1 - churn * position)


def expected_lifetime_months(churn: Fraction) -> float | None:
    """How long a client typically stays, from the rate at which they finish.

    The mean of a geometric distribution: if one client in twenty finishes each
    month, the average client stays twenty months. It is the number
    that turns a monthly fee into what a client is actually worth.

    Args:
        churn: The share of the caseload that stops coming in a month, 0 to 1.

    Returns:
        The expected number of months, or None when nobody has finished yet —
        a record too short to have seen an ending cannot be read as clients who
        never leave.
    """
    if churn <= 0:
        return None

    return min(float(1 / churn), float(MAX_LIFETIME_MONTHS))


def session_band(
    trials: Sequence[Trial],
    new_session_rate: Fraction = Fraction(0),
    new_session_fee_minor: int = 0,
    earned_so_far_minor: int = 0,
    months_used: int = 0,
    basis: ForecastBasis = ForecastBasis.HISTORY,
) -> ForecastBand:
    """Estimate a month by counting its appointments one at a time.

    Each appointment is a trial: it goes ahead and earns its fee, or it does
    not and earns nothing. Trials are treated as independent, so the total is a
    sum of independent amounts, and both halves of the answer come straight out
    of that:

        middle   = sum of (chance x fee)
        variance = sum of (chance x (1 - chance) x fee squared)

    Strangers are added on top. Nobody knows how many will ring up next month,
    but the count of independent arrivals in a fixed window is a Poisson
    quantity, whose mean and variance are the same number — so a practice that
    picks up two new people a month carries the uncertainty of about two
    sessions' worth of fee on that account alone.

    The band is then the middle plus or minus 1.96 standard deviations, which
    the central limit theorem makes a roughly 95% interval once there are more
    than a few appointments in the month. With very few it is wider than it
    strictly needs to be, which is the safe direction to be wrong in.

    Work already done is added as a floor rather than as a trial. It is a fact,
    it carries no uncertainty, and the month cannot end below it — which is what
    makes an estimate for the month in progress worth reading, because by the
    25th most of the answer is fact and the band has quietly closed around it.

    Args:
        trials: The appointments the month holds, each with its fee and the
            chance it goes ahead.
        new_session_rate: Sessions per month from clients the practice did not
            have before, averaged over the history window.
        new_session_fee_minor: What one of those sessions has typically earned.
        earned_so_far_minor: What the month has already earned. Zero for a
            month still to come.
        months_used: How many complete months the rates were measured over.
        basis: How much to trust those rates.

    Returns:
        The likely figure, the band around it, and what it is based on.
    """
    expected = Fraction(0)
    # In minor units squared. Large, and exact, because Python integers do not
    # overflow and Fractions do not drift.
    variance = Fraction(0)
    sessions = Fraction(0)

    for trial in trials:
        expected += trial.rate * trial.fee_minor
        variance += trial.rate * (1 - trial.rate) * trial.fee_minor**2
        sessions += trial.rate

    # A compound Poisson: the count has mean and variance both equal to the
    # rate, and each arrival carries a fee, so the money it contributes has
    # mean rate x fee and variance rate x fee squared.
    expected += new_session_rate * new_session_fee_minor
    variance += new_session_rate * new_session_fee_minor**2
    sessions += new_session_rate

    likely = earned_so_far_minor + _round_half_up(expected)
    # isqrt is an exact integer square root, so the whole module stays free of
    # floating point. Flooring the variance first costs less than one minor
    # unit of a figure already measured in hundreds of them.
    spread = _round_half_up(DEVIATIONS * math.isqrt(math.floor(variance)))

    return ForecastBand(
        likely_minor=likely,
        # Never below what the month has already banked, and never below zero,
        # since a month cannot earn less than nothing.
        low_minor=max(earned_so_far_minor, likely - spread),
        high_minor=likely + spread,
        months_used=months_used,
        basis=basis,
        expected_sessions=float(sessions),
    )


def history_band(
    monthly_totals: Sequence[int],
    earned_so_far_minor: int = 0,
) -> ForecastBand:
    """Estimate a month from what the months before it came to.

    The fallback, for a practice with no schedules and an empty diary. The band
    is the mean plus or minus one sample standard deviation, not the best and
    worst month observed. Observed extremes are set by the two most unusual
    months and get *wider* the longer you track, which is backwards for a figure
    presented as a confidence range: six months in, the range would be dominated
    by the August somebody took a holiday. A standard deviation narrows as a
    practice settles into a rhythm, which is the behaviour the number should
    have.

    Args:
        monthly_totals: What each complete month earned, in minor units, oldest
            first. The month being estimated must not be in here: a month that
            is part over is a fraction of itself and would drag the average
            down in exactly the week the estimate is worth reading.
        earned_so_far_minor: What the month has already earned, in minor units.
            A floor, and nothing more: months averaged from the past know
            nothing about this one.

    Returns:
        The likely figure, the band around it, and what it is based on.
    """
    values = trim_leading_empty(monthly_totals)
    count = len(values)

    if count == 0:
        # Nothing to average and nothing booked, so the month's own earnings are
        # the whole of the answer. The basis says not to lean on it.
        return ForecastBand(
            likely_minor=earned_so_far_minor,
            low_minor=earned_so_far_minor,
            high_minor=earned_so_far_minor,
            months_used=0,
            basis=ForecastBasis.INSUFFICIENT_HISTORY,
        )

    if count == 1:
        likely = values[0]
        spread = (likely * SINGLE_MONTH_SPREAD_PERCENT) // 100
        basis = ForecastBasis.SINGLE_MONTH
        deviation = spread
    else:
        likely = mean_minor(values)
        # Bessel's correction: these months are a sample of the practice, not
        # the whole of it. Squaring against the rounded mean rather than the
        # exact rational one adds less than a minor unit to the sum, which is
        # below the precision money is even expressed in.
        sum_of_squares = sum((value - likely) ** 2 for value in values)
        deviation = math.isqrt(sum_of_squares // (count - 1))
        basis = ForecastBasis.HISTORY

    likely = max(likely, earned_so_far_minor)

    return ForecastBand(
        likely_minor=likely,
        low_minor=max(earned_so_far_minor, likely - deviation),
        high_minor=likely + deviation,
        months_used=count,
        basis=basis,
    )
