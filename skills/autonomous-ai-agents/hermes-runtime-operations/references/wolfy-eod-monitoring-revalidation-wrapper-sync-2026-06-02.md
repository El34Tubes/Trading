# Wolfy EOD monitoring/revalidation wrapper sync — 2026-06-02

Use this pattern when Mike implements or repairs Wolfy EOD operations helpers that may be invoked by default-profile cron, Mike diagnostics, and Clerky handoffs.

## What was learned

A monitoring/revalidation helper should be treated as an operations feature with two durable requirements:

1. **Conservative EOD safety behavior**
   - Pre-open monitoring may reject/flag existing rows when deterministic DB facts show an invalidation breach or near-term event landmine.
   - Monthly revalidation may demote `strategies.status='approved'` back to `candidate` when validation is stale/missing or the latest OOS verdict failed.
   - It must never promote strategies, create trade recommendations, execute broker actions, or reason around risk gates.

2. **Wrapper/autorepair durability**
   - Add the live implementation under `/root/.hermes/wolfy/`.
   - Add a global wrapper under `/root/.hermes/scripts/` when cron/profile diagnostics may call it.
   - Sync wrappers into relevant profile script directories, especially Mike and Clerky.
   - Teach `mike_safe_autorepair.py` to preserve/sync the wrapper so future safe autorepair runs do not reintroduce profile-wrapper drift.

## TDD and verification pattern

1. Write behavior tests first, then verify RED on the missing module/behavior.
2. Implement the smallest conservative helper.
3. Verify the specific tests pass, then run a broader smoke suite covering EOD governance/backtest/features, agent coordination, and embedding sync.
4. Smoke every invocation layer:
   - live helper: `/root/.hermes/wolfy/<helper>.py --help` or a safe no-op run
   - global wrapper: `/root/.hermes/scripts/<helper>.py --help`
   - Mike wrapper: `/root/.hermes/profiles/mike/scripts/<helper>.py --help`
   - Clerky wrapper: `/root/.hermes/profiles/clerky/scripts/<helper>.py --help`
5. Run `mike_safe_autorepair.py` twice: the first run may report sync actions; the second should be silent.
6. Re-run the Postgres requirements guard and default-profile cron listing.
7. If smoke tests create temporary strategy/setup/position/run rows, clean them up and explicitly verify that no real approved strategies were demoted unless that was the intended operational action.
8. Comment and complete the relevant Mike Kanban card with exact test/guard output, then dispatch the board so downstream work moves.

## Verification transcript distilled from the session

- `test_eod_monitoring.py` failed RED with `ModuleNotFoundError: No module named 'eod_monitoring'`.
- After implementation, `test_eod_monitoring.py` passed.
- Broader smoke suite passed: `17 passed in 0.22s` for EOD monitoring/governance/backtest/features, agent coordination, and embedding tests.
- Postgres guard reported PostgreSQL 16.14 with `pg_trgm` and `vector` within Wolfy requirements.
- Embedding sync, stale coordination cleanup, usage snapshot, and a second autorepair run exited 0/silent.
- The default-profile cron list remained active/last-run OK.
- The live/global/Mike/Clerky wrapper paths all exposed CLI help.
- The current `strategies` table only contained `research_only` rows, so no live demotion occurred during verification.
