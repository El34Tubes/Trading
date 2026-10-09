# Wolfy technical-retrieval prune pattern — 2026-07-10

Use this when the user asks to focus Wolfy token/retrieval budget on technical trading strategy while preserving existing safety guardrails.

## Intent

The user wanted Wolfy optimized around technical trading. Some technical-setup knowledge is acceptable; broad fundamental, catalyst, company-story, filing, valuation, insider, analyst, cash-flow, and old alpha-lead narrative material should not consume retrieval context unless explicitly requested.

## Safe pruning shape

1. Back up/archive deleted `knowledge_chunks` before removal.
2. Classify chunks into:
   - `keep_technical_or_core_guardrail`: technical setups, Yang entry/exit/risk rules, EOD breakout/pullback/trend/volume/ATR/stop/relative-strength rules, portfolio/risk/account constraints, and compact no-auto-action / EOD-only / human-approval / approved-strategy / backtest-hygiene guardrails.
   - `remove_non_core_or_fundamental`: fundamental analysis, SEC filing analysis, catalyst narratives, alpha-lead research artifacts, company-specific research notes, insider/analyst/valuation/earnings/cash-flow material, and old scanner/research artifacts.
3. Keep source-of-truth guardrails intact even if retrieval chunks are trimmed. In this session the full `strategy_rules` source table stayed intact for audit/enforcement; only the retrieval/search surface was narrowed.
4. Trim SQLite/source notes that would otherwise re-sync removed notes back into Postgres retrieval.
5. Re-sync Postgres and embeddings after pruning; verify `count(*) == count(embedding)` for remaining chunks.
6. Smoke-test retrieval with technical queries and confirm top hits are technical/Yang/setup/risk material, not fundamental/catalyst narratives.
7. Keep 429/log hygiene coupled to the same checkpoint: stale quota evidence should be rotated/trimmed so watchdogs do not repeatedly rescan old raw payloads.

## Report shape

Keep the user-facing report short and concrete:

- before/after `knowledge_chunks` count;
- remaining counts by `source_table`;
- archive/deleted row count;
- embedding coverage;
- a few top technical smoke-test hits;
- watchdog/guardian status if relevant;
- commit hash and remote verification if pushed.

Avoid narrating every deleted category in detail unless asked; the user's preference is token-saving, technical-only focus, and concise no-filler status.

## Known verified outcome from this session

The implemented checkpoint reduced `knowledge_chunks` from 1,015 to 74; remaining retrieval chunks were 40 `sqlite.knowledge_notes` and 34 `sqlite.strategy_rules`, all embedded. Deleted chunks were archived locally under `/root/.hermes/wolfy/backups/`. Commit: `7040111 wolfy(knowledge): focus retrieval on technical trading`.
