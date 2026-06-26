#!/usr/bin/env python3
"""Wolfy free-data scanner.

Uses Yahoo chart endpoint for delayed/free daily bars. Outputs compact
RS/trend/risk ranking. No trade execution. Research only.
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import re
import sqlite3
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

from wolfy_postgres_pipeline import (
    persist_scanner_run as persist_scanner_run_postgres,
    refresh_universe_cache_postgres,
    load_universe_postgres,
)
from alpha_search_pipeline import REQUIRED_SECTIONS, record_alpha_payload, stable_fingerprint

# Keep the original curated list as the "core" seed so existing Wolfy focus names
# and cron behavior remain available even when external universe sources are down.
DEFAULT_SYMBOLS = ['SPY', 'QQQ', 'IWM', 'DIA', 'SMH', 'XLK', 'XLE', 'TLT', 'UUP', 'USO', 'GLD', 'VIXY', 'NVDA', 'AVGO', 'AMD', 'MSFT', 'AMZN', 'META', 'GOOGL', 'AAPL', 'TSLA', 'PLTR', 'CRWD', 'NOW', 'COST', 'JPM', 'XOM', 'UNH', 'LLY', 'GE', 'ANET', 'ORCL', 'PANW', 'NFLX', 'MU', 'ARM', 'HOOD', 'COIN', 'APP', 'SHOP', 'UBER', 'DELL', 'MRVL', 'INTC', 'WMT', 'HD', 'CAT']
MAJOR_ETFS = [
    ('SPY', 'SPDR S&P 500 ETF Trust'), ('QQQ', 'Invesco QQQ Trust'),
    ('IWM', 'iShares Russell 2000 ETF'), ('DIA', 'SPDR Dow Jones Industrial Average ETF'),
    ('XLK', 'Technology Select Sector SPDR'), ('XLF', 'Financial Select Sector SPDR'),
    ('XLY', 'Consumer Discretionary Select Sector SPDR'), ('XLI', 'Industrial Select Sector SPDR'),
    ('XLE', 'Energy Select Sector SPDR'), ('XLV', 'Health Care Select Sector SPDR'),
    ('XLP', 'Consumer Staples Select Sector SPDR'), ('XLU', 'Utilities Select Sector SPDR'),
    ('XLB', 'Materials Select Sector SPDR'), ('XLRE', 'Real Estate Select Sector SPDR'),
    ('XLC', 'Communication Services Select Sector SPDR'), ('SMH', 'VanEck Semiconductor ETF'),
    ('SOXX', 'iShares Semiconductor ETF'), ('IGV', 'iShares Expanded Tech-Software ETF'),
    ('HACK', 'ETFMG Prime Cyber Security ETF'), ('ARKK', 'ARK Innovation ETF'),
    ('IBB', 'iShares Biotechnology ETF'), ('XBI', 'SPDR S&P Biotech ETF'),
    ('KRE', 'SPDR S&P Regional Banking ETF'), ('KWEB', 'KraneShares CSI China Internet ETF'),
    ('TLT', 'iShares 20+ Year Treasury Bond ETF'), ('UUP', 'Invesco DB US Dollar Index Bullish Fund'),
    ('USO', 'United States Oil Fund'), ('GLD', 'SPDR Gold Shares'), ('VIXY', 'ProShares VIX Short-Term Futures ETF'),
]
HEADERS = {'User-Agent': 'Mozilla/5.0'}
DB = Path('/root/.hermes/wolfy/wolfy.db')


class WikiTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._table_class = ''
        self._rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'table' and 'wikitable' in attrs.get('class', ''):
            self._in_table = True
            self._rows = []
        elif self._in_table and tag == 'tr':
            self._row = []
        elif self._in_table and tag in {'td', 'th'}:
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if self._in_table and tag in {'td', 'th'} and self._cell is not None:
            text = html.unescape(' '.join(''.join(self._cell).split())).strip()
            if self._row is not None:
                self._row.append(text)
            self._cell = None
        elif self._in_table and tag == 'tr' and self._row is not None:
            if self._row:
                self._rows.append(self._row)
            self._row = None
        elif self._in_table and tag == 'table':
            self.tables.append(self._rows)
            self._in_table = False


def normalize_symbol(symbol: str) -> str:
    return re.sub(r'[^A-Z0-9.-]', '', symbol.upper().strip()).replace('.', '-')


def fetch(sym, days=420):
    end = int(time.time())
    start = end - days * 24 * 3600
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={start}&period2={end}&interval=1d'
    data = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=15))
    r = data['chart']['result'][0]
    q = r['indicators']['quote'][0]
    rows = []
    for i, t in enumerate(r['timestamp']):
        vals = [q[k][i] for k in ['open', 'high', 'low', 'close', 'volume']]
        if vals[3] is not None and vals[4] is not None:
            rows.append((datetime.datetime.fromtimestamp(t, datetime.timezone.utc).date().isoformat(), *vals))
    return rows


def metrics(rows):
    if len(rows) < 61:
        raise ValueError(f'need at least 61 daily rows, got {len(rows)}')
    closes = [x[4] for x in rows]
    opens = [x[1] for x in rows]
    highs = [x[2] for x in rows]
    lows = [x[3] for x in rows]
    volumes = [x[5] for x in rows]
    c = closes[-1]
    sma20 = sum(closes[-20:]) / 20
    sma50 = sum(closes[-50:]) / 50
    sma200 = sum(closes[-200:]) / min(200, len(closes))
    trs = [max(rows[i][2] - rows[i][3], abs(rows[i][2] - rows[i - 1][4]), abs(rows[i][3] - rows[i - 1][4])) for i in range(1, len(rows))]
    atr = sum(trs[-14:]) / 14
    atr_pct = (atr / c) * 100 if c else 0
    avgvol20 = sum(volumes[-20:]) / 20
    avgvol50 = sum(volumes[-50:]) / 50
    prior_avgvol20 = sum(volumes[-21:-1]) / 20
    prior_avgvol50 = sum(volumes[-51:-1]) / 50 if len(volumes) >= 51 else avgvol50
    avgvol5 = sum(volumes[-5:]) / 5
    # Breakout should compare the latest close to the prior 20-day high; including
    # today's high hides fresh breakouts on the signal bar.
    prior_high20 = max(highs[-21:-1])
    low20 = min(lows[-20:])
    tr20 = sum(trs[-20:]) / 20
    tr50 = sum(trs[-50:]) / 50 if len(trs) >= 50 else tr20
    squeeze_ratio = tr20 / tr50 if tr50 else 0
    prev_close = closes[-2]
    gap_pct = (opens[-1] / prev_close - 1) * 100 if prev_close else 0
    intraday_pct = (c / opens[-1] - 1) * 100 if opens[-1] else 0
    if gap_pct >= 1 and c > prev_close and intraday_pct >= -1:
        gap_reversal_flag = 'gap_up_hold'
    elif gap_pct >= 1 and intraday_pct < -1:
        gap_reversal_flag = 'gap_up_reversal'
    elif gap_pct <= -1 and c > opens[-1]:
        gap_reversal_flag = 'gap_down_reversal'
    else:
        gap_reversal_flag = 'none'
    if c > sma50 and sma50 > sma200:
        trend_regime = 'bull_50_200'
    elif c < sma50 and sma50 < sma200:
        trend_regime = 'bear_50_200'
    else:
        trend_regime = 'mixed'
    liquidity_spread_proxy = (atr_pct / max(avgvol20 / 1_000_000, 0.1))
    return {
        'date': rows[-1][0], 'close': c,
        'r5': (c / closes[-6] - 1) * 100,
        'r20': (c / closes[-21] - 1) * 100,
        'r60': (c / closes[-61] - 1) * 100,
        'vs20': (c / sma20 - 1) * 100,
        'vs50': (c / sma50 - 1) * 100,
        'hi20': max(highs[-20:]), 'lo20': low20,
        'atr': atr, 'atr_pct': atr_pct,
        'avgvol': avgvol20,
        'volume_surge_1d_20': volumes[-1] / prior_avgvol20 if prior_avgvol20 else 0,
        'volume_surge_5d_20': avgvol5 / prior_avgvol20 if prior_avgvol20 else 0,
        'volume_surge_1d_50': volumes[-1] / prior_avgvol50 if prior_avgvol50 else 0,
        'volume_surge_5d_50': avgvol5 / prior_avgvol50 if prior_avgvol50 else 0,
        'breakout_20d_pct': (c / prior_high20 - 1) * 100 if prior_high20 else 0,
        'trend_regime': trend_regime,
        'squeeze_ratio': squeeze_ratio,
        'squeeze_flag': 1 if squeeze_ratio and squeeze_ratio < 1.0 else 0,
        'gap_reversal_flag': gap_reversal_flag,
        'liquidity_spread_proxy': liquidity_spread_proxy,
    }


def ensure_universe_tables(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS universe_symbols (
          symbol TEXT PRIMARY KEY,
          name TEXT,
          source TEXT NOT NULL,
          sector TEXT,
          is_etf INTEGER NOT NULL DEFAULT 0,
          last_seen TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_universe_symbols_active_source ON universe_symbols(active, source)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_universe_symbols_etf ON universe_symbols(is_etf, active)")
    con.commit()


def core_records() -> list[dict]:
    etfs = {symbol for symbol, _name in MAJOR_ETFS}
    return [
        {'symbol': s, 'name': s, 'source': 'core_etf' if s in etfs else 'core', 'sector': 'ETF' if s in etfs else None, 'is_etf': 1 if s in etfs else 0}
        for s in DEFAULT_SYMBOLS
    ]


def etf_records() -> list[dict]:
    return [{'symbol': s, 'name': name, 'source': 'major_etf', 'sector': 'ETF', 'is_etf': 1} for s, name in MAJOR_ETFS]


def fetch_wiki_table_records(url: str, symbol_headers: Iterable[str], name_headers: Iterable[str], source: str, sector_headers: Iterable[str] = ()) -> list[dict]:
    page = urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=20).read().decode('utf-8', errors='replace')
    parser = WikiTableParser()
    parser.feed(page)
    symbol_headers = {h.lower() for h in symbol_headers}
    name_headers = {h.lower() for h in name_headers}
    sector_headers = {h.lower() for h in sector_headers}
    for table in parser.tables:
        if not table:
            continue
        headers = [h.lower() for h in table[0]]
        sym_idx = next((i for i, h in enumerate(headers) if h in symbol_headers), None)
        name_idx = next((i for i, h in enumerate(headers) if h in name_headers), None)
        sector_idx = next((i for i, h in enumerate(headers) if h in sector_headers), None)
        if sym_idx is None:
            continue
        records = []
        for row in table[1:]:
            if len(row) <= sym_idx:
                continue
            symbol = normalize_symbol(row[sym_idx])
            if not symbol:
                continue
            records.append({
                'symbol': symbol,
                'name': row[name_idx] if name_idx is not None and len(row) > name_idx else symbol,
                'source': source,
                'sector': row[sector_idx] if sector_idx is not None and len(row) > sector_idx else None,
                'is_etf': 0,
            })
        if records:
            return records
    return []


def fetch_sp500_records() -> list[dict]:
    return fetch_wiki_table_records(
        'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies',
        symbol_headers={'Symbol'},
        name_headers={'Security'},
        sector_headers={'GICS Sector'},
        source='sp500',
    )


def fetch_nasdaq100_records() -> list[dict]:
    return fetch_wiki_table_records(
        'https://en.wikipedia.org/wiki/Nasdaq-100',
        symbol_headers={'Ticker', 'Symbol'},
        name_headers={'Company'},
        sector_headers={'GICS Sector', 'Sector'},
        source='nasdaq100',
    )


def refresh_universe_cache(con: sqlite3.Connection, source_records: dict[str, list[dict]] | None = None, now: str | None = None) -> int:
    ensure_universe_tables(con)
    now = now or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    if source_records is None:
        source_records = {'core': core_records(), 'major_etf': etf_records()}
        for name, fetcher in [('sp500', fetch_sp500_records), ('nasdaq100', fetch_nasdaq100_records)]:
            try:
                records = fetcher()
                if records:
                    source_records[name] = records
            except Exception as exc:
                print(f'WARN universe source {name} failed: {exc}', file=sys.stderr)
    touched = 0
    for source, records in source_records.items():
        for record in records:
            symbol = normalize_symbol(record.get('symbol', ''))
            if not symbol:
                continue
            con.execute(
                """
                INSERT INTO universe_symbols(symbol,name,source,sector,is_etf,last_seen,active)
                VALUES(?,?,?,?,?,?,1)
                ON CONFLICT(symbol) DO UPDATE SET
                  name=COALESCE(excluded.name, universe_symbols.name),
                  source=CASE
                    WHEN instr(',' || universe_symbols.source || ',', ',' || excluded.source || ',') > 0 THEN universe_symbols.source
                    ELSE universe_symbols.source || ',' || excluded.source
                  END,
                  sector=COALESCE(excluded.sector, universe_symbols.sector),
                  is_etf=MAX(universe_symbols.is_etf, excluded.is_etf),
                  last_seen=excluded.last_seen,
                  active=1
                """,
                (symbol, record.get('name') or symbol, record.get('source') or source, record.get('sector'), int(record.get('is_etf') or 0), now),
            )
            touched += 1
    con.commit()
    return touched


def load_universe(con: sqlite3.Connection, universe: str = 'expanded') -> list[str]:
    ensure_universe_tables(con)
    if universe == 'core':
        where = "active=1 AND ((',' || source || ',') GLOB '*,core,*' OR (',' || source || ',') GLOB '*,core_etf,*')"
    elif universe == 'etf':
        where = 'active=1 AND is_etf=1'
    elif universe == 'expanded':
        where = 'active=1'
    else:
        raise ValueError(f'unknown universe {universe!r}')
    rows = con.execute(f"SELECT symbol FROM universe_symbols WHERE {where} ORDER BY symbol").fetchall()
    return [r[0] for r in rows]


def resolve_symbols(con: sqlite3.Connection, universe: str = 'expanded', ticker_list: str | None = None) -> list[str]:
    if universe == 'ticker-list':
        if not ticker_list:
            raise ValueError('--ticker-list is required when --universe ticker-list')
        return [s for s in (normalize_symbol(x) for x in ticker_list.split(',')) if s]
    symbols = load_universe(con, universe)
    if universe == 'expanded' and len(symbols) < 300:
        refresh_universe_cache(con)
        symbols = load_universe(con, universe)
    if not symbols:
        refresh_universe_cache(con, {'core': core_records(), 'major_etf': etf_records()})
        symbols = load_universe(con, universe)
    return symbols


def rank_metrics(data: dict[str, dict]) -> list[tuple[float, str, dict]]:
    spy = data.get('SPY', {}).get('r20', 0)
    qqq = data.get('QQQ', {}).get('r20', 0)
    rows = []
    for s, v in data.items():
        if s in {'SPY', 'QQQ'}:
            continue
        if v['avgvol'] < 1_000_000:
            continue
        v = dict(v)
        rs_spy = v['r20'] - spy
        rs_qqq = v['r20'] - qqq
        extended = v.get('extension_penalty', max(0, v['vs20'] - 12) * 1.5)
        breakout = max(0, v.get('breakout_20d_pct', 0))
        volume_surge = max(0, v.get('volume_surge_1d_20', 1) - 1) * 2.0 + max(0, v.get('volume_surge_5d_20', 1) - 1)
        squeeze = 2.0 if v.get('squeeze_flag') else 0
        trend_bonus = 2.0 if v.get('trend_regime') == 'bull_50_200' else (-2.0 if v.get('trend_regime') == 'bear_50_200' else 0)
        gap_penalty = 3.0 if v.get('gap_reversal_flag') == 'gap_up_reversal' else 0
        liquidity_penalty = max(0, v.get('liquidity_spread_proxy', 0) - 0.75)
        score = rs_spy + 0.25 * rs_qqq + 0.3 * v['r60'] + breakout + volume_surge + squeeze + trend_bonus - extended - gap_penalty - liquidity_penalty
        reasons = [f'RS{rs_spy:+.1f} vs SPY', f'RS{rs_qqq:+.1f} vs QQQ']
        if v.get('volume_surge_1d_20', 0) >= 1.5 or v.get('volume_surge_5d_20', 0) >= 1.3:
            reasons.append('volume surge')
        if breakout > 0:
            reasons.append(f'20d breakout +{breakout:.1f}%')
        if v.get('squeeze_flag'):
            reasons.append('squeeze')
        if extended:
            reasons.append(f'extension penalty -{extended:.1f}')
        if v.get('gap_reversal_flag') not in (None, 'none'):
            reasons.append(v['gap_reversal_flag'])
        v['rs_spy_20'] = rs_spy
        v['rs_qqq_20'] = rs_qqq
        v['extension_penalty'] = extended
        v['rank_reasons'] = '; '.join(reasons)
        rows.append((score, s, v))
    return sorted(rows, reverse=True)


def ensure_scanner_result_factor_columns(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS scanner_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_time TEXT NOT NULL DEFAULT (datetime('now')),
          data_source TEXT NOT NULL,
          universe TEXT,
          notes TEXT
        );
        CREATE TABLE IF NOT EXISTS scanner_results (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id INTEGER NOT NULL REFERENCES scanner_runs(id) ON DELETE CASCADE,
          ticker TEXT NOT NULL,
          score REAL,
          data_date TEXT,
          close REAL,
          r5 REAL, r20 REAL, r60 REAL,
          vs20 REAL, vs50 REAL,
          atr REAL,
          avg_volume REAL,
          high20 REAL,
          low20 REAL,
          extension_penalty REAL,
          liquidity_pass INTEGER,
          notes_json TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_scanner_results_ticker ON scanner_results(ticker);
        CREATE INDEX IF NOT EXISTS idx_scanner_results_run ON scanner_results(run_id, score DESC);
        """
    )
    columns = {row[1] for row in con.execute('PRAGMA table_info(scanner_results)').fetchall()}
    if 'notes_json' not in columns:
        con.execute('ALTER TABLE scanner_results ADD COLUMN notes_json TEXT')


def scanner_signal_code(metrics_row: dict) -> str | None:
    if metrics_row.get('breakout_20d_pct', 0) > 0:
        return 'breakout'
    if metrics_row.get('volume_surge_1d_20', 0) >= 1.5 or metrics_row.get('volume_surge_5d_20', 0) >= 1.3:
        return 'volume_surge'
    if metrics_row.get('squeeze_flag') and metrics_row.get('rs_spy_20', 0) >= 3:
        return 'squeeze_breakout'
    if metrics_row.get('rs_spy_20', 0) >= 5:
        return 'relative_strength'
    if metrics_row.get('trend_regime') == 'bull_50_200' and metrics_row.get('r20', 0) > 0:
        return 'risk_off_leader'
    return None


def scanner_alpha_risk_flags(metrics_row: dict, as_of_date: str | None = None) -> list[str]:
    flags = ['watch_only_no_catalyst']
    if as_of_date and metrics_row.get('date') and str(metrics_row.get('date')) < as_of_date:
        flags.append('stale_scanner_data')
    if metrics_row.get('avgvol', 0) < 1_000_000:
        flags.append('liquidity_below_1m_avg_volume')
    if metrics_row.get('liquidity_spread_proxy', 0) > 0.75:
        flags.append('wide_spread_proxy')
    if metrics_row.get('gap_reversal_flag') == 'gap_up_reversal':
        flags.append('gap_up_reversal')
    return flags


def scanner_alpha_passes_filters(metrics_row: dict, as_of_date: str | None = None) -> bool:
    if metrics_row.get('avgvol', 0) < 1_000_000:
        return False
    if metrics_row.get('liquidity_spread_proxy', 0) > 0.75:
        return False
    if as_of_date and metrics_row.get('date') and str(metrics_row.get('date')) < as_of_date:
        return False
    if metrics_row.get('gap_reversal_flag') == 'gap_up_reversal':
        return False
    return scanner_signal_code(metrics_row) is not None


def create_alpha_leads_from_scan(
    ranked: list[tuple[float, str, dict]],
    *,
    db_path: Path | str = DB,
    run_id: int | None = None,
    as_of_date: str | None = None,
    limit: int = 10,
    create_postgres_tasks: bool = True,
) -> dict[str, int]:
    """Persist top scanner anomalies as watch-only alpha leads and Jonah handoffs.

    These are discovery leads, not recommendations. Dedupe is by ticker + signal +
    scanner data_date so repeated scans update the same lead/evidence/handoff rows.
    """
    selected = []
    for score, ticker, row in ranked:
        if len(selected) >= limit:
            break
        if not scanner_alpha_passes_filters(row, as_of_date=as_of_date):
            continue
        signal = scanner_signal_code(row)
        if not signal:
            continue
        data_date = str(row.get('date') or '')
        risk_flags = scanner_alpha_risk_flags(row, as_of_date=as_of_date)
        fp = stable_fingerprint('scanner_alpha_lead', ticker, signal, data_date)
        reason_text = str(row.get('rank_reasons') or '')
        fact = (
            f"Wolfy scanner run {run_id or 'unknown'} flagged {ticker} on {data_date}: "
            f"signal={signal}; score={score:.2f}; r20={row.get('r20', 0):.2f}; "
            f"rs_spy_20={row.get('rs_spy_20', 0):.2f}; avg_volume={row.get('avgvol', 0):.0f}; "
            f"breakout_20d_pct={row.get('breakout_20d_pct', 0):.2f}; "
            f"volume_surge_1d_20={row.get('volume_surge_1d_20', 0):.2f}; reasons={reason_text}"
        )
        selected.append({
            'ticker': ticker,
            'lead_type': f'scanner_anomaly_{signal}',
            'title': f'{ticker} scanner anomaly: {signal}',
            'thesis': (
                f'{ticker} is a deterministic scanner lead ({signal}) with positive liquidity and relative-strength evidence. '
                'This is watch-only discovery context until Jonah finds a real catalyst and downstream gates approve it.'
            ),
            'status': 'needs_research',
            'next_research_question': (
                f'Watch-only: research whether {ticker} has a real public catalyst or durable theme behind the {signal} scanner anomaly; '
                'do not create a recommendation from scanner data alone.'
            ),
            'market_context': {'source': 'wolfy_scanner', 'scanner_run_id': run_id, 'data_date': data_date},
            'risk_notes': '; '.join(risk_flags),
            'suspicious_activity': {'recommended_action': 'clear', 'flags': []},
            'evidence': [{
                'evidence_type': 'scanner_result',
                'source_title': 'Wolfy scanner',
                'source_url': f'local:scanner_results:{run_id}:{ticker}' if run_id is not None else 'local:wolfy_scanner',
                'source_published_at': data_date,
                'quote_or_fact': fact,
                'quality_score': 0.62,
                'relevance_score': 0.78,
                'notes': 'Deterministic scanner evidence only; no catalyst verified.',
                'source_fingerprint': stable_fingerprint('scanner_alpha_evidence', ticker, signal, data_date),
            }],
            'handoffs': [{
                'target_agent': 'Jonah',
                'task_type': 'scanner_alpha_research',
                'title': f'Jonah research: {ticker} scanner alpha lead',
                'question': (
                    f'Research {ticker} scanner lead ({signal}) from Wolfy scanner run {run_id or "unknown"}. '
                    'Find public evidence/catalysts, manipulation/liquidity risks, and strategy-rule relevance. '
                    'Return research only; do not recommend a trade.'
                ),
                'priority': 35,
                'source_fingerprint': stable_fingerprint('scanner_alpha_handoff', ticker, signal, data_date, 'Jonah'),
            }],
            'signal': signal,
            'risk_flags': risk_flags,
            'scanner_run_id': run_id,
            'scanner_score': score,
            'scanner_data_date': data_date,
            'scanner_metrics': {k: row.get(k) for k in [
                'close', 'r5', 'r20', 'r60', 'vs20', 'vs50', 'atr', 'avgvol', 'breakout_20d_pct',
                'volume_surge_1d_20', 'volume_surge_5d_20', 'trend_regime', 'squeeze_ratio', 'squeeze_flag',
                'liquidity_spread_proxy', 'rs_spy_20', 'rs_qqq_20', 'rank_reasons',
            ]},
            'source_fingerprint': fp,
        })
    if not selected:
        return {'leads_seen': 0, 'leads_upserted': 0, 'evidence_rows_seen': 0, 'handoffs_seen': 0, 'postgres_tasks_created': 0}
    sections = {section: '' for section in REQUIRED_SECTIONS}
    sections.update({
        'top_alpha_leads': f'{len(selected)} deterministic scanner alpha leads queued for Jonah research.',
        'deeper_research_needed': 'Scanner leads are watch-only until catalysts, fundamentals, manipulation risk, and approved strategy gates are verified.',
        'yang_needs': 'Technical levels may be requested after Jonah research finds a real thesis.',
        'sentinel_challenges': 'Reject any lead with stale data, thin liquidity, no catalyst, or manipulation risk.',
    })
    payload = {
        'report': {
            'source_job_id': 'wolfy-scanner-alpha-leads',
            'title': 'Wolfy scanner alpha leads',
            'summary': f'{len(selected)} scanner anomalies persisted as watch-only alpha leads.',
            'market_context': 'Deterministic delayed/free scanner output; not a recommendation.',
            'sections': sections,
        },
        'leads': selected,
    }
    result = record_alpha_payload(payload, db_path=db_path, create_postgres_tasks=create_postgres_tasks)
    return {
        'leads_seen': result.leads_seen,
        'leads_upserted': result.leads_upserted,
        'evidence_rows_seen': result.evidence_rows_seen,
        'handoffs_seen': result.handoffs_seen,
        'postgres_tasks_created': result.postgres_tasks_created,
    }


def _persist_scan_sqlite_compat(ranked: list[tuple[float, str, dict]], db_path: Path, universe: str, notes: str) -> int:
    """Write a SQLite compatibility copy for tests/legacy inspection only.

    Live cron paths pass ``db_path=None`` and therefore stay Postgres-only.  Some
    smoke tests and ad-hoc fixtures still exercise the historical SQLite shape;
    keep that path deterministic without making it the live source of truth.
    """
    con = sqlite3.connect(db_path)
    try:
        ensure_scanner_result_factor_columns(con)
        cur = con.execute(
            'INSERT INTO scanner_runs (data_source, universe, notes) VALUES (?,?,?)',
            ('yahoo_chart_delayed', universe, notes),
        )
        if cur.lastrowid is None:
            raise RuntimeError('SQLite scanner_runs insert did not return a row id')
        run_id = int(cur.lastrowid)
        for score, ticker, v in ranked:
            payload = json.dumps({
                key: v.get(key)
                for key in [
                    'volume_surge_1d_20', 'volume_surge_5d_20', 'volume_surge_1d_50',
                    'volume_surge_5d_50', 'breakout_20d_pct', 'trend_regime', 'atr_pct',
                    'squeeze_ratio', 'squeeze_flag', 'gap_reversal_flag', 'liquidity_spread_proxy',
                    'rs_spy_20', 'rs_qqq_20', 'rank_reasons',
                ]
            }, sort_keys=True)
            con.execute(
                """
                INSERT INTO scanner_results (
                  run_id, ticker, score, data_date, close, r5, r20, r60,
                  vs20, vs50, atr, avg_volume, high20, low20,
                  extension_penalty, liquidity_pass, notes_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id, ticker, score, v.get('date'), v.get('close'), v.get('r5'), v.get('r20'), v.get('r60'),
                    v.get('vs20'), v.get('vs50'), v.get('atr'), v.get('avgvol'), v.get('hi20'), v.get('lo20'),
                    v.get('extension_penalty'), 1 if v.get('liquidity_pass', True) else 0, payload,
                ),
            )
        con.commit()
        return run_id
    finally:
        con.close()


def persist_scan(ranked: list[tuple[float, str, dict]], db_path: Path | None, universe: str, notes: str = 'wolfy_scanner.py automated run') -> int | None:
    """Persist scanner output to Postgres primary, with optional SQLite compatibility copy."""
    pg_run = persist_scanner_run_postgres(ranked, universe=universe, notes=notes)
    print(f'# postgres_scanner_run_id={pg_run}', file=sys.stderr)
    if universe == 'expanded':
        try:
            as_of_date = max((str(v.get('date')) for _score, _s, v in ranked if v.get('date')), default=None)
            alpha_db_path = Path(db_path) if db_path is not None else DB
            alpha_result = create_alpha_leads_from_scan(ranked, db_path=alpha_db_path, run_id=pg_run, as_of_date=as_of_date)
            print(f"# postgres_alpha_leads_upserted={alpha_result['leads_upserted']} handoffs_seen={alpha_result['handoffs_seen']}", file=sys.stderr)
        except Exception as exc:
            print(f'# WARN postgres_alpha_lead_handoff_failed={type(exc).__name__}: {exc}', file=sys.stderr)
    if db_path is not None:
        return _persist_scan_sqlite_compat(ranked, Path(db_path), universe, notes)
    return pg_run


def run_scan(symbols: list[str], db_path: Path | None = DB, persist: bool = True, universe: str = 'expanded', max_workers: int = 8) -> tuple[list[tuple[float, str, dict]], dict[str, str]]:
    data = {}
    failures: dict[str, str] = {}

    def fetch_metrics(symbol: str) -> tuple[str, dict]:
        return symbol, metrics(fetch(symbol))

    if max_workers <= 1:
        for s in symbols:
            try:
                symbol, value = fetch_metrics(s)
                data[symbol] = value
            except Exception as e:
                failures[s] = str(e)
                print(f'ERR {s}: {e}', file=sys.stderr)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(fetch_metrics, s): s for s in symbols}
            for future in as_completed(futures):
                s = futures[future]
                try:
                    symbol, value = future.result()
                    data[symbol] = value
                except Exception as e:
                    failures[s] = str(e)
                    print(f'ERR {s}: {e}', file=sys.stderr)
    ranked = rank_metrics(data)
    if persist and db_path:
        run = persist_scan(ranked, Path(db_path), universe)
        if run is not None:
            print(f'# db_run_id={run}', file=sys.stderr)
    return ranked, failures


def print_csv(ranked: list[tuple[float, str, dict]]) -> None:
    print('symbol,score,date,close,r5,r20,r60,vs20,vs50,atr,avgvol_m,hi20,lo20,vol1d20,breakout20,trend,rs_spy,rs_qqq,reasons')
    for score, s, v in ranked[:25]:
        reasons = str(v.get('rank_reasons', '')).replace(',', ';')
        print(f"{s},{score:.1f},{v['date']},{v['close']:.2f},{v['r5']:.1f},{v['r20']:.1f},{v['r60']:.1f},{v['vs20']:.1f},{v['vs50']:.1f},{v['atr']:.2f},{v['avgvol']/1e6:.1f},{v['hi20']:.2f},{v['lo20']:.2f},{v.get('volume_surge_1d_20', 0):.2f},{v.get('breakout_20d_pct', 0):.1f},{v.get('trend_regime', '')},{v.get('rs_spy_20', 0):.1f},{v.get('rs_qqq_20', 0):.1f},{reasons}")


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description='Wolfy delayed/free Yahoo chart scanner')
    parser.add_argument('--universe', choices=['core', 'expanded', 'etf', 'ticker-list'], default='expanded')
    parser.add_argument('--ticker-list', help='Comma-separated tickers for --universe ticker-list')
    parser.add_argument('--refresh-universe', action='store_true', help='Refresh cached universe before scanning')
    parser.add_argument('--no-persist', action='store_true', help='Do not write scanner_runs/scanner_results')
    parser.add_argument('--max-workers', type=int, default=8, help='Concurrent Yahoo fetch workers; use 1 for sequential')
    args = parser.parse_args(argv)

    if args.universe == 'ticker-list':
        symbols = resolve_symbols(None, args.universe, args.ticker_list)  # type: ignore[arg-type]
    else:
        source_records = {'core': core_records(), 'major_etf': etf_records()}
        for name, fetcher in [('sp500', fetch_sp500_records), ('nasdaq100', fetch_nasdaq100_records)]:
            try:
                records = fetcher()
                if records:
                    source_records[name] = records
            except Exception as exc:
                print(f'WARN universe source {name} failed: {exc}', file=sys.stderr)
        if args.refresh_universe or True:
            touched = refresh_universe_cache_postgres(source_records)
            print(f'# postgres_universe_touched={touched}', file=sys.stderr)
        symbols = load_universe_postgres(args.universe)
        if not symbols:
            symbols = sorted({r['symbol'] for records in source_records.values() for r in records})
    print(f'# universe={args.universe} symbols={len(symbols)}', file=sys.stderr)
    ranked, failures = run_scan(symbols, db_path=None, persist=not args.no_persist, universe=args.universe, max_workers=args.max_workers)
    if failures:
        print(f'# skipped_failures={len(failures)}', file=sys.stderr)
    print_csv(ranked)


if __name__ == '__main__':
    main()
