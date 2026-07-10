#!/usr/bin/env python3
"""Prune Wolfy knowledge retrieval to technical trading + guardrails.

Policy for 2026-07-09 user directive:
- Optimize token consumption toward technical swing-trading strategy.
- Keep the source strategy_rules table intact for guardrail enforcement/audit.
- Keep only technical setup / core guardrail notes and rules in knowledge_chunks retrieval.
- Remove fundamental/catalyst/filing/company-research artifacts from knowledge_chunks.
- Archive all deleted rows before deletion.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import Json

PG_DSN = "dbname=wolfy user=root host=/var/run/postgresql"
SQLITE_PATH = Path("/root/.hermes/wolfy/wolfy.db")
RUN_ID = datetime.now(timezone.utc).strftime("technical_prune_%Y%m%dT%H%M%SZ")

TECH_RE = re.compile(
    r"\b(technical|volume|trend|momentum|relative strength|moving average|\bSMA\b|\bEMA\b|\bATR\b|\bRSI\b|\bMACD\b|breakout|pullback|setup|trigger|stop|invalidation|support|resistance|volatility|consolidation|base|stage|Weinstein|Darvas|chart|gap|mean reversion|wedge|channel|entry|exit|risk/reward|position[- ]size|R multiple|sector rotation|market breadth|52[- ]week|high tight flag|vwap|trendline|trailing stop|Yang|Minervini)\b",
    re.I,
)
CORE_GUARDRAIL_RE = re.compile(
    r"\b(eod|end[- ]of[- ]day|no[-_ ]?(auto|trade|action|recommendation)|fact[-_ ]?vs[-_ ]?judgment|research[-_ ]only|risk control|data quality|backtest|evaluation|portfolio|universe|Robinhood|PDT|pattern day|long[- ]only|max three|human approval|guardrail|approved strategy|do not|must not|cannot|quality gate)\b",
    re.I,
)
EXPLICIT_NONTECH_RE = re.compile(
    r"\b(SEC|filing|10[- ]?K|10[- ]?Q|8[- ]?K|Form [A-Z0-9-]+|13F|13D|13G|Section 16|insider|ownership|shareholder|governance|compensation|accounting|financial statement|balance sheet|cash flow|cashflow|dcf|revenue|earnings|ARR|EBITDA|valuation|Graham|margin of safety|analyst|rating|price target|merger|acquisition|contract|guidance|gross margin|product|catalyst|dilution|warrant|offering|convertible|debt|covenant|auditor|legal proceedings|MD&A)\b",
    re.I,
)


def classify(source_table: str | None, metadata_table: str | None, title: str | None, content: str | None) -> tuple[str, bool, bool, bool]:
    text = " ".join([source_table or "", metadata_table or "", title or "", content or ""])
    is_tech = bool(TECH_RE.search(text))
    is_guard = bool(CORE_GUARDRAIL_RE.search(text))
    is_fundamental = bool(EXPLICIT_NONTECH_RE.search(text))

    # Keep full source tables intact; prune only the vector/trigram retrieval surface.
    protected_yang_technical = bool((title or "").startswith("Yang")) and is_tech
    if source_table in {"sqlite.strategy_rules", "sqlite.knowledge_notes"} and (is_tech or is_guard) and not (is_fundamental and not protected_yang_technical):
        return "keep_technical_or_core_guardrail", is_tech, is_guard, is_fundamental
    return "remove_non_core_or_fundamental", is_tech, is_guard, is_fundamental


def main() -> None:
    pg = psycopg2.connect(PG_DSN)
    pg.autocommit = False
    deleted_sqlite_note_ids: list[int] = []
    manifest: dict[str, object] = {"run_id": RUN_ID}

    try:
        with pg.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_chunks_prune_archive (
                    archived_at timestamptz NOT NULL DEFAULT now(),
                    prune_run_id text NOT NULL,
                    reason text NOT NULL,
                    flags jsonb NOT NULL DEFAULT '{}'::jsonb,
                    original_id bigint NOT NULL,
                    artifact_id bigint,
                    source_table text,
                    source_id text,
                    chunk_index integer,
                    content text NOT NULL,
                    metadata jsonb NOT NULL,
                    title text,
                    created_at timestamptz
                )
                """
            )
            cur.execute(
                """
                SELECT id, artifact_id, source_table, source_id, chunk_index, content,
                       metadata, title, created_at, COALESCE(metadata->>'table','') AS metadata_table
                FROM knowledge_chunks
                ORDER BY id
                """
            )
            rows = cur.fetchall()
            remove_ids: list[int] = []
            counters: Counter[str] = Counter()
            removed_by_source: Counter[str] = Counter()
            kept_by_source: Counter[str] = Counter()

            for row in rows:
                (row_id, artifact_id, source_table, source_id, chunk_index, content, metadata, title, created_at, metadata_table) = row
                reason, is_tech, is_guard, is_fundamental = classify(source_table, metadata_table, title, content)
                counters[reason] += 1
                if reason.startswith("keep"):
                    kept_by_source[source_table or ""] += 1
                    continue
                remove_ids.append(row_id)
                removed_by_source[source_table or ""] += 1
                flags = {"technical": is_tech, "core_guardrail": is_guard, "fundamental_or_catalyst": is_fundamental}
                cur.execute(
                    """
                    INSERT INTO knowledge_chunks_prune_archive
                      (prune_run_id, reason, flags, original_id, artifact_id, source_table, source_id,
                       chunk_index, content, metadata, title, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (RUN_ID, reason, Json(flags), row_id, artifact_id, source_table, source_id, chunk_index, content, Json(metadata), title, created_at),
                )
                if source_table == "sqlite.knowledge_notes" and source_id and str(source_id).isdigit():
                    deleted_sqlite_note_ids.append(int(source_id))

            if remove_ids:
                cur.execute("DELETE FROM knowledge_chunks WHERE id = ANY(%s)", (remove_ids,))

            manifest.update(
                {
                    "pg_before": len(rows),
                    "pg_deleted": len(remove_ids),
                    "pg_after": len(rows) - len(remove_ids),
                    "classification_counts": dict(counters),
                    "removed_by_source_table": dict(removed_by_source),
                    "kept_by_source_table": dict(kept_by_source),
                    "sqlite_knowledge_notes_to_archive_delete": len(set(deleted_sqlite_note_ids)),
                }
            )

        pg.commit()
    except Exception:
        pg.rollback()
        raise
    finally:
        pg.close()

    # Remove source knowledge_notes that would otherwise be re-synced into chunks.
    sqlite_deleted = 0
    if deleted_sqlite_note_ids:
        unique_ids = sorted(set(deleted_sqlite_note_ids))
        sq = sqlite3.connect(SQLITE_PATH)
        try:
            cur = sq.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_notes_prune_archive AS
                SELECT *, '' AS prune_run_id, '' AS archived_at_utc, '' AS prune_reason
                FROM knowledge_notes WHERE 0
                """
            )
            now = datetime.now(timezone.utc).isoformat()
            for note_id in unique_ids:
                cur.execute(
                    """
                    INSERT INTO knowledge_notes_prune_archive
                    SELECT *, ?, ?, ? FROM knowledge_notes WHERE id=?
                    """,
                    (RUN_ID, now, "remove_non_core_or_fundamental", note_id),
                )
                cur.execute("DELETE FROM knowledge_notes WHERE id=?", (note_id,))
                sqlite_deleted += cur.rowcount
            sq.commit()
        except Exception:
            sq.rollback()
            raise
        finally:
            sq.close()
    manifest["sqlite_knowledge_notes_deleted"] = sqlite_deleted

    out = Path(f"/root/.hermes/wolfy/backups/{RUN_ID}_manifest.json")
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    print(f"manifest={out}")


if __name__ == "__main__":
    main()
