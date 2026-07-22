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
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_DSN = os.environ.get("WOLFY_POSTGRES_DSN", "dbname=wolfy user=root host=/var/run/postgresql")
DEFAULT_MIN_DOLLAR_VOL = Decimal("25000000")
DEFAULT_SMA_FAST_WINDOW = 20
DEFAULT_SMA_SLOW_WINDOW = 50
DEFAULT_VOLUME_WINDOW = 20
DEFAULT_ATR_WINDOW = 14
MASSIVE_BASE_URL = os.environ.get("MASSIVE_BASE_URL", "https://api.massive.com")
EODHS_BASE_URL = os.environ.get("EODHS_BASE_URL", "https://eodhd.com")
ENV_FILE = Path(os.environ.get("HERMES_ENV_PATH", "/root/.hermes/.env"))


def _previous_business_day(day: date) -> date:
    candidate = day - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _default_massive_eod_end_dt(today: date | None = None) -> date:
    """Return the safest default Massive EOD aggregate end date.

    Wolfy's current Massive/Polygon plan has repeatedly returned 403
    NOT_AUTHORIZED for same-calendar-day daily aggregate requests even after the
    market close. Defaulting cron to the previous business day keeps the
    deterministic EOD ingest healthy on delayed/free plans. Operators with a
    real-time plan can opt back into same-day requests via
    WOLFY_MASSIVE_ALLOW_CURRENT_DAY=1 or an explicit --end-date.
    """
    current = today or date.today()
    if os.environ.get("WOLFY_MASSIVE_ALLOW_CURRENT_DAY", "").strip().lower() in {"1", "true", "yes", "on"}:
        return current
    return _previous_business_day(current)


def _env_secret(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() in names:
                return value.strip().strip("\"'")
    return None


def _massive_api_key() -> str:
    key = _env_secret("MASSIVE_API_KEY", "POLYGON_API_KEY")
    if not key:
        raise RuntimeError("MASSIVE_API_KEY is not set; add it to Hermes .env and reload before using Massive ingest")
    return key


def _massive_get_json(
    path_or_url: str,
    params: dict[str, object] | None = None,
    *,
    timeout: int = 30,
    max_attempts: int = 3,
    rate_limit_sleep_seconds: int = 65,
) -> dict:
    params = dict(params or {})
    params.setdefault("apiKey", _massive_api_key())
    if path_or_url.startswith("http"):
        url = path_or_url
        if "apiKey=" not in url:
            sep = "&" if "?" in url else "?"
            url = url + sep + urllib.parse.urlencode({"apiKey": params["apiKey"]})
    else:
        url = MASSIVE_BASE_URL.rstrip("/") + "/" + path_or_url.lstrip("/") + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "Hermes-Wolfy-EOD/1.0"})
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:500]
            if exc.code == 429 and attempt < max_attempts:
                retry_after = exc.headers.get("Retry-After")
                sleep_seconds = int(retry_after) if retry_after and retry_after.isdigit() else rate_limit_sleep_seconds
                time.sleep(sleep_seconds)
                continue
            raise RuntimeError(f"Massive API HTTP {exc.code} for {path_or_url}: {body}") from exc
        except urllib.error.URLError as exc:
            if attempt < max_attempts:
                time.sleep(min(5 * attempt, 15))
                continue
            raise RuntimeError(f"Massive API fetch failed for {path_or_url}: {exc}") from exc
    raise RuntimeError(f"Massive API fetch failed for {path_or_url}: exhausted attempts")


def _eodhs_api_key() -> str:
    key = _env_secret("EODHS_API_KEY", "EODHD_API_KEY")
    if not key:
        raise RuntimeError("EODHS_API_KEY/EODHD_API_KEY is not set; add it to Hermes .env and reload before using EODHS/EODHD fallback")
    return key


def _eodhs_get_json(path: str, params: dict[str, object] | None = None, *, timeout: int = 30) -> list | dict:
    params = dict(params or {})
    params.setdefault("api_token", _eodhs_api_key())
    params.setdefault("fmt", "json")
    url = EODHS_BASE_URL.rstrip("/") + "/" + path.lstrip("/") + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "Hermes-Wolfy-EOD/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"EODHS/EODHD API HTTP {exc.code} for {path}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"EODHS/EODHD API fetch failed for {path}: {exc}") from exc


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
          detail jsonb,
          source text
        )
        """
    )
    # Compatibility aliases for read-only ops probes.  Canonical EOD code uses
    # runs.started/runs.finished, but operational diagnostics often expect the
    # agent-ledger names started_at/completed_at and a feature-run projection.
    conn.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS started_at timestamptz")
    conn.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS completed_at timestamptz")
    conn.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS source text")
    conn.execute("UPDATE runs SET started_at=started WHERE started_at IS NULL AND started IS NOT NULL")
    conn.execute("UPDATE runs SET completed_at=finished WHERE completed_at IS NULL AND finished IS NOT NULL")
    conn.execute("UPDATE runs SET source=NULLIF(detail->>'source', '') WHERE source IS NULL AND detail ? 'source'")
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION wolfy_sync_runs_aliases()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.started_at IS NULL THEN
            NEW.started_at := NEW.started;
          END IF;
          IF NEW.completed_at IS NULL THEN
            NEW.completed_at := NEW.finished;
          END IF;
          IF NEW.source IS NULL THEN
            NEW.source := NULLIF(NEW.detail->>'source', '');
          END IF;
          RETURN NEW;
        END;
        $$;
        """
    )
    conn.execute("DROP TRIGGER IF EXISTS trg_runs_aliases_biu ON runs")
    conn.execute(
        """
        CREATE TRIGGER trg_runs_aliases_biu
          BEFORE INSERT OR UPDATE OF started, finished, started_at, completed_at, detail, source ON runs
          FOR EACH ROW EXECUTE FUNCTION wolfy_sync_runs_aliases()
        """
    )
    conn.execute(
        """
        DROP VIEW IF EXISTS eod_feature_runs;
        CREATE VIEW eod_feature_runs AS
        SELECT
          id,
          job,
          started,
          finished,
          started_at,
          completed_at,
          status,
          source,
          detail,
          NULLIF(detail->>'bars_loaded', '')::integer AS bars_loaded,
          NULLIF(detail->>'feature_rows_upserted', '')::integer AS feature_rows_upserted,
          NULLIF(detail->>'tickers_processed', '')::integer AS tickers_processed
        FROM runs
        WHERE job LIKE 'eod%' OR job LIKE 'feature%'
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_job_started ON runs(job, started DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_status_started ON runs(status, started DESC)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS universe_symbols (
          symbol text PRIMARY KEY,
          name text,
          source text NOT NULL,
          sector text,
          is_etf boolean NOT NULL DEFAULT false,
          last_seen timestamptz NOT NULL DEFAULT now(),
          active boolean NOT NULL DEFAULT true
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_universe_symbols_active_source ON universe_symbols(active, source)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_universe_symbols_etf ON universe_symbols(is_etf, active)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS price_data_quality_events (
          id serial PRIMARY KEY,
          run_at timestamptz NOT NULL DEFAULT now(),
          as_of date NOT NULL,
          ticker text,
          severity text NOT NULL,
          source text NOT NULL,
          reason text NOT NULL,
          detail jsonb NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_price_data_quality_events_as_of ON price_data_quality_events(as_of, severity, ticker)")


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


def fetch_massive_reference_symbols(*, types: Sequence[str] = ("CS", "ETF"), max_pages: int | None = None, page_limit: int = 1000) -> list[dict]:
    """Fetch active U.S. stock/common-share and ETF reference records from Massive."""
    records: list[dict] = []
    page_count = 0
    for ticker_type in types:
        next_url: str | None = None
        while True:
            payload = _massive_get_json(
                next_url or "/v3/reference/tickers",
                {"market": "stocks", "active": "true", "type": ticker_type, "limit": page_limit, "sort": "ticker"},
            )
            records.extend(payload.get("results") or [])
            page_count += 1
            if max_pages is not None and page_count >= max_pages:
                return records
            next_url = payload.get("next_url")
            if not next_url:
                break
    return records


def store_massive_reference_symbols(conn, records: Sequence[dict], *, source: str = "massive-reference") -> int:
    ensure_eod_feature_schema(conn)
    upserted = 0
    for rec in records:
        symbol = str(rec.get("ticker") or "").upper().strip()
        if not symbol:
            continue
        ticker_type = str(rec.get("type") or "").upper()
        conn.execute(
            """
            INSERT INTO universe_symbols(symbol, name, source, sector, is_etf, last_seen, active)
            VALUES (%s,%s,%s,%s,%s,now(),%s)
            ON CONFLICT (symbol) DO UPDATE SET
              name=COALESCE(EXCLUDED.name, universe_symbols.name),
              source=CASE
                WHEN position(EXCLUDED.source in universe_symbols.source) > 0 THEN universe_symbols.source
                ELSE universe_symbols.source || ',' || EXCLUDED.source
              END,
              sector=COALESCE(EXCLUDED.sector, universe_symbols.sector),
              is_etf=(universe_symbols.is_etf OR EXCLUDED.is_etf),
              last_seen=now(),
              active=EXCLUDED.active
            """,
            (symbol, rec.get("name"), source, rec.get("sic_description"), ticker_type == "ETF", bool(rec.get("active", True))),
        )
        upserted += 1
    return upserted


def refresh_massive_reference_universe(conn, *, types: Sequence[str] = ("CS", "ETF"), max_pages: int | None = None) -> dict:
    records = fetch_massive_reference_symbols(types=types, max_pages=max_pages)
    stored = store_massive_reference_symbols(conn, records)
    return {"source": "massive-reference", "records_fetched": len(records), "records_upserted": stored, "types": list(types)}


def fetch_massive_eod_bars(
    tickers: Sequence[str],
    *,
    start_dt: date,
    end_dt: date,
    adjusted: bool = True,
    pause_seconds: float = 0.0,
) -> list[PriceBar]:
    """Fetch adjusted daily aggregate bars from Massive for deterministic EOD ingest."""
    bars: list[PriceBar] = []
    for ticker in tickers:
        symbol = ticker.upper().strip()
        if not symbol:
            continue
        payload = _massive_get_json(
            f"/v2/aggs/ticker/{urllib.parse.quote(symbol)}/range/1/day/{start_dt.isoformat()}/{end_dt.isoformat()}",
            {"adjusted": str(adjusted).lower(), "sort": "asc", "limit": 50000},
        )
        for rec in payload.get("results") or []:
            if not all(k in rec for k in ("t", "o", "h", "l", "c", "v")):
                continue
            bars.append(
                PriceBar(
                    symbol,
                    datetime.fromtimestamp(int(rec["t"]) / 1000, tz=timezone.utc).date(),
                    _q(Decimal(str(rec["o"])), "0.0001"),
                    _q(Decimal(str(rec["h"])), "0.0001"),
                    _q(Decimal(str(rec["l"])), "0.0001"),
                    _q(Decimal(str(rec["c"])), "0.0001"),
                    int(rec["v"]),
                )
            )
        if pause_seconds:
            time.sleep(pause_seconds)
    return bars


def fetch_eodhs_eod_bars(
    tickers: Sequence[str],
    *,
    start_dt: date,
    end_dt: date,
    exchange_suffix: str = "US",
    pause_seconds: float = 1.0,
    max_tickers: int = 5,
) -> list[PriceBar]:
    """Fetch EODHS/EODHD daily bars as a conservative free-tier fallback.

    This is intentionally capped; Massive remains the primary EOD source.
    EODHS free tier is useful for small fallback/cross-check pulls, not bulk daily refreshes.
    """
    selected = [ticker.upper().strip() for ticker in tickers if ticker.strip()][:max_tickers]
    bars: list[PriceBar] = []
    for symbol in selected:
        eod_symbol = symbol if "." in symbol else f"{symbol}.{exchange_suffix}"
        payload = _eodhs_get_json(
            f"/api/eod/{urllib.parse.quote(eod_symbol)}",
            {"from": start_dt.isoformat(), "to": end_dt.isoformat(), "period": "d"},
        )
        if not isinstance(payload, list):
            continue
        for rec in payload:
            if not all(k in rec for k in ("date", "open", "high", "low", "close", "volume")):
                continue
            # Prefer adjusted_close for close so split/dividend-adjusted trend checks are less distorted;
            # OHLC remains vendor raw and this source is only fallback/cross-check.
            close_value = rec.get("adjusted_close") or rec.get("close")
            bars.append(
                PriceBar(
                    symbol,
                    date.fromisoformat(str(rec["date"])),
                    _q(Decimal(str(rec["open"])), "0.0001"),
                    _q(Decimal(str(rec["high"])), "0.0001"),
                    _q(Decimal(str(rec["low"])), "0.0001"),
                    _q(Decimal(str(close_value)), "0.0001"),
                    int(rec.get("volume") or 0),
                )
            )
        if pause_seconds:
            time.sleep(pause_seconds)
    return bars


def _massive_paginated_results(path: str, params: dict[str, object], *, max_pages: int | None = None) -> list[dict]:
    results: list[dict] = []
    next_url: str | None = None
    pages = 0
    while True:
        payload = _massive_get_json(next_url or path, params)
        results.extend(payload.get("results") or [])
        pages += 1
        if max_pages is not None and pages >= max_pages:
            break
        next_url = payload.get("next_url")
        if not next_url:
            break
    return results


def fetch_massive_corporate_actions(tickers: Sequence[str], *, since: date, until: date) -> dict[str, list[dict]]:
    """Fetch recent corporate actions in bulk and map them to requested tickers."""
    wanted = {ticker.upper() for ticker in tickers}
    actions: dict[str, list[dict]] = {ticker: [] for ticker in wanted}
    splits = _massive_paginated_results(
        "/v3/reference/splits",
        {"execution_date.gte": since.isoformat(), "execution_date.lte": until.isoformat(), "limit": 1000, "sort": "execution_date"},
        max_pages=5,
    )
    dividends = _massive_paginated_results(
        "/v3/reference/dividends",
        {"ex_dividend_date.gte": since.isoformat(), "ex_dividend_date.lte": until.isoformat(), "limit": 1000, "sort": "ex_dividend_date"},
        max_pages=5,
    )
    for row in splits:
        ticker = str(row.get("ticker") or "").upper()
        if ticker in wanted:
            actions[ticker].append({"kind": "split", **row})
    for row in dividends:
        ticker = str(row.get("ticker") or "").upper()
        if ticker in wanted:
            actions[ticker].append({"kind": "dividend", **row})
    return actions


def validate_price_data_quality(
    conn,
    *,
    tickers: Sequence[str],
    source: str,
    as_of: date | None = None,
    max_stale_days: int = 5,
    corporate_action_lookback_days: int = 45,
    check_corporate_actions: bool = True,
) -> dict:
    ensure_eod_feature_schema(conn)
    as_of = as_of or date.today()
    ticker_list = [ticker.upper() for ticker in tickers]
    rows = conn.execute(
        """
        SELECT ticker, max(dt) AS latest_dt, count(*) AS bars
        FROM prices
        WHERE ticker = ANY(%s)
        GROUP BY ticker
        """,
        (ticker_list,),
    ).fetchall()
    by_ticker = {row[0]: {"latest_dt": row[1], "bars": row[2]} for row in rows}
    events: list[dict] = []
    for ticker in ticker_list:
        info = by_ticker.get(ticker)
        if not info:
            events.append({"ticker": ticker, "severity": "blocker", "reason": "missing_price_history", "detail": {}})
            continue
        latest_dt = info["latest_dt"]
        stale_days = (as_of - latest_dt).days
        if stale_days > max_stale_days:
            events.append({"ticker": ticker, "severity": "blocker", "reason": "stale_price_history", "detail": {"latest_dt": latest_dt.isoformat(), "stale_days": stale_days, "bars": int(info["bars"])}})
    corporate_actions: dict[str, list[dict]] = {}
    if check_corporate_actions and ticker_list:
        since = as_of - timedelta(days=corporate_action_lookback_days)
        corporate_actions = fetch_massive_corporate_actions(ticker_list, since=since, until=as_of)
        for ticker, action_rows in corporate_actions.items():
            splits = [row for row in action_rows if row.get("kind") == "split"]
            if splits:
                events.append({"ticker": ticker, "severity": "review", "reason": "recent_split_requires_adjustment_audit", "detail": {"splits": splits[:5]}})
    for event in events:
        conn.execute(
            """
            INSERT INTO price_data_quality_events(as_of, ticker, severity, source, reason, detail)
            VALUES (%s,%s,%s,%s,%s,%s::jsonb)
            """,
            (as_of, event.get("ticker"), event["severity"], source, event["reason"], json.dumps(event.get("detail") or {}, sort_keys=True, default=str)),
        )
    return {
        "as_of": as_of.isoformat(),
        "source": source,
        "tickers_checked": len(ticker_list),
        "events_recorded": len(events),
        "blockers": sum(1 for e in events if e["severity"] == "blocker"),
        "reviews": sum(1 for e in events if e["severity"] == "review"),
        "events": events,
    }


def _price_history_state(conn, tickers: Sequence[str]) -> dict[str, dict[str, object]]:
    rows = conn.execute(
        """
        SELECT ticker, max(dt) AS latest_dt, count(*) AS bars
        FROM prices
        WHERE ticker = ANY(%s)
        GROUP BY ticker
        """,
        ([ticker.upper() for ticker in tickers],),
    ).fetchall()
    return {row[0]: {"latest_dt": row[1], "bars": int(row[2])} for row in rows}


def _fetch_incremental_massive_bars(
    conn,
    *,
    tickers: Sequence[str],
    days: int,
    adjusted: bool,
    pause_seconds: float,
    min_history_bars: int,
    end_dt: date | None = None,
) -> tuple[list[PriceBar], list[dict]]:
    end_dt = end_dt or _default_massive_eod_end_dt()
    full_start_dt = end_dt - timedelta(days=days)
    state = _price_history_state(conn, tickers)
    bars: list[PriceBar] = []
    fetch_plan: list[dict] = []
    for ticker in [ticker.upper() for ticker in tickers]:
        info = state.get(ticker)
        if not info or int(info.get("bars") or 0) < min_history_bars:
            start_dt = full_start_dt
            reason = "bootstrap_or_insufficient_history"
        else:
            latest_dt = info.get("latest_dt")
            start_dt = latest_dt + timedelta(days=1) if latest_dt else full_start_dt
            reason = "incremental_missing_days"
        if start_dt > end_dt:
            fetch_plan.append({"ticker": ticker, "skipped": True, "reason": "already_current", "latest_dt": str(info.get("latest_dt")) if info else None})
            continue
        fetched = fetch_massive_eod_bars([ticker], start_dt=start_dt, end_dt=end_dt, adjusted=adjusted, pause_seconds=pause_seconds)
        bars.extend(fetched)
        fetch_plan.append({"ticker": ticker, "skipped": False, "reason": reason, "start_dt": start_dt.isoformat(), "end_dt": end_dt.isoformat(), "bars_fetched": len(fetched)})
    return bars, fetch_plan


def massive_ingest(
    *,
    tickers: Sequence[str],
    days: int = 730,
    dsn: str = DEFAULT_DSN,
    min_dollar_vol: Decimal = DEFAULT_MIN_DOLLAR_VOL,
    refresh_universe: bool = False,
    validate: bool = True,
    adjusted: bool = True,
    pause_seconds: float = 0.0,
    min_history_bars: int = 500,
    eodhs_fallback_max_tickers: int = 0,
    end_dt: date | None = None,
) -> dict:
    import psycopg

    with psycopg.connect(dsn) as conn:
        universe_result = refresh_massive_reference_universe(conn) if refresh_universe else None
        bars, fetch_plan = _fetch_incremental_massive_bars(
            conn,
            tickers=tickers,
            days=days,
            adjusted=adjusted,
            pause_seconds=pause_seconds,
            min_history_bars=min_history_bars,
            end_dt=end_dt,
        )
        eodhs_fallback = None
        if eodhs_fallback_max_tickers > 0:
            missing = [item["ticker"] for item in fetch_plan if not item.get("skipped") and item.get("bars_fetched") == 0]
            if missing:
                fallback_end_dt = end_dt or _default_massive_eod_end_dt()
                fallback_bars = fetch_eodhs_eod_bars(
                    missing,
                    start_dt=fallback_end_dt - timedelta(days=min(days, 30)),
                    end_dt=fallback_end_dt,
                    max_tickers=eodhs_fallback_max_tickers,
                )
                bars.extend(fallback_bars)
                eodhs_fallback = {"requested_tickers": missing[:eodhs_fallback_max_tickers], "bars_fetched": len(fallback_bars), "max_tickers": eodhs_fallback_max_tickers}
        ingest_run = ingest_price_bars(conn, bars, source="massive-adjusted-eod" if adjusted else "massive-raw-eod") if bars else None
        feature_run = compute_and_store_features(conn, tickers=tickers, min_dollar_vol=min_dollar_vol)
        validation = validate_price_data_quality(conn, tickers=tickers, source="massive-adjusted-eod", check_corporate_actions=bool(bars)) if validate else None
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
        "source": "massive-adjusted-eod" if adjusted else "massive-raw-eod",
        "tickers": [ticker.upper() for ticker in tickers],
        "bars_fetched": len(bars),
        "fetch_plan": fetch_plan,
        "ingest_run_id": ingest_run,
        "feature_run_id": feature_run,
        "universe_refresh": universe_result,
        "eodhs_fallback": eodhs_fallback,
        "validation": validation,
        "latest": [{"ticker": row[0], "latest_dt": row[1].isoformat(), "bars": row[2]} for row in latest],
    }

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
    parser.add_argument("--days", type=int, default=730, help="Daily bars lookback")
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    parser.add_argument("--min-dollar-vol", default=str(DEFAULT_MIN_DOLLAR_VOL))
    parser.add_argument("--source", choices=["massive", "eodhs", "yahoo"], default="massive", help="Preferred price source; yahoo/eodhs remain fallback/smoke only")
    parser.add_argument("--refresh-universe", action="store_true", help="Refresh Massive active U.S. stock/ETF reference universe before ingest")
    parser.add_argument("--no-validate", action="store_true", help="Skip freshness/corporate-action data-quality validation")
    parser.add_argument("--raw", action="store_true", help="Request raw Massive bars instead of adjusted bars")
    parser.add_argument("--pause-seconds", type=float, default=0.0, help="Optional pause between API ticker calls")
    parser.add_argument("--min-history-bars", type=int, default=500, help="Only bootstrap full Massive history below this stored bar count; otherwise fetch missing days only")
    parser.add_argument("--eodhs-fallback-max-tickers", type=int, default=0, help="Conservative EODHS fallback cap for Massive missing-ticker retries; 0 disables")
    parser.add_argument("--end-date", default=None, help="Override Massive/EODHS end date (YYYY-MM-DD); defaults to previous business day unless WOLFY_MASSIVE_ALLOW_CURRENT_DAY=1")
    args = parser.parse_args(argv)
    tickers = [ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()]
    end_dt = _parse_date(args.end_date)
    if args.source == "massive":
        result = massive_ingest(
            tickers=tickers,
            days=args.days,
            dsn=args.dsn,
            min_dollar_vol=Decimal(args.min_dollar_vol),
            refresh_universe=args.refresh_universe,
            validate=not args.no_validate,
            adjusted=not args.raw,
            pause_seconds=args.pause_seconds,
            min_history_bars=args.min_history_bars,
            eodhs_fallback_max_tickers=args.eodhs_fallback_max_tickers,
            end_dt=end_dt,
        )
    elif args.source == "eodhs":
        fallback_end_dt = end_dt or _default_massive_eod_end_dt()
        start_dt = fallback_end_dt - timedelta(days=args.days)
        bars = fetch_eodhs_eod_bars(tickers, start_dt=start_dt, end_dt=fallback_end_dt, pause_seconds=args.pause_seconds, max_tickers=min(len(tickers), 5))
        result = {"source": "eodhs-eod-fallback", "tickers": tickers[:5], "bars_fetched": len(bars), "writes": False, "note": "EODHS free-tier source is capped and does not write by default; Massive remains primary."}
    else:
        result = smoke_ingest(tickers=tickers, days=args.days, dsn=args.dsn, min_dollar_vol=Decimal(args.min_dollar_vol))
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
