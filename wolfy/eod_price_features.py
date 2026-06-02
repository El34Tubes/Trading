from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Sequence


DEFAULT_DSN = os.environ.get("WOLFY_POSTGRES_DSN", "dbname=wolfy user=root host=/var/run/postgresql")
DEFAULT_MIN_DOLLAR_VOL = Decimal("25000000")
DEFAULT_SMA_FAST_WINDOW = 20
DEFAULT_SMA_SLOW_WINDOW = 50
DEFAULT_VOLUME_WINDOW = 20
DEFAULT_ATR_WINDOW = 14


@dataclass(frozen=True)
class PriceBar:
    ticker: str
    dt: date
    open: Decimal | int | float | str
    high: Decimal | int | float | str
    low: Decimal | int | float | str
    close: Decimal | int | float | str
    volume: int


@dataclass(frozen=True)
class FeatureRow:
    ticker: str
    dt: date
    sma_fast: Decimal | None
    sma_slow: Decimal | None
    vol_ratio: Decimal | None
    dollar_vol: Decimal
    atr: Decimal | None
    liquidity: bool
    vol_regime: str


def _dec(value: Decimal | int | float | str | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _q(value: Decimal | None, places: str = "0.0001") -> Decimal | None:
    if value is None:
        return None
    quantized = value.quantize(Decimal(places), rounding=ROUND_HALF_UP)
    return quantized.normalize()


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))


def _true_range(bar: PriceBar, previous_close: Decimal | None) -> Decimal:
    high = _dec(bar.high)
    low = _dec(bar.low)
    if high is None or low is None:
        raise ValueError("high and low are required for ATR")
    ranges = [high - low]
    if previous_close is not None:
        ranges.append(abs(high - previous_close))
        ranges.append(abs(low - previous_close))
    return max(ranges)


def _vol_regime(vol_ratio: Decimal | None) -> str:
    if vol_ratio is None:
        return "unknown"
    if vol_ratio >= Decimal("2.0"):
        return "high"
    if vol_ratio <= Decimal("0.5"):
        return "low"
    return "normal"


def compute_feature_rows(
    bars: Iterable[PriceBar],
    *,
    sma_fast_window: int = DEFAULT_SMA_FAST_WINDOW,
    sma_slow_window: int = DEFAULT_SMA_SLOW_WINDOW,
    volume_window: int = DEFAULT_VOLUME_WINDOW,
    atr_window: int = DEFAULT_ATR_WINDOW,
    min_dollar_vol: Decimal = DEFAULT_MIN_DOLLAR_VOL,
) -> list[FeatureRow]:
    """Compute deterministic EOD features from chronological bars for one or more tickers."""
    if min(sma_fast_window, sma_slow_window, volume_window, atr_window) <= 0:
        raise ValueError("feature windows must be positive")

    grouped: dict[str, list[PriceBar]] = {}
    for bar in bars:
        grouped.setdefault(bar.ticker.upper(), []).append(bar)

    rows: list[FeatureRow] = []
    for ticker in sorted(grouped):
        ticker_bars = sorted(grouped[ticker], key=lambda b: b.dt)
        closes: list[Decimal] = []
        volumes: list[Decimal] = []
        true_ranges: list[Decimal] = []
        previous_close: Decimal | None = None
        for bar in ticker_bars:
            close = _dec(bar.close)
            volume = Decimal(int(bar.volume or 0))
            if close is None:
                raise ValueError("close is required for feature computation")
            closes.append(close)
            volumes.append(volume)
            true_ranges.append(_true_range(bar, previous_close))
            previous_close = close

            sma_fast = _q(_mean(closes[-sma_fast_window:])) if len(closes) >= sma_fast_window else None
            sma_slow = _q(_mean(closes[-sma_slow_window:])) if len(closes) >= sma_slow_window else None
            avg_volume = _mean(volumes[-volume_window:]) if len(volumes) >= volume_window else None
            vol_ratio = _q(volume / avg_volume) if avg_volume and avg_volume != 0 else None
            atr = _q(_mean(true_ranges[-atr_window:])) if len(true_ranges) >= atr_window else None
            dollar_vol = _q(close * volume, "0.01") or Decimal("0")
            rows.append(
                FeatureRow(
                    ticker=ticker,
                    dt=bar.dt,
                    sma_fast=sma_fast,
                    sma_slow=sma_slow,
                    vol_ratio=vol_ratio,
                    dollar_vol=dollar_vol,
                    atr=atr,
                    liquidity=dollar_vol >= min_dollar_vol,
                    vol_regime=_vol_regime(vol_ratio),
                )
            )
    return rows


def ensure_eod_feature_schema(conn) -> None:
    """Create/upgrade the non-destructive EOD price/feature/runs schema."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS prices (
          ticker text NOT NULL,
          dt date NOT NULL,
          open numeric,
          high numeric,
          low numeric,
          close numeric,
          volume bigint,
          PRIMARY KEY (ticker, dt)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_prices_dt ON prices(dt, ticker)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS features (
          ticker text NOT NULL,
          dt date NOT NULL,
          sma_fast numeric,
          sma_slow numeric,
          vol_ratio numeric,
          dollar_vol numeric,
          atr numeric,
          vol_regime text,
          PRIMARY KEY (ticker, dt)
        )
        """
    )
    conn.execute("ALTER TABLE features ADD COLUMN IF NOT EXISTS liquidity boolean")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_features_dt_liquidity ON features(dt, liquidity, dollar_vol DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_features_vol_regime ON features(vol_regime, dt DESC)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
          id serial PRIMARY KEY,
          job text,
          started timestamptz,
          finished timestamptz,
          status text,
          detail jsonb
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_job_started ON runs(job, started DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_status_started ON runs(status, started DESC)")


def _start_run(conn, job: str, detail: dict) -> int:
    row = conn.execute(
        "INSERT INTO runs(job, started, status, detail) VALUES (%s, now(), %s, %s::jsonb) RETURNING id",
        (job, "running", json.dumps(detail, sort_keys=True)),
    ).fetchone()
    return int(row[0])


def _finish_run(conn, run_id: int, status: str, detail: dict) -> None:
    conn.execute(
        "UPDATE runs SET finished=now(), status=%s, detail=%s::jsonb WHERE id=%s",
        (status, json.dumps(detail, sort_keys=True), run_id),
    )


def ingest_price_bars(conn, bars: Sequence[PriceBar], *, source: str = "manual-fixture") -> int:
    ensure_eod_feature_schema(conn)
    run_id = _start_run(conn, "eod_price_ingest", {"source": source, "rows_requested": len(bars)})
    upserted = 0
    try:
        for bar in bars:
            conn.execute(
                """
                INSERT INTO prices(ticker, dt, open, high, low, close, volume)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, dt) DO UPDATE SET
                  open=EXCLUDED.open,
                  high=EXCLUDED.high,
                  low=EXCLUDED.low,
                  close=EXCLUDED.close,
                  volume=EXCLUDED.volume
                """,
                (
                    bar.ticker.upper(),
                    bar.dt,
                    _dec(bar.open),
                    _dec(bar.high),
                    _dec(bar.low),
                    _dec(bar.close),
                    int(bar.volume or 0),
                ),
            )
            upserted += 1
        _finish_run(conn, run_id, "ok", {"source": source, "rows_upserted": upserted})
        return run_id
    except Exception as exc:
        _finish_run(conn, run_id, "error", {"source": source, "rows_upserted": upserted, "error": str(exc)})
        raise


def _load_price_bars(conn, tickers: Sequence[str], start_dt: date | None, end_dt: date | None) -> list[PriceBar]:
    params: list[object] = [[ticker.upper() for ticker in tickers]]
    where = ["ticker = ANY(%s)"]
    if start_dt is not None:
        where.append("dt >= %s")
        params.append(start_dt)
    if end_dt is not None:
        where.append("dt <= %s")
        params.append(end_dt)
    sql = "SELECT ticker, dt, open, high, low, close, volume FROM prices WHERE " + " AND ".join(where) + " ORDER BY ticker, dt"
    return [PriceBar(*row) for row in conn.execute(sql, params).fetchall()]


def store_feature_rows(conn, rows: Sequence[FeatureRow]) -> int:
    for row in rows:
        conn.execute(
            """
            INSERT INTO features(ticker, dt, sma_fast, sma_slow, vol_ratio, dollar_vol, atr, liquidity, vol_regime)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ticker, dt) DO UPDATE SET
              sma_fast=EXCLUDED.sma_fast,
              sma_slow=EXCLUDED.sma_slow,
              vol_ratio=EXCLUDED.vol_ratio,
              dollar_vol=EXCLUDED.dollar_vol,
              atr=EXCLUDED.atr,
              liquidity=EXCLUDED.liquidity,
              vol_regime=EXCLUDED.vol_regime
            """,
            (row.ticker, row.dt, row.sma_fast, row.sma_slow, row.vol_ratio, row.dollar_vol, row.atr, row.liquidity, row.vol_regime),
        )
    return len(rows)


def compute_and_store_features(
    conn,
    *,
    tickers: Sequence[str],
    start_dt: date | None = None,
    end_dt: date | None = None,
    sma_fast_window: int = DEFAULT_SMA_FAST_WINDOW,
    sma_slow_window: int = DEFAULT_SMA_SLOW_WINDOW,
    volume_window: int = DEFAULT_VOLUME_WINDOW,
    atr_window: int = DEFAULT_ATR_WINDOW,
    min_dollar_vol: Decimal = DEFAULT_MIN_DOLLAR_VOL,
) -> int:
    ensure_eod_feature_schema(conn)
    detail = {
        "tickers": [t.upper() for t in tickers],
        "start_dt": start_dt.isoformat() if start_dt else None,
        "end_dt": end_dt.isoformat() if end_dt else None,
        "sma_fast_window": sma_fast_window,
        "sma_slow_window": sma_slow_window,
        "volume_window": volume_window,
        "atr_window": atr_window,
        "min_dollar_vol": str(min_dollar_vol),
    }
    run_id = _start_run(conn, "eod_feature_compute", detail)
    try:
        bars = _load_price_bars(conn, tickers, start_dt, end_dt)
        rows = compute_feature_rows(
            bars,
            sma_fast_window=sma_fast_window,
            sma_slow_window=sma_slow_window,
            volume_window=volume_window,
            atr_window=atr_window,
            min_dollar_vol=min_dollar_vol,
        )
        stored = store_feature_rows(conn, rows)
        detail.update({"bars_loaded": len(bars), "feature_rows_upserted": stored})
        _finish_run(conn, run_id, "ok", detail)
        return run_id
    except Exception as exc:
        detail.update({"error": str(exc)})
        _finish_run(conn, run_id, "error", detail)
        raise


def fetch_yahoo_chart_bars(tickers: Sequence[str], *, days: int = 90) -> list[PriceBar]:
    """Fetch free delayed daily bars from Yahoo's chart endpoint for smoke/small-universe ingest."""
    bars: list[PriceBar] = []
    period2 = int(time.time())
    period1 = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    for ticker in tickers:
        symbol = ticker.upper()
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            + urllib.parse.quote(symbol)
            + f"?period1={period1}&period2={period2}&interval=1d&events=history&includeAdjustedClose=true"
        )
        request = urllib.request.Request(url, headers={"User-Agent": "Hermes-Wolfy-EOD/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Yahoo fetch failed for {symbol}: {exc}") from exc
        result = (payload.get("chart", {}).get("result") or [None])[0]
        if not result:
            continue
        timestamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []
        for idx, ts in enumerate(timestamps):
            try:
                o, h, l, c = opens[idx], highs[idx], lows[idx], closes[idx]
                v = volumes[idx]
            except IndexError:
                continue
            if None in (o, h, l, c, v):
                continue
            open_dec = _q(Decimal(str(o)), "0.0001")
            high_dec = _q(Decimal(str(h)), "0.0001")
            low_dec = _q(Decimal(str(l)), "0.0001")
            close_dec = _q(Decimal(str(c)), "0.0001")
            if None in (open_dec, high_dec, low_dec, close_dec):
                continue
            assert open_dec is not None and high_dec is not None and low_dec is not None and close_dec is not None
            bars.append(
                PriceBar(
                    symbol,
                    datetime.fromtimestamp(ts, tz=timezone.utc).date(),
                    open_dec,
                    high_dec,
                    low_dec,
                    close_dec,
                    int(v),
                )
            )
    return bars


def smoke_ingest(
    *,
    tickers: Sequence[str],
    days: int = 90,
    dsn: str = DEFAULT_DSN,
    min_dollar_vol: Decimal = DEFAULT_MIN_DOLLAR_VOL,
) -> dict:
    import psycopg

    bars = fetch_yahoo_chart_bars(tickers, days=days)
    with psycopg.connect(dsn) as conn:
        ingest_run = ingest_price_bars(conn, bars, source="yahoo-chart-delayed")
        feature_run = compute_and_store_features(conn, tickers=tickers, min_dollar_vol=min_dollar_vol)
        latest = conn.execute(
            """
            SELECT ticker, max(dt) AS latest_dt, count(*) AS bars
            FROM prices
            WHERE ticker = ANY(%s)
            GROUP BY ticker
            ORDER BY ticker
            """,
            ([ticker.upper() for ticker in tickers],),
        ).fetchall()
    return {
        "source": "yahoo-chart-delayed",
        "tickers": [ticker.upper() for ticker in tickers],
        "bars_fetched": len(bars),
        "ingest_run_id": ingest_run,
        "feature_run_id": feature_run,
        "latest": [{"ticker": row[0], "latest_dt": row[1].isoformat(), "bars": row[2]} for row in latest],
    }


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wolfy EOD price ingest and deterministic feature service")
    parser.add_argument("--tickers", default="SPY,QQQ,IWM", help="Comma-separated ticker universe")
    parser.add_argument("--days", type=int, default=90, help="Yahoo delayed daily bars lookback")
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    parser.add_argument("--min-dollar-vol", default=str(DEFAULT_MIN_DOLLAR_VOL))
    args = parser.parse_args(argv)
    tickers = [ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()]
    result = smoke_ingest(tickers=tickers, days=args.days, dsn=args.dsn, min_dollar_vol=Decimal(args.min_dollar_vol))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
