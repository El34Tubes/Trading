# Wolfy knowledge-objective audit + stale 429 log hygiene (2026-07-09)

Use this reference when the user asks whether Wolfy's learned knowledge is conflicting with the primary technical swing-trading goal, or asks to trim logs/stale 429 evidence before committing ops changes.

## Objective audit pattern

Primary question to answer: does the knowledge base directly conflict with the target operating mode, or is it merely broader than the target?

For the current Wolfy goal, separate these classes:

- **Core target:** EOD technical swing-trading strategy, deterministic signals/features/risk gates, human-gated strategy approval.
- **Allowed supporting context after 2026-07-09 pruning:** technical setup knowledge plus compact guardrails/risk controls only. Source/audit tables may retain broader records, but `knowledge_chunks` retrieval should not spend context on fundamentals, catalyst narratives, SEC filing analysis, or company-research artifacts.
- **Potential conflicts:** live/auto execution, intraday/day-trading instructions, crypto/forex/futures, shorts, unapproved strategy recommendations, LLM-invented edge, or reintroduced fundamental/catalyst chunks in `knowledge_chunks`.

Report the distinction plainly:

- If conflict terms mostly appear inside gating language, provenance, or risk context, say **retrieval dilution / taxonomy issue**, not direct contradiction.
- If live/auto-execution or non-approved-strategy action appears as instruction, treat it as a real conflict and recommend quarantine/relabeling.
- Always state current `strategies.status` and whether any strategy is `approved`; if none are approved, outputs remain research/watch-only even if knowledge chunks are useful.

Useful output shape:

```markdown
| Metric | Count |
|---|---:|
| Total chunks | ... |
| Embedded chunks | ... |
| Explicit EOD/research-only gated chunks | ... |
| Technical setup chunks | ... |
| Fundamental/catalyst chunks | ... |
| Foreign/manipulation/geopolitical-risk chunks | ... |
| Live/auto-execution matches | ... |
| Crypto/forex/futures matches | ... |
| Approved strategies | ... |
```

Conclusion language for the observed 2026-07-09 state: the knowledge was **not fundamentally conflicting** with the technical swing-trading goal, but it was not sharply focused enough; the main issue was retrieval dilution from mixing technical setup, catalyst/fundamental, filing, governance, scanner, and ops content.

## Stale 429/log hygiene pattern

When a 429/usage-limit log line has caused repeated false alarms or noisy reports:

1. Trim or rotate stale log/state evidence instead of continuing to rescan old raw traceback/payload lines.
2. Keep watchdog output minimal: event + fresh timestamp only.
3. Avoid writing raw quota-pattern strings back into logs/state fields that the next watchdog tick will scan as fresh evidence.
4. Reconcile watchdog state with live cron enabled/paused status before reporting jobs are still quota-gated.
5. Treat repo commits as source/config checkpoints only: ignore runtime logs, caches, temp JSON, backup files, known-good snapshots, skill usage counters, and other generated state unless the user explicitly asks to version them.

Commit/report shape after a hygiene change:

```markdown
CHANGED
- Trimmed stale 429 evidence / stopped tracking runtime state.

VERIFIED
- watchdog: silent or fresh event only
- guardian/config check: ok
- git: local HEAD == origin/main
```
