from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from test_db import test_connection

NY = ZoneInfo("America/New_York")


def test_paid_mode_uses_current_weekday_only_after_market_close():
    from eod_readiness import SourceMode, resolve_expected_session

    assert resolve_expected_session(
        datetime(2026, 8, 25, 15, 59, tzinfo=NY),
        source_mode=SourceMode.PAID_CURRENT_DAY,
    ) == date(2026, 8, 24)
    assert resolve_expected_session(
        datetime(2026, 8, 25, 16, 0, tzinfo=NY),
        source_mode=SourceMode.PAID_CURRENT_DAY,
    ) == date(2026, 8, 25)


def test_weekend_resolves_to_friday_session():
    from eod_readiness import SourceMode, resolve_expected_session

    assert resolve_expected_session(
        datetime(2026, 8, 29, 12, 0, tzinfo=NY),
        source_mode=SourceMode.PAID_CURRENT_DAY,
    ) == date(2026, 8, 28)


def test_nyse_holiday_and_special_closure_resolve_to_prior_session():
    from eod_readiness import NYSE_CALENDAR_VERSION, SourceMode, resolve_expected_session

    assert NYSE_CALENDAR_VERSION == "wolfy-nyse-1990-2100-v1"
    assert resolve_expected_session(
        datetime(2026, 11, 26, 17, 0, tzinfo=NY),  # Thanksgiving
        source_mode=SourceMode.PAID_CURRENT_DAY,
    ) == date(2026, 11, 25)
    assert resolve_expected_session(
        datetime(2018, 12, 5, 17, 0, tzinfo=NY),  # Bush memorial closure
        source_mode=SourceMode.PAID_CURRENT_DAY,
    ) == date(2018, 12, 4)


def _store_complete(conn, session: date, symbols: tuple[str, ...]) -> None:
    for symbol in symbols:
        conn.execute(
            """
            INSERT INTO prices(ticker,dt,close) VALUES (%s,%s,100)
            ON CONFLICT (ticker,dt) DO UPDATE SET close=EXCLUDED.close
            """,
            (symbol, session),
        )
        conn.execute(
            """
            INSERT INTO features(ticker,dt,sma_fast) VALUES (%s,%s,100)
            ON CONFLICT (ticker,dt) DO UPDATE SET sma_fast=EXCLUDED.sma_fast
            """,
            (symbol, session),
        )


def test_complete_paid_current_session_returns_typed_publishable_readiness():
    from eod_readiness import EODReadiness, SourceMode, evaluate_eod_readiness

    session = date(2026, 8, 25)
    symbols = ("SPY", "ZZREADYA", "ZZREADYB")
    with test_connection() as conn:
        _store_complete(conn, session, symbols)
        result = evaluate_eod_readiness(
            conn,
            as_of=datetime(2026, 8, 25, 17, 0, tzinfo=NY),
            universe=symbols[1:],
            source_mode=SourceMode.PAID_CURRENT_DAY,
            provider_availability_verified=True,
        )

    assert isinstance(result, EODReadiness)
    assert result.expected_session == session
    assert result.latest_complete_session == session
    assert result.coverage_numerator == 3
    assert result.coverage_denominator == 3
    assert result.missing_symbols == ()
    assert result.source_mode == SourceMode.PAID_CURRENT_DAY
    assert result.publishable is True


def test_free_t_plus_one_resolves_friday_on_monday_but_fails_closed_friday_after_close():
    from eod_readiness import SourceMode, evaluate_eod_readiness

    friday = date(2026, 8, 28)
    symbols = ("SPY", "ZZFREE")
    with test_connection() as conn:
        _store_complete(conn, friday, symbols)
        monday = evaluate_eod_readiness(
            conn,
            as_of=datetime(2026, 8, 31, 8, 0, tzinfo=NY),
            universe=("ZZFREE",),
            source_mode=SourceMode.FREE_T_PLUS_1,
        )
        unverified_friday = evaluate_eod_readiness(
            conn,
            as_of=datetime(2026, 8, 28, 17, 0, tzinfo=NY),
            universe=("ZZFREE",),
            source_mode=SourceMode.FREE_T_PLUS_1,
        )

    assert monday.expected_session == friday
    assert monday.latest_complete_session == friday
    assert monday.publishable is True
    assert unverified_friday.expected_session == friday
    assert unverified_friday.publishable is False


def test_missing_benchmark_fails_closed_and_reports_it():
    from eod_readiness import SourceMode, evaluate_eod_readiness

    session = date(2026, 8, 24)
    with test_connection() as conn:
        _store_complete(conn, session, ("ZZNOBENCH",))
        result = evaluate_eod_readiness(
            conn,
            as_of=datetime(2026, 8, 25, 8, 0, tzinfo=NY),
            universe=("ZZNOBENCH",),
            source_mode=SourceMode.FREE_T_PLUS_1,
        )

    assert result.coverage_numerator == 1
    assert result.coverage_denominator == 2
    assert result.missing_symbols == ("SPY",)
    assert result.latest_complete_session is None
    assert result.publishable is False


def test_partial_universe_fails_closed_with_deterministic_missing_symbols():
    from eod_readiness import SourceMode, evaluate_eod_readiness

    session = date(2026, 8, 21)
    with test_connection() as conn:
        _store_complete(conn, session, ("SPY", "ZZPARTA"))
        result = evaluate_eod_readiness(
            conn,
            as_of=datetime(2026, 8, 24, 8, 0, tzinfo=NY),
            universe=("ZZPARTB", "ZZPARTA"),
            source_mode=SourceMode.FREE_T_PLUS_1,
        )

    assert result.coverage_numerator == 2
    assert result.coverage_denominator == 3
    assert result.missing_symbols == ("ZZPARTB",)
    assert result.publishable is False


def test_stale_features_do_not_count_as_current_coverage():
    from eod_readiness import SourceMode, evaluate_eod_readiness

    prior = date(2026, 8, 20)
    expected = date(2026, 8, 21)
    symbols = ("SPY", "ZZSTALE")
    with test_connection() as conn:
        _store_complete(conn, prior, symbols)
        for symbol in symbols:
            conn.execute(
                "INSERT INTO prices(ticker,dt,close) VALUES (%s,%s,101)",
                (symbol, expected),
            )
        conn.execute(
            "INSERT INTO features(ticker,dt,sma_fast) VALUES ('SPY',%s,101)",
            (expected,),
        )
        result = evaluate_eod_readiness(
            conn,
            as_of=datetime(2026, 8, 22, 8, 0, tzinfo=NY),
            universe=("ZZSTALE",),
            source_mode=SourceMode.FREE_T_PLUS_1,
        )

    assert result.missing_symbols == ("ZZSTALE",)
    assert result.latest_complete_session == prior
    assert result.publishable is False


def test_future_rows_are_ignored_when_resolving_latest_complete_session():
    from eod_readiness import SourceMode, evaluate_eod_readiness

    expected = date(2026, 8, 24)
    future = date(2026, 8, 25)
    symbols = ("SPY", "ZZFUTURE")
    with test_connection() as conn:
        _store_complete(conn, expected, symbols)
        _store_complete(conn, future, symbols)
        result = evaluate_eod_readiness(
            conn,
            as_of=datetime(2026, 8, 25, 8, 0, tzinfo=NY),
            universe=("ZZFUTURE",),
            source_mode=SourceMode.FREE_T_PLUS_1,
        )

    assert result.expected_session == expected
    assert result.latest_complete_session == expected
    assert result.publishable is True


def test_calendar_range_and_naive_datetimes_fail_closed():
    from eod_readiness import SourceMode, resolve_expected_session

    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_expected_session(
            datetime(2026, 8, 25, 17, 0),
            source_mode=SourceMode.PAID_CURRENT_DAY,
        )
    with pytest.raises(ValueError, match="outside NYSE calendar"):
        resolve_expected_session(
            datetime(2101, 1, 3, 17, 0, tzinfo=NY),
            source_mode=SourceMode.PAID_CURRENT_DAY,
        )


def test_next_session_skips_weekends_and_exchange_holidays():
    from eod_readiness import next_nyse_session

    assert next_nyse_session(date(2026, 9, 4)) == date(2026, 9, 8)


def test_current_orchestration_fails_closed_before_signal_generation(monkeypatch):
    import psycopg
    import orchestration_runner
    from eod_readiness import EODReadiness, SourceMode

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    incomplete = EODReadiness(
        expected_session=date(2026, 8, 28),
        latest_complete_session=date(2026, 8, 27),
        coverage_numerator=1,
        coverage_denominator=2,
        missing_symbols=("ZZMISSING",),
        source_mode=SourceMode.FREE_T_PLUS_1,
        publishable=False,
    )
    generated = False

    def fake_signal_call(cmd):
        nonlocal generated
        generated = True
        return 0

    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: FakeConnection())
    monkeypatch.setattr(
        orchestration_runner,
        "evaluate_current_eod_readiness",
        lambda conn, *, tickers: incomplete,
    )
    monkeypatch.setattr(orchestration_runner.subprocess, "call", fake_signal_call)

    rc = orchestration_runner.run_eod_features_signals(tickers_csv_value="SPY,ZZMISSING")

    assert rc == 3
    assert generated is False


def test_replay_orchestration_checks_exact_signal_date_and_fails_closed(monkeypatch):
    import psycopg
    import orchestration_runner
    from eod_readiness import EODReadiness, SourceMode

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    replay_dt = date(2026, 8, 18)
    incomplete = EODReadiness(
        expected_session=replay_dt,
        latest_complete_session=date(2026, 8, 17),
        coverage_numerator=1,
        coverage_denominator=2,
        missing_symbols=("ZZREPLAY",),
        source_mode=SourceMode.FREE_T_PLUS_1,
        publishable=False,
    )
    checked = {}

    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: FakeConnection())

    def fake_replay_readiness(conn, *, tickers, signal_dt):
        checked["tickers"] = tickers
        checked["signal_dt"] = signal_dt
        return incomplete

    monkeypatch.setattr(
        orchestration_runner,
        "evaluate_replay_eod_readiness",
        fake_replay_readiness,
    )
    monkeypatch.setattr(
        orchestration_runner.subprocess,
        "call",
        lambda cmd: pytest.fail("signal generation must not run for an incomplete replay"),
    )

    rc = orchestration_runner.run_eod_features_signals(
        tickers_csv_value="SPY,ZZREPLAY",
        signal_dt_value=replay_dt.isoformat(),
    )

    assert rc == 3
    assert checked == {"tickers": ["SPY", "ZZREPLAY"], "signal_dt": replay_dt}
