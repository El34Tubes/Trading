# Wolfy scanner_results alias drift + fixture compatibility (2026-06-12)

## Trigger
Jonah/Wolfy cron/tool output repeatedly failed on ad-hoc Postgres probes that selected `scanner_results.rs_spy_20` and related deterministic scanner factor names. Canonical Postgres rows stored those values in `scanner_results.notes` JSONB, while LLM-authored probes expected top-level columns.

A related regression appeared in local tests after the live scanner path moved Postgres-first/Postgres-only: fixture tests still passed a temp SQLite DB and expected historical SQLite compatibility rows (`scanner_runs`, `scanner_results.notes_json`) and SQLite-based freshness behavior when a connection was injected.

## Safe repair pattern
1. Treat missing scanner factor columns as compatibility alias drift, not a reason to rewrite scanner logic.
2. Add nullable, non-destructive Postgres aliases and backfill from `notes` JSONB:
   - `rs_spy_20`, `rs_qqq_20`
   - `breakout_20d_pct`
   - `volume_surge_1d_20`, `volume_surge_5d_20`, `volume_surge_1d_50`, `volume_surge_5d_50`
   - `atr_pct`, `squeeze_ratio`, `squeeze_flag`, `liquidity_spread_proxy`
   - `trend_regime`, `rank_reasons`, `gap_reversal_flag`
3. Preserve the alias repair in every layer that can recreate or maintain schema:
   - `/root/.hermes/wolfy/mike_safe_autorepair.py`
   - `/root/.hermes/wolfy/postgres_init.sql`
   - `/root/.hermes/wolfy/wolfy_postgres_pipeline.py` operational initializer
4. Keep live cron paths Postgres-first/Postgres-only by passing `db_path=None` in scanner execution.
5. Restore explicit SQLite compatibility only for tests/legacy fixture inspection:
   - `persist_scan(..., db_path=<temp sqlite path>, ...)` writes a temp SQLite compatibility copy and returns the SQLite run id.
   - `persist_scan(..., db_path=None, ...)` returns the Postgres run id and does not write live SQLite.
   - If `wolfy_report_context.get_scanner_freshness(con=...)` receives an injected SQLite connection, use fixture/legacy SQLite freshness logic. With no connection, use Postgres live freshness.
6. When clearing review-only Kanban blockers, rerun the cited verification plus the current full local smoke suite before completing the card.

## Verification commands used
```bash
/root/.hermes/wolfy/check_postgres_requirements.py
psql -d wolfy -P pager=off -c "select ticker, score, close, r5, r20, r60, rs_spy_20, rs_qqq_20, breakout_20d_pct, volume_surge_1d_20, trend_regime from scanner_results where run_id=50 order by score desc limit 3;"
cd /root/.hermes/wolfy && python3 -m pytest -q .
python3 -m py_compile /root/.hermes/wolfy/mike_safe_autorepair.py /root/.hermes/wolfy/wolfy_postgres_pipeline.py /root/.hermes/wolfy/wolfy_scanner.py /root/.hermes/wolfy/wolfy_report_context.py
python3 /root/.hermes/wolfy/mike_safe_autorepair.py  # run twice; second should be silent
psql -d wolfy -P pager=off -c "select count(*) filter (where status='started' and started_at < now() - interval '2 hours') stale_started_runs from agent_runs; select count(*) synthetic_blocked_tasks from agent_tasks where status='blocked' and title ilike '%smoke%'; select count(*) duplicate_claim_noise from agent_runs where error_message='duplicate-or-already-claimed' and started_at > now() - interval '24 hours'; select count(*) total, count(embedding) embedded from knowledge_chunks;"
```

Observed verification from the session:
- Postgres guard OK: PostgreSQL 16.14, `pg_trgm` 1.6, `vector` 0.6.0.
- Full Wolfy tests: `93 passed in 1.61s`.
- Autorepair second run: silent.
- Coordination smoke: `0` stale started runs, `0` synthetic blocked tasks, `0` duplicate claim noise.
- Embeddings: `717 / 717` chunks embedded.

## Pitfalls
- Do not remove fixture SQLite compatibility just because live operations are Postgres-only. Tests and diagnostics may intentionally pass temp SQLite connections/paths.
- Do not route live cron/report/scanner writes back through `/root/.hermes/wolfy/wolfy.db`; the compatibility copy is for temp fixtures or legacy inspection only.
- Do not add top-level aliases for every JSON key preemptively. Add aliases for recurring operational probe drift or documented consumer needs, and preserve them in autorepair/init layers.
- Running only targeted tests can miss fixture-compat regressions; after scanner/report persistence changes, run the full `/root/.hermes/wolfy` pytest suite when cheap.
