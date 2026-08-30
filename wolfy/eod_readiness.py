"""Deterministic NYSE session resolution and fail-closed EOD readiness."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from functools import lru_cache
from typing import Sequence
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
MARKET_CLOSE = time(16, 0)
NYSE_CALENDAR_VERSION = "wolfy-nyse-1990-2100-v1"
NYSE_CALENDAR_START = date(1990, 1, 1)
NYSE_CALENDAR_END = date(2100, 12, 31)

# Full-session exceptional closures in the supported range. Regular closures are
# generated below from this version's NYSE holiday rules. Early closes remain
# sessions and therefore do not belong in this table.
_EXCEPTIONAL_CLOSURES = frozenset(
    {
        date(1994, 4, 27),  # President Nixon funeral
        date(2001, 9, 11),
        date(2001, 9, 12),
        date(2001, 9, 13),
        date(2001, 9, 14),
        date(2004, 6, 11),  # President Reagan funeral
        date(2007, 1, 2),  # President Ford funeral
        date(2012, 10, 29),  # Hurricane Sandy
        date(2012, 10, 30),
        date(2018, 12, 5),  # President G.H.W. Bush funeral
        date(2025, 1, 9),  # President Carter funeral
    }
)


class SourceMode(StrEnum):
    """Supported EOD provider availability contracts."""

    FREE_T_PLUS_1 = "free_t_plus_1"
    PAID_CURRENT_DAY = "paid_current_day"


@dataclass(frozen=True)
class EODReadiness:
    """Auditable result of the EOD completeness gate."""

    expected_session: date
    latest_complete_session: date | None
    coverage_numerator: int
    coverage_denominator: int
    missing_symbols: tuple[str, ...]
    source_mode: SourceMode
    publishable: bool


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    first_next = date(year + (month == 12), month % 12 + 1, 1)
    day = first_next - timedelta(days=1)
    return day - timedelta(days=(day.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _easter_sunday(year: int) -> date:
    """Return Gregorian Easter using the Meeus/Jones/Butcher algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = (h + ell - 7 * m + 114) % 31 + 1
    return date(year, month, day)


@lru_cache(maxsize=1)
def _nyse_closures() -> frozenset[date]:
    closures = set(_EXCEPTIONAL_CLOSURES)
    for year in range(NYSE_CALENDAR_START.year, NYSE_CALENDAR_END.year + 1):
        closures.add(_observed(date(year, 1, 1)))
        if year >= 1998:
            closures.add(_nth_weekday(year, 1, 0, 3))  # MLK Day
        closures.add(_nth_weekday(year, 2, 0, 3))  # Washington's Birthday
        closures.add(_easter_sunday(year) - timedelta(days=2))  # Good Friday
        closures.add(_last_weekday(year, 5, 0))  # Memorial Day
        if year >= 2022:
            closures.add(_observed(date(year, 6, 19)))
        closures.add(_observed(date(year, 7, 4)))
        closures.add(_nth_weekday(year, 9, 0, 1))  # Labor Day
        closures.add(_nth_weekday(year, 11, 3, 4))  # Thanksgiving
        closures.add(_observed(date(year, 12, 25)))
    return frozenset(
        day for day in closures if NYSE_CALENDAR_START <= day <= NYSE_CALENDAR_END
    )


def is_nyse_session(day: date) -> bool:
    """Return whether ``day`` is a full NYSE trading session in the pinned table."""
    if not NYSE_CALENDAR_START <= day <= NYSE_CALENDAR_END:
        raise ValueError(
            f"date {day} is outside NYSE calendar {NYSE_CALENDAR_VERSION} "
            f"[{NYSE_CALENDAR_START}, {NYSE_CALENDAR_END}]"
        )
    return day.weekday() < 5 and day not in _nyse_closures()


def previous_nyse_session(day: date, *, inclusive: bool = False) -> date:
    """Return the prior session, optionally accepting ``day`` itself."""
    candidate = day if inclusive else day - timedelta(days=1)
    while not is_nyse_session(candidate):
        candidate -= timedelta(days=1)
    return candidate


def next_nyse_session(day: date) -> date:
    """Return the first NYSE session strictly after ``day``."""
    candidate = day + timedelta(days=1)
    while not is_nyse_session(candidate):
        candidate += timedelta(days=1)
    return candidate


def resolve_expected_session(as_of: datetime, *, source_mode: SourceMode) -> date:
    """Resolve the newest session whose close should be evaluated at ``as_of``."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    SourceMode(source_mode)
    local = as_of.astimezone(NY)
    day = local.date()
    if is_nyse_session(day) and local.time().replace(tzinfo=None) >= MARKET_CLOSE:
        return day
    return previous_nyse_session(day)


def evaluate_eod_readiness(
    conn,
    *,
    as_of: datetime,
    universe: Sequence[str],
    source_mode: SourceMode,
    benchmark: str = "SPY",
    provider_availability_verified: bool = False,
    expected_session: date | None = None,
) -> EODReadiness:
    """Read exact-session Postgres coverage and fail closed on any gap.

    The benchmark is always part of the required universe. Current-calendar-day
    data is not publishable until the provider explicitly verifies availability;
    prior-session T+1 data is eligible without that same-day verification.
    """
    mode = SourceMode(source_mode)
    expected = expected_session or resolve_expected_session(as_of, source_mode=mode)
    expected_is_session = is_nyse_session(expected)
    required = tuple(
        sorted(
            {
                symbol.strip().upper()
                for symbol in (*universe, benchmark)
                if symbol and symbol.strip()
            }
        )
    )
    if not required or benchmark.strip().upper() not in required:
        raise ValueError("a non-empty benchmark and universe are required")

    complete_rows = conn.execute(
        """
        SELECT required.ticker
        FROM unnest(%s::text[]) AS required(ticker)
        JOIN prices AS p ON p.ticker=required.ticker AND p.dt=%s
        JOIN features AS f ON f.ticker=required.ticker AND f.dt=%s
        ORDER BY required.ticker
        """,
        (list(required), expected, expected),
    ).fetchall()
    complete = {row[0] for row in complete_rows}
    missing = tuple(symbol for symbol in required if symbol not in complete)

    candidate_rows = conn.execute(
        """
        SELECT p.dt, count(DISTINCT p.ticker)
        FROM prices AS p
        JOIN features AS f ON f.ticker=p.ticker AND f.dt=p.dt
        WHERE p.ticker = ANY(%s) AND p.dt <= %s
        GROUP BY p.dt
        HAVING count(DISTINCT p.ticker) = %s
        ORDER BY p.dt DESC
        """,
        (list(required), expected, len(required)),
    ).fetchall()
    latest_complete = next(
        (row[0] for row in candidate_rows if is_nyse_session(row[0])),
        None,
    )

    local_day = as_of.astimezone(NY).date()
    availability_ok = expected < local_day or provider_availability_verified
    publishable = (
        expected_is_session
        and availability_ok
        and not missing
        and latest_complete == expected
        and expected <= local_day
    )
    return EODReadiness(
        expected_session=expected,
        latest_complete_session=latest_complete,
        coverage_numerator=len(complete),
        coverage_denominator=len(required),
        missing_symbols=missing,
        source_mode=mode,
        publishable=publishable,
    )
