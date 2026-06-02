# Wolfy Postgres-primary optimization handoff — 2026-06-02

## Trigger

User clarified that Wolfy should move away from SQLite and use the Postgres database as the primary operational store. The user also corrected wording: use **optimize** role alignment/distribution, not "metabolize."

## Durable direction

- Treat PostgreSQL as Wolfy's intended primary operational database.
- Keep `/root/.hermes/wolfy/wolfy.db` only as compatibility/fallback until each live consumer is inventoried, migrated, and verified.
- Do not destructively remove SQLite tables or compatibility paths during routine migration.
- Use Postgres-first helpers/adapters for new work; fallback to SQLite should be explicit and surfaced in reports/handoffs.
- Maintain EOD-only safety: closing-data decisions, next-session human execution, deterministic signal/risk gates, LLM for interpretation/ranking/explanation only, no brokerage authority.

## Cards created during the session

- `t_72faf09a` — Mike: live SQLite consumer inventory and migration map.
- `t_5f49bf70` — default: shared DB adapter with Postgres-first defaults.
- `t_010ecac8` — default: migrate scanner/alpha/report/recommendation pipeline off SQLite primary.
- `t_30486fb4` — Clerky: update cron wrappers/prompts and verify Postgres-first autonomous runs.
- `t_c0c67ec9` — Clerky: optimize Wolfy role alignment and Kanban distribution.

## Verification used

- `/root/.hermes/wolfy/check_postgres_requirements.py` passed.
- `python3 -m pytest -q /root/.hermes/wolfy` returned `60 passed`.
- Review-blocked EOD foundation cards were completed after the user's approval of the direction.

## Workflow lesson

For future Wolfy migration/orchestration sessions:

1. Inventory current board/cron/profile state first.
2. Accept previously review-blocked implementation cards only after rerunning their verification commands.
3. Save a durable project plan under `/root/.hermes/wolfy/` and reference it from cards.
4. Create dependency-linked migration cards rather than one broad omnibus card.
5. Assign by actual profile roles: Mike = infra/Postgres/runtime; Clerky = board/dependencies/status; Yang = technical entry/exit after alpha/setup exists; default = implementation until more specialist profiles exist.
6. Use the user's wording: **optimize** alignment/distribution.
