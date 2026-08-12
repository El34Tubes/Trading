from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from eod_price_features import PriceBar, compute_and_store_features, ingest_price_bars


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


def test_recommendation_universe_uses_broad_current_universe_with_data_gates():
    psycopg = pytest.importorskip("psycopg")
    from eod_signals import recommendation_universe_tickers, seed_default_strategies

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    tickers = ["ZZBLUE", "ZZSMALL", "ZZNONE", "ZZINACT", "ZZSTALE", "ZZTHIN"]
    signal_dt = date(2099, 2, 4)
    with psycopg.connect(dsn) as conn:
        try:
            seed_default_strategies(conn)
            _cleanup(conn, tickers)
            rows = [
                ("ZZBLUE", "blue_chip", True),
                ("ZZSMALL", "small_cap", True),
                ("ZZNONE", None, True),
                ("ZZINACT", "large_cap", False),
                ("ZZSTALE", "mid_cap", True),
                ("ZZTHIN", "small_cap", True),
            ]
            for symbol, tier, active in rows:
                conn.execute(
                    """
                    INSERT INTO universe_symbols(symbol, name, source, active, wolfy_tier, backfill_enabled)
                    VALUES (%s, %s, 'unit-test', %s, %s, true)
                    """,
                    (symbol, symbol, active, tier),
                )
            for ticker in ["ZZBLUE", "ZZSMALL", "ZZNONE", "ZZINACT", "ZZSTALE"]:
                ingest_price_bars(conn, _breakout_bars(ticker), source="unit-broad-universe")
                compute_and_store_features(conn, tickers=[ticker], sma_fast_window=5, sma_slow_window=20, volume_window=5, atr_window=5, min_dollar_vol=Decimal("1000"))
            ingest_price_bars(conn, _breakout_bars("ZZTHIN", n=8), source="unit-broad-universe")
            compute_and_store_features(conn, tickers=["ZZTHIN"], sma_fast_window=3, sma_slow_window=5, volume_window=3, atr_window=3, min_dollar_vol=Decimal("1000"))
            conn.execute("DELETE FROM features WHERE ticker='ZZSTALE' AND dt=%s", (signal_dt,))

            result = recommendation_universe_tickers(conn, signal_dt=signal_dt, min_history_bars=20)
        finally:
            _cleanup(conn, tickers)

    assert "ZZBLUE" in result
    assert "ZZSMALL" in result
    assert "ZZNONE" in result
    assert "ZZINACT" not in result
    assert "ZZSTALE" not in result
    assert "ZZTHIN" not in result


def test_generate_eod_signals_can_use_broad_recommendation_universe_when_tickers_omitted():
    psycopg = pytest.importorskip("psycopg")
    from eod_signals import generate_eod_signals, seed_default_strategies

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    tickers = ["ZZAUTO", "SPY"]
    signal_dt = date(2099, 2, 4)
    with psycopg.connect(dsn) as conn:
        try:
            seed_default_strategies(conn)
            _restore_default_strategy_statuses(conn)
            _cleanup(conn, tickers)
            for symbol in tickers:
                conn.execute(
                    "INSERT INTO universe_symbols(symbol, name, source, active, wolfy_tier, backfill_enabled) VALUES (%s, %s, 'unit-test', true, 'small_cap', true) ON CONFLICT (symbol) DO UPDATE SET active=true",
                    (symbol, symbol),
                )
            ingest_price_bars(conn, _breakout_bars("ZZAUTO", daily_step=Decimal("0.70"), breakout_lift=Decimal("2.50")), source="unit-auto-universe")
            ingest_price_bars(conn, _breakout_bars("SPY", daily_step=Decimal("0.05"), breakout_lift=Decimal("0.00")), source="unit-auto-universe")
            compute_and_store_features(conn, tickers=tickers, sma_fast_window=5, sma_slow_window=20, volume_window=5, atr_window=5, min_dollar_vol=Decimal("1000"))

            result = generate_eod_signals(conn, tickers=None, signal_dt=signal_dt, momentum_lookback_days=20, momentum_top_n=1)
        finally:
            _cleanup(conn, tickers)
            _restore_default_strategy_statuses(conn)

    assert result["universe_source"] == "broad_current_with_data_gates"
    assert "ZZAUTO" in result["tickers_considered"]
    assert result["signals_by_strategy"]["liquid_rs_breakout_continuation"] >= 1


def test_seed_default_strategies_includes_rs_breakout_as_research_only():
    psycopg = pytest.importorskip("psycopg")
    from eod_signals import seed_default_strategies

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    with psycopg.connect(dsn) as conn:
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
    psycopg = pytest.importorskip("psycopg")
    from eod_signals import generate_eod_signals, seed_default_strategies

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    tickers = ["ZZRSBO", "SPY"]
    signal_dt = date(2099, 2, 4)
    with psycopg.connect(dsn) as conn:
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
    psycopg = pytest.importorskip("psycopg")
    from eod_signals import generate_eod_signals, seed_default_strategies

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    tickers = ["ZZSIG", "ZZMOM"]
    signal_dt = date(2099, 2, 4)
    with psycopg.connect(dsn) as conn:
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
    psycopg = pytest.importorskip("psycopg")
    from eod_signals import seed_default_strategies, write_approved_paper_recommendations

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    signal_dt = date(2099, 2, 4)
    tickers = ["ZZREC1", "ZZREC2", "ZZREC3", "ZZREC4", "ZZBLOCK"]
    with psycopg.connect(dsn) as conn:
        try:
            seed_default_strategies(conn)
            _cleanup(conn, tickers)
            approved_id = conn.execute("SELECT id FROM strategies WHERE name='liquid_rs_breakout_close_confirm_1r'").fetchone()[0]
            blocked_id = conn.execute("SELECT id FROM strategies WHERE name='liquid_rs_breakout_continuation'").fetchone()[0]
            conn.execute("UPDATE strategies SET status='approved' WHERE id=%s", (approved_id,))
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


def test_log_approved_paper_recommendation_trades_creates_open_paper_rows_idempotently():
    psycopg = pytest.importorskip("psycopg")
    from eod_signals import log_approved_paper_recommendation_trades, seed_default_strategies, write_approved_paper_recommendations

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    signal_dt = date(2099, 2, 4)
    tickers = ["ZZPLOG1", "ZZPLOG2", "ZZPLOG3", "ZZPLOG4"]
    with psycopg.connect(dsn) as conn:
        try:
            seed_default_strategies(conn)
            _cleanup(conn, tickers)
            approved_id = conn.execute("SELECT id FROM strategies WHERE name='liquid_rs_breakout_close_confirm_1r'").fetchone()[0]
            conn.execute("UPDATE strategies SET status='approved' WHERE id=%s", (approved_id,))
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
    psycopg = pytest.importorskip("psycopg")
    from eod_signals import generate_eod_signals, propose_approved_setups, seed_default_strategies

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    ticker = "ZZGATE"
    signal_dt = date(2099, 2, 4)
    with psycopg.connect(dsn) as conn:
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
    psycopg = pytest.importorskip("psycopg")
    from eod_signals import generate_eod_signals, propose_approved_setups, seed_default_strategies

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    ticker = "ZZDRY"
    signal_dt = date(2099, 2, 4)
    with psycopg.connect(dsn) as conn:
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
    psycopg = pytest.importorskip("psycopg")
    from eod_signals import generate_eod_signals, propose_approved_setups, seed_default_strategies

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    tickers = ["ZZILLQ", "ZZEVNT", "ZZOPT", "ZZHEAT"]
    signal_dt = date(2099, 2, 4)
    with psycopg.connect(dsn) as conn:
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
    psycopg = pytest.importorskip("psycopg")
    from eod_signals import generate_eod_signals, propose_approved_setups, seed_default_strategies

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    tickers = ["ZZSLOT1", "ZZSLOT2", "ZZSLOT3", "ZZSLOT4"]
    signal_dt = date(2099, 2, 4)
    with psycopg.connect(dsn) as conn:
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
