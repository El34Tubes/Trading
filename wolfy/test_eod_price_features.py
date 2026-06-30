from datetime import date
from decimal import Decimal

import pytest


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
    psycopg = pytest.importorskip("psycopg")
    from eod_price_features import (
        PriceBar,
        compute_and_store_features,
        ensure_eod_feature_schema,
        ingest_price_bars,
    )

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    ticker = "ZZTESTEOD"
    bars = [
        PriceBar(ticker, date(2026, 2, 1), 10, 11, 9, 10, 1000),
        PriceBar(ticker, date(2026, 2, 2), 11, 12, 10, 11, 2000),
        PriceBar(ticker, date(2026, 2, 3), 12, 13, 11, 12, 3000),
    ]

    with psycopg.connect(dsn) as conn:
        ensure_eod_feature_schema(conn)
        ingest_run_1 = ingest_price_bars(conn, bars, source="unit-fixture")
        ingest_run_2 = ingest_price_bars(conn, bars, source="unit-fixture")
        feature_run = compute_and_store_features(
            conn,
            tickers=[ticker],
            start_dt=date(2026, 2, 1),
            end_dt=date(2026, 2, 3),
            sma_fast_window=2,
            sma_slow_window=3,
            volume_window=3,
            atr_window=3,
            min_dollar_vol=Decimal("25000"),
        )

        price_count = conn.execute("SELECT count(*) FROM prices WHERE ticker=%s", (ticker,)).fetchone()[0]
        feature = conn.execute(
            "SELECT sma_fast, sma_slow, vol_ratio, dollar_vol, atr, liquidity, vol_regime FROM features WHERE ticker=%s AND dt=%s",
            (ticker, date(2026, 2, 3)),
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
    psycopg = pytest.importorskip("psycopg")
    from eod_price_features import ensure_eod_feature_schema, store_massive_reference_symbols

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    symbol = "ZZMASSIVEETF"
    records = [{"ticker": symbol, "name": "Massive Fixture ETF", "type": "ETF", "active": True}]

    with psycopg.connect(dsn) as conn:
        ensure_eod_feature_schema(conn)
        stored = store_massive_reference_symbols(conn, records)
        row = conn.execute("SELECT symbol, name, source, is_etf, active FROM universe_symbols WHERE symbol=%s", (symbol,)).fetchone()
        conn.execute("DELETE FROM universe_symbols WHERE symbol=%s", (symbol,))

    assert stored == 1
    assert row == (symbol, "Massive Fixture ETF", "massive-reference", True, True)


def test_validate_price_data_quality_records_stale_blocker_without_corporate_action_fetch():
    psycopg = pytest.importorskip("psycopg")
    from eod_price_features import PriceBar, ensure_eod_feature_schema, ingest_price_bars, validate_price_data_quality

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    ticker = "ZZSTALEMASSIVE"
    as_of = date(2026, 2, 10)
    bars = [PriceBar(ticker, date(2026, 1, 1), 10, 10, 10, 10, 1000)]

    with psycopg.connect(dsn) as conn:
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
    psycopg = pytest.importorskip("psycopg")
    from eod_price_features import PriceBar, _fetch_incremental_massive_bars, ensure_eod_feature_schema, ingest_price_bars

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    ticker = "ZZCURRENTAPI"
    today = date.today()
    bars = [PriceBar(ticker, today, 10, 11, 9, 10, 1000)]

    def fail_fetch(*args, **kwargs):
        raise AssertionError("Massive should not be called when stored data is already current")

    monkeypatch.setattr("eod_price_features.fetch_massive_eod_bars", fail_fetch)

    with psycopg.connect(dsn) as conn:
        ensure_eod_feature_schema(conn)
        run_id = ingest_price_bars(conn, bars, source="unit-current-api")
        fetched, plan = _fetch_incremental_massive_bars(conn, tickers=[ticker], days=730, adjusted=True, pause_seconds=0, min_history_bars=1)
        conn.execute("DELETE FROM prices WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM runs WHERE id=%s", (run_id,))

    assert fetched == []
    assert plan == [{"ticker": ticker, "skipped": True, "reason": "already_current", "latest_dt": str(today)}]
