import argparse
import sqlite3

from stocktwits_social_scanner import (
    fetch_trending_symbols,
    normalize_messages,
    persist_run,
    run_scan,
    summarize,
)


def sample_payload():
    return {
        "messages": [
            {
                "id": 101,
                "body": "$AAPL breakout watch with $QQQ strength",
                "created_at": "2026-06-01T08:00:00Z",
                "user": {"username": "trader1", "followers": 1200},
                "entities": {"sentiment": {"basic": "Bullish"}},
                "symbols": [{"symbol": "AAPL"}],
            },
            {
                "id": 102,
                "body": "$AAPL valuation still stretched",
                "created_at": "2026-06-01T08:01:00Z",
                "user": {"username": "riskmgr", "followers": "88"},
                "entities": {"sentiment": {"basic": "Bearish"}},
                "symbols": [{"symbol": "AAPL"}],
            },
        ]
    }


def test_normalize_messages_expands_cashtags_and_sentiment():
    rows = normalize_messages(sample_payload(), requested_symbol="AAPL")
    tickers = sorted({r.ticker for r in rows})
    assert tickers == ["AAPL", "QQQ"]
    aapl_rows = [r for r in rows if r.ticker == "AAPL"]
    assert len(aapl_rows) == 2
    assert {r.sentiment for r in aapl_rows} == {"bullish", "bearish"}
    assert aapl_rows[0].source_url == "https://stocktwits.com/trader1/message/101"


def test_summarize_counts_authors_and_sentiment():
    summary = summarize(normalize_messages(sample_payload(), requested_symbol="AAPL"))
    top = {row["ticker"]: row for row in summary["top_tickers"]}
    assert top["AAPL"]["messages"] == 2
    assert top["AAPL"]["unique_authors"] == 2
    assert top["AAPL"]["bullish"] == 1
    assert top["AAPL"]["bearish"] == 1


def test_persist_run_dedupes_messages(tmp_path):
    db = tmp_path / "wolfy.db"
    rows = normalize_messages(sample_payload(), requested_symbol="AAPL")
    run_id, inserted, summary = persist_run(db, {"symbols": ["AAPL"]}, rows, [])
    assert run_id == 1
    assert inserted == 3  # message 101 is stored for AAPL and QQQ; message 102 for AAPL
    run_id2, inserted2, _ = persist_run(db, {"symbols": ["AAPL"]}, rows, [])
    assert run_id2 == 2
    assert inserted2 == 0
    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT COUNT(*) FROM social_scanner_runs").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM social_scanner_messages").fetchone()[0] == 3
    finally:
        con.close()


def test_fetch_trending_filters_to_us_equities():
    def fake_fetch(url):
        return {
            "symbols": [
                {"symbol": "SPY", "instrument_class": "ETF", "region": "US"},
                {"symbol": "BTC.X", "instrument_class": "Crypto", "region": "US"},
                {"symbol": "TSLA", "instrument_class": "Stock", "region": "US"},
                {"symbol": "BABA", "instrument_class": "Stock", "region": "CN"},
            ]
        }

    assert fetch_trending_symbols(fake_fetch, 10) == ["SPY", "TSLA"]


def test_run_scan_uses_fake_fetcher_and_dry_run(tmp_path):
    def fake_fetch(url):
        if "trending" in url:
            return {"symbols": [{"symbol": "AAPL", "instrument_class": "Stock", "region": "US"}]}
        return sample_payload()

    args = argparse.Namespace(
        db=str(tmp_path / "wolfy.db"),
        symbols=["SPY"],
        symbols_file=None,
        include_trending=True,
        trending_limit=5,
        message_limit=2,
        sleep_seconds=0,
        dry_run=True,
    )
    result = run_scan(args, fetcher=fake_fetch)
    assert result["dry_run"] is True
    assert result["query"]["symbols"] == ["SPY", "AAPL"]
    assert result["summary"]["message_rows"] >= 4
