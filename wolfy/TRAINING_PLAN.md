# Wolfy Autonomous Training Plan

## Objective
Build Wolfy into an accountable stock-market research and swing-trading analyst by combining a durable knowledge base, repeatable scanner/data pipeline, recommendation logging, paper-trade tracking, and performance review.

## Operating constraints
- U.S. stocks and ETFs first.
- Robinhood-tradable only where verifiable/proxy-passable.
- Long-only; no shorts.
- Options allowed, preferably defined-risk during paper trading.
- $5,000 starting paper account.
- Max 3 concurrent positions.
- Stops/invalidation required.
- Respect pattern day trading limits.
- Avoid thin, promotional, low-float, foreign manipulation-risk names.

## Hourly training loop
Each hour, if model/Codex quota is available:
1. Read `/root/.hermes/wolfy/hourly_knowledge_context.py` output.
2. Select the next queued source/framework and task from `wolfy.db`.
3. Use legal/public material or user-provided notes only.
4. Extract 1-3 principles.
5. Translate principles into Wolfy-specific strategy/risk rules.
6. Insert rows into `knowledge_notes` and/or `strategy_rules`.
7. Update source/task status.
8. Record a short progress report in `reports`.
9. Include new learnings in the next Wolfy progress report.

## Curriculum priority
1. O'Neil CAN SLIM / relative strength / earnings + breakouts.
2. Minervini trend template / VCP / risk-first swing entries.
3. Buffett/Munger quality, moat, capital allocation.
4. Graham margin of safety and balance-sheet discipline.
5. Howard Marks risk/cycles.
6. Weinstein stage analysis and sector rotation.
7. Market Wizards process/risk/psychology.
8. Damodaran valuation and narrative/numbers.
9. Mauboussin expectations/base rates.
10. Adaptive Markets/model decay.

## Recommendation tracking loop
Every Wolfy market report should log:
- report content,
- ticker recommendations,
- thesis,
- setup type,
- entry/trigger,
- stop,
- target,
- confidence,
- proposed paper size,
- status.

A daily/weekly grader should update:
- whether entry triggered,
- stop/target progress,
- max favorable/adverse excursion,
- R multiple,
- days held,
- thesis quality.

## Storage/statistics monitoring
Track hourly/daily:
- `/root/.hermes` size,
- `/root/.hermes/wolfy` size,
- `wolfy.db` size,
- root filesystem % used and available bytes,
- cron job count,
- table counts.

## Scale-up plan
Remain on SQLite until one of these trips:
- `wolfy.db` > 1GB: add archival/partitioning and optimize indexes.
- `wolfy.db` > 5GB or multiple concurrent writer failures: migrate to Postgres.
- `/root/.hermes/wolfy` > 20GB: move raw artifacts to object storage or compressed archives.
- root disk > 70% used: prune/archive logs, move DB backup off-disk, increase volume.
- Need semantic search over large notes: add vector index (sqlite-vss/lancedb/Chroma) while keeping SQLite as source of truth.
- Need dashboard or multi-agent heavy writes: Postgres + pgvector + scheduled backups.

## Honesty rule
Wolfy must not claim it learned from books/materials unless notes were actually inserted into the database from public/legal material or user-provided content.
