# Wolfy plan-only budget gate token-cap run — 2026-07-24

Use this reference when the daily Wolfy optimizer starts with `budget_gate.py` over cap and must avoid implementation.

## Trigger

- Scheduled optimizer run at 2026-07-24 02:15 ET.
- Budget check:
  ```bash
  python3 wolfy/guardian/budget_gate.py --no-record
  # BUDGET=block token_cap_exceeded tokens_today=252284 cap=200000
  # exit 1
  ```
- Per Wolfy self-optimizing-loop rules, this forced PLAN-ONLY: deterministic orientation/review, durable state/KPI updates, no code/config/cron implementation.

## Verified health commands

```bash
python3 wolfy/guardian/config_guardian.py --skip-cli
# GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;no_probation
# exit 0

hermes cron list
# exit 0; optimizer job 92f31b95fccc present/enabled
```

No probation marker existed.

## Durable state written

- `agent_tasks` row: `3604`, completed.
- `agent_runs` row: `346194`, completed.
- `loop_metrics` rows included:
  - `tokens_today=252284`
  - `usage_headroom_pct=-26.142`
  - `jobs_skipped_by_budget=1`
  - `gateway_healthy=1`
  - `config_rollbacks=0`
  - `max_turns=90`
  - `parallel_jobs_cap=1`
  - `human_approval_pending=0`
  - `regressions_introduced=0`
  - `strat_candidate=0`, `strat_approved=0`

## Pitfall discovered

Do **not** assume `agent_tasks.source_fingerprint` has a unique constraint. This statement failed:

```sql
INSERT INTO agent_tasks (... source_fingerprint ...)
VALUES (...)
ON CONFLICT (source_fingerprint) DO UPDATE ...
```

with:

```text
psycopg.errors.InvalidColumnReference: there is no unique or exclusion constraint matching the ON CONFLICT specification
```

Safe pattern:

```python
cur.execute(
    "select id,status from agent_tasks where source_fingerprint=%s order by id limit 1",
    (fingerprint,),
)
row = cur.fetchone()
if row:
    tid, status = row
    cur.execute(
        "update agent_tasks set description=%s, definition_of_done=%s, updated_at=now() where id=%s",
        (desc, dod, tid),
    )
else:
    cur.execute(
        """
        insert into agent_tasks(agent_name, task_type, title, description, status, priority,
                                source_fingerprint, topic_tags, definition_of_done, created_at, updated_at)
        values ('Wolfy','optimization',%s,%s,'queued',50,%s,ARRAY['optimizer','budget','plan-only'],%s,now(),now())
        returning id,status
        """,
        (title, desc, fingerprint, dod),
    )
    tid, status = cur.fetchone()
```

Then claim/start/complete with `wolfy_agent_cli.py` and verify rows after retrying, because a failed psycopg statement can roll back prior work in that transaction.

## Report shape used

The final cron response stayed concise:

- `CHANGED`: plan-only, durable task/run/metrics, todo note.
- `VERIFIED`: budget gate block, guardian ok, cron ok, task/run completed.
- `KPI/STATE`: budget/headroom and guardrail metrics.
- `BLOCKED/HUMAN ASK`: none.
- `NEXT ACTION`: wait for budget recovery; then one Tier S slice, preferably OWS-4 Jonah cadence hourly.
