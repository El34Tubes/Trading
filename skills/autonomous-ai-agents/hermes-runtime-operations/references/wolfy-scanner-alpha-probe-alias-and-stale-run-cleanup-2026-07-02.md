# Wolfy scanner alpha probe aliases + stale Jonah run cleanup (2026-07-02)

## Trigger
Mike ops recent-error tails showed Jonah scanner-alpha research probes failing on Postgres alias drift rather than live pipeline failures:

- `scanner_results.avg_volume_20d` missing
- strategy-rule probe aliases such as `timeframe` / `reasons` missing
- alpha-search probe alias `evidence` missing
- stale `agent_runs.status='started'` row left open after a transient OpenAI Codex `usage_limit_reached` 429 before Jonah could finish its linked task

## Safe repair pattern
Use non-destructive compatibility aliases; do not rewrite canonical scanner/strategy pipelines.

Preserve aliases in both live DB and durability layers:

- `/root/.hermes/wolfy/postgres_init.sql`
- `/root/.hermes/scripts/mike_safe_autorepair.py`
- synced autorepair copies under `/root/.hermes/wolfy/`, `/root/.hermes/profiles/mike/scripts/`, and `/root/.hermes/profiles/clerky/scripts/`

Useful scanner-result aliases seen in Jonah probes:

- `symbol`, `ticker_symbol` from canonical `ticker`
- `volume`, `avg_volume_20d` from canonical `avg_volume`
- `close_price` from canonical `close`
- `as_of_date` from canonical `data_date`
- `metadata`, `metrics`, `flags`, `raw` from canonical `notes` / compact pattern JSON
- `trend_50_200`, `pattern`, `pattern_flags`
- `rs_spy_20d`, `rs_qqq_20d`, `rs_vs_spy_20d`, `rs_vs_qqq_20d`
- `r1`, `rank_position`, `setup_type` when probes ask for compact ranking/setup fields

Related probe aliases:

- `alpha_search_leads.evidence` as a read-only view expression from `rationale`, `summary`, `thesis`, raw payload evidence/rationale, or title.
- `strategy_rules.timeframe` and `strategy_rules.reasons` in the read-only compatibility view, mirrored from setup/rule type and description/body text.

## Stale run cleanup rule
If an LLM-driven Jonah run opens an `agent_runs.status='started'` row and then fails before creating an artifact because of a transient provider usage-limit/startup failure:

1. Close only the stale run row as `blocked` with `records_created=0` and a specific summary.
2. Requeue the linked `agent_tasks` row if the task was merely claimed and no durable artifact/report was created.
3. Do not mark the research complete and do not fabricate the missed report.
4. Verify:
   - `stale_started_runs = 0`
   - `duplicate_claim_noise = 0`
   - usage-limit watchdog runs silently twice or otherwise reports a fresh actionable limit
   - exact failing probe queries now run

## Verification shape
- Run canonical autorepair twice; the second run should be silent.
- Apply `postgres_init.sql` against the live DB to prove the schema initializer preserves the aliases.
- Re-run the exact `tmp_*_query.py` or SQL probe that failed before claiming the drift is fixed.
- Check embedding coverage and coordination noise after the cleanup so ops does not introduce stale ledger rows.
