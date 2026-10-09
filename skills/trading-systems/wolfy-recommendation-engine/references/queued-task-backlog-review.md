# Queued task backlog review

Use this when reviewing Wolfy's Postgres `agent_tasks` queue. The goal is to distinguish an executable queue from accumulated historical intentions.

## Audit sequence

1. Inspect the live `agent_tasks` schema before querying; compatibility aliases and payload fields may coexist.
2. Count queued cards by effective type, owner, creation month, and age.
3. Produce a compact row list using effective values such as `coalesce(task_type,type,payload->>'type')`, `coalesce(title,payload->>'title',metadata->>'title')`, and the available owner aliases.
4. Check queued titles/source fingerprints against completed tasks. Exact completed predecessors and explicitly superseded work are closure candidates.
5. Detect repeated ticker work, but do not treat every same-ticker pair as a duplicate: Sentinel risk review and Yang technical review are separate lanes. Compare date, role, source run, and requested output.
6. Apply freshness semantics by task class:
   - scanner/catalyst/technical lead cards expire quickly; close stale cards and regenerate from current market data;
   - engineering, security, governance, and data-integrity cards require live-state revalidation before execution;
   - plan-only budget cards are accounting records, not implementation work;
   - old implementation plans should be rewritten when the current architecture has changed.
7. Apply standing policy before retaining research cards. Exclude policy-ineligible foreign exposure, broad/leveraged products, manipulation-risk instruments, or other unsupported security classes rather than spending research budget on them.
8. Review dependency fields and implicit prose dependencies. A queue with no machine-readable dependencies is not an execution graph even if descriptions say “depends on.”
9. Recommend dispositions explicitly: retain, elevate, rewrite, consolidate, expire, superseded-close, or human-verification required.
10. Do not mutate the board during a review unless the user authorizes cleanup. Preserve closed-card context in completion/verification metadata for auditability.

## Prioritization principles

Lead with blockers to trustworthy recommendations, not nominal numeric priority:

1. credential/repository safety;
2. complete and current EOD coverage;
3. usage/cadence controls that prevent autonomous work;
4. price-data integrity;
5. strategy-validation integrity;
6. architecture, learning-loop, and optional research improvements.

Security exceptions should not remain low-priority indefinitely. Session-sensitive market research should not become permanent backlog. Large old optimization batches should be consolidated into class-level workstreams after checking which behavior already exists.

## Reporting shape

Give the user:

- total queued count and composition;
- the central diagnosis (clean execution queue versus stale backlog);
- grouped disposition counts with representative IDs/titles;
- a proposed smaller ordered queue;
- the exact cleanup scope requiring authorization.

Avoid dumping raw JSON payloads or every verbose task description. Distinguish review recommendations from board changes actually performed.