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
    highs = [x[2] for x in rows]
    lows = [x[3] for x in rows]
    c = closes[-1]
    sma20 = sum(closes[-20:]) / 20
    sma50 = sum(closes[-50:]) / 50
    trs = [max(rows[i][2] - rows[i][3], abs(rows[i][2] - rows[i - 1][4]), abs(rows[i][3] - rows[i - 1][4])) for i in range(1, len(rows))]
    atr = sum(trs[-14:]) / 14
    return {'date': rows[-1][0], 'close': c, 'r5': (c / closes[-6] - 1) * 100, 'r20': (c / closes[-21] - 1) * 100, 'r60': (c / closes[-61] - 1) * 100, 'vs20': (c / sma20 - 1) * 100, 'vs50': (c / sma50 - 1) * 100, 'hi20': max(highs[-20:]), 'lo20': min(lows[-20:]), 'atr': atr, 'avgvol': sum(x[5] for x in rows[-20:]) / 20}


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
    rows = []
    for s, v in data.items():
        if s == 'SPY':
            continue
        if v['avgvol'] < 1_000_000:
            continue
        extended = max(0, v['vs20'] - 12) * 1.5
        score = (v['r20'] - spy) + 0.3 * v['r60'] - extended
        rows.append((score, s, v))
    return sorted(rows, reverse=True)


def persist_scan(ranked: list[tuple[float, str, dict]], db_path: Path, universe: str, notes: str = 'wolfy_scanner.py automated run') -> int | None:
    if not db_path or not db_path.exists():
        return None
    con = sqlite3.connect(db_path)
    run = con.execute(
        "INSERT INTO scanner_runs(data_source,universe,notes) VALUES(?,?,?)",
        ('Yahoo chart endpoint', universe, notes),
    ).lastrowid
    for score, s, v in ranked:
        extension_penalty = max(0, v['vs20'] - 12) * 1.5
        con.execute(
            """INSERT INTO scanner_results(run_id,ticker,score,data_date,close,r5,r20,r60,vs20,vs50,atr,avg_volume,high20,low20,extension_penalty,liquidity_pass)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run, s, score, v['date'], v['close'], v['r5'], v['r20'], v['r60'], v['vs20'], v['vs50'], v['atr'], v['avgvol'], v['hi20'], v['lo20'], extension_penalty, 1),
        )
    con.commit()
    con.close()
    return run


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
    print('symbol,score,date,close,r5,r20,r60,vs20,vs50,atr,avgvol_m,hi20,lo20')
    for score, s, v in ranked[:25]:
        print(f"{s},{score:.1f},{v['date']},{v['close']:.2f},{v['r5']:.1f},{v['r20']:.1f},{v['r60']:.1f},{v['vs20']:.1f},{v['vs50']:.1f},{v['atr']:.2f},{v['avgvol']/1e6:.1f},{v['hi20']:.2f},{v['lo20']:.2f}")


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description='Wolfy delayed/free Yahoo chart scanner')
    parser.add_argument('--universe', choices=['core', 'expanded', 'etf', 'ticker-list'], default='expanded')
    parser.add_argument('--ticker-list', help='Comma-separated tickers for --universe ticker-list')
    parser.add_argument('--refresh-universe', action='store_true', help='Refresh cached universe before scanning')
    parser.add_argument('--no-persist', action='store_true', help='Do not write scanner_runs/scanner_results')
    parser.add_argument('--max-workers', type=int, default=8, help='Concurrent Yahoo fetch workers; use 1 for sequential')
    args = parser.parse_args(argv)

    con = sqlite3.connect(DB)
    try:
        ensure_universe_tables(con)
        if args.refresh_universe or con.execute('SELECT COUNT(*) FROM universe_symbols WHERE active=1').fetchone()[0] == 0:
            refresh_universe_cache(con)
        symbols = resolve_symbols(con, args.universe, args.ticker_list)
    finally:
        con.close()
    print(f'# universe={args.universe} symbols={len(symbols)}', file=sys.stderr)
    ranked, failures = run_scan(symbols, db_path=DB, persist=not args.no_persist, universe=args.universe, max_workers=args.max_workers)
    if failures:
        print(f'# skipped_failures={len(failures)}', file=sys.stderr)
    print_csv(ranked)


if __name__ == '__main__':
    main()
