#!/usr/bin/env python3
"""Read-only Wolfy visible progress ledger.

Prints a concise deterministic snapshot for Wolfy/Hermes progress: data
freshness, signals, setups, validation gates, blockers, and next action. This
script never writes to Postgres, never approves strategies, and never proposes
live trades; it is safe for cron context generation or manual status checks.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import date, datetime, timezone
from typing import Any

DEFAULT_DSN = os.environ.get("WOLFY_POSTGRES_DSN", "dbname=wolfy user=root host=/var/run/postgresql")


def _connect(dsn: str):
    import psycopg
    from psycopg.rows import dict_row

    # psycopg's runtime accepts dict_row here; some bundled pyright stubs are
    # overly narrow for generic Connection typing.
    return psycopg.connect(dsn, row_factory=dict_row)  # type: ignore[arg-type]


def _one(cur, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    cur.execute(sql, params)
    row = cur.fetchone()
    return dict(row or {})


def _all(cur, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cur.execute(sql, params)
    return [dict(row) for row in cur.fetchall()]


def _table_count(cur, table: str) -> int | None:
    try:
        cur.execute(f"SELECT count(*) AS n FROM {table}")
        return int(cur.fetchone()["n"])
    except Exception:
        cur.connection.rollback()
        return None


def _safe_query(cur, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    try:
        return _one(cur, sql, params)
    except Exception as exc:
        cur.connection.rollback()
        return {"error": f"{type(exc).__name__}: {exc}"}


def _safe_all(cur, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    try:
        return _all(cur, sql, params)
    except Exception as exc:
        cur.connection.rollback()
        return [{"error": f"{type(exc).__name__}: {exc}"}]


def collect_progress(dsn: str = DEFAULT_DSN) -> dict[str, Any]:
    """Collect read-only Wolfy progress facts from Postgres and cron metadata."""
    now = datetime.now(timezone.utc)
    data: dict[str, Any] = {
        "generated_at_utc": now.isoformat(timespec="seconds"),
        "eod_constitution": "closing-data only; deterministic gates; no auto-execution; human approval required",
        "constraints": "Robinhood-tradable U.S. stocks/ETFs only, long-only, max 3 positions, stops required, paper-trading orientation",
        "postgres": {},
        "cron": {},
    }
    try:
        with _connect(dsn) as conn:
            with conn.cursor() as cur:
                data["postgres"]["counts"] = {
                    table: _table_count(cur, table)
                    for table in (
                        "prices",
                        "features",
                        "signals",
                        "setups",
                        "strategies",
                        "scanner_runs",
                        "scanner_results",
                        "recommendations",
                        "recommendation_reviews",
                        "paper_trades",
                        "agent_tasks",
                        "agent_runs",
                    )
                }
                data["postgres"]["data_freshness"] = _safe_query(
                    cur,
                    """
                    WITH price_latest AS (SELECT max(dt) AS dt FROM prices),
                         feature_latest AS (SELECT max(dt) AS dt FROM features)
                    SELECT price_latest.dt::text AS latest_price_dt,
                           (SELECT count(DISTINCT ticker) FROM prices WHERE dt = price_latest.dt) AS latest_price_tickers,
                           feature_latest.dt::text AS latest_feature_dt,
                           (SELECT count(DISTINCT ticker) FROM features WHERE dt = feature_latest.dt) AS latest_feature_tickers
                    FROM price_latest, feature_latest
                    """,
                )
                data["postgres"]["historical_depth"] = _safe_query(
                    cur,
                    """
                    WITH per_ticker AS (
                        SELECT ticker, min(dt) AS first_dt, max(dt) AS last_dt, count(*)::int AS bar_count
                        FROM prices
                        GROUP BY ticker
                    )
                    SELECT count(*)::int AS tickers_with_prices,
                           min(first_dt)::text AS earliest_first_dt,
                           max(last_dt)::text AS latest_last_dt,
                           min(bar_count)::int AS min_bars,
                           percentile_cont(0.5) WITHIN GROUP (ORDER BY bar_count)::int AS median_bars,
                           count(*) FILTER (WHERE bar_count >= 500)::int AS tickers_ge_500_bars,
                           count(*) FILTER (WHERE bar_count < 500)::int AS tickers_lt_500_bars
                    FROM per_ticker
                    """,
                )
                data["postgres"]["scanner_freshness"] = _safe_query(
                    cur,
                    """
                    SELECT sr.id AS latest_run_id,
                           sr.run_time::text AS latest_run_time,
                           max(res.data_date)::text AS latest_data_date,
                           count(res.id) AS candidate_count
                    FROM scanner_runs sr
                    LEFT JOIN scanner_results res ON res.run_id = sr.id
                    GROUP BY sr.id, sr.run_time
                    ORDER BY sr.run_time DESC, sr.id DESC
                    LIMIT 1
                    """,
                )
                data["postgres"]["strategies"] = _safe_all(
                    cur,
                    """
                    SELECT name, setup_type, status, latest_oos_sharpe::text AS latest_oos_sharpe,
                           latest_oos_verdict, last_validated::text AS last_validated
                    FROM strategies
                    ORDER BY name
                    """,
                )
                data["postgres"]["latest_backtests"] = _safe_all(
                    cur,
                    """
                    SELECT DISTINCT ON (st.id)
                           st.name,
                           bt.id AS backtest_id,
                           bt.run_at::text AS run_at,
                           bt.window_start::text AS window_start,
                           bt.window_end::text AS window_end,
                           bt.is_sharpe::text AS is_sharpe,
                           bt.oos_sharpe::text AS oos_sharpe,
                           bt.oos_cagr::text AS oos_cagr,
                           bt.max_dd::text AS max_dd,
                           bt.turnover::text AS turnover,
                           bt.survives_oos,
                           coalesce((bt.report->'walk_forward'->>'oos_trades')::int, NULL) AS oos_trades,
                           coalesce((bt.report->'walk_forward'->>'is_trades')::int, NULL) AS is_trades
                    FROM strategies st
                    JOIN backtests bt ON bt.strategy_id = st.id
                    ORDER BY st.id, bt.run_at DESC, bt.id DESC
                    """,
                )
                data["postgres"]["strategy_readiness"] = _safe_all(
                    cur,
                    """
                    WITH signal_summary AS (
                        SELECT strategy_id, max(dt) AS latest_signal_dt, count(*)::int AS total_signals
                        FROM signals
                        GROUP BY strategy_id
                    ), latest_signal_counts AS (
                        SELECT s.strategy_id, count(*)::int AS latest_signal_count
                        FROM signals s
                        JOIN signal_summary ss
                          ON ss.strategy_id = s.strategy_id AND ss.latest_signal_dt = s.dt
                        GROUP BY s.strategy_id
                    ), setup_summary AS (
                        SELECT strategy_id,
                               max(created_dt) AS latest_setup_dt,
                               count(*)::int AS total_setups,
                               count(*) FILTER (WHERE status IN ('proposed','pending_review'))::int AS open_or_pending_setups
                        FROM setups
                        GROUP BY strategy_id
                    )
                    SELECT st.name,
                           st.status,
                           ss.latest_signal_dt::text AS latest_signal_dt,
                           coalesce(lsc.latest_signal_count, 0)::int AS latest_signal_count,
                           coalesce(ss.total_signals, 0)::int AS total_signals,
                           su.latest_setup_dt::text AS latest_setup_dt,
                           coalesce(su.total_setups, 0)::int AS total_setups,
                           coalesce(su.open_or_pending_setups, 0)::int AS open_or_pending_setups,
                           CASE
                             WHEN st.status = 'approved' THEN 'approved-strategy gate can be evaluated against deterministic risk checks'
                             WHEN ss.latest_signal_dt IS NULL THEN 'no deterministic signals yet; research/watch-only'
                             ELSE 'candidate/research only; candidate is not approved'
                           END AS gate_note
                    FROM strategies st
                    LEFT JOIN signal_summary ss ON ss.strategy_id = st.id
                    LEFT JOIN latest_signal_counts lsc ON lsc.strategy_id = st.id
                    LEFT JOIN setup_summary su ON su.strategy_id = st.id
                    ORDER BY st.name
                    """,
                )
                data["postgres"]["recent_signals"] = _safe_query(
                    cur,
                    """
                    SELECT max(s.dt)::text AS latest_signal_dt,
                           count(*) FILTER (WHERE s.dt = (SELECT max(dt) FROM signals)) AS latest_signal_count,
                           count(*) FILTER (WHERE s.dt >= current_date - interval '7 days') AS seven_day_signal_count
                    FROM signals s
                    """,
                )
                data["postgres"]["setups"] = _safe_query(
                    cur,
                    """
                    SELECT count(*) AS total,
                           count(*) FILTER (WHERE status IN ('proposed','pending_review')) AS open_or_pending,
                           max(created_dt)::text AS latest_created_dt
                    FROM setups
                    """,
                )
                data["postgres"]["positions"] = _safe_query(
                    cur,
                    """
                    SELECT count(*) FILTER (WHERE status = 'open') AS open_positions,
                           count(*) AS total_positions
                    FROM positions
                    """,
                )
                data["postgres"]["paper_ledger"] = _safe_query(
                    cur,
                    """
                    SELECT (SELECT count(*)::int FROM paper_trades) AS paper_trades_total,
                           (SELECT count(*)::int FROM paper_trades WHERE status = 'open') AS open_paper_trades,
                           (SELECT count(*)::int FROM paper_trades WHERE status = 'open' AND stop_price IS NULL) AS open_paper_trades_without_stop,
                           (SELECT coalesce(round(sum(pnl)::numeric, 2), 0)::text FROM paper_trades WHERE status = 'closed') AS closed_pnl_total,
                           (SELECT max(coalesce(exit_date, entry_date))::text FROM paper_trades) AS latest_paper_trade_dt,
                           (SELECT count(*)::int FROM recommendations) AS recommendations_total,
                           (SELECT count(*)::int FROM recommendations WHERE status IN ('pending_review','proposed','open')) AS pending_recommendations,
                           (SELECT count(*)::int FROM recommendations WHERE status IN ('pending_review','proposed','open') AND coalesce(nullif(trim(stop), ''), null) IS NULL) AS pending_recommendations_without_stop
                    """,
                )
                data["postgres"]["backlog_hygiene"] = _safe_query(
                    cur,
                    """
                    WITH active AS (
                        SELECT *
                        FROM agent_tasks
                        WHERE status IN ('queued','ready','in_progress','blocked')
                    ), duplicate_fingerprints AS (
                        SELECT source_fingerprint
                        FROM active
                        WHERE source_fingerprint IS NOT NULL
                        GROUP BY source_fingerprint
                        HAVING count(*) > 1
                    )
                    SELECT count(*) FILTER (WHERE status IN ('queued','ready'))::int AS queued_or_ready,
                           count(*) FILTER (WHERE status = 'in_progress')::int AS in_progress,
                           count(*) FILTER (WHERE status = 'blocked')::int AS blocked,
                           count(*) FILTER (WHERE status = 'in_progress' AND updated_at < now() - interval '6 hours')::int AS stale_in_progress_gt_6h,
                           (SELECT count(*)::int FROM duplicate_fingerprints) AS duplicate_active_fingerprints,
                           min(created_at)::text AS oldest_active_created_at
                    FROM active
                    """,
                )
                data["postgres"]["recent_blockers"] = _safe_all(
                    cur,
                    """
                    SELECT agent_name, status, left(coalesce(error_message, summary, result_summary, ''), 180) AS reason,
                           coalesce(ended_at, completed_at, started_at)::text AS ts
                    FROM agent_runs
                    WHERE status IN ('blocked','error','failed')
                    ORDER BY coalesce(ended_at, completed_at, started_at) DESC NULLS LAST
                    LIMIT 5
                    """,
                )
    except Exception as exc:
        data["postgres"]["error"] = f"{type(exc).__name__}: {exc}"

    try:
        cron = subprocess.run(
            ["hermes", "--profile", "default", "cron", "list", "--all"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
        lines = cron.stdout.splitlines()
        data["cron"] = {
            "exit_code": cron.returncode,
            "paused_count": sum("[paused]" in line for line in lines),
            "active_count": sum("[active]" in line for line in lines),
            "recent_usage_limit_seen": any("usage limit" in line.lower() or "HTTP 429" in line for line in lines),
        }
    except Exception as exc:
        data["cron"] = {"error": f"{type(exc).__name__}: {exc}"}
    return data


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    def cell(value: Any) -> str:
        text = "" if value is None else str(value)
        return text.replace("|", "\\|").replace("\n", " ")

    out = ["| " + " | ".join(cell(h) for h in headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        out.append("| " + " | ".join(cell(value) for value in row) + " |")
    return "\n".join(out)


def render_markdown(data: dict[str, Any], blocker_limit: int | None = None) -> str:
    pg = data.get("postgres", {})
    counts = pg.get("counts", {}) or {}
    freshness = pg.get("data_freshness", {}) or {}
    scanner = pg.get("scanner_freshness", {}) or {}
    depth = pg.get("historical_depth", {}) or {}
    signals = pg.get("recent_signals", {}) or {}
    setups = pg.get("setups", {}) or {}
    positions = pg.get("positions", {}) or {}
    paper = pg.get("paper_ledger", {}) or {}
    backlog = pg.get("backlog_hygiene", {}) or {}
    cron = data.get("cron", {}) or {}

    lines = [
        f"# Wolfy Visible Progress Ledger — {data.get('generated_at_utc')}",
        "",
        f"Constitution: {data.get('eod_constitution')}",
        f"User constraints: {data.get('constraints')}",
        "",
        "## Snapshot",
        _md_table(
            ["Area", "Fact"],
            [
                ["Prices/features", f"latest_price_dt={freshness.get('latest_price_dt')} tickers={freshness.get('latest_price_tickers')} | latest_feature_dt={freshness.get('latest_feature_dt')} tickers={freshness.get('latest_feature_tickers')}"] ,
                ["Historical depth", f"tickers={depth.get('tickers_with_prices')} median_bars={depth.get('median_bars')} min_bars={depth.get('min_bars')} ge_500_bars={depth.get('tickers_ge_500_bars')} lt_500_bars={depth.get('tickers_lt_500_bars')} span={depth.get('earliest_first_dt')}→{depth.get('latest_last_dt')}"] ,
                ["Scanner", f"latest_run_id={scanner.get('latest_run_id')} latest_data_date={scanner.get('latest_data_date')} candidates={scanner.get('candidate_count')}"] ,
                ["Signals", f"latest_signal_dt={signals.get('latest_signal_dt')} latest_count={signals.get('latest_signal_count')} seven_day_count={signals.get('seven_day_signal_count')}"] ,
                ["Setups", f"total={setups.get('total')} open_or_pending={setups.get('open_or_pending')} latest_created_dt={setups.get('latest_created_dt')}"] ,
                ["Positions", f"open={positions.get('open_positions')} total={positions.get('total_positions')} max_allowed=3"],
                ["Paper/accountability", f"paper_trades={paper.get('paper_trades_total')} open={paper.get('open_paper_trades')} open_without_stop={paper.get('open_paper_trades_without_stop')} pending_recs={paper.get('pending_recommendations')} pending_recs_without_stop={paper.get('pending_recommendations_without_stop')}"] ,
                ["Backlog hygiene", f"queued_ready={backlog.get('queued_or_ready')} in_progress={backlog.get('in_progress')} blocked={backlog.get('blocked')} stale_in_progress_gt_6h={backlog.get('stale_in_progress_gt_6h')} duplicate_active_fingerprints={backlog.get('duplicate_active_fingerprints')}"] ,
                ["Cron", f"active={cron.get('active_count')} paused={cron.get('paused_count')} usage_limit_seen={cron.get('recent_usage_limit_seen')}"],
            ],
        ),
        "",
        "## Strategy gates",
    ]
    strategy_rows = pg.get("strategies") or []
    if strategy_rows and "error" not in strategy_rows[0]:
        lines.append(
            _md_table(
                ["Strategy", "Status", "OOS Sharpe", "OOS Verdict", "Last Validated", "Gate"],
                [
                    [
                        row.get("name"),
                        row.get("status"),
                        row.get("latest_oos_sharpe"),
                        row.get("latest_oos_verdict"),
                        row.get("last_validated"),
                        "actionable only if approved; candidate is not approved" if row.get("status") != "approved" else "approved-strategy gate can be evaluated",
                    ]
                    for row in strategy_rows
                ],
            )
        )
    else:
        lines.append(f"Strategy status unavailable: {strategy_rows}")

    backtest_rows = pg.get("latest_backtests") or []
    lines.extend(["", "## Latest walk-forward validation"])
    if backtest_rows and "error" not in backtest_rows[0]:
        lines.append(
            _md_table(
                ["Strategy", "Backtest", "Window", "IS Sharpe", "OOS Sharpe", "OOS CAGR", "Max DD", "Turnover", "Survived", "Trades IS/OOS"],
                [
                    [
                        row.get("name"),
                        row.get("backtest_id"),
                        f"{row.get('window_start')}→{row.get('window_end')}",
                        row.get("is_sharpe"),
                        row.get("oos_sharpe"),
                        row.get("oos_cagr"),
                        row.get("max_dd"),
                        row.get("turnover"),
                        row.get("survives_oos"),
                        f"{row.get('is_trades')}/{row.get('oos_trades')}",
                    ]
                    for row in backtest_rows
                ],
            )
        )
    else:
        lines.append(f"Latest validation unavailable: {backtest_rows}")

    readiness_rows = pg.get("strategy_readiness") or []
    lines.extend(["", "## Deterministic strategy readiness"])
    if readiness_rows and "error" not in readiness_rows[0]:
        lines.append(
            _md_table(
                ["Strategy", "Status", "Latest Signal", "Signals @ Latest", "Total Signals", "Latest Setup", "Open/Pending Setups", "Gate Note"],
                [
                    [
                        row.get("name"),
                        row.get("status"),
                        row.get("latest_signal_dt"),
                        row.get("latest_signal_count"),
                        row.get("total_signals"),
                        row.get("latest_setup_dt"),
                        row.get("open_or_pending_setups"),
                        row.get("gate_note"),
                    ]
                    for row in readiness_rows
                ],
            )
        )
    else:
        lines.append(f"Strategy readiness unavailable: {readiness_rows}")

    lines.extend(["", "## Paper/accountability gate"])
    if paper and "error" not in paper:
        lines.append(
            _md_table(
                ["Paper Trades", "Open", "Open Missing Stops", "Closed PnL", "Latest Trade Date", "Recommendations", "Pending", "Pending Missing Stops", "Gate"],
                [[
                    paper.get("paper_trades_total"),
                    paper.get("open_paper_trades"),
                    paper.get("open_paper_trades_without_stop"),
                    paper.get("closed_pnl_total"),
                    paper.get("latest_paper_trade_dt"),
                    paper.get("recommendations_total"),
                    paper.get("pending_recommendations"),
                    paper.get("pending_recommendations_without_stop"),
                    "paper/accountability only; no live trading or auto-execution",
                ]],
            )
        )
    else:
        lines.append(f"Paper/accountability status unavailable: {paper}")

    blockers = pg.get("recent_blockers") or []
    if blocker_limit is not None and blocker_limit >= 0:
        blockers = blockers[:blocker_limit]
    lines.extend(["", "## Blockers / noise"])
    if blockers and "error" not in blockers[0]:
        lines.append(
            _md_table(
                ["Agent", "Status", "When", "Reason"],
                [[b.get("agent_name"), b.get("status"), b.get("ts"), b.get("reason")] for b in blockers],
            )
        )
    else:
        lines.append("No recent blocked/error agent_run rows found, or blocker query unavailable.")

    next_action = "Keep script-only EOD ingest/signals running; do not create actionable setups until a strategy is human-approved and closing-data gates pass."
    if backlog.get("stale_in_progress_gt_6h") not in (None, 0, "0") or backlog.get("duplicate_active_fingerprints") not in (None, 0, "0"):
        next_action = "Next build target: run bounded backlog hygiene on stale/duplicate Jonah/Sentinel/Yang tasks after allocator/stale-cleanup jobs are idle; avoid mutating active claims."
    if depth.get("tickers_lt_500_bars") not in (None, 0, "0"):
        next_action = "Next build target: complete historical OHLCV depth before trusting walk-forward OOS; keep any shallow-depth strategy output watch-only."
    if any(row.get("name") == "sector_cross_sectional_momentum" and row.get("status") == "candidate" for row in strategy_rows if isinstance(row, dict)):
        next_action = "Next decision target: review sector_cross_sectional_momentum candidate evidence. OOS survived, but IS Sharpe/max drawdown must be challenged before any human approval."
    elif any(row.get("name") == "trend_volume_vol_regime" and row.get("status") != "approved" for row in strategy_rows if isinstance(row, dict)):
        next_action = "Next build target: improve trend_volume_vol_regime definition and walk-forward OOS validation; keep outputs watch-only until human approval."
    lines.extend(["", "## Next recommended action", f"- {next_action}"])
    if counts:
        lines.extend(["", "## Table counts", json.dumps(counts, sort_keys=True)])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Print read-only Wolfy visible progress ledger")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="output format; --json is retained as a compatibility alias",
    )
    parser.add_argument("--limit", type=int, default=None, help="limit blocker rows in Markdown output")
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    args = parser.parse_args()
    data = collect_progress(args.dsn)
    if args.json or args.format == "json":
        print(json.dumps(data, indent=2, sort_keys=True, default=str))
    else:
        print(render_markdown(data, blocker_limit=args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
