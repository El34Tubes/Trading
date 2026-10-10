# Wolfy Trading Research and Paper-Recommendation System

Wolfy is a deterministic, end-of-day U.S. equities research and **paper-only** recommendation system operated through Hermes Agent. It ingests market data, computes auditable features and signals, validates strategy evidence, selects exact option structures when safe, falls back to the underlying when necessary, allocates a bounded paper portfolio, records outcomes, and produces concise decision reports.

> **Safety boundary:** this repository does not authorize live trading. No component is permitted to submit, modify, or cancel a broker order; move money; or alter a real position. Robinhood integration is read-only enrichment/validation. All recommendations and portfolio records are simulated.

This repository also preserves the surrounding Hermes operations layer: profiles, scheduled jobs, watchdogs, skills, coordination scripts, release controls, and disaster-recovery instructions.

## Current state — 2026-10-09

| Component | State |
|---|---|
| Server preservation snapshot | `652f025`, tagged `wolfy-server-preservation-2026-10-09-final` (tag pushed to `origin`) |
| Scheduler | **Frozen** — 0 enabled jobs, per `RECOVERY-MANIFEST.json` `scheduler_frozen: true` |
| Recovery asset set | `frozen-*` is primary; the unprefixed assets remain as a verified pre-freeze baseline |
| Existing close-confirmed breakout paper pipeline | Production-active |
| Trend pullback/reclaim sleeve | Implemented and tested; research/shadow only |
| Volatility-contraction breakout sleeve | Implemented and tested; research/shadow only |
| Mid/small-cap schema migrations | Applied to production PostgreSQL |
| Mid/small production adapter | Implemented at `e95a70c`; 1,032 tests passed |
| Mid/small publisher and recurring scheduler | **Disabled pending successful independent exact-snapshot review and canary** |
| Options expression | Exact fresh canonical chains preferred; stock fallback allowed |
| Broker execution | **Disabled / prohibited** |
| Public source backup | `https://github.com/El34Tubes/Trading` |
| Encrypted operational recovery backup | Private GitHub repository `El34Tubes/Trading-Recovery-Private` |

The last independent review of the earlier release snapshot `85084d5` was **NO-GO for publication** because it lacked a concrete production adapter. The adapter was then added at `e95a70c` and passed the full suite, but its subsequent independent review was interrupted by a provider HTTP 429. Passing tests are not a substitute for that review; production activation remains disabled.

## Design principles

1. **End-of-day only.** Actionable decisions use completed closing data and are for next-session human review.
2. **Deterministic and auditable.** Every decision is tied to source rows, run identities, gate results, and immutable configuration/version metadata.
3. **Fail closed.** Missing identity, capitalization, liquidity, freshness, benchmark, chain, or strategy evidence produces no trade or an explicit incomplete result.
4. **Point-in-time evidence.** Universe membership and security identity are evaluated as-of the decision session; current metadata is not silently projected into historical decisions.
5. **Paper only.** The recommendation writer persists simulations; no order-routing capability is accepted.
6. **One allocator and writer.** All strategy sleeves share global position, risk, and sector limits.
7. **No forced trades.** A valid day may end in deterministic no-trade.
8. **Separation of research and production.** A strategy can exist, backtest, and run in shadow mode without authorization to publish.

## High-level architecture

```text
Massive / public market sources / SEC / Cboe / read-only broker context
                              |
                              v
                 EOD price and reference ingestion
                              |
                              v
       PostgreSQL prices -> features -> signals -> setup gates
                              |
             +----------------+----------------+
             |                                 |
             v                                 v
   approved production sleeve          research/shadow sleeves
   close-confirmed breakout            pullback + VCP
             |                                 |
             +---------------+-----------------+
                             v
              deterministic setup-candidate contract
                             |
                             v
       exact option-chain decision or underlying fallback
                             |
                             v
       globally serialized paper allocator/recommendation writer
                             |
                             v
    recommendations + paper trades + separate instrument outcomes
                             |
                             v
       summary / Sentinel review / Yang technical context / Discord
```

## Repository layout

### Core Wolfy application

- `wolfy/postgres_init.sql` — canonical PostgreSQL schema and compatibility definitions.
- `wolfy/migrations/` — ordered production migrations.
- `wolfy/eod_price_features.py` — Massive EOD price ingest and deterministic feature computation.
- `wolfy/eod_signals.py` — strategy signal generation, setup gating, and legacy approved recommendation path.
- `wolfy/eod_backtest.py` — governed strategy backtesting.
- `wolfy/eod_monitoring.py` — strategy evidence freshness and fail-closed monitoring.
- `wolfy/eod_readiness.py` — run/session readiness and prerequisite evidence gates.
- `wolfy/daily_evaluation_ledger.py` — durable daily-run, ingestion, derived-stage, and gate ledger.
- `wolfy/daily_multi_strategy.py` — deterministic multi-sleeve evaluation contract.
- `wolfy/setup_evaluators.py` — shared candidate schema and strategy evaluators.
- `wolfy/security_master.py` — point-in-time identity and eligibility evidence.
- `wolfy/recommendation_universe.py` — immutable universe snapshots and members.
- `wolfy/option_chain_provider.py` — canonical read-only option-chain normalization and snapshot provenance.
- `wolfy/instrument_decision.py` — option-preferred versus underlying-fallback decision.
- `wolfy/options_structure_selector.py` — exact defined-risk option structure selection.
- `wolfy/portfolio_allocator.py` — globally bounded allocation.
- `wolfy/recommendation_writer.py` — serialized paper recommendation persistence.
- `wolfy/option_outcome_review.py` and `wolfy/recommendation_outcome_review.py` — separate option/underlying result accounting.
- `wolfy/orchestration_runner.py` — shadow/full orchestration.
- `wolfy/production_release.py` — default-disabled paper-production bootstrap, canary, authorization, scheduled run, readback, and rollback adapter.
- `wolfy/shadow_pivot_report.py` — migration manifest, rehearsals, baseline comparison, and shadow-release evidence.
- `wolfy/recommendation_engine_daily_summary.py` — concise current recommendation/outcome summary.

### Research and discovery

- `wolfy/alpha_search_pipeline.py` / `wolfy/alpha_search_context.py` — structured alpha leads, evidence, reports, and handoffs.
- `wolfy/wolfy_scanner.py` / `wolfy/intraday_scanner_snapshot.py` — deterministic delayed scanner snapshots; not an intraday execution engine.
- `wolfy/free_technical_data.py` — public market-structure and volatility inputs.
- `wolfy/cboe_delayed_options.py` — delayed options research data.
- `wolfy/experimental_options_pipeline.py` — research-only options forwarding/evaluation.
- `wolfy/options_research_ledger.py` — options research provenance.
- `wolfy/insider_buying.py` and `wolfy/suspicious_activity.py` — research signals and risk context.
- `wolfy/query_*.py`, `insert_*_research.py`, and validation helpers — preserved one-off research/reconstruction programs. They are not scheduled production entry points.

Downloaded issuer reports and raw source payloads are not published in this public repository. They are included in the encrypted private recovery package.

### Operations and coordination

- `scripts/` — stable cron-facing wrappers. Most delegate to canonical modules in `wolfy/`.
- `cron/jobs.public.json` — sanitized, disabled, local-only scheduler inventory suitable for public recovery documentation. The exact live `cron/jobs.json`, including routing and current operational state, is private runtime data preserved only in the encrypted recovery archive.
- `wolfy/guardian/` — configuration guardian and usage-budget gate.
- `wolfy/mike_*` and `scripts/mike_*` — deterministic IT/admin diagnostics and safe repair.
- `wolfy/wolfy_agent_coordination.py`, `wolfy/wolfy_agent_cli.py`, and `wolfy/visible_progress_ledger.py` — PostgreSQL-backed task/run coordination.
- `profiles/mike/` — IT/admin profile; no market recommendations.
- `profiles/clerky/` — administrative task, dependency, and handoff profile; no market analysis by default.
- `profiles/yang/` — technical entry/exit context profile.
- `skills/` — reusable Wolfy, operations, GitHub, testing, and research procedures.
- `.hermes/plans/` — accepted implementation plans.

Generated sessions, logs, memories, databases, credentials, caches, usage counters, prompt snapshots, and source downloads are intentionally excluded from public Git.

## Market universe

The mid/small-cap policy requires all of the following as-of the decision session:

- U.S. common stock;
- market capitalization from **$200 million through $15 billion**;
- closing price at least **$3**;
- at least **$5 million** average daily dollar volume over the last 20 trading sessions;
- accepted U.S. exchange and issuer evidence;
- complete source/provenance identifiers.

Fail-closed exclusions include:

- foreign issuers and ADRs;
- OTC securities;
- leveraged and inverse products;
- known manipulation-risk names;
- known government-intervention-risk names;
- securities lacking point-in-time identity, capitalization, price, or liquidity evidence.

`SPY`, `IWM`, and `MDY` are benchmark/context instruments only. They are not an ETF recommendation sleeve.

## Strategy sleeves

### Production-approved: close-confirmed relative-strength breakout

The approved strategy is preserved through the pivot adapter rather than reinterpreted. It requires completed closing data, relative strength, benchmark context, liquidity, breakout, and volume/confirmation evidence. Its evidence, monitoring, and paper lifecycle predate the mid/small pivot.

Historical governed validation recorded 1,085 evaluated setups, 272 out-of-sample setups, 63.13% overall hit rate, 68.75% out-of-sample hit rate, 35.94% stop rate, and 1.8539R median maximum favorable excursion. These numbers describe the governed historical study; they do not guarantee future returns.

### Research-only: trend pullback/reclaim

Implemented in the pivot as a common setup candidate, backtested and shadow-capable. It may not publish production recommendations until separately approved.

### Research-only: volatility-contraction breakout

Implemented, backtested, and shadow-capable. It may not publish production recommendations until separately approved.

No ETF/industry-rotation sleeve exists in the approved scope.

## Options and underlying fallback

1. Validate the underlying setup first.
2. Read an exact, fresh, ticker-bound, canonical option-chain snapshot.
3. Select a defined-risk structure only when expirations, strikes, quotes, spread, maximum loss, and provenance satisfy policy.
4. Permit multiple contracts only when combined maximum defined loss fits the position budget.
5. If no safe exact option exists, allow an underlying-stock paper recommendation.
6. Never force a stale, malformed, mismatched, synthetic, or unpriced option.
7. Track option outcomes separately from underlying setup outcomes.

Option-chain access and Robinhood context are read-only. The system contains no authorized broker submission path.

## Paper portfolio contract

- Maximum concurrent positions: **20**.
- Defined paper risk per position: **exactly 5%** of the configured paper portfolio.
- Aggregate defined paper risk: **maximum 100%**.
- Sector concentration: **maximum five positions per sector**.
- All sleeves use one global serialization lock and cumulative-cap check.
- Account ruin is allowed as a measured paper experiment outcome, never hidden from governance metrics.

Historical legacy tests and fixtures may use earlier portfolio examples. The production adapter enforces the current mid/small contract.

## Decision outcomes

Every complete run must produce one of:

1. an actionable **paper** recommendation;
2. a deterministic no-trade;
3. an explicit pipeline-incomplete decision.

An empty recommendation list is valid only when the pipeline and all required gates completed. Missing data must never be reported as no-trade.

## PostgreSQL data model

PostgreSQL 16 with `pg_trgm` and `vector` extensions is the canonical operational store. Major relation groups include:

- universe/security master and source observations;
- daily prices and deterministic features;
- strategy definitions, backtests, and monitoring evidence;
- signals and setup candidates;
- recommendations, paper trades, and outcomes;
- option-chain snapshots and structure evaluations;
- daily evaluation runs, stage/ingestion manifests, and gate evaluations;
- agent tasks, agent runs, run events, progress, and metrics;
- Alpha Search reports, leads, evidence, and handoffs;
- knowledge sources/chunks and embeddings;
- scanner snapshots and technical reviews.

SQLite remains only for selected Hermes runtime/session state and legacy local compatibility. Wolfy market/recommendation state is PostgreSQL-first.

### Ordered pivot migrations

Apply these in order on an existing installation:

1. `wolfy/migrations/20260917_daily_evaluation_ledger.sql`
2. `wolfy/migrations/20260917_option_snapshot_provenance.sql`
3. `wolfy/migrations/20260917_recommendation_uniqueness.sql`
4. `wolfy/migrations/20260917_security_master.sql`
5. `wolfy/migrations/20260917_recommendation_universe.sql`
6. `wolfy/migrations/20260917_setup_candidates.sql`
7. `wolfy/migrations/20260917_instrument_outcomes.sql`

The set was rehearsed transactionally, applied to a clone of production, backed up, and then applied to production. Applying schema does **not** activate the publisher.

## Scheduler topology

A sanitized scheduler inventory lives in `cron/jobs.public.json`; every entry is intentionally disabled and local-only. The exact live definitions and routing live in `cron/jobs.json`, which is Git-ignored and must be restored from the encrypted private runtime archive. Review destinations and keep jobs disabled until validation. The major workflow is:

1. five after-close Massive price-ingestion shards;
2. deterministic feature and approved-signal generation;
3. EOD report;
4. Sentinel review;
5. Yang technical context;
6. pre-open risk monitoring;
7. weekly research review;
8. monthly strategy revalidation;
9. recommendation summary;
10. background knowledge, embeddings, storage, usage, coordination, and safe-repair jobs.

The mid/small production scheduler is intentionally not active. Do not add a second writer. Production activation must replace or explicitly coordinate with the existing publisher so only one globally serialized paper writer exists.

## Release lifecycle

### Shadow

Run the pivot without publishing. Verify universe completeness, setup counts, options decisions, allocation, outcomes, migration state, and deterministic reruns.

### Bootstrap

`wolfy/production_release.py` creates an exact snapshot-bound, default-disabled release artifact. Bootstrap must use source-backed security/capitalization evidence and exact trading-session calculations.

### Canary

A canary:

- operates only on production paper tables;
- permits only the approved breakout sleeve;
- rejects the pullback and VCP research sleeves;
- performs no broker or external-delivery action;
- records exact release/snapshot evidence;
- accepts a complete deterministic no-trade;
- verifies idempotency and portfolio/sector/risk readback.

### Scheduled authorization

Recurring authorization requires successful canary evidence for the exact immutable release snapshot and configuration fingerprint. A test-only or synthetic canary cannot authorize production.

### Rollback

Rollback disables the pivot publisher and restores the previous publisher/universe choice without deleting audit, recommendation, or outcome rows.

## Profiles

- **Wolfy/default** — market research, deterministic recommendations, strategy evaluation, and reporting.
- **Mike** — system health, storage, usage limits, PostgreSQL, embeddings, and bounded repairs. Mike does not make market calls.
- **Clerky** — task allocation, Kanban hygiene, progress ledgers, dependencies, and handoffs. Clerky does not alter infrastructure or do market analysis unless explicitly tasked.
- **Yang** — technical entry/exit context after Sentinel; not an independent portfolio writer.

Profile-local credentials, memories, and sessions are not public Git content. They are part of the encrypted recovery archive.

## Fresh installation

### 1. Base system

Recommended baseline:

- Ubuntu 24.04 or compatible Linux;
- Python 3.11+;
- PostgreSQL 16;
- `pgvector` and `pg_trgm`;
- Git, `curl`, SQLite, and build tools;
- Hermes Agent from the official documentation: <https://hermes-agent.nousresearch.com/docs>.

### 2. Clone source

```bash
git clone https://github.com/El34Tubes/Trading.git /root/.hermes
cd /root/.hermes
git checkout main
```

The repository is rooted at Hermes home. Do not overwrite a live Hermes home without first backing up `.env`, `auth.json`, state databases, sessions, memories, and cron state.

### 3. Python dependencies

The Wolfy modules primarily require:

```bash
python3 -m pip install psycopg[binary] requests PyYAML pytest
```

Install Hermes through its official installer/environment rather than trying to reconstruct the Hermes framework solely from this operations repository.

### 4. PostgreSQL

Create a local peer-authenticated owner/database, enable extensions, then either restore the private dump or initialize a new empty database.

Fresh empty schema:

```bash
psql -d wolfy -v ON_ERROR_STOP=1 -f wolfy/postgres_init.sql
```

Recovery restore is preferred when historical evidence and recommendations must survive; see **Disaster recovery** below.

### 5. Test database

Tests must never target production. Create a dedicated local database named `wolfy_test` with Unix-socket peer authentication. Do not use TCP, passwords, URI DSNs, `PGSERVICE`, or ambient remote libpq overrides.

Canonical suite:

```bash
cd /root/.hermes
pytest -q wolfy
```

Do not use bare repository-root test discovery without the `wolfy` target: installed/profile skill trees may contain duplicate third-party test modules.

### 6. Credentials and configuration

Secrets belong in `/root/.hermes/.env` or Hermes credential storage, never in Git. Common names used by Wolfy include:

- `MASSIVE_API_KEY` (or legacy `POLYGON_API_KEY`);
- `OPENAI_API_KEY` only when semantic embeddings are explicitly selected;
- `SEC_USER_AGENT` for SEC requests;
- `WOLFY_POSTGRES_DSN` / `WOLFY_PG_DSN` for an intentional local override;
- `HERMES_HOME` and `HERMES_ENV_PATH` when paths differ from defaults.

Optional policy/configuration variables include `WOLFY_MASSIVE_ALLOW_CURRENT_DAY`, `WOLFY_STRATEGY_STALE_AFTER_DAYS`, embedding provider/model/timeouts, and budget-gate thresholds. Keep same-day Massive access disabled unless the data entitlement truly supports it.

### 7. Hermes profiles and cron

After restoring config and profile state:

```bash
hermes config check
hermes doctor
hermes profile list
hermes cron list --all
```

Inspect every schedule and delivery destination before enabling jobs. Start with publishers disabled, test the data path, then enable ingestion/reporting in dependency order.

## Testing and verification

Primary checks:

```bash
python3 -m compileall -q wolfy scripts
pytest -q wolfy
git diff --check
git diff --cached --check
```

Production-release focused checks:

```bash
pytest -q \
  wolfy/test_production_release.py \
  wolfy/test_recommendation_writer.py \
  wolfy/test_orchestration_runner.py \
  wolfy/test_shadow_pivot_report.py
```

Database/release checks must additionally verify:

- guarded `wolfy_test` DSN resolution;
- production schema baseline and protected row counts;
- migration order and transactional rehearsal;
- exact universe/session evidence;
- idempotent rerun behavior;
- top-20, 5%-risk, 100%-aggregate, and five-per-sector limits;
- no research-sleeve publication;
- no broker imports/calls or external delivery in canary;
- non-destructive rollback;
- an independent review tied to the exact commit.

A historical test leak was found when two split-ingestion tests hard-coded the production database. `wolfy/test_eod_price_features.py` was corrected to use the guarded test-DSN resolver. Preserve that safeguard.

## Routine operations

Useful read-only checks:

```bash
hermes status --all
hermes cron list --all
python3 wolfy/recommendation_engine_daily_summary.py
python3 wolfy/check_postgres_requirements.py
psql -d wolfy -c "SELECT max(dt), count(DISTINCT ticker) FROM prices;"
```

Do not infer readiness from the legacy `universe_symbols.last_seen` field alone. The pivot requires point-in-time source-backed identity and universe evidence.

## Disaster recovery

The public Git repository preserves source and history. Private runtime state is stored as encrypted release assets in:

```text
https://github.com/El34Tubes/Trading-Recovery-Private
```

The recovery set contains, as separate encrypted/checksummed artifacts:

- full PostgreSQL custom-format dump;
- consistent SQLite backups for Hermes/default, profile sessions, and Kanban;
- private Hermes credentials/config, memories, sessions, logs, cron output, raw source evidence, release artifacts, and deployment configuration;
- complete Git bundle with all branches and tags;
- machine/package/schema inventory and SHA-256 manifest.

The decryption key is deliberately delivered separately and is **not** in either GitHub repository.

### Restore order

1. Provision Linux, PostgreSQL 16, extensions, Python, and Hermes Agent.
2. Clone `El34Tubes/Trading`.
3. Download the private recovery release assets and verify SHA-256 hashes.
4. Decrypt each asset with the separately retained key.
5. Restore PostgreSQL into a new empty database. Create extensions as the PostgreSQL administrator, then restore application objects as the application role while suppressing extension comments:

   ```bash
   sudo -u postgres createdb -O root wolfy
   sudo -u postgres psql -d wolfy -v ON_ERROR_STOP=1 \
     -c 'CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;'
   pg_restore --no-owner --no-acl --no-comments --exit-on-error \
     -d wolfy wolfy.dump
   ```

   This exact sequence was restore-drilled successfully. A plain application-role restore fails when it attempts to create or comment on administrator-owned extensions.

6. Restore SQLite backups only while Hermes/gateway/scheduler processes are stopped.
7. Restore private runtime tar paths and set `.env`/`auth.json` permissions to `0600`.
8. Run `hermes config check`, `hermes doctor`, database checks, compilation, and `pytest -q wolfy`.
9. Keep all publishers disabled until read-only validation and a paper-only canary pass.
10. Re-enable cron jobs in dependency order and verify exactly one recommendation writer.

### Restore test

A backup is not considered complete merely because the dump command succeeded. Required evidence includes:

- `pg_restore --list` succeeds;
- restore into a temporary database succeeds;
- protected production table counts match the manifest;
- every SQLite backup returns `ok` from `PRAGMA quick_check`;
- Git bundle verifies and contains all expected refs;
- encrypted files decrypt and match their pre-encryption hashes;
- GitHub asset sizes/hashes match the local manifest.

## Important history

- `15eb747` — hardened strategy revalidation and existing paper lifecycle.
- `19f9858` — canonical daily evaluator/derived-stage ledger lineage.
- `5c4b249` — hardened aggressive-options research path.
- `3380fd4` — completed mid/small strategy pivot; 1,018 tests passed at that snapshot.
- `45f852b` — isolated split-ingestion tests from production.
- `85084d5` — completed ordered production migration set.
- `e95a70c` — bounded default-disabled production paper adapter; 1,032 tests passed.
- `47b8256` — tagged `wolfy-server-preservation-2026-10-09`; superseded as a restore target.
- `652f025` — closed the preservation audit blockers. Tagged
  `wolfy-server-preservation-2026-10-09-final` and recorded as the `public_source_commit`
  of `RECOVERY-MANIFEST.json` (schema `wolfy-recovery-manifest-v2`); the clean-clone result
  recorded for this snapshot is 1,041 tests passed. **This is the restore target** — prefer
  it over `47b8256`.

All historical feature/release branches are preserved and pushed in addition to `main`.

## Known limitations and disabled components

- The mid/small publisher and recurring schedule remain disabled until an exact-snapshot independent review and real paper canary complete.
- Pullback/reclaim and VCP are research-only.
- Bulk source evidence is a dated cache and must be refreshed/revalidated for each new authorization context.
- Massive free/delayed entitlement may not provide same-calendar-day EOD aggregates; the default intentionally uses the prior business day.
- External source availability, option-chain freshness, and issuer-country completeness can produce explicit incomplete decisions.
- No live brokerage capability is authorized.
- Raw credentials, databases, sessions, memories, logs, and licensed/downloaded source evidence are not present in the public repository.

## Pre-wipe checklist

Do not wipe the server until every item is true:

- [ ] Public `main` and all historical branches are visible on GitHub at the documented SHAs.
- [ ] No local commit remains ahead of its remote counterpart.
- [ ] Public history secret scan reports zero confirmed secrets.
- [ ] PostgreSQL dump is checksummed and successfully test-restored.
- [ ] Every SQLite backup passes `PRAGMA quick_check`.
- [ ] Git bundle verifies and contains all expected refs.
- [ ] Runtime/config/source-evidence archive is encrypted.
- [ ] Encrypted assets are uploaded to the confirmed private recovery repository.
- [ ] Uploaded assets are downloaded or range-read and hash-verified.
- [ ] The separate recovery key has been saved off-server by the owner.
- [ ] README restore instructions have been checked against a clean test location.
- [ ] Any services/jobs still writing state are stopped or their final state is re-backed up.

Until the key is confirmed off-server and private assets are verified, the server is **not wipe-ready**.

## License and data rights

Repository-authored code and documentation are preserved for the owner. Bundled third-party Hermes skills retain their own notices/licenses. Market/source data may be subject to provider terms and is therefore excluded from the public source repository. Do not redistribute private recovery assets.

## Disclaimer

Wolfy is research software. Paper results, backtests, and historical hit rates are not guarantees. Nothing in this repository is investment advice or authorization for live execution.
