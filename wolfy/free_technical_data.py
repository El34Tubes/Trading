#!/usr/bin/env python3
"""Free technical and market-structure data for Wolfy's EOD paper engine.

Only public/free sources are supported here. Observations preserve source and
availability timestamps so historical joins cannot see information early.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Mapping, Sequence

from eod_price_features import PriceBar

DEFAULT_DSN = os.environ.get("WOLFY_POSTGRES_DSN", "dbname=wolfy user=root host=/var/run/postgresql")
CBOE_VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
FINRA_DAILY_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{yyyymmdd}.txt"
CBOE_OPTIONS_DAILY_URL = "https://www.cboe.com/markets/us/options/market-statistics/daily"
TREASURY_CURVE_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv"
SECTOR_ETFS = {
    "Communication Services": "XLC",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Industrials": "XLI",
    "Information Technology": "XLK",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
}


def _dec(value: object | None) -> Decimal | None:
    if value in (None, "", "."):
        return None
    return Decimal(str(value).replace(",", "").strip())


def _q(value: Decimal | None, places: str = "0.0001") -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP).normalize()


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    return sum(values, Decimal("0")) / Decimal(len(values)) if values else None


def _population_std(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    mean = _mean(values)
    assert mean is not None
    variance = sum(((value - mean) ** 2 for value in values), Decimal("0")) / Decimal(len(values))
    return Decimal(str(math.sqrt(float(variance))))


def _percentile_rank(values: Sequence[Decimal], current: Decimal) -> Decimal | None:
    if not values:
        return None
    return Decimal(sum(1 for value in values if value <= current)) / Decimal(len(values))


@dataclass(frozen=True)
class OptionsTechnicalFeature:
    ticker: str
    dt: date
    atr_pct: Decimal | None
    realized_vol_annualized: Decimal | None
    pre_breakout_contraction_ratio: Decimal | None
    range_expansion_ratio: Decimal | None
    close_location_value: Decimal | None
    upper_wick_ratio: Decimal | None
    volume_percentile: Decimal | None
    options_volatility_setup: bool
    high_volatility_allowed: bool = True


def compute_options_oriented_features(
    bars: Iterable[PriceBar],
    *,
    realized_vol_window: int = 20,
    contraction_window: int = 5,
    baseline_window: int = 20,
    volume_window: int = 63,
) -> list[OptionsTechnicalFeature]:
    """Calculate volatility setup quality without imposing a maximum volatility cap.

    A qualified volatility setup requires contraction immediately before the
    current bar, current range expansion, a close in the upper 30% of the bar,
    and above-median volume. High realized volatility is recorded but allowed.
    """
    if min(realized_vol_window, contraction_window, baseline_window, volume_window) <= 0:
        raise ValueError("technical feature windows must be positive")
    grouped: dict[str, list[PriceBar]] = {}
    for bar in bars:
        grouped.setdefault(bar.ticker.upper(), []).append(bar)
    output: list[OptionsTechnicalFeature] = []
    annualizer = Decimal(str(math.sqrt(252)))
    for ticker in sorted(grouped):
        history: list[PriceBar] = []
        closes: list[Decimal] = []
        ranges: list[Decimal] = []
        returns: list[Decimal] = []
        volumes: list[Decimal] = []
        for bar in sorted(grouped[ticker], key=lambda item: item.dt):
            close = _dec(bar.close)
            high = _dec(bar.high)
            low = _dec(bar.low)
            if close is None or high is None or low is None:
                raise ValueError("close/high/low are required")
            current_range = max(high - low, Decimal("0"))
            if closes and closes[-1] != 0 and close > 0 and closes[-1] > 0:
                returns.append(Decimal(str(math.log(float(close / closes[-1])))))
            closes.append(close)
            ranges.append(current_range)
            volumes.append(Decimal(int(bar.volume or 0)))

            atr_pct = None
            if len(ranges) >= baseline_window:
                atr = _mean(ranges[-baseline_window:])
                atr_pct = _q(atr / close) if atr is not None and close else None
            realized = None
            if len(returns) >= realized_vol_window:
                std = _population_std(returns[-realized_vol_window:])
                realized = _q(std * annualizer) if std is not None else None

            contraction = None
            range_expansion = None
            # Exclude today's bar from contraction/baseline to avoid lookahead
            # and to explicitly model compression followed by expansion.
            prior_ranges = ranges[:-1]
            if len(prior_ranges) >= max(contraction_window, baseline_window):
                recent_mean = _mean(prior_ranges[-contraction_window:])
                baseline_mean = _mean(prior_ranges[-baseline_window:])
                contraction = _q(recent_mean / baseline_mean) if recent_mean is not None and baseline_mean else None
                range_expansion = _q(current_range / recent_mean) if recent_mean else None

            clv = _q((close - low) / current_range) if current_range else None
            upper_wick = _q((high - close) / current_range) if current_range else None
            volume_pct = _q(_percentile_rank(volumes[-volume_window:], volumes[-1]))
            setup = bool(
                contraction is not None
                and contraction <= Decimal("0.75")
                and range_expansion is not None
                and range_expansion >= Decimal("1.50")
                and clv is not None
                and clv >= Decimal("0.70")
                and volume_pct is not None
                and volume_pct >= Decimal("0.50")
            )
            output.append(OptionsTechnicalFeature(ticker, bar.dt, atr_pct, realized, contraction, range_expansion, clv, upper_wick, volume_pct, setup, True))
            history.append(bar)
    return output


def compute_point_in_time_breadth(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    eligible = [row for row in rows if row.get("eligible", True)]
    count = len(eligible)
    advancers = sum(1 for row in eligible if _dec(row.get("close")) is not None and _dec(row.get("previous_close")) is not None and _dec(row.get("close")) > _dec(row.get("previous_close")))
    decliners = sum(1 for row in eligible if _dec(row.get("close")) is not None and _dec(row.get("previous_close")) is not None and _dec(row.get("close")) < _dec(row.get("previous_close")))

    def fraction(predicate) -> Decimal | None:
        return _q(Decimal(sum(1 for row in eligible if predicate(row))) / Decimal(count)) if count else None

    total_volume = sum((_dec(row.get("volume")) or Decimal("0") for row in eligible), Decimal("0"))
    up_volume = sum((_dec(row.get("volume")) or Decimal("0") for row in eligible if (_dec(row.get("close")) or 0) > (_dec(row.get("previous_close")) or 0)), Decimal("0"))
    return {
        "eligible_count": count,
        "advancers": advancers,
        "decliners": decliners,
        "advance_decline_ratio": _q(Decimal(advancers) / Decimal(max(decliners, 1))),
        "pct_above_20dma": fraction(lambda row: _dec(row.get("sma20")) is not None and _dec(row.get("close")) > _dec(row.get("sma20"))),
        "pct_above_50dma": fraction(lambda row: _dec(row.get("sma50")) is not None and _dec(row.get("close")) > _dec(row.get("sma50"))),
        "pct_above_200dma": fraction(lambda row: _dec(row.get("sma200")) is not None and _dec(row.get("close")) > _dec(row.get("sma200"))),
        "new_20d_high_fraction": fraction(lambda row: _dec(row.get("high20")) is not None and _dec(row.get("close")) >= _dec(row.get("high20"))),
        "new_20d_low_fraction": fraction(lambda row: _dec(row.get("low20")) is not None and _dec(row.get("close")) <= _dec(row.get("low20"))),
        "up_volume_fraction": _q(up_volume / total_volume) if total_volume else None,
    }


def parse_cboe_vix_csv(text: str) -> list[dict[str, object]]:
    result = []
    for row in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        if not row.get("DATE"):
            continue
        result.append({
            "observation_date": datetime.strptime(row["DATE"], "%m/%d/%Y").date(),
            "series": "VIX",
            "open": _dec(row.get("OPEN")),
            "high": _dec(row.get("HIGH")),
            "low": _dec(row.get("LOW")),
            "value": _dec(row.get("CLOSE")),
        })
    return result


def parse_cboe_options_daily_html(text: str, *, observation_date: date) -> list[dict[str, object]]:
    """Extract the documented aggregate ratios embedded in Cboe's rendered page."""
    import re

    normalized = text.replace('\\"', '"')
    supported = {
        "TOTAL PUT/CALL RATIO": "CBOE_TOTAL_PUT_CALL",
        "INDEX PUT/CALL RATIO": "CBOE_INDEX_PUT_CALL",
        "EXCHANGE TRADED PRODUCTS PUT/CALL RATIO": "CBOE_ETP_PUT_CALL",
        "EQUITY PUT/CALL RATIO": "CBOE_EQUITY_PUT_CALL",
        "CBOE VOLATILITY INDEX (VIX) PUT/CALL RATIO": "CBOE_VIX_PUT_CALL",
        "SPX + SPXW PUT/CALL RATIO": "CBOE_SPX_PUT_CALL",
    }
    found: dict[str, Decimal] = {}
    for name, value in re.findall(r'"name"\s*:\s*"([^"]+)"\s*,\s*"value"\s*:\s*"([0-9.]+)"', normalized):
        series = supported.get(name)
        if series:
            found[series] = Decimal(value)
    return [{"observation_date": observation_date, "series": series, "value": value} for series, value in found.items()]


def compute_sector_relative_strength(
    *,
    ticker: str,
    sector: str | None,
    stock_return: Decimal,
    sector_return: Decimal | None,
    spy_return: Decimal,
) -> dict[str, object]:
    sector_etf = SECTOR_ETFS.get(sector or "")
    stock_vs_sector = _q(stock_return - sector_return) if sector_return is not None else None
    sector_vs_spy = _q(sector_return - spy_return) if sector_return is not None else None
    return {
        "ticker": ticker.upper(),
        "sector": sector,
        "sector_etf": sector_etf,
        "stock_vs_sector": stock_vs_sector,
        "sector_vs_spy": sector_vs_spy,
        "sector_confirmation": bool(stock_vs_sector is not None and stock_vs_sector > 0 and sector_vs_spy is not None and sector_vs_spy > 0),
    }


def parse_finra_short_volume(text: str) -> list[dict[str, object]]:
    result = []
    for row in csv.DictReader(io.StringIO(text), delimiter="|"):
        if not row.get("Date") or not row.get("Symbol"):
            continue
        short = _dec(row.get("ShortVolume")) or Decimal("0")
        exempt = _dec(row.get("ShortExemptVolume")) or Decimal("0")
        total = _dec(row.get("TotalVolume")) or Decimal("0")
        result.append({
            "observation_date": datetime.strptime(row["Date"], "%Y%m%d").date(),
            "ticker": row["Symbol"].upper(),
            "short_volume": short,
            "short_exempt_volume": exempt,
            "total_volume": total,
            "market": row.get("Market"),
            "finra_off_exchange_short_fraction": _q(short / total) if total else None,
            "short_exempt_fraction": _q(exempt / total) if total else None,
            "scope": "finra_reported_public_trades_not_consolidated_market",
        })
    return result


def parse_nasdaq_short_interest(payload: Mapping[str, object], *, published_at: date | datetime) -> list[dict[str, object]]:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return []
    ticker = str(data.get("symbol") or "").upper()
    table = data.get("shortInterestTable")
    if not ticker or not isinstance(table, Mapping):
        return []
    result = []
    for row in table.get("rows") or []:
        if not isinstance(row, Mapping) or not row.get("settlementDate"):
            continue
        result.append({
            "ticker": ticker,
            "settlement_date": datetime.strptime(str(row["settlementDate"]), "%m/%d/%Y").date(),
            "available_at": published_at,
            "short_interest": _dec(row.get("interest")),
            "average_daily_share_volume": _dec(row.get("avgDailyShareVolume")),
            "days_to_cover": _dec(row.get("daysToCover")),
        })
    return result


def parse_treasury_curve_csv(text: str) -> list[dict[str, object]]:
    result = []
    for row in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        if not row.get("Date"):
            continue
        two = _dec(row.get("2 Yr"))
        ten = _dec(row.get("10 Yr"))
        result.append({
            "observation_date": datetime.strptime(row["Date"], "%m/%d/%Y").date(),
            "two_year": two,
            "ten_year": ten,
            "ten_minus_two": _q(ten - two) if ten is not None and two is not None else None,
        })
    return result


def ensure_free_technical_schema(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS technical_market_series (
          series text NOT NULL,
          observation_date date NOT NULL,
          available_at timestamptz NOT NULL,
          value numeric,
          open numeric,
          high numeric,
          low numeric,
          source text NOT NULL,
          source_url text,
          license_class text NOT NULL DEFAULT 'free_public_terms_apply',
          ingested_at timestamptz NOT NULL DEFAULT now(),
          raw jsonb NOT NULL DEFAULT '{}'::jsonb,
          PRIMARY KEY(series, observation_date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_technical_market_series_available ON technical_market_series(series, available_at DESC)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS finra_short_volume (
          ticker text NOT NULL,
          observation_date date NOT NULL,
          available_at timestamptz NOT NULL,
          short_volume numeric,
          short_exempt_volume numeric,
          total_volume numeric,
          short_fraction numeric,
          short_exempt_fraction numeric,
          market text,
          scope text NOT NULL,
          source text NOT NULL,
          source_url text,
          ingested_at timestamptz NOT NULL DEFAULT now(),
          raw jsonb NOT NULL DEFAULT '{}'::jsonb,
          PRIMARY KEY(ticker, observation_date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_finra_short_volume_available ON finra_short_volume(observation_date, available_at, ticker)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nasdaq_short_interest (
          ticker text NOT NULL,
          settlement_date date NOT NULL,
          available_at timestamptz NOT NULL,
          short_interest numeric,
          average_daily_share_volume numeric,
          days_to_cover numeric,
          source text NOT NULL,
          source_url text,
          ingested_at timestamptz NOT NULL DEFAULT now(),
          raw jsonb NOT NULL DEFAULT '{}'::jsonb,
          PRIMARY KEY(ticker, settlement_date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nasdaq_short_interest_available ON nasdaq_short_interest(ticker, available_at DESC)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS options_technical_features (
          ticker text NOT NULL,
          dt date NOT NULL,
          atr_pct numeric,
          realized_vol_annualized numeric,
          pre_breakout_contraction_ratio numeric,
          range_expansion_ratio numeric,
          close_location_value numeric,
          upper_wick_ratio numeric,
          volume_percentile numeric,
          options_volatility_setup boolean NOT NULL,
          high_volatility_allowed boolean NOT NULL DEFAULT true,
          transformation_version text NOT NULL DEFAULT 'options-vol-v1',
          PRIMARY KEY(ticker, dt)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_breadth (
          dt date PRIMARY KEY,
          eligible_count integer NOT NULL,
          advancers integer,
          decliners integer,
          advance_decline_ratio numeric,
          pct_above_20dma numeric,
          pct_above_50dma numeric,
          pct_above_200dma numeric,
          new_20d_high_fraction numeric,
          new_20d_low_fraction numeric,
          up_volume_fraction numeric,
          universe_definition text NOT NULL,
          transformation_version text NOT NULL DEFAULT 'breadth-v1',
          ingested_at timestamptz NOT NULL DEFAULT now()
        )
    """)


def _availability(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.combine(value, time(23, 59), tzinfo=timezone.utc)


def store_market_series(conn, rows: Sequence[Mapping[str, object]], *, source: str, available_at: date | datetime, source_url: str | None = None) -> int:
    ensure_free_technical_schema(conn)
    available = _availability(available_at)
    for row in rows:
        row_available = _availability(row.get("available_at", available))
        conn.execute("""
            INSERT INTO technical_market_series(series,observation_date,available_at,value,open,high,low,source,source_url,raw)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
            ON CONFLICT(series,observation_date) DO UPDATE SET
              available_at=EXCLUDED.available_at,value=EXCLUDED.value,open=EXCLUDED.open,
              high=EXCLUDED.high,low=EXCLUDED.low,source=EXCLUDED.source,
              source_url=EXCLUDED.source_url,ingested_at=now(),raw=EXCLUDED.raw
        """, (row["series"], row["observation_date"], row_available, row.get("value"), row.get("open"), row.get("high"), row.get("low"), source, source_url, json.dumps(row, default=str, sort_keys=True)))
    return len(rows)


def store_short_volume(conn, rows: Sequence[Mapping[str, object]], *, source: str, available_at: date | datetime, source_url: str | None = None) -> int:
    ensure_free_technical_schema(conn)
    available = _availability(available_at)
    for row in rows:
        row_available = _availability(row.get("available_at", available))
        conn.execute("""
            INSERT INTO finra_short_volume(ticker,observation_date,available_at,short_volume,short_exempt_volume,total_volume,short_fraction,short_exempt_fraction,market,scope,source,source_url,raw)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
            ON CONFLICT(ticker,observation_date) DO UPDATE SET
              available_at=EXCLUDED.available_at,short_volume=EXCLUDED.short_volume,
              short_exempt_volume=EXCLUDED.short_exempt_volume,total_volume=EXCLUDED.total_volume,
              short_fraction=EXCLUDED.short_fraction,short_exempt_fraction=EXCLUDED.short_exempt_fraction,
              market=EXCLUDED.market,scope=EXCLUDED.scope,source=EXCLUDED.source,
              source_url=EXCLUDED.source_url,ingested_at=now(),raw=EXCLUDED.raw
        """, (row["ticker"], row["observation_date"], row_available, row.get("short_volume"), row.get("short_exempt_volume"), row.get("total_volume"), row.get("finra_off_exchange_short_fraction"), row.get("short_exempt_fraction"), row.get("market"), row["scope"], source, source_url, json.dumps(row, default=str, sort_keys=True)))
    return len(rows)


def store_nasdaq_short_interest(conn, rows: Sequence[Mapping[str, object]], *, source: str, source_url: str | None = None) -> int:
    ensure_free_technical_schema(conn)
    for row in rows:
        available = _availability(row["available_at"])
        conn.execute("""
            INSERT INTO nasdaq_short_interest(ticker,settlement_date,available_at,short_interest,average_daily_share_volume,days_to_cover,source,source_url,raw)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
            ON CONFLICT(ticker,settlement_date) DO UPDATE SET
              available_at=EXCLUDED.available_at,short_interest=EXCLUDED.short_interest,
              average_daily_share_volume=EXCLUDED.average_daily_share_volume,days_to_cover=EXCLUDED.days_to_cover,
              source=EXCLUDED.source,source_url=EXCLUDED.source_url,ingested_at=now(),raw=EXCLUDED.raw
        """, (row["ticker"],row["settlement_date"],available,row.get("short_interest"),row.get("average_daily_share_volume"),row.get("days_to_cover"),source,source_url,json.dumps(row,default=str,sort_keys=True)))
    return len(rows)


def fetch_nasdaq_short_interest(tickers: Sequence[str], *, published_at: date | datetime, pause_seconds: float = 0.25) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for ticker in tickers:
        symbol = ticker.upper().strip()
        if not symbol:
            continue
        url = f"https://api.nasdaq.com/api/quote/{urllib.parse.quote(symbol)}/short-interest?assetclass=stocks"
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Hermes-Wolfy-Paper-Research/1.0", "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        rows.extend(parse_nasdaq_short_interest(payload, published_at=published_at))
        if pause_seconds:
            import time as _time
            _time.sleep(pause_seconds)
    return rows


def store_options_features(conn, rows: Sequence[OptionsTechnicalFeature]) -> int:
    ensure_free_technical_schema(conn)
    for row in rows:
        conn.execute("""
            INSERT INTO options_technical_features(ticker,dt,atr_pct,realized_vol_annualized,pre_breakout_contraction_ratio,range_expansion_ratio,close_location_value,upper_wick_ratio,volume_percentile,options_volatility_setup,high_volatility_allowed)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(ticker,dt) DO UPDATE SET
              atr_pct=EXCLUDED.atr_pct,realized_vol_annualized=EXCLUDED.realized_vol_annualized,
              pre_breakout_contraction_ratio=EXCLUDED.pre_breakout_contraction_ratio,
              range_expansion_ratio=EXCLUDED.range_expansion_ratio,close_location_value=EXCLUDED.close_location_value,
              upper_wick_ratio=EXCLUDED.upper_wick_ratio,volume_percentile=EXCLUDED.volume_percentile,
              options_volatility_setup=EXCLUDED.options_volatility_setup,high_volatility_allowed=EXCLUDED.high_volatility_allowed
        """, (row.ticker,row.dt,row.atr_pct,row.realized_vol_annualized,row.pre_breakout_contraction_ratio,row.range_expansion_ratio,row.close_location_value,row.upper_wick_ratio,row.volume_percentile,row.options_volatility_setup,row.high_volatility_allowed))
    return len(rows)


def compute_and_store_options_features(conn, *, tickers: Sequence[str], end_dt: date | None = None) -> int:
    ensure_free_technical_schema(conn)
    params: list[object] = [[ticker.upper() for ticker in tickers]]
    where = ["ticker=ANY(%s)"]
    if end_dt:
        where.append("dt<=%s")
        params.append(end_dt)
    sql = "SELECT ticker,dt,open,high,low,close,volume FROM prices WHERE " + " AND ".join(where) + " ORDER BY ticker,dt"
    bars = [PriceBar(*row) for row in conn.execute(sql, params).fetchall()]
    return store_options_features(conn, compute_options_oriented_features(bars))


def compute_and_store_breadth(conn, *, signal_dt: date) -> dict[str, object]:
    ensure_free_technical_schema(conn)
    rows = conn.execute("""
        SELECT u.symbol, p.close,
               lagp.close AS previous_close,
               avg20.sma20, avg50.sma50, avg200.sma200,
               hl.high20, hl.low20, p.volume,
               coalesce(u.active,true) AND coalesce(u.enabled,true) AS eligible
        FROM universe u
        JOIN prices p ON p.ticker=u.symbol AND p.dt=%s
        JOIN LATERAL (SELECT close FROM prices WHERE ticker=u.symbol AND dt<p.dt ORDER BY dt DESC LIMIT 1) lagp ON true
        LEFT JOIN LATERAL (SELECT avg(close) sma20 FROM (SELECT close FROM prices WHERE ticker=u.symbol AND dt<=p.dt ORDER BY dt DESC LIMIT 20) x) avg20 ON true
        LEFT JOIN LATERAL (SELECT avg(close) sma50 FROM (SELECT close FROM prices WHERE ticker=u.symbol AND dt<=p.dt ORDER BY dt DESC LIMIT 50) x) avg50 ON true
        LEFT JOIN LATERAL (SELECT avg(close) sma200 FROM (SELECT close FROM prices WHERE ticker=u.symbol AND dt<=p.dt ORDER BY dt DESC LIMIT 200) x) avg200 ON true
        LEFT JOIN LATERAL (SELECT max(high) high20,min(low) low20 FROM (SELECT high,low FROM prices WHERE ticker=u.symbol AND dt<=p.dt ORDER BY dt DESC LIMIT 20) x) hl ON true
    """, (signal_dt,)).fetchall()
    keys = ("ticker","close","previous_close","sma20","sma50","sma200","high20","low20","volume","eligible")
    breadth = compute_point_in_time_breadth([dict(zip(keys, row)) for row in rows])
    conn.execute("""
        INSERT INTO market_breadth(dt,eligible_count,advancers,decliners,advance_decline_ratio,pct_above_20dma,pct_above_50dma,pct_above_200dma,new_20d_high_fraction,new_20d_low_fraction,up_volume_fraction,universe_definition)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'point_in_time_active_enabled_universe')
        ON CONFLICT(dt) DO UPDATE SET eligible_count=EXCLUDED.eligible_count,advancers=EXCLUDED.advancers,
          decliners=EXCLUDED.decliners,advance_decline_ratio=EXCLUDED.advance_decline_ratio,
          pct_above_20dma=EXCLUDED.pct_above_20dma,pct_above_50dma=EXCLUDED.pct_above_50dma,
          pct_above_200dma=EXCLUDED.pct_above_200dma,new_20d_high_fraction=EXCLUDED.new_20d_high_fraction,
          new_20d_low_fraction=EXCLUDED.new_20d_low_fraction,up_volume_fraction=EXCLUDED.up_volume_fraction,ingested_at=now()
    """, (signal_dt,breadth["eligible_count"],breadth["advancers"],breadth["decliners"],breadth["advance_decline_ratio"],breadth["pct_above_20dma"],breadth["pct_above_50dma"],breadth["pct_above_200dma"],breadth["new_20d_high_fraction"],breadth["new_20d_low_fraction"],breadth["up_volume_fraction"]))
    return breadth


def _fetch_text(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Hermes-Wolfy-Free-Technical/1.0 contact=local-paper-research"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8-sig")


def ingest_free_sources(conn, *, as_of: date) -> dict[str, object]:
    """Ingest stable free sources. Nasdaq short interest is intentionally excluded.

    Its broad public access is symbol-by-symbol and fragile; bulk access is paid.
    We do not scrape it or enroll in a trial.
    """
    vix_rows = [row for row in parse_cboe_vix_csv(_fetch_text(CBOE_VIX_URL)) if row["observation_date"] <= as_of]
    for row in vix_rows:
        row["available_at"] = row["observation_date"] + timedelta(days=1)
    vix_stored = store_market_series(conn, vix_rows, source="cboe-public-vix", available_at=as_of, source_url=CBOE_VIX_URL)
    cboe_options_rows = parse_cboe_options_daily_html(_fetch_text(CBOE_OPTIONS_DAILY_URL), observation_date=as_of)
    cboe_options_stored = store_market_series(conn, cboe_options_rows, source="cboe-public-daily-options-statistics", available_at=as_of, source_url=CBOE_OPTIONS_DAILY_URL)
    finra_url = FINRA_DAILY_URL.format(yyyymmdd=as_of.strftime("%Y%m%d"))
    finra_rows = parse_finra_short_volume(_fetch_text(finra_url))
    finra_stored = store_short_volume(conn, finra_rows, source="finra-consolidated-nms-short-volume", available_at=as_of + timedelta(days=1), source_url=finra_url)
    treasury_url = TREASURY_CURVE_URL.format(year=as_of.year)
    treasury_rows = [row for row in parse_treasury_curve_csv(_fetch_text(treasury_url)) if row["observation_date"] <= as_of]
    market_rows = []
    for row in treasury_rows:
        for series, key in (("DGS2_DIRECT_TREASURY", "two_year"), ("DGS10_DIRECT_TREASURY", "ten_year"), ("T10Y2Y_DIRECT_TREASURY", "ten_minus_two")):
            market_rows.append({"observation_date": row["observation_date"], "available_at": row["observation_date"] + timedelta(days=1), "series": series, "value": row[key]})
    treasury_stored = store_market_series(conn, market_rows, source="us-treasury-daily-rates", available_at=as_of, source_url=treasury_url)
    return {"as_of": as_of.isoformat(), "vix_rows": vix_stored, "cboe_options_rows": cboe_options_stored, "finra_rows": finra_stored, "treasury_rows": treasury_stored, "nasdaq_short_interest": "skipped_no_stable_free_bulk_source", "paid_sources": 0, "free_trials": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--tickers", default="")
    parser.add_argument("--nasdaq-short-interest", action="store_true", help="Fetch free public per-symbol Nasdaq short interest for --tickers")
    args = parser.parse_args()
    import psycopg
    with psycopg.connect(DEFAULT_DSN) as conn:
        result = ingest_free_sources(conn, as_of=args.as_of)
        tickers = [ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()]
        if tickers:
            result["options_feature_rows"] = compute_and_store_options_features(conn, tickers=tickers, end_dt=args.as_of)
        if args.nasdaq_short_interest and tickers:
            nasdaq_rows = fetch_nasdaq_short_interest(tickers, published_at=args.as_of)
            result["nasdaq_short_interest_rows"] = store_nasdaq_short_interest(
                conn,
                nasdaq_rows,
                source="nasdaq-public-per-symbol-short-interest",
                source_url="https://api.nasdaq.com/api/quote/{symbol}/short-interest?assetclass=stocks",
            )
            result["nasdaq_short_interest"] = "free_public_per_symbol"
        result["breadth"] = compute_and_store_breadth(conn, signal_dt=args.as_of)
    print(json.dumps(result, default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
