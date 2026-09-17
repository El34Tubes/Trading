"""Deterministic NYSE session resolution and fail-closed EOD readiness."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from functools import lru_cache
from typing import Any, Mapping, Sequence
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
    universe_snapshot_id: str | None = None
    universe_policy_version: str | None = None
    universe_source_fingerprint: str | None = None
    benchmark_coverage_numerator: int = 0
    benchmark_coverage_denominator: int = 0
    member_coverage_numerator: int = 0
    member_coverage_denominator: int = 0
    incomplete_reasons: tuple[str, ...] = ()


def _parse_aware_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _included_member_evidence_is_valid(
    row: Sequence[Any], *, snapshot_decision_at: datetime, expected_session: date
) -> bool:
    from orchestration_config import MID_SMALL_PIVOT_POLICY

    (
        _ticker,
        identity_ids,
        market_cap_observation_id,
        market_cap,
        bar_observation_ids,
        close,
        average_dollar_volume,
        source_evidence,
    ) = row
    if (
        not identity_ids
        or not market_cap_observation_id
        or market_cap is None
        or close is None
        or average_dollar_volume is None
        or not MID_SMALL_PIVOT_POLICY.market_cap_min
        <= market_cap
        <= MID_SMALL_PIVOT_POLICY.market_cap_max
        or close < MID_SMALL_PIVOT_POLICY.minimum_price
        or average_dollar_volume < MID_SMALL_PIVOT_POLICY.minimum_average_dollar_volume
        or len(bar_observation_ids or ()) != 20
        or not isinstance(source_evidence, Mapping)
    ):
        return False
    market_cap_evidence = source_evidence.get("market_cap")
    bars = source_evidence.get("bars")
    if not isinstance(market_cap_evidence, Mapping) or not isinstance(bars, list) or len(bars) != 20:
        return False
    if (
        tuple(sorted(source_evidence.get("identity_observation_ids", ())))
        != tuple(sorted(identity_ids))
        or market_cap_evidence.get("observation_id") != market_cap_observation_id
        or tuple(bar.get("observation_id") for bar in bars if isinstance(bar, Mapping))
        != tuple(bar_observation_ids)
    ):
        return False
    cap_available = _parse_aware_timestamp(market_cap_evidence.get("available_at"))
    cap_effective = _parse_aware_timestamp(market_cap_evidence.get("effective_at"))
    if (
        cap_available is None
        or cap_effective is None
        or cap_available > snapshot_decision_at
        or cap_effective > snapshot_decision_at
    ):
        return False
    sessions: list[date] = []
    for bar in bars:
        if not isinstance(bar, Mapping):
            return False
        available = _parse_aware_timestamp(bar.get("available_at"))
        try:
            session = date.fromisoformat(str(bar.get("session")))
        except ValueError:
            return False
        if available is None or available > snapshot_decision_at:
            return False
        sessions.append(session)
    return len(set(sessions)) == 20 and max(sessions) == expected_session


def _load_pivot_snapshot(
    conn,
    *,
    expected_session: date,
    decision_at: datetime,
    snapshot_id: str | None,
) -> tuple[tuple[Any, ...] | None, tuple[tuple[Any, ...], ...]]:
    from orchestration_config import MID_SMALL_PIVOT_POLICY

    if conn.execute(
        "SELECT to_regclass('recommendation_universe_snapshots')"
    ).fetchone()[0] is None:
        return None, ()
    if snapshot_id is None:
        header = conn.execute(
            """SELECT snapshot_id::text,signal_dt,decision_at,policy_version,
                      source_fingerprint,included_count,excluded_count
                 FROM recommendation_universe_snapshots
                WHERE signal_dt=%s AND policy_version=%s AND decision_at <= %s
                ORDER BY decision_at DESC,source_fingerprint DESC LIMIT 1""",
            (expected_session, MID_SMALL_PIVOT_POLICY.version, decision_at),
        ).fetchone()
    else:
        header = conn.execute(
            """SELECT snapshot_id::text,signal_dt,decision_at,policy_version,
                      source_fingerprint,included_count,excluded_count
                 FROM recommendation_universe_snapshots
                WHERE snapshot_id::text=%s""",
            (str(snapshot_id),),
        ).fetchone()
    if header is None:
        return None, ()
    counts = conn.execute(
        """SELECT count(*) FILTER (WHERE included),count(*) FILTER (WHERE NOT included)
             FROM recommendation_universe_members WHERE snapshot_id=%s""",
        (header[0],),
    ).fetchone()
    members = conn.execute(
        """SELECT ticker,identity_observation_ids,market_cap_observation_id,
                  market_cap,bar_observation_ids,close,average_dollar_volume,
                  source_evidence
             FROM recommendation_universe_members
            WHERE snapshot_id=%s AND included
            ORDER BY ticker""",
        (header[0],),
    ).fetchall()
    return (*tuple(header), *tuple(counts)), tuple(tuple(row) for row in members)


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
    decision_at: datetime | None = None,
    universe_snapshot_id: str | None = None,
    require_universe_snapshot: bool = False,
) -> EODReadiness:
    """Read exact-session coverage and optionally require a pivot snapshot.

    Legacy callers may still supply an explicit universe plus one benchmark. The
    pivot path resolves members only from an immutable point-in-time snapshot
    and always requires SPY, IWM, and MDY as context-only benchmarks.
    """
    mode = SourceMode(source_mode)
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    expected = expected_session or resolve_expected_session(as_of, source_mode=mode)
    expected_is_session = is_nyse_session(expected)
    snapshot_id: str | None = None
    policy_version: str | None = None
    source_fingerprint: str | None = None
    member_symbols: tuple[str, ...]
    benchmark_symbols: tuple[str, ...]
    incomplete_reasons: list[str] = []

    if require_universe_snapshot:
        from orchestration_config import MID_SMALL_PIVOT_POLICY

        gate_decision_at = decision_at or as_of
        if gate_decision_at.tzinfo is None or gate_decision_at.utcoffset() is None:
            raise ValueError("decision_at must be timezone-aware")
        header, member_rows = _load_pivot_snapshot(
            conn,
            expected_session=expected,
            decision_at=gate_decision_at,
            snapshot_id=universe_snapshot_id,
        )
        if header is None:
            incomplete_reasons.append("missing_universe_snapshot")
            member_symbols = ()
            benchmark_symbols = ()
        else:
            (
                snapshot_id,
                snapshot_signal_dt,
                snapshot_decision_at,
                policy_version,
                source_fingerprint,
                included_count,
                excluded_count,
                actual_included_count,
                actual_excluded_count,
            ) = header
            if snapshot_signal_dt != expected:
                incomplete_reasons.append("universe_snapshot_signal_date_mismatch")
            elif snapshot_decision_at > gate_decision_at:
                incomplete_reasons.append("universe_snapshot_after_decision")
            elif (
                policy_version != MID_SMALL_PIVOT_POLICY.version
                or included_count != actual_included_count
                or excluded_count != actual_excluded_count
                or not isinstance(source_fingerprint, str)
                or len(source_fingerprint) != 64
                or any(
                    not _included_member_evidence_is_valid(
                        row,
                        snapshot_decision_at=snapshot_decision_at,
                        expected_session=expected,
                    )
                    for row in member_rows
                )
            ):
                incomplete_reasons.append("invalid_universe_snapshot")
            member_symbols = tuple(str(row[0]) for row in member_rows)
            benchmark_symbols = tuple(sorted(MID_SMALL_PIVOT_POLICY.benchmark_only))
            if incomplete_reasons:
                member_symbols = ()
                benchmark_symbols = ()
    else:
        member_symbols = tuple(
            sorted({symbol.strip().upper() for symbol in universe if symbol and symbol.strip()})
        )
        canonical_benchmark = benchmark.strip().upper()
        if not canonical_benchmark:
            raise ValueError("a non-empty benchmark is required")
        benchmark_symbols = (canonical_benchmark,)

    required = tuple(sorted(set((*member_symbols, *benchmark_symbols))))
    if required:
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
        complete = {str(row[0]) for row in complete_rows}
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
    else:
        complete = set()
        latest_complete = None
    missing = tuple(symbol for symbol in required if symbol not in complete)
    complete_benchmarks = set(benchmark_symbols).intersection(complete)
    complete_members = set(member_symbols).intersection(complete)

    if require_universe_snapshot and not incomplete_reasons:
        if len(complete_benchmarks) != len(benchmark_symbols):
            incomplete_reasons.append("incomplete_benchmark_coverage")
        if len(complete_members) != len(member_symbols):
            incomplete_reasons.append("incomplete_member_coverage")

    local_day = as_of.astimezone(NY).date()
    availability_ok = expected < local_day or provider_availability_verified
    if require_universe_snapshot and not availability_ok:
        incomplete_reasons.append("provider_availability_unverified")
    if require_universe_snapshot and (not expected_is_session or expected > local_day):
        incomplete_reasons.append("invalid_expected_session")
    publishable = (
        expected_is_session
        and availability_ok
        and not missing
        and latest_complete == expected
        and expected <= local_day
        and not incomplete_reasons
    )
    return EODReadiness(
        expected_session=expected,
        latest_complete_session=latest_complete,
        coverage_numerator=len(complete),
        coverage_denominator=len(required),
        missing_symbols=missing,
        source_mode=mode,
        publishable=publishable,
        universe_snapshot_id=snapshot_id,
        universe_policy_version=policy_version,
        universe_source_fingerprint=source_fingerprint,
        benchmark_coverage_numerator=len(complete_benchmarks),
        benchmark_coverage_denominator=len(benchmark_symbols),
        member_coverage_numerator=len(complete_members),
        member_coverage_denominator=len(member_symbols),
        incomplete_reasons=tuple(incomplete_reasons),
    )
