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
