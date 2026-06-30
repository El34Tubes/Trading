#!/usr/bin/env python3
"""Build Wolfy's tiered stock universe for Massive backfills.

This is a selector, not a recommender. It tags active U.S. symbols into
blue-chip, large-cap, mid-cap, small-cap, and ETF buckets using public index
membership plus Wolfy risk rules. It avoids microcap/promo/SPAC-heavy names by
using S&P index membership as the initial liquid/Robinhood-safe universe.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence

DEFAULT_DSN = os.environ.get("WOLFY_POSTGRES_DSN", "dbname=wolfy user=root host=/var/run/postgresql")

INDEX_URLS = {
    "blue_chip": "https://en.wikipedia.org/wiki/S%26P_100",
    "large_cap": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "mid_cap": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
    "small_cap": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
}

CORE_ETFS = [
    "SPY", "QQQ", "IWM", "DIA", "SMH",
    "XLK", "XLF", "XLY", "XLI", "XLE", "XLV", "XLP", "XLU", "XLB", "XLRE", "XLC",
]

EXCLUDE_NAME_PATTERNS = re.compile(
    r"\b(SPAC|Acquisition|Blank Check|Warrant|Rights|Unit|Depositary|ADR|ADS|Preferred|Notes?|Bond|CLO|2X|3X|Inverse|Bear|Ultra|Daily)\b",
    re.IGNORECASE,
)

TIER_RULES = {
    "blue_chip": {
        "description": "S&P 100 / household institutional leaders; highest-quality liquid common stocks.",
        "role": "core leadership/backtest anchor and primary candidate pool",
        "min_price": 20,
        "min_avg_dollar_vol": 100_000_000,
        "max_position_risk_multiplier": 1.0,
        "notes": "Prefer mega/large durable franchises; still requires deterministic signal/risk gates.",
    },
    "large_cap": {
        "description": "S&P 500 constituents not already tagged blue-chip.",
        "role": "broad liquid large-cap opportunity set",
        "min_price": 15,
        "min_avg_dollar_vol": 50_000_000,
        "max_position_risk_multiplier": 0.85,
        "notes": "Higher confidence than mid/small, but no automatic approval.",
    },
    "mid_cap": {
        "description": "S&P MidCap 400 constituents.",
        "role": "growth/valuation dislocation hunting ground",
        "min_price": 10,
        "min_avg_dollar_vol": 25_000_000,
        "max_position_risk_multiplier": 0.65,
        "notes": "Require stronger liquidity and volatility checks before paper trades.",
    },
    "small_cap": {
        "description": "S&P SmallCap 600 constituents only; microcaps excluded by design.",
        "role": "selective alpha leads, watch-only until clean liquidity/manipulation gates pass",
        "min_price": 5,
        "min_avg_dollar_vol": 10_000_000,
        "max_position_risk_multiplier": 0.35,
        "notes": "No low-float/promo/penny behavior; size down and use stricter stops.",
    },
    "etf_core": {
        "description": "Core index/sector/theme ETFs used for regime, benchmarks, and ETF candidates.",
        "role": "regime context and lower single-name risk alternatives",
        "min_price": 10,
        "min_avg_dollar_vol": 25_000_000,
        "max_position_risk_multiplier": 0.8,
        "notes": "ETFs are tracked separately from cap-tier common stocks.",
    },
}

@dataclass(frozen=True)
class IndexMember:
    symbol: str
    name: str | None
    tier: str
    source_url: str


def _strip_tags(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", value)).replace("\xa0", " ").strip()


def _clean_symbol(value: str) -> str:
    symbol = _strip_tags(value).split()[0].upper().replace("-", ".")
    return re.sub(r"[^A-Z0-9.]", "", symbol)


def _first_wikitable(html_text: str, *, table_id: str | None = None) -> str:
    if table_id:
        id_pos = html_text.find(f'id="{table_id}"')
        if id_pos >= 0:
            start = html_text.rfind("<table", 0, id_pos)
            end = html_text.find("</table>", id_pos)
            if start >= 0 and end >= 0:
                return html_text[start : end + len("</table>")]
    marker = html_text.find("wikitable")
    if marker < 0:
        return ""
    start = html_text.rfind("<table", 0, marker)
    end = html_text.find("</table>", marker)
    return html_text[start : end + len("</table>")] if start >= 0 and end >= 0 else ""


def parse_index_members(html_text: str, tier: str, source_url: str) -> list[IndexMember]:
    table = _first_wikitable(html_text, table_id="constituents")
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, flags=re.S | re.I)
    members: list[IndexMember] = []
    seen: set[str] = set()
    for row in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.S | re.I)
        if len(cells) < 2:
            continue
        symbol = _clean_symbol(cells[0])
        if not symbol or symbol in {"SYMBOL", "CLOSING", "INTRADAY"} or symbol in seen:
            continue
        name = _strip_tags(cells[1]) or None
        members.append(IndexMember(symbol=symbol, name=name, tier=tier, source_url=source_url))
        seen.add(symbol)
    return members


def fetch_index_members(urls: dict[str, str] = INDEX_URLS) -> list[IndexMember]:
    all_members: list[IndexMember] = []
    for tier, url in urls.items():
        request = urllib.request.Request(url, headers={"User-Agent": "Hermes-Wolfy/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8", "replace")
        all_members.extend(parse_index_members(text, tier, url))
    return all_members


def ensure_schema(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS universe_tier_rules (
          tier text PRIMARY KEY,
          description text NOT NULL,
          role text NOT NULL,
          min_price numeric NOT NULL,
          min_avg_dollar_vol numeric NOT NULL,
          max_position_risk_multiplier numeric NOT NULL,
          notes text NOT NULL,
          updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS universe_backfill_targets (
          symbol text PRIMARY KEY,
          tier text NOT NULL,
          source text NOT NULL,
          name text,
          priority int NOT NULL,
          active boolean NOT NULL DEFAULT true,
          reason text NOT NULL,
          selected_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_universe_backfill_targets_tier_priority ON universe_backfill_targets(tier, priority)")
    conn.execute("ALTER TABLE universe_symbols ADD COLUMN IF NOT EXISTS wolfy_tier text")
    conn.execute("ALTER TABLE universe_symbols ADD COLUMN IF NOT EXISTS tier_source text")
    conn.execute("ALTER TABLE universe_symbols ADD COLUMN IF NOT EXISTS backfill_priority int")
    conn.execute("ALTER TABLE universe_symbols ADD COLUMN IF NOT EXISTS backfill_enabled boolean NOT NULL DEFAULT false")
    conn.execute("ALTER TABLE universe_symbols ADD COLUMN IF NOT EXISTS tier_notes text")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_universe_symbols_wolfy_tier ON universe_symbols(wolfy_tier, backfill_enabled, backfill_priority)")


def upsert_rules(conn) -> None:
    for tier, rule in TIER_RULES.items():
        conn.execute(
            """
            INSERT INTO universe_tier_rules(tier, description, role, min_price, min_avg_dollar_vol, max_position_risk_multiplier, notes, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,now())
            ON CONFLICT (tier) DO UPDATE SET
              description=EXCLUDED.description,
              role=EXCLUDED.role,
              min_price=EXCLUDED.min_price,
              min_avg_dollar_vol=EXCLUDED.min_avg_dollar_vol,
              max_position_risk_multiplier=EXCLUDED.max_position_risk_multiplier,
              notes=EXCLUDED.notes,
              updated_at=now()
            """,
            (tier, rule["description"], rule["role"], rule["min_price"], rule["min_avg_dollar_vol"], rule["max_position_risk_multiplier"], rule["notes"]),
        )


def _risk_allowed(symbol: str, name: str | None, is_etf: bool = False) -> tuple[bool, str]:
    if symbol.endswith("W") or symbol.endswith("U") or symbol.endswith("R"):
        return False, "warrant/unit/right suffix risk"
    if name and EXCLUDE_NAME_PATTERNS.search(name):
        # Let our hand-picked core ETFs through despite generic ETF words; block leveraged/inverse/CLO/etc.
        if is_etf and symbol in CORE_ETFS and not re.search(r"\b(2X|3X|Inverse|Bear|Ultra|Daily|CLO)\b", name, re.I):
            return True, "core ETF exception"
        return False, "name risk filter"
    return True, "index/liquidity seed"


def select_targets(conn, members: Sequence[IndexMember]) -> dict:
    # Priority: blue_chip, large_cap, mid_cap, small_cap, ETF core.
    tier_order = {"blue_chip": 1, "large_cap": 2, "mid_cap": 3, "small_cap": 4, "etf_core": 5}
    by_symbol: dict[str, IndexMember] = {}
    for member in members:
        current = by_symbol.get(member.symbol)
        if current is None or tier_order[member.tier] < tier_order[current.tier]:
            by_symbol[member.symbol] = member

    rows = conn.execute("SELECT symbol, name, is_etf, active FROM universe_symbols").fetchall()
    ref = {str(symbol).upper(): {"name": name, "is_etf": bool(is_etf), "active": bool(active)} for symbol, name, is_etf, active in rows}

    # Include core ETFs separately.
    for symbol in CORE_ETFS:
        info = ref.get(symbol, {})
        by_symbol[symbol] = IndexMember(symbol=symbol, name=info.get("name") or symbol, tier="etf_core", source_url="wolfy-core-etf-list")

    inserted = 0
    rejected = 0
    tier_counts: dict[str, int] = {tier: 0 for tier in TIER_RULES}
    for symbol in sorted(by_symbol):
        member = by_symbol[symbol]
        info = ref.get(symbol)
        if not info or not info.get("active"):
            rejected += 1
            continue
        is_etf = bool(info.get("is_etf"))
        if member.tier != "etf_core" and is_etf:
            rejected += 1
            continue
        name = member.name or info.get("name")
        allowed, reason = _risk_allowed(symbol, name, is_etf=is_etf)
        if not allowed:
            rejected += 1
            continue
        tier_counts[member.tier] += 1
        priority = tier_order[member.tier] * 100000 + tier_counts[member.tier]
        full_reason = f"{reason}; tier={member.tier}; source={member.source_url}"
        conn.execute(
            """
            INSERT INTO universe_backfill_targets(symbol, tier, source, name, priority, active, reason, selected_at)
            VALUES (%s,%s,%s,%s,%s,true,%s,now())
            ON CONFLICT (symbol) DO UPDATE SET
              tier=EXCLUDED.tier,
              source=EXCLUDED.source,
              name=COALESCE(EXCLUDED.name, universe_backfill_targets.name),
              priority=EXCLUDED.priority,
              active=true,
              reason=EXCLUDED.reason,
              selected_at=now()
            """,
            (symbol, member.tier, member.source_url, name, priority, full_reason),
        )
        conn.execute(
            """
            UPDATE universe_symbols
            SET wolfy_tier=%s, tier_source=%s, backfill_priority=%s, backfill_enabled=true, tier_notes=%s
            WHERE symbol=%s
            """,
            (member.tier, member.source_url, priority, full_reason, symbol),
        )
        inserted += 1
    conn.execute(
        """
        UPDATE universe_symbols u
        SET backfill_enabled=false
        WHERE backfill_enabled=true
          AND NOT EXISTS (SELECT 1 FROM universe_backfill_targets t WHERE t.symbol=u.symbol AND t.active=true)
        """
    )
    return {"selected": inserted, "rejected_or_missing": rejected, "tier_counts": tier_counts}


def build_universe(*, dsn: str = DEFAULT_DSN, fetch_live: bool = True, fixture_members: Sequence[IndexMember] | None = None) -> dict:
    import psycopg

    members = list(fixture_members) if fixture_members is not None else fetch_index_members()
    with psycopg.connect(dsn) as conn:
        ensure_schema(conn)
        upsert_rules(conn)
        result = select_targets(conn, members)
        totals = conn.execute(
            "SELECT tier, count(*) FROM universe_backfill_targets WHERE active GROUP BY tier ORDER BY min(priority)"
        ).fetchall()
    result.update({"members_seen": len(members), "active_targets_by_tier": {tier: count for tier, count in totals}, "built_at": datetime.now(timezone.utc).isoformat()})
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Wolfy's blue/mid/small/ETF tiered Massive backfill universe")
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    args = parser.parse_args(argv)
    print(json.dumps(build_universe(dsn=args.dsn), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
