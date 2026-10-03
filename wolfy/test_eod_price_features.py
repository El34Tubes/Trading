from datetime import date, timedelta
from decimal import Decimal
import json

import pytest

from test_db import future_fixture, test_connection


def test_default_massive_eod_end_dt_uses_previous_business_day(monkeypatch):
    from eod_price_features import _default_massive_eod_end_dt

    monkeypatch.delenv("WOLFY_MASSIVE_ALLOW_CURRENT_DAY", raising=False)
    assert _default_massive_eod_end_dt(date(2026, 7, 21)) == date(2026, 7, 20)
    assert _default_massive_eod_end_dt(date(2026, 7, 20)) == date(2026, 7, 17)

    monkeypatch.setenv("WOLFY_MASSIVE_ALLOW_CURRENT_DAY", "1")
    assert _default_massive_eod_end_dt(date(2026, 7, 21)) == date(2026, 7, 21)


def test_compute_eod_features_uses_deterministic_rolling_math():
    from eod_price_features import PriceBar, compute_feature_rows

    bars = [
        PriceBar("ABC", date(2026, 1, 1), 10, 11, 9, 10, 100),
        PriceBar("ABC", date(2026, 1, 2), 11, 12, 10, 11, 200),
        PriceBar("ABC", date(2026, 1, 3), 12, 13, 11, 12, 300),
        PriceBar("ABC", date(2026, 1, 4), 13, 14, 12, 13, 600),
    ]

    rows = compute_feature_rows(
        bars,
        sma_fast_window=2,
        sma_slow_window=3,
        volume_window=3,
        atr_window=3,
        min_dollar_vol=Decimal("5000"),
    )

    latest = rows[-1]
    assert latest.ticker == "ABC"
    assert latest.dt == date(2026, 1, 4)
    assert latest.sma_fast == Decimal("12.5")
    assert latest.sma_slow == Decimal("12")
    assert latest.vol_ratio == Decimal("1.6364")
    assert latest.dollar_vol == Decimal("7800")
    assert latest.atr == Decimal("2")
    assert latest.liquidity is True
    assert latest.vol_regime == "normal"


def test_compute_eod_features_marks_insufficient_windows_and_liquidity_false():
    from eod_price_features import PriceBar, compute_feature_rows

    bars = [PriceBar("XYZ", date(2026, 1, 1), 20, 21, 19, 20, 10)]

    row = compute_feature_rows(
        bars,
        sma_fast_window=2,
        sma_slow_window=3,
        volume_window=3,
        atr_window=3,
        min_dollar_vol=Decimal("1000"),
    )[0]

    assert row.sma_fast is None
    assert row.sma_slow is None
    assert row.vol_ratio is None
    assert row.atr is None
    assert row.dollar_vol == Decimal("200")
    assert row.liquidity is False
    assert row.vol_regime == "unknown"


def test_prices_and_features_are_idempotently_upserted_into_postgres():
    pytest.importorskip("psycopg")
    from eod_price_features import (
        PriceBar,
        compute_and_store_features,
        ensure_eod_feature_schema,
        ingest_price_bars,
    )

    fixture = future_fixture("prices")
    ticker = fixture.ticker
    start_dt = fixture.signal_dt
    bars = [
        PriceBar(ticker, start_dt, 10, 11, 9, 10, 1000),
        PriceBar(ticker, start_dt + timedelta(days=1), 11, 12, 10, 11, 2000),
        PriceBar(ticker, start_dt + timedelta(days=2), 12, 13, 11, 12, 3000),
    ]

    with test_connection() as conn:
        ensure_eod_feature_schema(conn)
        ingest_run_1 = ingest_price_bars(conn, bars, source="unit-fixture")
        ingest_run_2 = ingest_price_bars(conn, bars, source="unit-fixture")
        feature_run = compute_and_store_features(
            conn,
            tickers=[ticker],
            start_dt=start_dt,
            end_dt=start_dt + timedelta(days=2),
            sma_fast_window=2,
            sma_slow_window=3,
            volume_window=3,
            atr_window=3,
            min_dollar_vol=Decimal("25000"),
        )

        price_count = conn.execute("SELECT count(*) FROM prices WHERE ticker=%s", (ticker,)).fetchone()[0]
        feature = conn.execute(
            "SELECT sma_fast, sma_slow, vol_ratio, dollar_vol, atr, liquidity, vol_regime FROM features WHERE ticker=%s AND dt=%s",
            (ticker, start_dt + timedelta(days=2)),
        ).fetchone()
        runs = conn.execute(
            "SELECT job, status FROM runs WHERE id = ANY(%s) ORDER BY id",
            ([ingest_run_1, ingest_run_2, feature_run],),
        ).fetchall()

        conn.execute("DELETE FROM features WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM prices WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM runs WHERE id = ANY(%s)", ([ingest_run_1, ingest_run_2, feature_run],))

    assert price_count == 3
    assert feature == (Decimal("11.5"), Decimal("11"), Decimal("1.5"), Decimal("36000"), Decimal("2"), True, "normal")
    assert runs == [("eod_price_ingest", "ok"), ("eod_price_ingest", "ok"), ("eod_feature_compute", "ok")]



class _FakeResponse:
    def __init__(self, payload):
        import json
        self.payload = json.dumps(payload).encode("utf-8")
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


def test_fetch_massive_eod_bars_maps_adjusted_aggregates(monkeypatch):
    from eod_price_features import fetch_massive_eod_bars

    captured = []

    def fake_urlopen(request, timeout=30):
        captured.append(request.full_url)
        return _FakeResponse(
            {
                "status": "OK",
                "results": [
                    {"t": 1767225600000, "o": 10.1, "h": 11.2, "l": 9.9, "c": 10.8, "v": 12345},
                ],
            }
        )

    monkeypatch.setenv("MASSIVE_API_KEY", "x" * 32)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    bars = fetch_massive_eod_bars(["spy"], start_dt=date(2026, 1, 1), end_dt=date(2026, 1, 2))

    assert len(bars) == 1
    assert bars[0].ticker == "SPY"
    assert bars[0].dt == date(2026, 1, 1)
    assert bars[0].close == Decimal("10.8")
    assert bars[0].volume == 12345
    assert "adjusted=true" in captured[0]
    assert "apiKey=" in captured[0]


def test_store_massive_reference_symbols_upserts_universe_in_postgres():
    pytest.importorskip("psycopg")
    from eod_price_features import ensure_eod_feature_schema, store_massive_reference_symbols

    symbol = future_fixture("massiveetf").ticker
    records = [{"ticker": symbol, "name": "Massive Fixture ETF", "type": "ETF", "active": True}]

    with test_connection() as conn:
        ensure_eod_feature_schema(conn)
        stored = store_massive_reference_symbols(conn, records)
        row = conn.execute("SELECT symbol, name, source, is_etf, active FROM universe_symbols WHERE symbol=%s", (symbol,)).fetchone()
        conn.execute("DELETE FROM universe_symbols WHERE symbol=%s", (symbol,))

    assert stored == 1
    assert row == (symbol, "Massive Fixture ETF", "massive-reference", True, True)


def test_validate_price_data_quality_records_stale_blocker_without_corporate_action_fetch():
    pytest.importorskip("psycopg")
    from eod_price_features import PriceBar, ensure_eod_feature_schema, ingest_price_bars, validate_price_data_quality

    fixture = future_fixture("stale")
    ticker = fixture.ticker
    as_of = fixture.signal_dt
    bars = [PriceBar(ticker, as_of - timedelta(days=40), 10, 10, 10, 10, 1000)]

    with test_connection() as conn:
        ensure_eod_feature_schema(conn)
        run_id = ingest_price_bars(conn, bars, source="unit-fixture")
        result = validate_price_data_quality(
            conn,
            tickers=[ticker],
            source="massive-adjusted-eod",
            as_of=as_of,
            max_stale_days=5,
            check_corporate_actions=False,
        )
        recorded = conn.execute(
            "SELECT severity, reason FROM price_data_quality_events WHERE ticker=%s AND as_of=%s ORDER BY id DESC LIMIT 1",
            (ticker, as_of),
        ).fetchone()
        conn.execute("DELETE FROM price_data_quality_events WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM prices WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM runs WHERE id=%s", (run_id,))

    assert result["blockers"] == 1
    assert recorded == ("blocker", "stale_price_history")



def test_fetch_eodhs_eod_bars_is_capped_and_uses_adjusted_close(monkeypatch):
    from eod_price_features import fetch_eodhs_eod_bars

    captured = []

    def fake_urlopen(request, timeout=30):
        captured.append(request.full_url)
        return _FakeResponse([
            {"date": "2026-06-26", "open": 100, "high": 102, "low": 99, "close": 101, "adjusted_close": 50.5, "volume": 1000}
        ])

    monkeypatch.setenv("EODHS_API_KEY", "x" * 23)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    bars = fetch_eodhs_eod_bars(["AAPL", "MSFT"], start_dt=date(2026, 6, 26), end_dt=date(2026, 6, 26), max_tickers=1, pause_seconds=0)

    assert len(captured) == 1
    assert "AAPL.US" in captured[0]
    assert len(bars) == 1
    assert bars[0].ticker == "AAPL"
    assert bars[0].close == Decimal("50.5")


def test_incremental_massive_plan_skips_current_ticker_without_api_call(monkeypatch):
    pytest.importorskip("psycopg")
    from eod_price_features import PriceBar, _fetch_incremental_massive_bars, ensure_eod_feature_schema, ingest_price_bars

    fixture = future_fixture("currentapi")
    ticker = fixture.ticker
    latest_accessible_dt = fixture.signal_dt
    bars = [PriceBar(ticker, latest_accessible_dt, 10, 11, 9, 10, 1000)]

    def fail_fetch(*args, **kwargs):
        raise AssertionError("Massive should not be called when stored data is already current")

    monkeypatch.setattr("eod_price_features.fetch_massive_eod_bars", fail_fetch)
    monkeypatch.setattr("eod_price_features.fetch_massive_corporate_actions", lambda *args, **kwargs: {ticker: []})

    with test_connection() as conn:
        ensure_eod_feature_schema(conn)
        run_id = ingest_price_bars(conn, bars, source="unit-current-api")
        fetched, plan = _fetch_incremental_massive_bars(
            conn,
            tickers=[ticker],
            days=730,
            adjusted=True,
            pause_seconds=0,
            min_history_bars=1,
            end_dt=latest_accessible_dt,
        )
        conn.execute("DELETE FROM prices WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM runs WHERE id=%s", (run_id,))

    assert fetched == []
    assert plan == [{"ticker": ticker, "skipped": True, "reason": "already_current", "latest_dt": str(latest_accessible_dt)}]


def test_incremental_massive_plan_refetches_full_history_after_split(monkeypatch):
    psycopg = pytest.importorskip("psycopg")
    from eod_price_features import PriceBar, _fetch_incremental_massive_bars, ensure_eod_feature_schema, ingest_price_bars, validate_price_data_quality

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    ticker = "ZZSPLITAPI"
    end_dt = date(2026, 7, 20)
    days = 730
    full_start_dt = end_dt - timedelta(days=days)
    stored_dt = date(2025, 1, 2)
    stored_bars = [
        PriceBar(ticker, stored_dt, 100, 101, 99, 100, 1000),
        PriceBar(ticker, end_dt, 104, 105, 103, 104, 1200),
    ]
    adjusted_bar = PriceBar(ticker, stored_dt, 25, 26, 24, 25, 4000)
    fetch_calls = []

    def fake_actions(tickers, *, since, until, **kwargs):
        assert tickers == [ticker]
        assert since in {stored_dt, end_dt - timedelta(days=45)}
        assert until == end_dt
        return {ticker: [{"kind": "split", "execution_date": "2026-07-15", "split_from": 1, "split_to": 4}]}

    def fake_fetch(tickers, *, start_dt, end_dt, adjusted, pause_seconds):
        fetch_calls.append((tickers, start_dt, end_dt, adjusted, pause_seconds))
        return [adjusted_bar]

    monkeypatch.setattr("eod_price_features.fetch_massive_corporate_actions", fake_actions)
    monkeypatch.setattr("eod_price_features.fetch_massive_eod_bars", fake_fetch)

    with psycopg.connect(dsn) as conn:
        ensure_eod_feature_schema(conn)
        run_id = ingest_price_bars(conn, stored_bars, source="unit-split-api")
        fetched, plan = _fetch_incremental_massive_bars(
            conn,
            tickers=[ticker],
            days=days,
            adjusted=True,
            pause_seconds=0,
            min_history_bars=1,
            end_dt=end_dt,
        )
        conn.execute("DELETE FROM prices WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM runs WHERE id=%s", (run_id,))

    assert fetched == [adjusted_bar]
    assert fetch_calls == [([ticker], full_start_dt, end_dt, True, 0)]
    assert plan == [{
        "ticker": ticker,
        "skipped": False,
        "reason": "corporate_action_refetch",
        "start_dt": full_start_dt.isoformat(),
        "end_dt": end_dt.isoformat(),
        "bars_fetched": 1,
        "split_execution_dates": ["2026-07-15"],
    }]

    with psycopg.connect(dsn) as conn:
        ensure_eod_feature_schema(conn)
        run_id = ingest_price_bars(conn, stored_bars, source="unit-split-api")
        conn.execute(
            """
            INSERT INTO price_data_quality_events(as_of, ticker, severity, source, reason, detail)
            VALUES (%s, %s, 'info', 'unit-split-api', 'corporate_action_refetch_completed', %s::jsonb)
            """,
            (end_dt, ticker, json.dumps({"split_execution_dates": ["2026-07-15"]})),
        )
        fetch_calls.clear()
        second_fetched, second_plan = _fetch_incremental_massive_bars(
            conn,
            tickers=[ticker],
            days=days,
            adjusted=True,
            pause_seconds=0,
            min_history_bars=1,
            end_dt=end_dt,
        )
        validation = validate_price_data_quality(
            conn,
            tickers=[ticker],
            source="unit-split-api",
            as_of=end_dt,
        )
        unresolved_split_audits = conn.execute(
            """
            SELECT count(*) FROM price_data_quality_events
            WHERE ticker=%s AND reason='recent_split_requires_adjustment_audit'
            """,
            (ticker,),
        ).fetchone()[0]
        conn.execute("DELETE FROM price_data_quality_events WHERE ticker=%s AND source='unit-split-api'", (ticker,))
        conn.execute("DELETE FROM prices WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM runs WHERE id=%s", (run_id,))

    assert second_fetched == []
    assert fetch_calls == []
    assert second_plan == [{"ticker": ticker, "skipped": True, "reason": "already_current", "latest_dt": str(end_dt)}]
    assert validation["events_recorded"] == 0
    assert unresolved_split_audits == 0


def test_massive_ingest_records_completed_split_refetch(monkeypatch):
    psycopg = pytest.importorskip("psycopg")
    from eod_price_features import PriceBar, ensure_eod_feature_schema, massive_ingest

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    ticker = "ZZSPLITMARKER"
    end_dt = date(2026, 7, 20)
    split_dt = "2026-07-15"
    adjusted_bar = PriceBar(ticker, end_dt, 25, 26, 24, 25, 4000)

    monkeypatch.setattr(
        "eod_price_features._fetch_incremental_massive_bars",
        lambda *args, **kwargs: ([adjusted_bar], [{
            "ticker": ticker,
            "skipped": False,
            "reason": "corporate_action_refetch",
            "start_dt": "2024-07-20",
            "end_dt": end_dt.isoformat(),
            "bars_fetched": 1,
            "split_execution_dates": [split_dt],
        }]),
    )
    monkeypatch.setattr("eod_price_features.compute_and_store_features", lambda *args, **kwargs: None)

    result = massive_ingest(tickers=[ticker], dsn=dsn, validate=False, end_dt=end_dt)

    with psycopg.connect(dsn) as conn:
        ensure_eod_feature_schema(conn)
        marker = conn.execute(
            """
            SELECT severity, detail->'split_execution_dates'
            FROM price_data_quality_events
            WHERE ticker=%s AND reason='corporate_action_refetch_completed'
            ORDER BY id DESC LIMIT 1
            """,
            (ticker,),
        ).fetchone()
        conn.execute("DELETE FROM price_data_quality_events WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM prices WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM runs WHERE id=%s", (result["ingest_run_id"],))

    assert marker == ("info", [split_dt])
