#!/usr/bin/env python3
"""Free social-momentum scanner prototype for Wolfy.

Primary source: Stocktwits public symbol/trending endpoints. This is not an X
scraper and does not bypass login walls. It gives Wolfy a legal/free substitute
for financial Twitter-style cashtag chatter while X API access is unavailable or
not cost-effective.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

DEFAULT_DB = Path("/root/.hermes/wolfy/wolfy.db")
STOCKTWITS_BASE = "https://api.stocktwits.com/api/2"
DEFAULT_USER_AGENT = "WolfySocialScanner/0.1 (+local Hermes research desk)"
CASHTAG_RE = re.compile(r"(?<![A-Za-z0-9_])\$([A-Z][A-Z0-9.]{0,9})(?![A-Za-z0-9_])")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]{2,}")
STOPWORDS = {
    "the", "and", "for", "this", "that", "with", "from", "are", "was", "were", "have", "has",
    "had", "you", "your", "its", "it's", "but", "not", "all", "our", "out", "into", "over",
    "under", "can", "will", "just", "about", "after", "before", "stock", "stocks", "market",
    "today", "tomorrow", "bull", "bear", "bullish", "bearish",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS social_scanner_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  source TEXT NOT NULL,
  query_json TEXT NOT NULL,
  summary_json TEXT NOT NULL,
  error_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_social_runs_created ON social_scanner_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_social_runs_source ON social_scanner_runs(source, created_at DESC);

CREATE TABLE IF NOT EXISTS social_scanner_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER REFERENCES social_scanner_runs(id) ON DELETE SET NULL,
  first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
  source TEXT NOT NULL,
  source_message_id TEXT NOT NULL,
  ticker TEXT NOT NULL,
  author TEXT,
  author_followers INTEGER,
  body TEXT NOT NULL,
  sentiment TEXT,
  created_at TEXT,
  source_url TEXT,
  raw_json TEXT NOT NULL,
  source_fingerprint TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_social_messages_ticker_seen ON social_scanner_messages(ticker, first_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_social_messages_sentiment ON social_scanner_messages(sentiment, first_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_social_messages_source_id ON social_scanner_messages(source, source_message_id);
"""


class FetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class SocialMessage:
    source_message_id: str
    ticker: str
    author: str | None
    author_followers: int | None
    body: str
    sentiment: str | None
    created_at: str | None
    source_url: str | None
    raw: Mapping[str, Any]

    @property
    def fingerprint(self) -> str:
        h = hashlib.sha256()
        h.update(b"stocktwits\0")
        h.update(self.source_message_id.encode("utf-8"))
        h.update(b"\0")
        h.update(self.ticker.encode("utf-8"))
        return h.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def ensure_tables(db_path: str | Path = DEFAULT_DB) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        con.executescript(SCHEMA)
        con.commit()
    finally:
        con.close()


def fetch_json(url: str, timeout: int = 20, user_agent: str = DEFAULT_USER_AGENT) -> dict[str, Any]:
    req = Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:  # nosec B310 - fixed https endpoints; URL visible in caller.
            data = resp.read()
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise FetchError(f"HTTP {exc.code} for {url}: {body}") from exc
    except URLError as exc:
        raise FetchError(f"Network error for {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise FetchError(f"Timeout fetching {url}") from exc
    try:
        parsed = json.loads(data.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise FetchError(f"Non-JSON response from {url}") from exc
    if not isinstance(parsed, dict):
        raise FetchError(f"Unexpected JSON shape from {url}")
    return parsed


def normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("$", "")


def extract_cashtags(body: str) -> set[str]:
    return {normalize_ticker(m.group(1)) for m in CASHTAG_RE.finditer(body or "")}


def normalize_sentiment(message: Mapping[str, Any]) -> str | None:
    entities = message.get("entities") if isinstance(message.get("entities"), Mapping) else {}
    sentiment = entities.get("sentiment") if isinstance(entities.get("sentiment"), Mapping) else None
    if sentiment:
        basic = str(sentiment.get("basic") or "").strip().lower()
        if basic in {"bullish", "bearish"}:
            return basic
    return None


def message_url(message: Mapping[str, Any]) -> str | None:
    user = message.get("user") if isinstance(message.get("user"), Mapping) else {}
    username = user.get("username") if user else None
    mid = message.get("id")
    if username and mid:
        return f"https://stocktwits.com/{username}/message/{mid}"
    return None


def normalize_messages(payload: Mapping[str, Any], requested_symbol: str | None = None) -> list[SocialMessage]:
    requested = normalize_ticker(requested_symbol)
    out: list[SocialMessage] = []
    for msg in payload.get("messages") or []:
        if not isinstance(msg, Mapping):
            continue
        mid = str(msg.get("id") or "").strip()
        body = str(msg.get("body") or "").strip()
        if not mid or not body:
            continue
        user = msg.get("user") if isinstance(msg.get("user"), Mapping) else {}
        symbols: set[str] = set()
        for sym in msg.get("symbols") or []:
            if isinstance(sym, Mapping):
                ticker = normalize_ticker(sym.get("symbol") or sym.get("symbol_display"))
                if ticker:
                    symbols.add(ticker)
        symbols |= extract_cashtags(body)
        if requested:
            symbols.add(requested)
        author_followers = user.get("followers") if user else None
        try:
            author_followers = int(author_followers) if author_followers is not None else None
        except (TypeError, ValueError):
            author_followers = None
        for ticker in sorted(symbols):
            out.append(
                SocialMessage(
                    source_message_id=mid,
                    ticker=ticker,
                    author=str(user.get("username")) if user and user.get("username") else None,
                    author_followers=author_followers,
                    body=body,
                    sentiment=normalize_sentiment(msg),
                    created_at=str(msg.get("created_at")) if msg.get("created_at") else None,
                    source_url=message_url(msg),
                    raw=msg,
                )
            )
    return out


def fetch_trending_symbols(fetcher: Callable[[str], Mapping[str, Any]], limit: int) -> list[str]:
    if limit <= 0:
        return []
    payload = fetcher(f"{STOCKTWITS_BASE}/trending/symbols.json")
    symbols = []
    for row in payload.get("symbols") or []:
        if isinstance(row, Mapping):
            ticker = normalize_ticker(row.get("symbol") or row.get("symbol_display"))
            instrument_class = str(row.get("instrument_class") or "").lower()
            region = str(row.get("region") or "").upper()
            if ticker and (not instrument_class or instrument_class in {"stock", "etf", "fund"}) and (not region or region == "US"):
                symbols.append(ticker)
    return symbols[:limit]


def fetch_symbol_messages(fetcher: Callable[[str], Mapping[str, Any]], symbol: str, limit: int) -> list[SocialMessage]:
    symbol = quote(normalize_ticker(symbol), safe="")
    payload = fetcher(f"{STOCKTWITS_BASE}/streams/symbol/{symbol}.json?limit={int(limit)}")
    return normalize_messages(payload, requested_symbol=symbol)


def summarize(messages: Iterable[SocialMessage]) -> dict[str, Any]:
    rows = list(messages)
    by_ticker: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[SocialMessage]] = defaultdict(list)
    for row in rows:
        grouped[row.ticker].append(row)
    for ticker, items in sorted(grouped.items()):
        sentiments = Counter(row.sentiment or "unlabeled" for row in items)
        authors = {row.author for row in items if row.author}
        words = Counter()
        for row in items:
            for word in WORD_RE.findall(row.body.lower()):
                if word not in STOPWORDS and not word.startswith("http"):
                    words[word] += 1
        by_ticker[ticker] = {
            "messages": len(items),
            "unique_authors": len(authors),
            "bullish": sentiments.get("bullish", 0),
            "bearish": sentiments.get("bearish", 0),
            "unlabeled": sentiments.get("unlabeled", 0),
            "top_terms": [w for w, _ in words.most_common(8)],
            "sample_urls": [row.source_url for row in items[:3] if row.source_url],
        }
    ranked = sorted(
        by_ticker.items(),
        key=lambda kv: (kv[1]["messages"], kv[1]["unique_authors"], kv[1]["bullish"] - kv[1]["bearish"]),
        reverse=True,
    )
    return {
        "source": "stocktwits",
        "generated_at": utc_now(),
        "message_rows": len(rows),
        "tickers_seen": len(by_ticker),
        "top_tickers": [{"ticker": t, **stats} for t, stats in ranked[:20]],
    }


def persist_run(db_path: str | Path, query: Mapping[str, Any], messages: list[SocialMessage], errors: list[str]) -> tuple[int, int, dict[str, Any]]:
    ensure_tables(db_path)
    summary = summarize(messages)
    con = sqlite3.connect(db_path)
    try:
        cur = con.execute(
            "INSERT INTO social_scanner_runs(source, query_json, summary_json, error_json) VALUES(?,?,?,?)",
            ("stocktwits", json_dumps(query), json_dumps(summary), json_dumps(errors)),
        )
        run_id = int(cur.lastrowid)
        inserted = 0
        for msg in messages:
            cur = con.execute(
                """
                INSERT OR IGNORE INTO social_scanner_messages(
                  run_id, source, source_message_id, ticker, author, author_followers, body,
                  sentiment, created_at, source_url, raw_json, source_fingerprint
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    "stocktwits",
                    msg.source_message_id,
                    msg.ticker,
                    msg.author,
                    msg.author_followers,
                    msg.body,
                    msg.sentiment,
                    msg.created_at,
                    msg.source_url,
                    json_dumps(msg.raw),
                    msg.fingerprint,
                ),
            )
            inserted += int(cur.rowcount or 0)
        con.commit()
        return run_id, inserted, summary
    finally:
        con.close()


def load_symbols(args: argparse.Namespace) -> list[str]:
    symbols: list[str] = []
    if args.symbols:
        symbols.extend(args.symbols)
    if args.symbols_file:
        for line in Path(args.symbols_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                symbols.append(line.split()[0])
    seen = set()
    out = []
    for symbol in symbols:
        ticker = normalize_ticker(symbol)
        if ticker and ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
    return out


def run_scan(args: argparse.Namespace, fetcher: Callable[[str], Mapping[str, Any]] = fetch_json) -> dict[str, Any]:
    errors: list[str] = []
    symbols = load_symbols(args)
    if args.include_trending:
        try:
            for symbol in fetch_trending_symbols(fetcher, args.trending_limit):
                if symbol not in symbols:
                    symbols.append(symbol)
        except Exception as exc:  # keep symbol scans alive when trending endpoint fails
            errors.append(f"trending: {exc}")
    if not symbols:
        symbols = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA"]
    all_messages: list[SocialMessage] = []
    for i, symbol in enumerate(symbols, start=1):
        try:
            all_messages.extend(fetch_symbol_messages(fetcher, symbol, args.message_limit))
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
        if args.sleep_seconds and i < len(symbols):
            time.sleep(args.sleep_seconds)
    query = {
        "symbols": symbols,
        "include_trending": bool(args.include_trending),
        "trending_limit": args.trending_limit,
        "message_limit": args.message_limit,
    }
    if args.dry_run:
        summary = summarize(all_messages)
        return {"dry_run": True, "inserted_messages": 0, "query": query, "summary": summary, "errors": errors}
    run_id, inserted, summary = persist_run(args.db, query, all_messages, errors)
    return {"dry_run": False, "run_id": run_id, "inserted_messages": inserted, "query": query, "summary": summary, "errors": errors}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan Stocktwits social chatter for Wolfy alpha leads.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path; default: /root/.hermes/wolfy/wolfy.db")
    parser.add_argument("--symbols", nargs="*", default=[], help="Tickers/cashtags to scan, e.g. SPY NVDA AAPL")
    parser.add_argument("--symbols-file", help="Optional newline-delimited ticker file")
    parser.add_argument("--include-trending", action="store_true", help="Also scan currently trending U.S. stock/ETF symbols")
    parser.add_argument("--trending-limit", type=int, default=10, help="Max trending symbols to add")
    parser.add_argument("--message-limit", type=int, default=30, help="Max Stocktwits messages per symbol request")
    parser.add_argument("--sleep-seconds", type=float, default=0.25, help="Pause between symbol requests")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and summarize without writing SQLite")
    parser.add_argument("--json", action="store_true", help="Print full JSON result")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_scan(args)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        summary = result["summary"]
        print(f"Stocktwits scan: {summary['message_rows']} message rows, {summary['tickers_seen']} tickers, inserted={result['inserted_messages']}")
        for row in summary["top_tickers"][:10]:
            print(
                f"{row['ticker']}: messages={row['messages']} authors={row['unique_authors']} "
                f"bull={row['bullish']} bear={row['bearish']} terms={','.join(row['top_terms'][:5])}"
            )
        if result["errors"]:
            print("Errors:", "; ".join(result["errors"]), file=sys.stderr)
    return 0 if not result["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
