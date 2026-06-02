#!/usr/bin/env python3
"""Wolfy insider-buying alpha support module.

Uses SEC Form 4 semantics to turn insider transactions into thesis-support
leads. Insider buying is never a standalone trade trigger for Wolfy; qualified
signals must still pass scanner, Yang technical, and Sentinel risk review.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

BASE = Path("/root/.hermes/wolfy")
DEFAULT_DB = BASE / "wolfy.db"
SEC_UA = os.environ.get("SEC_USER_AGENT", "Hermes Agent Wolfy Research admin@example.com")
OPEN_MARKET_BUY_CODES = {"P"}
EXERCISE_AWARD_CODES = {"A", "M", "F", "G", "J", "D", "S"}
HIGH_QUALITY_ROLE_TERMS = (
    "chief executive", "ceo", "chief financial", "cfo", "chief operating", "coo",
    "president", "chair", "chairman", "chairwoman", "director", "10% owner", "ten percent",
)

INSIDER_SCHEMA = """
CREATE TABLE IF NOT EXISTS insider_transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  cik TEXT,
  accession TEXT,
  filing_date TEXT,
  transaction_date TEXT,
  owner_name TEXT,
  owner_title TEXT,
  officer_title TEXT,
  transaction_code TEXT NOT NULL,
  transaction_type TEXT NOT NULL,
  shares REAL,
  price REAL,
  dollar_value REAL,
  shares_owned_after REAL,
  security_title TEXT,
  source_url TEXT,
  raw_json TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(ticker, accession, owner_name, transaction_date, transaction_code, shares, price)
);
CREATE INDEX IF NOT EXISTS idx_insider_tx_ticker_date ON insider_transactions(ticker, transaction_date DESC);
CREATE INDEX IF NOT EXISTS idx_insider_tx_code ON insider_transactions(transaction_code);

CREATE TABLE IF NOT EXISTS insider_leads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  evaluated_at TEXT NOT NULL DEFAULT (datetime('now')),
  status TEXT NOT NULL,
  score REAL NOT NULL,
  recommended_use TEXT NOT NULL DEFAULT 'thesis_support_only',
  open_market_buy_count INTEGER NOT NULL DEFAULT 0,
  distinct_buyers INTEGER NOT NULL DEFAULT 0,
  total_buy_value REAL NOT NULL DEFAULT 0,
  role_quality TEXT,
  materiality_label TEXT,
  liquidity_label TEXT,
  risk_flags TEXT,
  positive_factors TEXT,
  evidence_json TEXT NOT NULL,
  notes TEXT,
  UNIQUE(ticker, evaluated_at)
);
CREATE INDEX IF NOT EXISTS idx_insider_leads_ticker_eval ON insider_leads(ticker, evaluated_at DESC);
CREATE INDEX IF NOT EXISTS idx_insider_leads_status_score ON insider_leads(status, score DESC);
"""


def ensure_insider_tables(db_path: str | Path = DEFAULT_DB) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        con.executescript(INSIDER_SCHEMA)
        con.commit()
    finally:
        con.close()


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _find_text(node: ET.Element | None, path: str) -> str:
    if node is None:
        return ""
    found = node.find(path)
    return _clean(found.text if found is not None else "")


def parse_form4_xml(xml_text: str, accession: str = "", source_url: str = "") -> list[dict[str, Any]]:
    """Parse a SEC Form 4 ownershipDocument XML into transaction dictionaries."""
    root = ET.fromstring(xml_text)
    ticker = _find_text(root, "./issuer/issuerTradingSymbol").upper()
    cik = _find_text(root, "./issuer/issuerCik")
    owner = root.find("./reportingOwner")
    owner_name = _find_text(owner, "./reportingOwnerId/rptOwnerName")
    rel = owner.find("./reportingOwnerRelationship") if owner is not None else None
    officer_title = _find_text(rel, "./officerTitle")
    owner_roles: list[str] = []
    if _find_text(rel, "./isDirector") in {"1", "true", "True"}:
        owner_roles.append("Director")
    if _find_text(rel, "./isOfficer") in {"1", "true", "True"}:
        owner_roles.append("Officer")
    if _find_text(rel, "./isTenPercentOwner") in {"1", "true", "True"}:
        owner_roles.append("10% Owner")
    if officer_title:
        owner_roles.append(officer_title)
    rows: list[dict[str, Any]] = []
    for tx in root.findall(".//nonDerivativeTransaction"):
        shares = _num(_find_text(tx, "./transactionAmounts/transactionShares/value"))
        price = _num(_find_text(tx, "./transactionAmounts/transactionPricePerShare/value"))
        rows.append({
            "ticker": ticker,
            "cik": cik,
            "accession": accession,
            "filing_date": "",
            "transaction_date": _find_text(tx, "./transactionDate/value"),
            "owner_name": owner_name,
            "owner_title": ", ".join(owner_roles),
            "officer_title": officer_title,
            "transaction_code": _find_text(tx, "./transactionCoding/transactionCode").upper(),
            "shares": shares,
            "price": price,
            "shares_owned_after": _num(_find_text(tx, "./postTransactionAmounts/sharesOwnedFollowingTransaction/value")),
            "security_title": _find_text(tx, "./securityTitle/value"),
            "source_url": source_url,
        })
    return rows


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _transaction_type(code: str, price: float, security_title: str = "") -> str:
    code = code.upper().strip()
    title = security_title.lower()
    if code in OPEN_MARKET_BUY_CODES and price > 0:
        return "open_market_buy"
    if code in {"A"} or "restricted stock" in title or "rsu" in title:
        return "award_or_grant"
    if code in {"M"} or "option" in title:
        return "option_exercise_or_conversion"
    if code == "S":
        return "sale"
    return "non_open_market_or_other"


def _role_quality(rows: list[dict[str, Any]]) -> tuple[str, list[str]]:
    roles = " ".join((r.get("owner_title") or "") + " " + (r.get("officer_title") or "") for r in rows).lower()
    hits = sorted({term for term in HIGH_QUALITY_ROLE_TERMS if term in roles})
    if any(term in hits for term in ["ceo", "chief executive", "cfo", "chief financial"]):
        return "high", hits
    if hits:
        return "medium", hits
    return "low", []


def assess_insider_transactions(
    ticker: str,
    transactions: Iterable[Mapping[str, Any]],
    market_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Score SEC Form 4 transactions as Wolfy thesis support.

    Qualified results are support signals only, not trade triggers.
    """
    ticker = _clean(ticker).upper()
    market_context = dict(market_context or {})
    normalized: list[dict[str, Any]] = []
    for row in transactions:
        code = _clean(row.get("transaction_code") or row.get("code")).upper()
        shares = _num(row.get("shares") or row.get("transaction_shares"))
        price = _num(row.get("price") or row.get("transaction_price"))
        title = _clean(row.get("security_title"))
        transaction_type = _transaction_type(code, price, title)
        normalized.append({
            "ticker": _clean(row.get("ticker") or ticker).upper(),
            "cik": _clean(row.get("cik")),
            "accession": _clean(row.get("accession")),
            "filing_date": _clean(row.get("filing_date")),
            "transaction_date": _clean(row.get("transaction_date")),
            "owner_name": _clean(row.get("owner_name") or row.get("reporting_owner")),
            "owner_title": _clean(row.get("owner_title")),
            "officer_title": _clean(row.get("officer_title")),
            "transaction_code": code,
            "transaction_type": transaction_type,
            "shares": shares,
            "price": price,
            "dollar_value": shares * price if shares and price else 0.0,
            "shares_owned_after": _num(row.get("shares_owned_after")),
            "security_title": title,
            "source_url": _clean(row.get("source_url")),
            "raw": dict(row),
        })

    open_buys = [r for r in normalized if r["transaction_type"] == "open_market_buy"]
    distinct_buyers = len({r["owner_name"].lower() for r in open_buys if r["owner_name"]})
    total_buy_value = sum(r["dollar_value"] for r in open_buys)
    role_quality, role_hits = _role_quality(open_buys)
    market_cap = _num(market_context.get("market_cap"))
    avg_volume = _num(market_context.get("avg_volume"))
    float_shares = _num(market_context.get("float_shares"))

    positive: list[str] = []
    risks: list[str] = []
    score = 0.0

    if open_buys:
        positive.append("open_market_purchase")
        score += 35
    else:
        risks.append("no_open_market_buys")

    if any(r["transaction_code"] in EXERCISE_AWARD_CODES or r["transaction_type"] in {"award_or_grant", "option_exercise_or_conversion"} for r in normalized):
        risks.append("exercise_or_award")
        score -= 20

    if distinct_buyers >= 2:
        positive.append("cluster_buying")
        score += 20
    elif distinct_buyers == 1:
        score += 5

    if role_quality == "high":
        positive.append("high_quality_role")
        score += 15
    elif role_quality == "medium":
        positive.append("credible_role")
        score += 8

    if total_buy_value >= 1_000_000:
        materiality_label = "high"
        positive.append("material_dollar_value")
        score += 15
    elif total_buy_value >= 100_000:
        materiality_label = "medium"
        score += 8
    elif total_buy_value > 0:
        materiality_label = "low"
        score += 2
    else:
        materiality_label = "none"

    if market_cap and total_buy_value and total_buy_value / market_cap >= 0.001:
        positive.append("material_vs_market_cap")
        score += 5

    if avg_volume and avg_volume < 500_000:
        liquidity_label = "thin"
        risks.append("thin_liquidity")
        score -= 15
    else:
        liquidity_label = "acceptable" if avg_volume else "unknown"

    if market_cap and (market_cap < 300_000_000 or (float_shares and float_shares < 15_000_000)):
        risks.append("thin_or_microcap_manipulation_risk")
        score -= 25
    if market_context.get("recent_promotion") or market_context.get("pump_risk"):
        risks.append("promotion_or_pump_risk")
        score -= 25

    score = max(0.0, min(100.0, score))
    hard_reject = "no_open_market_buys" in risks or "thin_or_microcap_manipulation_risk" in risks or "promotion_or_pump_risk" in risks
    lead_qualified = bool(open_buys) and not hard_reject and score >= 55
    status = "qualified" if lead_qualified else "rejected"

    evidence = {
        "ticker": ticker,
        "transaction_count": len(normalized),
        "open_market_buy_count": len(open_buys),
        "distinct_buyers": distinct_buyers,
        "total_buy_value": total_buy_value,
        "role_quality": role_quality,
        "role_hits": role_hits,
        "market_context": market_context,
        "transactions": normalized,
        "disclaimer": "Insider buying is thesis support only and requires independent technical/fundamental/risk confirmation.",
    }
    return {
        "ticker": ticker,
        "status": status,
        "lead_qualified": lead_qualified,
        "score": round(score, 2),
        "recommended_use": "thesis_support_only",
        "open_market_buy_count": len(open_buys),
        "distinct_buyers": distinct_buyers,
        "total_buy_value": round(total_buy_value, 2),
        "role_quality": role_quality,
        "materiality_label": materiality_label,
        "liquidity_label": liquidity_label,
        "positive_factors": positive,
        "risk_flags": risks,
        "transactions": normalized,
        "evidence": evidence,
        "notes": "Use as supporting conviction only; never as a standalone Wolfy trigger.",
    }


def persist_insider_leads(db_path: str | Path, assessment: Mapping[str, Any]) -> dict[str, int]:
    ensure_insider_tables(db_path)
    con = sqlite3.connect(db_path)
    try:
        inserted_tx = 0
        for tx in assessment.get("transactions", []):
            cur = con.execute(
                """
                INSERT OR IGNORE INTO insider_transactions(
                  ticker,cik,accession,filing_date,transaction_date,owner_name,owner_title,officer_title,
                  transaction_code,transaction_type,shares,price,dollar_value,shares_owned_after,security_title,source_url,raw_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    tx["ticker"], tx["cik"], tx["accession"], tx["filing_date"], tx["transaction_date"], tx["owner_name"],
                    tx["owner_title"], tx["officer_title"], tx["transaction_code"], tx["transaction_type"], tx["shares"], tx["price"],
                    tx["dollar_value"], tx["shares_owned_after"], tx["security_title"], tx["source_url"], json.dumps(tx.get("raw", {}), sort_keys=True),
                ),
            )
            inserted_tx += cur.rowcount
        cur = con.execute(
            """
            INSERT INTO insider_leads(
              ticker,status,score,recommended_use,open_market_buy_count,distinct_buyers,total_buy_value,
              role_quality,materiality_label,liquidity_label,risk_flags,positive_factors,evidence_json,notes
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                assessment["ticker"], assessment["status"], assessment["score"], assessment["recommended_use"],
                assessment["open_market_buy_count"], assessment["distinct_buyers"], assessment["total_buy_value"],
                assessment["role_quality"], assessment["materiality_label"], assessment["liquidity_label"],
                json.dumps(assessment["risk_flags"], sort_keys=True), json.dumps(assessment["positive_factors"], sort_keys=True),
                json.dumps(assessment["evidence"], sort_keys=True), assessment.get("notes", ""),
            ),
        )
        con.commit()
        return {"lead_id": cur.lastrowid, "transactions_inserted": inserted_tx}
    finally:
        con.close()


def fetch_sec_company_tickers() -> dict[str, str]:
    req = urllib.request.Request("https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": SEC_UA})
    data = json.load(urllib.request.urlopen(req, timeout=30))
    return {row["ticker"].upper(): str(row["cik_str"]).zfill(10) for row in data.values()}


def _sec_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": SEC_UA, "Accept-Encoding": "identity"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def _sec_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": SEC_UA, "Accept-Encoding": "identity"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="replace")


def fetch_recent_form4_transactions(ticker: str, limit: int = 10) -> list[dict[str, Any]]:
    """Fetch recent SEC Form 4 non-derivative transactions for a ticker.

    Uses SEC company_tickers + submissions JSON + filing index/XML. This is a
    public legal data path; callers should rate-limit when looping tickers.
    """
    ticker = ticker.upper().strip()
    cik = fetch_sec_company_tickers().get(ticker)
    if not cik:
        raise ValueError(f"SEC CIK not found for ticker {ticker}")
    submissions = _sec_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
    recent = submissions.get("filings", {}).get("recent", {})
    rows: list[dict[str, Any]] = []
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])
    for idx, form in enumerate(forms):
        if form != "4" or len(rows) >= limit:
            continue
        accession = accessions[idx]
        accession_dir = accession.replace("-", "")
        primary_doc = primary_docs[idx]
        base_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_dir}"
        doc_url = f"{base_url}/{primary_doc}"
        try:
            xml_text = _sec_text(doc_url)
            parsed = parse_form4_xml(xml_text, accession=accession, source_url=doc_url)
        except ET.ParseError:
            index = _sec_json(f"{base_url}/index.json")
            xml_name = next(
                (
                    item["name"]
                    for item in index.get("directory", {}).get("item", [])
                    if item.get("name", "").lower().endswith(".xml")
                    and item.get("name") not in {"FilingSummary.xml", "MetaLinks.json"}
                ),
                None,
            )
            if not xml_name:
                continue
            doc_url = f"{base_url}/{xml_name}"
            xml_text = _sec_text(doc_url)
            parsed = parse_form4_xml(xml_text, accession=accession, source_url=doc_url)
        for row in parsed:
            row["filing_date"] = filing_dates[idx]
        rows.extend(parsed)
    return rows[:limit]


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assess and persist Wolfy insider-buying leads from SEC Form 4 or JSON transactions.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--transactions-json", help="Path to JSON list of Form 4-like transaction objects")
    parser.add_argument("--sec-fetch", action="store_true", help="Fetch recent public SEC Form 4 filings for --ticker")
    parser.add_argument("--limit", type=int, default=10, help="Max SEC transactions to fetch")
    parser.add_argument("--market-context-json", help="Optional JSON object with market_cap, avg_volume, float_shares, promotion flags")
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args(argv)
    if args.sec_fetch:
        txs = fetch_recent_form4_transactions(args.ticker, args.limit)
    elif args.transactions_json:
        txs = json.loads(Path(args.transactions_json).read_text())
    else:
        raise SystemExit("Provide --transactions-json or --sec-fetch")
    market_context = json.loads(Path(args.market_context_json).read_text()) if args.market_context_json else {}
    assessment = assess_insider_transactions(args.ticker, txs, market_context)
    result: dict[str, Any] = {"assessment": assessment}
    if args.persist:
        result["persisted"] = persist_insider_leads(args.db, assessment)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
