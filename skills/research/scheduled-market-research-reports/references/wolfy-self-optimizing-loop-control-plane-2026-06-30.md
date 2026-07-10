# Wolfy self-optimizing loop control-plane prompt (2026-06-30)

## Trigger

Use when the user provides a full replacement prompt for Wolfy's daily/self-optimizing optimizer cron job, especially prompts that change the autonomy model, orchestration backlog, budget gates, or self-modification policy.

## Durable lesson

When the user sends a long prompt and then asks whether it was read, the correct workflow is exact and evidence-backed:

1. Treat the uploaded document as the source of truth, not the previous prompt summary.
2. Install the full prompt into the existing Wolfy optimizer job (`92f31b95fccc`) without changing schedule/state unless explicitly requested.
3. Verify the installed prompt by checking distinctive markers from the new document, not just cron list status.
4. Commit only `cron/jobs.json` unless the user explicitly asks to include other dirty files.
5. Push to GitHub only when the user explicitly asks; otherwise report the local commit hash as unpushed.

Useful verification markers for the 2026-06-30 self-optimizing version:

- Starts with `You are Wolfy's self-optimizing loop`.
- Contains `Tier S — SELF-OPTIMIZE AUTONOMOUSLY`.
- Contains `SELF-MODIFICATION PROTOCOL`.
- Contains `OWS-1 — Proactive budget gate`.
- Contains `OWS-2 — Config guardian + last-known-good auto-restore`.
- Preserves `Do not push git commits` inside the cron prompt, meaning the cron job itself should commit locally only; a human chat instruction to push is separate and can be honored by the assistant outside the cron run.

## Key autonomy change from the earlier optimizer prompt

Earlier Wolfy optimizer prompts treated cron schedules, config changes, repo untracking, broad refactors, and project-direction changes as Tier B recommendation-only items. The self-optimizing control-plane prompt deliberately changes this:

- Tier S: cron schedules, `config.yaml`, orchestration params, structural refactors, and Postgres-only migrations are autonomous **after** OWS-1/OWS-2 guardians exist and under the Self-Modification Protocol.
- Tier B is narrowed to: installs/upgrades, new credentials/API keys/secrets, and marking a strategy `approved`.
- The optimizer must never disable/pause/delete/reschedule its own job or modify/remove guardian scripts or budget/concurrency gates.
- Only one orchestration/config change per run is allowed, and it must be reversible with snapshot, validation, probation, and next-run confirmation.

## Prompt-install verification pattern

After updating the job, verify with both job state and prompt content:

```bash
hermes --profile default cron list --all | sed -n '/92f31b95fccc/,/886554b9a87e/p'
python3 - <<'PY'
import json
job = next(j for j in json.load(open('/root/.hermes/cron/jobs.json'))['jobs'] if j.get('id') == '92f31b95fccc')
print(job['prompt'].splitlines()[0])
print('prompt_chars', len(job['prompt']))
print('contains_tier_s', 'Tier S — SELF-OPTIMIZE AUTONOMOUSLY' in job['prompt'])
print('contains_OWS_1', 'OWS-1 — Proactive budget gate' in job['prompt'])
print('contains_guardian', 'OWS-2 — Config guardian' in job['prompt'])
PY
```

Then commit just the cron prompt update:

```bash
git -C /root/.hermes add cron/jobs.json
git -C /root/.hermes commit -m "wolfy(cron): enable self-optimizing loop prompt"
```

If the user says `commit to github` or equivalent, push and verify remote HEAD matches local HEAD:

```bash
git -C /root/.hermes push origin main
git -C /root/.hermes rev-parse HEAD
git -C /root/.hermes ls-remote origin refs/heads/main
```

## Pitfalls

- Do not answer only `yes` when the user asks if the prompt was read; list the distinctive incorporated changes so they can see it was the current prompt, not the prior one.
- Do not let unrelated dirty skill/curator/profile changes ride along when committing `cron/jobs.json`.
- Do not convert the cron prompt's internal `Do not push git commits` rule into a global refusal to push when the user explicitly asks from chat; that rule governs the autonomous cron run.
- Do not use `cronjob.update` if you need to preserve exact document bytes and later prove prompt markers; direct JSON update plus marker verification is acceptable for prompt-only edits, but keep schedule/state unchanged.
