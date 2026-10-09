# Wolfy intraday scanner zero-ranked smoke nuance (2026-07-10)

During a Mike ops run, the cron-facing intraday scanner helper was already Postgres-only and bounded, but a manual relaxed smoke failed:

```bash
python3 /root/.hermes/scripts/wolfy_intraday_scanner_snapshot.py --max-symbols 4 --min-ranked 0
```

The helper returned an alert because `latest_data_date` was missing when the tiny bounded batch produced zero ranked rows. That is not a data-freshness failure when the operator explicitly set `--min-ranked 0`; it is a valid relaxed smoke for proving the wrapper, Postgres persistence path, and timeout bounds without requiring a signal in the sampled tickers.

Safe fix pattern:

1. Keep normal cron behavior strict (`min_ranked` default remains 1; ranked rows without dates still alert).
2. Only suppress the missing-`latest_data_date` alert when both conditions are true:
   - `min_ranked == 0`
   - no ranked rows were returned.
3. Add a regression test proving `run_snapshot(..., min_ranked=0)` returns status with `ranked_count == 0` and `latest_data_date is None` instead of raising.
4. Verify:

```bash
cd /root/.hermes/wolfy
python3 -m pytest test_intraday_scanner_snapshot.py -q
python3 /root/.hermes/scripts/wolfy_intraday_scanner_snapshot.py --max-symbols 4 --min-ranked 0
python3 /root/.hermes/scripts/mike_safe_autorepair.py && python3 /root/.hermes/scripts/mike_safe_autorepair.py
```

Expected results: tests pass, relaxed smoke exits 0 silently, autorepair second run is silent.

Related triage lesson: recent-error tails showed an older `tmp_xbi_3454_query.py` failure for `scanner_results.metadata`, but the live DB already had the compatibility aliases. Rerunning the exact scratch probe first showed it now exited 0, so no schema migration was needed. Treat recent scratch-probe warnings as leads, not current truth.
