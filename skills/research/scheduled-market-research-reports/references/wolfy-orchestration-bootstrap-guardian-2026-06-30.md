# Wolfy orchestration bootstrap control plane — 2026-06-30

Use this reference when the user asks to bootstrap, repair, or safely self-modify Wolfy's orchestration layer after LLM quota/429 issues.

## User intent

The user shifted Wolfy from conservative recommendation-only orchestration changes to autonomous Tier S self-optimization:

- Wolfy may autonomously change cron schedules, `config.yaml`, orchestration params, concurrency/cadence/max_turns/delegation, Kanban, structural refactors, and Postgres-only migrations.
- Human gating is narrow: installs/upgrades, new credentials/API keys/secrets, and marking a strategy `approved`.
- Self-protection comes first: build deterministic budget/config guardians before any other config/schedule changes.
- Do not push commits unless the user explicitly asks.

## Bootstrap pattern

1. Pause token-heavy LLM jobs first if the user instructs it, especially Jonah `*/20`, and confirm the daily optimizer remains active.
2. Build `wolfy/guardian/budget_gate.py` as deterministic/no-agent logic:
   - Reads `agent_usage_snapshots`, `hermes auth list openai-codex`, and today's `agent_runs` token sum vs a daily cap.
   - Prints `BUDGET=ok ...` and exits 0 when safe.
   - Prints `BUDGET=block <reason>` and exits non-zero when low/limited.
   - Supports simulation env vars to prove over-cap and under-cap behavior without spending tokens.
   - Records `usage_headroom_pct` and `tokens_today` to `loop_metrics`.
3. Build `wolfy/guardian/config_guardian.py` plus a no-agent wrapper under `scripts/`:
   - Snapshots `config.yaml` and `cron/jobs.json` into `wolfy/guardian/known_good/<UTC>/`.
   - Health check: config YAML parses, `hermes cron list` succeeds, optimizer job `92f31b95fccc` is present/enabled, probation marker not expired.
   - On unhealthy config or expired unconfirmed probation, restores latest known-good and clears probation.
   - Test with a temporary Hermes home: deliberately broken `config.yaml` + expired probation must restore known-good and log rollback.
   - Then prove the real restore path end-to-end: snapshot real config, deliberately break it, run guardian, confirm YAML parse and `hermes cron list` succeed after restore.
   - Record `gateway_healthy` and `config_rollbacks` to `loop_metrics`.
4. Schedule the guardian as no-agent every ~15m only after the restore test passes.
5. Only after OWS-1/OWS-2 are verified, apply one reversible config/schedule change under the Self-Modification Protocol:
   - snapshot first;
   - apply one change;
   - validate parse + `hermes cron list`;
   - write `wolfy/guardian/probation.json` expiring at/after the next expected optimizer run;
   - commit locally.

## Concrete first autonomous change

The safe first config change was the concurrency governor:

```yaml
cron.max_parallel_jobs: 1
kanban.max_in_progress_per_profile: 1
```

DoD: YAML parses, `hermes cron list` exits 0, probation marker exists, `parallel_jobs_cap=1` written to `loop_metrics`.

## Re-enable policy after 429

Do not re-enable paused LLM jobs while the real budget gate prints `BUDGET=block codex_usage_limited` or other block reason. Leave them paused, report the blocker, and make the next action: wire paused LLM jobs to consult the budget gate, then re-enable low-frequency jobs gradually. Do not restore Jonah to `*/20`; keep it paused or move it hourly/adaptive behind the gate.

## Reporting shape

Report FACT/DECISION/RECOMMENDATIONS/NEXT ACTION:

- FACT: files built, deterministic verification output, local unpushed commit hashes, current KPIs.
- DECISION: which jobs stayed paused vs re-enabled and why.
- RECOMMENDATIONS FOR HUMAN: Tier B only, especially fallback-provider credentials/API keys.
- NEXT ACTION: usually confirm probation, wire paused jobs to budget gate, and re-enable conservatively.

## Pitfalls

- A guardian that snapshots after detecting a broken config will preserve the broken state. Health-check first; if unhealthy, restore prior known-good instead of snapshotting the changed files.
- The guardian cron wrapper must live under `~/.hermes/scripts/`; `cronjob.create` rejects absolute script paths.
- Running `hermes cron list` can mutate `cron/jobs.json` timestamps/repeat counters. If that mutation is part of the verified guardian state, commit it intentionally; otherwise avoid mixing it with unrelated blocks.
- Keep unrelated dirty skill/profile/curator files untouched when committing Wolfy orchestration blocks.
