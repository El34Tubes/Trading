# Wolfy Postgres Sentinel / Alpha Search alias drift (2026-06-12)

## Trigger

Use this when Wolfy/Jonah/Sentinel cron logs show Postgres ad-hoc query errors like:

- `operator does not exist: text = bigint` joining `recommendation_reviews.recommendation_id` to `recommendations.id`
- `relation "alpha_search_leads" does not exist`
- `column "rationale" does not exist` on `alpha_leads`
- `column "signal" does not exist` on `scanner_results`
- `ModuleNotFoundError: No module named 'psycopg2'` from older helper snippets while `psycopg` is installed

## Safe repair pattern

1. Treat recent error tails as leads, then inspect live schema and rerun exact failing query shapes.
2. Prefer non-destructive compatibility over changing canonical write paths:
   - Convert `recommendation_reviews.recommendation_id` to `BIGINT` only after confirming all existing values are numeric:
     ```sql
     select count(*) filter (where recommendation_id !~ '^[0-9]+$') as nonnumeric,
            count(*) as total
     from recommendation_reviews;
     alter table recommendation_reviews
       alter column recommendation_id type bigint using recommendation_id::bigint;
     ```
   - Add nullable alias columns and backfill:
     ```sql
     alter table alpha_leads add column if not exists rationale text;
     alter table alpha_leads add column if not exists summary text;
     update alpha_leads
     set rationale=coalesce(rationale, thesis, raw_payload->>'rationale', raw_payload->>'summary'),
         summary=coalesce(summary, raw_payload->>'summary', thesis, title)
     where rationale is null or summary is null;

     alter table scanner_results add column if not exists signal text;
     update scanner_results
     set signal=coalesce(signal, notes->>'signal', notes->>'scanner_type', scanner_type)
     where signal is null;
     ```
   - For retired table names, create read-only compatibility views rather than duplicate mutable tables:
     ```sql
     create or replace view alpha_search_leads as
     select id, sqlite_id, report_id, created_at, updated_at, ticker, lead_type,
            title, thesis, rationale, summary, status,
            evidence_quality_score as score, evidence_quality_score,
            evidence_count, highest_source_quality, suspicious_action,
            suspicious_flags, catalyst_window, social_context, filing_context,
            insider_context, complete_ticket, recommendation_id,
            next_research_question, company_name, scanner_type, market_context,
            raw_payload, source_fingerprint
     from alpha_leads;
     ```
3. Preserve every live DB compatibility fix in both:
   - `/root/.hermes/wolfy/postgres_init.sql`
   - `/root/.hermes/wolfy/mike_safe_autorepair.py`
   Then sync `/root/.hermes/scripts/mike_safe_autorepair.py` and Mike/Clerky profile wrappers.
4. If old snippets import `psycopg2`, install the bridge in the Hermes runtime venv, not system Python:
   ```bash
   uv pip install --python /usr/local/lib/hermes-agent/venv/bin/python psycopg2-binary
   /usr/local/lib/hermes-agent/venv/bin/python -c 'import psycopg2; print(psycopg2.__version__)'
   ```

## Verification commands

Run the exact failing shape, plus silent/idempotence checks:

```bash
/root/.hermes/wolfy/check_postgres_requirements.py
psql -d wolfy -v ON_ERROR_STOP=1 -c "select rr.id, rr.recommendation_id, r.ticker from recommendation_reviews rr left join recommendations r on rr.recommendation_id=r.id order by rr.id desc limit 3;"
psql -d wolfy -v ON_ERROR_STOP=1 -c "select id,ticker,lead_type,status,created_at,summary from alpha_search_leads order by created_at desc limit 3;"
psql -d wolfy -v ON_ERROR_STOP=1 -c "select id,ticker,lead_type,score,created_at,updated_at,substr(coalesce(rationale,''),1,80) from alpha_leads order by updated_at desc limit 3;"
psql -d wolfy -v ON_ERROR_STOP=1 -c "select id,scanner_run_id,ticker,signal,score,data_date,close from scanner_results order by id desc limit 3;"
python3 /root/.hermes/wolfy/sentinel_reviews.py --source postgres --dry-run --limit 2
/root/.hermes/scripts/mike_safe_autorepair.py
/root/.hermes/scripts/mike_safe_autorepair.py
```

The second autorepair run should be silent. Also verify representative pytest/smoke suites when cheap, e.g. `python3 -m pytest test_postgres_primary_pipeline.py test_agent_coordination_smoke.py -q` from `/root/.hermes/wolfy`.
