from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from eod_price_features import PriceBar, compute_and_store_features, ingest_price_bars
from recommendation_universe import (
    AdjustedDailyBarObservation,
    MarketCapObservation,
    UniverseSecurityEvidence,
    build_universe_snapshot,
    persist_universe_snapshot,
)
from security_master import SecurityEligibilityDecision
from test_db import test_connection


def _bars(ticker: str, *, start: date = date(2099, 1, 1), n: int = 35, volume: int = 2_000_000) -> list[PriceBar]:
    rows: list[PriceBar] = []
    close = Decimal("20")
    for i in range(n):
        close += Decimal("0.75")
        vol = volume * (3 if i == n - 1 else 1)
        rows.append(PriceBar(ticker, start + timedelta(days=i), close - Decimal("0.5"), close + Decimal("0.5"), close - Decimal("0.75"), close, vol))
    return rows


def _breakout_bars(
    ticker: str,
    *,
    start: date = date(2099, 1, 1),
    n: int = 35,
    start_close: Decimal = Decimal("50"),
    daily_step: Decimal = Decimal("0.30"),
    breakout_lift: Decimal = Decimal("2.00"),
    volume: int = 2_000_000,
) -> list[PriceBar]:
    rows: list[PriceBar] = []
    close = start_close
    for i in range(n):
        close += daily_step
        if i == n - 1:
            close += breakout_lift
        vol = volume * (2 if i == n - 1 else 1)
        rows.append(PriceBar(ticker, start + timedelta(days=i), close - Decimal("0.25"), close + Decimal("0.40"), close - Decimal("0.50"), close, vol))
    return rows


def _cleanup(conn, tickers: list[str]) -> None:
    unit_tickers = [ticker for ticker in tickers if ticker != "SPY"]
    if unit_tickers:
        conn.execute("DELETE FROM paper_trades WHERE ticker = ANY(%s)", (unit_tickers,))
        conn.execute("DELETE FROM recommendations WHERE ticker = ANY(%s)", (unit_tickers,))
        conn.execute("DELETE FROM setups WHERE ticker = ANY(%s)", (unit_tickers,))
        conn.execute("DELETE FROM signals WHERE ticker = ANY(%s)", (unit_tickers,))
        conn.execute("DELETE FROM earnings_calendar WHERE ticker = ANY(%s)", (unit_tickers,))
        conn.execute("DELETE FROM features WHERE ticker = ANY(%s)", (unit_tickers,))
        conn.execute("DELETE FROM prices WHERE ticker = ANY(%s)", (unit_tickers,))
        conn.execute("DELETE FROM universe_symbols WHERE symbol = ANY(%s)", (unit_tickers,))
    if "SPY" in tickers:
        # SPY is the live benchmark; tests may insert isolated 2099 fixture rows,
        # but cleanup must never erase real historical SPY prices/features.
        conn.execute("DELETE FROM features WHERE ticker='SPY' AND dt >= DATE '2099-01-01'")
        conn.execute("DELETE FROM prices WHERE ticker='SPY' AND dt >= DATE '2099-01-01'")


def _restore_default_strategy_statuses(conn) -> None:
    # Tests run against the live Wolfy Postgres database. Do not reset real
    # strategy governance fields here; strategy status is production state.
    return None


def _persist_eligible_snapshot(conn, *, ticker: str, signal_dt: date, price_bars: list[PriceBar]) -> None:
    decision_at = datetime.combine(signal_dt, datetime.max.time(), tzinfo=timezone.utc)
    identity = SecurityEligibilityDecision(
        ticker=ticker,
        decision_at=decision_at,
        eligible=True,
        reason_codes=("eligible_us_common_stock",),
        identity_observation_ids=(f"identity:{ticker}",),
        risk_observation_ids=(),
        denylist_observation_ids=(),
    )
    observed_bars = tuple(
        AdjustedDailyBarObservation(
            observation_id=f"bar:{ticker}:{bar.dt}",
            ticker=ticker,
            session=bar.dt,
            close=Decimal(bar.close),
            volume=bar.volume,
            provider="unit-test",
            source_url="https://example.test/adjusted-bars",
            available_at=decision_at - timedelta(minutes=1),
            adjusted=True,
        )
        for bar in price_bars
    )
    item = UniverseSecurityEvidence(
        ticker=ticker,
        sector="Industrials",
        identity_decision=identity,
        market_cap_observations=(
            MarketCapObservation(
                observation_id=f"cap:{ticker}",
                ticker=ticker,
                market_cap=Decimal("1000000000"),
                provider="unit-test",
                source_url="https://example.test/market-cap",
                effective_at=decision_at - timedelta(hours=2),
                available_at=decision_at - timedelta(hours=1),
            ),
        ),
        bars=observed_bars,
    )
    persist_universe_snapshot(
        conn,
        build_universe_snapshot(
            signal_dt=signal_dt,
            decision_at=decision_at,
            evidence=(item,),
        ),
    )


def test_recommendation_universe_requires_immutable_policy_snapshot():
    pytest.importorskip("psycopg")
    from eod_signals import recommendation_universe_tickers, seed_default_strategies

    tickers = ["ZZBLUE", "ZZUNSNAP"]
    signal_dt = date(2099, 2, 4)
    with test_connection() as conn:
        try:
            seed_default_strategies(conn)
            _cleanup(conn, tickers)
            for symbol in tickers:
                conn.execute(
                    """
                    INSERT INTO universe_symbols(symbol, name, source, active, wolfy_tier, backfill_enabled)
                    VALUES (%s, %s, 'unit-test', true, 'small_cap', true)
                    """,
                    (symbol, symbol),
                )
                ticker_bars = _breakout_bars(symbol)
                ingest_price_bars(conn, ticker_bars, source="unit-snapshot-universe")
                compute_and_store_features(conn, tickers=[symbol], sma_fast_window=5, sma_slow_window=20, volume_window=5, atr_window=5, min_dollar_vol=Decimal("1000"))
            _persist_eligible_snapshot(
                conn,
                ticker="ZZBLUE",
                signal_dt=signal_dt,
                price_bars=_breakout_bars("ZZBLUE"),
            )
            result = recommendation_universe_tickers(conn, signal_dt=signal_dt, min_history_bars=20)
        finally:
            _cleanup(conn, tickers)

    assert result == ["ZZBLUE"]


def test_generate_eod_signals_can_use_broad_recommendation_universe_when_tickers_omitted():
    pytest.importorskip("psycopg")
    from eod_signals import generate_eod_signals, seed_default_strategies

    tickers = ["ZZAUTO", "SPY"]
    signal_dt = date(2099, 2, 4)
    with test_connection() as conn:
        try:
            seed_default_strategies(conn)
            _restore_default_strategy_statuses(conn)
            _cleanup(conn, tickers)
            for symbol in tickers:
                conn.execute(
                    "INSERT INTO universe_symbols(symbol, name, source, active, wolfy_tier, backfill_enabled) VALUES (%s, %s, 'unit-test', true, 'small_cap', true) ON CONFLICT (symbol) DO UPDATE SET active=true",
                    (symbol, symbol),
                )
            auto_bars = _breakout_bars(
                "ZZAUTO",
                start_close=Decimal("200"),
                daily_step=Decimal("0.70"),
                breakout_lift=Decimal("2.50"),
            )
            ingest_price_bars(conn, auto_bars, source="unit-auto-universe")
            ingest_price_bars(conn, _breakout_bars("SPY", daily_step=Decimal("0.05"), breakout_lift=Decimal("0.00")), source="unit-auto-universe")
            compute_and_store_features(conn, tickers=tickers, sma_fast_window=5, sma_slow_window=20, volume_window=5, atr_window=5, min_dollar_vol=Decimal("1000"))
            _persist_eligible_snapshot(
                conn,
                ticker="ZZAUTO",
                signal_dt=signal_dt,
                price_bars=auto_bars,
            )

            result = generate_eod_signals(conn, tickers=None, signal_dt=signal_dt, momentum_lookback_days=20, momentum_top_n=1)
            adapted = conn.execute(
                """SELECT s.raw
                     FROM signals AS s
                     JOIN strategies AS st ON st.id=s.strategy_id
                    WHERE s.ticker='ZZAUTO' AND s.dt=%s
                      AND st.name='liquid_rs_breakout_close_confirm_1r'""",
                (signal_dt,),
            ).fetchone()
        finally:
            _cleanup(conn, tickers)
            _restore_default_strategy_statuses(conn)

    assert result["universe_source"] == "immutable_mid_small_snapshot"
    assert "ZZAUTO" in result["tickers_considered"]
    assert result["signals_by_strategy"]["liquid_rs_breakout_continuation"] >= 1
    assert adapted is not None
    assert adapted[0]["common_setup_evaluation"]["strategy_version"] == "approved-2026-08-03"
    assert adapted[0]["common_setup_evaluation"]["reason_codes"] == ["passed"]
    assert adapted[0]["common_setup_candidate_terms"]["stop"] == adapted[0]["prior_5d_high"]


def test_seed_default_strategies_includes_rs_breakout_as_research_only():
    pytest.importorskip("psycopg")
    from eod_signals import seed_default_strategies

    with test_connection() as conn:
        seed_default_strategies(conn)
        _restore_default_strategy_statuses(conn)
        rows = conn.execute(
            "SELECT name, setup_type, status, params, notes FROM strategies WHERE name IN ('liquid_rs_breakout_continuation','liquid_rs_breakout_tight_risk_volume','liquid_rs_breakout_close_confirm_1r')"
        ).fetchall()

    by_name = {row[0]: row for row in rows}
    row = by_name["liquid_rs_breakout_continuation"]
    assert row[1] == "rs_breakout_continuation"
    assert row[2] == "research_only"
    assert row[3]["requires_backtest"] is True
    assert "Human approval required" in row[4]
    tight = by_name["liquid_rs_breakout_tight_risk_volume"]
    assert tight[2] == "research_only"
    assert tight[3]["parent_strategy"] == "liquid_rs_breakout_continuation"
    assert tight[3]["max_stop_risk_pct"] == "0.04"
    close_confirm = by_name["liquid_rs_breakout_close_confirm_1r"]
    assert close_confirm[2] in {"research_only", "candidate", "approved"}
    assert close_confirm[3]["market_regime"] == "SPY_above_50_sma"
    assert close_confirm[3]["stop_rule"] == "close_below_breakout_level"
    assert close_confirm[3]["target_r"] == "1.0"


def test_generate_liquid_rs_breakout_continuation_signal():
    pytest.importorskip("psycopg")
    from eod_signals import generate_eod_signals, seed_default_strategies

    tickers = ["ZZRSBO", "SPY"]
    signal_dt = date(2099, 2, 4)
    with test_connection() as conn:
        try:
            seed_default_strategies(conn)
            _restore_default_strategy_statuses(conn)
            _cleanup(conn, tickers)
            ingest_price_bars(conn, _breakout_bars("ZZRSBO", daily_step=Decimal("0.70"), breakout_lift=Decimal("2.50")), source="unit-rs-breakout")
            ingest_price_bars(conn, _breakout_bars("SPY", daily_step=Decimal("0.05"), breakout_lift=Decimal("0.00")), source="unit-rs-breakout")
            compute_and_store_features(conn, tickers=tickers, sma_fast_window=5, sma_slow_window=20, volume_window=5, atr_window=5, min_dollar_vol=Decimal("1000"))

            result = generate_eod_signals(conn, tickers=["ZZRSBO"], signal_dt=signal_dt, momentum_lookback_days=20, momentum_top_n=1)
            row = conn.execute(
                """
                SELECT st.status, s.direction, s.raw
                FROM signals s JOIN strategies st ON st.id=s.strategy_id
                WHERE s.ticker=%s AND s.dt=%s AND st.name='liquid_rs_breakout_continuation'
                """,
                ("ZZRSBO", signal_dt),
            ).fetchone()
            setup_count = conn.execute("SELECT COUNT(*) FROM setups WHERE ticker=%s AND created_dt=%s", ("ZZRSBO", signal_dt)).fetchone()[0]
        finally:
            _cleanup(conn, tickers)
            _restore_default_strategy_statuses(conn)

    assert result["signals_by_strategy"]["liquid_rs_breakout_continuation"] == 1
    assert row is not None
    assert row[0] == "research_only"
    assert row[1] == "long"
    raw = row[2]
    assert raw["strategy"] == "liquid_rs_breakout_continuation"
    assert raw["gate_status"] == "research_only"
    assert Decimal(str(raw["rs_excess_20d"])) > 0
    assert Decimal(str(raw["vol_ratio"])) >= Decimal("1.2")
    assert raw["within_5pct_recent_high"] is True
    assert raw["stop_rule"] == "prior_5_day_low"
    assert raw["max_hold_days"] == 10
    assert raw["option_liquidity_hard_gate"] is False
    assert setup_count == 0


def test_generate_eod_signals_seeds_research_only_strategies_and_writes_deterministic_signals():
    pytest.importorskip("psycopg")
    from eod_signals import generate_eod_signals, seed_default_strategies

    tickers = ["ZZSIG", "ZZMOM"]
    signal_dt = date(2099, 2, 4)
    with test_connection() as conn:
        try:
            seed_default_strategies(conn)
            _restore_default_strategy_statuses(conn)
            _cleanup(conn, tickers)
            for ticker in tickers:
                ingest_price_bars(conn, _bars(ticker), source="unit-eod-signals")
            compute_and_store_features(conn, tickers=tickers, sma_fast_window=3, sma_slow_window=5, volume_window=3, atr_window=3, min_dollar_vol=Decimal("1000"))
            conn.execute("INSERT INTO earnings_calendar(ticker, event_dt, session, confirmed) VALUES (%s,%s,'amc',true) ON CONFLICT (ticker,event_dt) DO UPDATE SET confirmed=EXCLUDED.confirmed", ("ZZSIG", signal_dt - timedelta(days=1)))

            result = generate_eod_signals(conn, tickers=tickers, signal_dt=signal_dt, momentum_lookback_days=20, momentum_top_n=2)
            rows = conn.execute(
                """
                SELECT st.name, st.status, s.ticker, s.direction, s.raw
                FROM signals s JOIN strategies st ON st.id=s.strategy_id
                WHERE s.ticker = ANY(%s) AND s.dt=%s
                ORDER BY st.name, s.ticker
                """,
                (tickers, signal_dt),
            ).fetchall()
        finally:
            _cleanup(conn, tickers)
            _restore_default_strategy_statuses(conn)

    assert result["signals_upserted"] >= 3
    names = {(row[0], row[1]) for row in rows}
    assert ("pead", "research_only") in names
    assert any(name == "trend_volume_vol_regime" and status in {"research_only", "candidate", "approved"} for name, status in names)
    assert ("sector_cross_sectional_momentum", "research_only") in names
    assert all(row[3] == "long" for row in rows)
    assert all(row[4]["gate_status"] in {"research_only", "candidate", "approved"} for row in rows)


def test_write_approved_paper_recommendations_only_uses_approved_signals_and_caps_daily_rows():
    pytest.importorskip("psycopg")
    from eod_signals import seed_default_strategies, write_approved_paper_recommendations

    signal_dt = date(2099, 2, 4)
    tickers = ["ZZREC1", "ZZREC2", "ZZREC3", "ZZREC4", "ZZBLOCK"]
    with test_connection() as conn:
        try:
            seed_default_strategies(conn)
            _cleanup(conn, tickers)
            approved_id = conn.execute("SELECT id FROM strategies WHERE name='liquid_rs_breakout_close_confirm_1r'").fetchone()[0]
            blocked_id = conn.execute("SELECT id FROM strategies WHERE name='liquid_rs_breakout_continuation'").fetchone()[0]
            conn.execute(
                """
                UPDATE strategies
                SET status='approved',
                    metadata=coalesce(metadata, '{}'::jsonb) ||
                        '{"approval_scope":"paper_only_no_live_execution","paper_recommendation_approval":true}'::jsonb
                WHERE id=%s
                """,
                (approved_id,),
            )
            conn.execute("UPDATE strategies SET status='research_only' WHERE id=%s", (blocked_id,))
            for idx, ticker in enumerate(tickers, start=1):
                ingest_price_bars(conn, _breakout_bars(ticker, start_close=Decimal("50") + idx), source="unit-recommendation-writer")
                compute_and_store_features(conn, tickers=[ticker], sma_fast_window=5, sma_slow_window=20, volume_window=5, atr_window=5, min_dollar_vol=Decimal("1000"))
                raw = {
                    "strategy": "liquid_rs_breakout_close_confirm_1r" if ticker != "ZZBLOCK" else "liquid_rs_breakout_continuation",
                    "close": str(Decimal("60") + idx),
                    "prior_5d_high": str(Decimal("59") + idx),
                    "prior_5d_low": str(Decimal("57") + idx),
                    "invalidation": str(Decimal("59") + idx),
                    "target_r": "1.0",
                    "stop_rule": "close_below_breakout_level",
                    "rs_excess_20d": "0.05",
                    "vol_ratio": "1.8",
                    "preferred_instrument": "2-3wk slightly OTM call spread",
                    "option_liquidity_hard_gate": False,
                }
                conn.execute(
                    """
                    INSERT INTO signals(ticker, dt, strategy_id, direction, raw)
                    VALUES (%s,%s,%s,'long',%s::jsonb)
                    ON CONFLICT (ticker, dt, strategy_id) DO UPDATE SET raw=EXCLUDED.raw
                    """,
                    (ticker, signal_dt, approved_id if ticker != "ZZBLOCK" else blocked_id, __import__("json").dumps(raw)),
                )

            result = write_approved_paper_recommendations(conn, signal_dt=signal_dt, tickers=tickers, max_recommendations=3, dry_run=False)
            rows = conn.execute("SELECT ticker, status, recommendation_type, entry_trigger, stop, target, position_size_suggestion, notes FROM recommendations WHERE ticker = ANY(%s) ORDER BY ticker", (tickers,)).fetchall()
        finally:
            _cleanup(conn, tickers)

    assert result["recommendations_created"] == 3
    assert result["blocked_by_strategy_status"] == 1
    assert [row[0] for row in rows] == ["ZZREC1", "ZZREC2", "ZZREC3"]
    assert all(row[1] == "paper_candidate" for row in rows)
    assert all(row[2] == "equity_plus_option_spread_when_data_exists" for row in rows)
    assert all("EOD close" in row[3] for row in rows)
    assert all("5.00%" in row[6] for row in rows)
    assert rows[0][7]["paper_entry_baseline"] == "eod_close"
    assert rows[0][7]["review_gate_required"] is False


def test_runtime_schema_helper_does_not_create_recommendation_unique_indexes():
    from eod_signals import ensure_signal_schema

    class RecordingConnection:
        def __init__(self) -> None:
            self.statements: list[str] = []

        def execute(self, statement, params=None):
            del params
            self.statements.append(str(statement))
            return self

        def fetchone(self):
            return None

    conn = RecordingConnection()
    ensure_signal_schema(conn)
    runtime_sql = "\n".join(conn.statements).lower()
    assert "uq_experimental_paper_recommendation_signal" not in runtime_sql
    assert "uq_paper_recommendation_signal" not in runtime_sql
    assert "duplicate experimental paper recommendations" not in runtime_sql


def test_log_approved_paper_recommendation_trades_creates_open_paper_rows_idempotently():
    pytest.importorskip("psycopg")
    from eod_signals import log_approved_paper_recommendation_trades, seed_default_strategies, write_approved_paper_recommendations

    signal_dt = date(2099, 2, 4)
    tickers = ["ZZPLOG1", "ZZPLOG2", "ZZPLOG3", "ZZPLOG4"]
    with test_connection() as conn:
        try:
            seed_default_strategies(conn)
            _cleanup(conn, tickers)
            approved_id = conn.execute("SELECT id FROM strategies WHERE name='liquid_rs_breakout_close_confirm_1r'").fetchone()[0]
            conn.execute(
                """
                UPDATE strategies
                SET status='approved',
                    metadata=coalesce(metadata, '{}'::jsonb) ||
                        '{"approval_scope":"paper_only_no_live_execution","paper_recommendation_approval":true}'::jsonb
                WHERE id=%s
                """,
                (approved_id,),
            )
            for idx, ticker in enumerate(tickers, start=1):
                raw = {
                    "strategy": "liquid_rs_breakout_close_confirm_1r",
                    "close": str(Decimal("60") + idx),
                    "invalidation": str(Decimal("59") + idx),
                    "prior_5d_high": str(Decimal("59") + idx),
                    "target_r": "1.0",
                    "rs_excess_20d": "0.04",
                    "vol_ratio": "1.6",
                    "preferred_instrument": "2-3wk slightly OTM call spread",
                }
                conn.execute(
                    """
                    INSERT INTO signals(ticker, dt, strategy_id, direction, raw)
                    VALUES (%s,%s,%s,'long',%s::jsonb)
                    ON CONFLICT (ticker, dt, strategy_id) DO UPDATE SET raw=EXCLUDED.raw
                    """,
                    (ticker, signal_dt, approved_id, __import__("json").dumps(raw)),
                )
            write_approved_paper_recommendations(conn, signal_dt=signal_dt, tickers=tickers, max_recommendations=3, dry_run=False)

            first = log_approved_paper_recommendation_trades(conn, signal_dt=signal_dt, tickers=tickers, max_trades=10, dry_run=False)
            second = log_approved_paper_recommendation_trades(conn, signal_dt=signal_dt, tickers=tickers, max_trades=10, dry_run=False)
            rows = conn.execute(
                """
                SELECT pt.ticker, pt.recommendation_id, pt.status, pt.entry_date, pt.entry_price, pt.quantity, pt.stop_price, pt.target_price, pt.instrument, pt.data_source, pt.notes, r.status
                FROM paper_trades pt JOIN recommendations r ON r.id::text=pt.recommendation_id
                WHERE pt.ticker = ANY(%s)
                ORDER BY pt.ticker
                """,
                (tickers,),
            ).fetchall()
        finally:
            _cleanup(conn, tickers)

    assert first["paper_trades_created"] == 3
    assert first["blocked_by_strategy_status"] == 0
    assert second["paper_trades_created"] == 0
    assert second["skipped_existing"] == 3
    assert [row[0] for row in rows] == ["ZZPLOG1", "ZZPLOG2", "ZZPLOG3"]
    assert all(row[2] == "open" for row in rows)
    assert all(row[3] == signal_dt for row in rows)
    assert all(row[4] is not None and row[6] is not None and row[7] is not None for row in rows)
    assert rows[0][5] == pytest.approx(250.0)
    assert all(row[8] == "equity_fallback_plus_option_spread_advisory" for row in rows)
    assert all(row[9] == "approved_deterministic_recommendation" for row in rows)
    assert rows[0][10]["paper_only"] is True
    assert rows[0][10]["no_live_execution"] is True
    assert rows[0][10]["risk_fraction"] == "0.05"
    assert all(row[11] == "paper_logged" for row in rows)


def test_approved_strategy_gate_creates_setups_only_for_approved_signals():
    pytest.importorskip("psycopg")
    from eod_signals import generate_eod_signals, propose_approved_setups, seed_default_strategies

    ticker = "ZZGATE"
    signal_dt = date(2099, 2, 4)
    with test_connection() as conn:
        try:
            seed_default_strategies(conn)
            _restore_default_strategy_statuses(conn)
            _cleanup(conn, [ticker])
            ingest_price_bars(conn, _bars(ticker), source="unit-eod-gate")
            compute_and_store_features(conn, tickers=[ticker], sma_fast_window=3, sma_slow_window=5, volume_window=3, atr_window=3, min_dollar_vol=Decimal("1000"))
            conn.execute("UPDATE strategies SET status='approved' WHERE name='trend_volume_vol_regime'")
            conn.execute("UPDATE strategies SET status='research_only' WHERE name IN ('pead','sector_cross_sectional_momentum')")
            generate_eod_signals(conn, tickers=[ticker], signal_dt=signal_dt, momentum_lookback_days=20, momentum_top_n=1)

            result = propose_approved_setups(conn, signal_dt=signal_dt, for_session=signal_dt + timedelta(days=1), tickers=[ticker])
            setups = conn.execute(
                """
                SELECT st.name, st.status, se.ticker, se.status, se.thesis
                FROM setups se JOIN strategies st ON st.id=se.strategy_id
                WHERE se.ticker=%s AND se.created_dt=%s
                ORDER BY se.id
                """,
                (ticker, signal_dt),
            ).fetchall()
        finally:
            _cleanup(conn, [ticker])
            _restore_default_strategy_statuses(conn)

    assert result["setups_created"] == 1
    assert result["blocked_by_strategy_status"] >= 1
    assert [(row[0], row[1], row[2], row[3]) for row in setups] == [("trend_volume_vol_regime", "approved", ticker, "pending_review")]
    assert "approved deterministic EOD signal" in setups[0][4]


def test_nightly_screening_dry_run_ranks_setups_without_writing_rows():
    pytest.importorskip("psycopg")
    from eod_signals import generate_eod_signals, propose_approved_setups, seed_default_strategies

    ticker = "ZZDRY"
    signal_dt = date(2099, 2, 4)
    with test_connection() as conn:
        try:
            seed_default_strategies(conn)
            _restore_default_strategy_statuses(conn)
            _cleanup(conn, [ticker])
            ingest_price_bars(conn, _bars(ticker), source="unit-eod-dry-run")
            compute_and_store_features(conn, tickers=[ticker], sma_fast_window=3, sma_slow_window=5, volume_window=3, atr_window=3, min_dollar_vol=Decimal("1000"))
            conn.execute("UPDATE strategies SET status='approved' WHERE name='trend_volume_vol_regime'")
            generate_eod_signals(conn, tickers=[ticker], signal_dt=signal_dt, momentum_lookback_days=20, momentum_top_n=1)

            result = propose_approved_setups(
                conn,
                signal_dt=signal_dt,
                for_session=signal_dt + timedelta(days=1),
                tickers=[ticker],
                dry_run=True,
                screening_context={"account_equity_usd": "5000"},
            )
            setup_count = conn.execute("SELECT COUNT(*) FROM setups WHERE ticker=%s AND created_dt=%s", (ticker, signal_dt)).fetchone()[0]
        finally:
            _cleanup(conn, [ticker])
            _restore_default_strategy_statuses(conn)

    assert result["dry_run"] is True
    assert result["setups_created"] == 0
    assert result["setups_ranked"] == 1
    assert result["quiet_night"] is False
    assert result["ranked_setups"][0]["ticker"] == ticker
    assert result["ranked_setups"][0]["size"]["risk_amount_usd"] == "50.00"
    assert result["ranked_setups"][0]["invalidation"] != ""
    assert setup_count == 0


def test_nightly_screening_blocks_liquidity_events_options_and_portfolio_breakers():
    pytest.importorskip("psycopg")
    from eod_signals import generate_eod_signals, propose_approved_setups, seed_default_strategies

    tickers = ["ZZILLQ", "ZZEVNT", "ZZOPT", "ZZHEAT"]
    signal_dt = date(2099, 2, 4)
    with test_connection() as conn:
        try:
            seed_default_strategies(conn)
            _restore_default_strategy_statuses(conn)
            _cleanup(conn, tickers)
            for ticker in tickers:
                ingest_price_bars(conn, _bars(ticker), source="unit-eod-risk-gates")
            compute_and_store_features(conn, tickers=tickers, sma_fast_window=3, sma_slow_window=5, volume_window=3, atr_window=3, min_dollar_vol=Decimal("1000"))
            conn.execute("INSERT INTO earnings_calendar(ticker, event_dt, session, confirmed) VALUES (%s,%s,'bmo',true) ON CONFLICT (ticker,event_dt) DO UPDATE SET confirmed=EXCLUDED.confirmed", ("ZZEVNT", signal_dt + timedelta(days=1)))
            conn.execute("UPDATE strategies SET status='approved' WHERE name='trend_volume_vol_regime'")
            generate_eod_signals(conn, tickers=tickers, signal_dt=signal_dt, momentum_lookback_days=20, momentum_top_n=4)
            conn.execute("UPDATE features SET liquidity=false WHERE ticker=%s AND dt=%s", ("ZZILLQ", signal_dt))

            result = propose_approved_setups(
                conn,
                signal_dt=signal_dt,
                for_session=signal_dt + timedelta(days=1),
                tickers=tickers,
                screening_context={
                    "account_equity_usd": "5000",
                    "current_drawdown_fraction": "0.11",
                    "instruments": {
                        "ZZOPT": {
                            "instrument_type": "option",
                            "option_liquidity_ok": False,
                            "defined_risk": False,
                            "iv_view": {"aligned": False, "note": "IV too rich for the view"},
                        }
                    },
                },
            )
            setup_count = conn.execute("SELECT COUNT(*) FROM setups WHERE ticker = ANY(%s) AND created_dt=%s", (tickers, signal_dt)).fetchone()[0]
        finally:
            _cleanup(conn, tickers)
            _restore_default_strategy_statuses(conn)

    assert result["setups_created"] == 0
    assert result["setups_ranked"] == 0
    assert result["quiet_night"] is True
    assert setup_count == 0
    reasons_by_ticker = {blocked["ticker"]: blocked["reasons"] for blocked in result["blocked_setups"]}
    assert any("liquidity" in reason for reason in reasons_by_ticker["ZZILLQ"])
    assert any("event landmine" in reason for reason in reasons_by_ticker["ZZEVNT"])
    assert any("option liquidity" in reason for reason in reasons_by_ticker["ZZOPT"])
    assert any("defined-risk" in reason for reason in reasons_by_ticker["ZZOPT"])
    assert any("IV" in reason for reason in reasons_by_ticker["ZZOPT"])
    assert any("drawdown kill" in reason for reason in reasons_by_ticker["ZZHEAT"])


def test_nightly_screening_applies_cumulative_heat_and_position_slots():
    pytest.importorskip("psycopg")
    from eod_signals import generate_eod_signals, propose_approved_setups, seed_default_strategies

    tickers = ["ZZSLOT1", "ZZSLOT2", "ZZSLOT3", "ZZSLOT4"]
    signal_dt = date(2099, 2, 4)
    with test_connection() as conn:
        try:
            seed_default_strategies(conn)
            _restore_default_strategy_statuses(conn)
            _cleanup(conn, tickers)
            for ticker in tickers:
                ingest_price_bars(conn, _bars(ticker), source="unit-eod-slot-gates")
            compute_and_store_features(conn, tickers=tickers, sma_fast_window=3, sma_slow_window=5, volume_window=3, atr_window=3, min_dollar_vol=Decimal("1000"))
            conn.execute("UPDATE strategies SET status='approved' WHERE name='trend_volume_vol_regime'")
            generate_eod_signals(conn, tickers=tickers, signal_dt=signal_dt, momentum_lookback_days=20, momentum_top_n=4)

            result = propose_approved_setups(
                conn,
                signal_dt=signal_dt,
                for_session=signal_dt + timedelta(days=1),
                tickers=tickers,
                dry_run=True,
                screening_context={"account_equity_usd": "5000", "max_concurrent_positions": 3},
            )
        finally:
            _cleanup(conn, tickers)
            _restore_default_strategy_statuses(conn)

    assert result["setups_ranked"] == 3
    assert len(result["blocked_setups"]) == 1
    assert any("max concurrent positions" in reason or "max portfolio heat" in reason for reason in result["blocked_setups"][0]["reasons"])
