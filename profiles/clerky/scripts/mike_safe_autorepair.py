#!/usr/bin/env python3
"""Script-only safe autorepair for Mike's Wolfy/Hermes operations lane.

This does deterministic, non-destructive fixes that do not need an LLM.
It stays silent when everything is healthy.
"""
from __future__ import annotations

import shutil
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path('/root/.hermes')
SCRIPTS = ROOT / 'scripts'
WOLFY = ROOT / 'wolfy'
WOLFY_DB = WOLFY / 'wolfy.db'
MIKE = ROOT / 'profiles' / 'mike' / 'scripts'
CLERKY = ROOT / 'profiles' / 'clerky' / 'scripts'

# Scripts that may be invoked directly by cron/planners via their shebang.
# Keep execute bits repaired so shell-level smokes do not fail with
# Permission denied after file-tool writes that create 0600 files.
EXECUTABLE_WOLFY_SCRIPTS = [
    'check_postgres_requirements.py',
    'visible_progress_ledger.py',
]

MIKE_SCRIPTS = [
    'wolfy_storage_watchdog.py',
    'wolfy_usage_limit_watchdog.py',
    'wolfy_embed_knowledge_chunks.py',
    'wolfy_cleanup_stale_agent_coordination.py',
    'wolfy_capture_usage_snapshot.py',
    'wolfy_sync_cron_usage_to_agent_runs.py',
    'wolfy_hourly_knowledge_context.py',
    'wolfy_alpha_search_context.py',
    'wolfy_intraday_scanner_snapshot.py',
    'wolfy_sentinel_review_context.py',
    'wolfy_yang_technical_context.py',
    'eod_monitoring.py',
    'mike_environment_triage_context.py',
    'mike_safe_autorepair.py',
]
CLERKY_SCRIPTS = [
    'wolfy_clerky_activity_context.py',
    'wolfy_kanban_allocator.py',
    # Keep operations watchdog wrappers available in Clerky too so
    # profile-scoped diagnostics can smoke-test the same paths without
    # rediscovering missing-profile-wrapper false alarms.
    'wolfy_usage_limit_watchdog.py',
    'wolfy_sync_cron_usage_to_agent_runs.py',
    'wolfy_hourly_knowledge_context.py',
    'wolfy_alpha_search_context.py',
    'wolfy_intraday_scanner_snapshot.py',
    'wolfy_cleanup_stale_agent_coordination.py',
    'wolfy_capture_usage_snapshot.py',
    'eod_monitoring.py',
    # Keep Mike's script-only autorepair callable from profile-scoped
    # diagnostics when Clerky is auditing operations handoffs.
    'mike_safe_autorepair.py',
    # Keep legacy wrappers synchronized across profiles so profile-scoped
    # diagnostics/cron handoffs can invoke the same compatibility path.
    'wolfy_embed_knowledge_chunks.py',
]
WOLFY_SCRIPTS_FROM_GLOBAL: list[str] = []
LEGACY_WRAPPERS = {
    'wolfy-alpha-search-report.sh': "#!/usr/bin/env bash\nset -euo pipefail\nexec python3 /root/.hermes/wolfy/alpha_search_context.py \"$@\"\n",
    'wolfy_alpha_search_context.py': """#!/usr/bin/env python3
\"\"\"Compatibility wrapper for Wolfy's standalone Alpha Search context.\"\"\"
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/wolfy/alpha_search_context.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, *sys.argv[1:]]))
""",
    'wolfy_embed_knowledge_chunks.py': """#!/usr/bin/env python3
\"\"\"Compatibility wrapper for Wolfy's knowledge embedding sync.

Cron/profile wrappers and older diagnostics may still call this legacy name;
the live implementation is /root/.hermes/wolfy/embed_knowledge_chunks.py.
\"\"\"
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/wolfy/embed_knowledge_chunks.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, '--limit', '200', *sys.argv[1:]]))
""",
    'wolfy_hourly_knowledge_context.py': """#!/usr/bin/env python3
\"\"\"Compatibility wrapper for Jonah's hourly/autonomous knowledge context.\"\"\"
from __future__ import annotations

import runpy
import sys
from pathlib import Path

WOLFY_DIR = Path('/root/.hermes/wolfy')
if str(WOLFY_DIR) not in sys.path:
    sys.path.insert(0, str(WOLFY_DIR))

runpy.run_path(str(WOLFY_DIR / 'hourly_knowledge_context.py'), run_name='__main__')
""",
    'wolfy_sentinel_review_context.py': """#!/usr/bin/env python3
\"\"\"Compatibility wrapper for Sentinel's post-Wolfy review context.\"\"\"
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/wolfy/sentinel_review_context.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, *sys.argv[1:]]))
""",
    'wolfy_yang_technical_context.py': """#!/usr/bin/env python3
\"\"\"Compatibility wrapper for Yang's post-Sentinel technical context.\"\"\"
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/wolfy/yang_technical_context.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, *sys.argv[1:]]))
""",
    'wolfy_intraday_scanner_snapshot.py': """#!/usr/bin/env python3
\"\"\"Hermes no_agent wrapper for Wolfy's silent intraday scanner snapshot.\"\"\"
from __future__ import annotations

import sys
from pathlib import Path

WOLFY_DIR = Path('/root/.hermes/wolfy')
sys.path.insert(0, str(WOLFY_DIR))

from intraday_scanner_snapshot import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main())
""",
}
LEGACY_WOLFY_WRAPPERS = {
    'wolfy_alpha_search_context.py': """#!/usr/bin/env python3
\"\"\"Compatibility wrapper for Wolfy's standalone Alpha Search context.

Older diagnostics may still call wolfy_alpha_search_context.py directly;
the live implementation is alpha_search_context.py.
\"\"\"
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name('alpha_search_context.py')

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, str(SCRIPT), *sys.argv[1:]]))
""",
    'wolfy_embed_knowledge_chunks.py': """#!/usr/bin/env python3
\"\"\"Compatibility wrapper for the Wolfy knowledge embedding sync.

Some diagnostics and older cron/context snippets refer to this legacy filename;
the live implementation is embed_knowledge_chunks.py.
\"\"\"
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name('embed_knowledge_chunks.py')

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, str(SCRIPT), '--limit', '200', *sys.argv[1:]]))
""",
    'wolfy_hourly_knowledge_context.py': """#!/usr/bin/env python3
\"\"\"Compatibility wrapper for Jonah's hourly/autonomous knowledge context.

Older diagnostics may still call wolfy_hourly_knowledge_context.py directly;
the live implementation is hourly_knowledge_context.py.
\"\"\"
from __future__ import annotations

import runpy
import sys
from pathlib import Path

WOLFY_DIR = Path(__file__).resolve().parent
if str(WOLFY_DIR) not in sys.path:
    sys.path.insert(0, str(WOLFY_DIR))

runpy.run_path(str(WOLFY_DIR / 'hourly_knowledge_context.py'), run_name='__main__')
""",
    'wolfy_sentinel_review_context.py': """#!/usr/bin/env python3
\"\"\"Compatibility wrapper for Sentinel's post-Wolfy review context.

Older diagnostics may still call wolfy_sentinel_review_context.py directly;
the live implementation is sentinel_review_context.py.
\"\"\"
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name('sentinel_review_context.py')

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, str(SCRIPT), *sys.argv[1:]]))
""",
    'wolfy_yang_technical_context.py': """#!/usr/bin/env python3
\"\"\"Compatibility wrapper for Yang's post-Sentinel technical context.

Older diagnostics may still call wolfy_yang_technical_context.py directly;
the live implementation is yang_technical_context.py.
\"\"\"
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name('yang_technical_context.py')

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, str(SCRIPT), *sys.argv[1:]]))
""",
    'wolfy_intraday_scanner_snapshot.py': """#!/usr/bin/env python3
\"\"\"Compatibility wrapper for Wolfy's silent intraday scanner snapshot.

Older diagnostics may still call wolfy_intraday_scanner_snapshot.py directly;
the live implementation is intraday_scanner_snapshot.py.
\"\"\"
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name('intraday_scanner_snapshot.py')

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, str(SCRIPT), *sys.argv[1:]]))
""",
    'wolfy_cleanup_stale_agent_coordination.py': """#!/usr/bin/env python3
\"\"\"Compatibility wrapper for Wolfy's stale agent-coordination cleanup.\"\"\"
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name('cleanup_stale_agent_coordination.py')

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, str(SCRIPT), *sys.argv[1:]]))
""",
    'wolfy_capture_usage_snapshot.py': """#!/usr/bin/env python3
\"\"\"Compatibility wrapper for Wolfy's aggregate usage snapshot helper.\"\"\"
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name('capture_usage_snapshot.py')

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, str(SCRIPT), *sys.argv[1:]]))
""",
    'wolfy_usage_limit_watchdog.py': """#!/usr/bin/env python3
\"\"\"Compatibility wrapper for Wolfy's usage-limit watchdog.\"\"\"
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/scripts/wolfy_usage_limit_watchdog.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, *sys.argv[1:]]))
""",
    'wolfy_clerky_activity_context.py': """#!/usr/bin/env python3
\"\"\"Compatibility wrapper for Clerky's deterministic activity context.\"\"\"
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/scripts/wolfy_clerky_activity_context.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, *sys.argv[1:]]))
""",
    'wolfy_kanban_allocator.py': """#!/usr/bin/env python3
\"\"\"Compatibility wrapper for Clerky's bounded Kanban allocator.\"\"\"
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/scripts/wolfy_kanban_allocator.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, *sys.argv[1:]]))
""",
}


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 90) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True, timeout=timeout)
    return proc.returncode, ((proc.stdout or '') + (proc.stderr or '')).strip()


def sync_scripts() -> list[str]:
    changed: list[str] = []
    for name, content in LEGACY_WRAPPERS.items():
        dest = SCRIPTS / name
        if not dest.exists() or dest.read_text() != content:
            dest.write_text(content)
            dest.chmod(0o755)
            changed.append(f'WROTE_LEGACY_WRAPPER {dest}')
    for name, content in LEGACY_WOLFY_WRAPPERS.items():
        dest = WOLFY / name
        if not dest.exists() or dest.read_text() != content:
            dest.write_text(content)
            dest.chmod(0o755)
            changed.append(f'WROTE_LEGACY_WOLFY_WRAPPER {dest}')
    wolfy_autorepair = WOLFY / 'mike_safe_autorepair.py'
    self_script = SCRIPTS / 'mike_safe_autorepair.py'
    if self_script.exists() and (not wolfy_autorepair.exists() or self_script.read_bytes() != wolfy_autorepair.read_bytes()):
        shutil.copy2(self_script, wolfy_autorepair)
        wolfy_autorepair.chmod(0o755)
        changed.append(f'SYNCED_WOLFY_AUTOREPAIR {wolfy_autorepair}')
    for name in WOLFY_SCRIPTS_FROM_GLOBAL:
        src = SCRIPTS / name
        dest = WOLFY / name
        if not src.exists():
            changed.append(f'MISSING_SOURCE_SCRIPT {src}')
            continue
        if not dest.exists() or src.read_bytes() != dest.read_bytes():
            shutil.copy2(src, dest)
            dest.chmod(0o755)
            changed.append(f'SYNCED_WOLFY_SCRIPT {dest}')
    for dest_dir, names in [(MIKE, MIKE_SCRIPTS), (CLERKY, CLERKY_SCRIPTS)]:
        dest_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            src = SCRIPTS / name
            dest = dest_dir / name
            if not src.exists():
                changed.append(f'MISSING_SOURCE_SCRIPT {src}')
                continue
            if not dest.exists() or src.read_bytes() != dest.read_bytes():
                shutil.copy2(src, dest)
                dest.chmod(0o755)
                changed.append(f'SYNCED_PROFILE_SCRIPT {dest}')
    return changed


def ensure_script_modes() -> list[str]:
    changed: list[str] = []
    for name in EXECUTABLE_WOLFY_SCRIPTS:
        path = WOLFY / name
        if not path.exists():
            continue
        mode = path.stat().st_mode & 0o777
        if mode != 0o755:
            path.chmod(0o755)
            changed.append(f'FIXED_EXECUTABLE_MODE {path}')
    return changed


def ensure_sqlite_compatibility_aliases() -> list[str]:
    """Apply non-destructive SQLite compatibility aliases used by diagnostics.

    Jonah/Wolfy LLM-generated smoke queries sometimes ask common note-ledger
    names (title/category/note/content/note_type) while the canonical Wolfy
    table uses topic/tags/summary. They also sometimes ask knowledge_sources
    for path while the canonical table uses url_or_reference. Keep aliases
    nullable and backfilled instead of changing the canonical write path.
    """
    if not WOLFY_DB.exists():
        return [f'MISSING_WOLFY_DB {WOLFY_DB}']
    changed: list[str] = []
    with sqlite3.connect(WOLFY_DB) as con:
        cols = {row[1] for row in con.execute('PRAGMA table_info(knowledge_notes)')}
        for name in ('title', 'category', 'note', 'content', 'note_type', 'source_type'):
            if name not in cols:
                con.execute(f'ALTER TABLE knowledge_notes ADD COLUMN {name} TEXT')
                changed.append(f'ADDED_SQLITE_ALIAS knowledge_notes.{name}')
        source_cols = {row[1] for row in con.execute('PRAGMA table_info(knowledge_sources)')}
        for name in ('path', 'url'):
            if name not in source_cols:
                con.execute(f'ALTER TABLE knowledge_sources ADD COLUMN {name} TEXT')
                changed.append(f'ADDED_SQLITE_ALIAS knowledge_sources.{name}')
        rule_cols = {row[1] for row in con.execute('PRAGMA table_info(strategy_rules)')}
        for name in ('category', 'source_id', 'rule_text'):
            if name not in rule_cols:
                con.execute(f'ALTER TABLE strategy_rules ADD COLUMN {name} TEXT')
                changed.append(f'ADDED_SQLITE_ALIAS strategy_rules.{name}')
        if 'is_active' not in rule_cols:
            con.execute('ALTER TABLE strategy_rules ADD COLUMN is_active INTEGER')
            changed.append('ADDED_SQLITE_ALIAS strategy_rules.is_active')
        con.execute(
            """
            UPDATE knowledge_notes
            SET title=COALESCE(title, topic),
                category=COALESCE(category, tags),
                note=COALESCE(note, summary),
                content=COALESCE(content, summary),
                note_type=COALESCE(note_type, category, tags),
                source_type=COALESCE(source_type, note_type, category, tags)
            WHERE title IS NULL OR category IS NULL OR note IS NULL OR content IS NULL OR note_type IS NULL OR source_type IS NULL
            """
        )
        con.execute(
            """
            UPDATE knowledge_sources
            SET path=COALESCE(path, url_or_reference),
                url=COALESCE(url, url_or_reference)
            WHERE path IS NULL OR url IS NULL
            """
        )
        con.execute(
            """
            UPDATE strategy_rules
            SET category=COALESCE(category, rule_type),
                source_id=COALESCE(source_id, source_basis),
                rule_text=COALESCE(rule_text, description),
                is_active=COALESCE(is_active, enabled),
                name=COALESCE(name, rule_name),
                status=COALESCE(status, implementation_status, CASE WHEN enabled=1 THEN 'active' ELSE 'inactive' END),
                asset_class=COALESCE(asset_class, 'equity_etf_process')
            WHERE category IS NULL OR source_id IS NULL OR rule_text IS NULL OR is_active IS NULL OR name IS NULL OR status IS NULL OR asset_class IS NULL
            """
        )
        if con.total_changes:
            changed.append(f'BACKFILLED_SQLITE_ALIASES rows_changed={con.total_changes}')
        con.executescript(
            """
            DROP TRIGGER IF EXISTS trg_knowledge_notes_alias_after_insert;
            DROP TRIGGER IF EXISTS trg_knowledge_notes_alias_after_update;
            DROP TRIGGER IF EXISTS trg_knowledge_sources_path_after_insert;
            DROP TRIGGER IF EXISTS trg_knowledge_sources_path_after_update;
            DROP TRIGGER IF EXISTS trg_strategy_rules_alias_after_insert;
            DROP TRIGGER IF EXISTS trg_strategy_rules_alias_after_update;

            CREATE TRIGGER IF NOT EXISTS trg_knowledge_notes_alias_after_insert
            AFTER INSERT ON knowledge_notes
            FOR EACH ROW
            WHEN NEW.title IS NULL OR NEW.category IS NULL OR NEW.note IS NULL OR NEW.content IS NULL OR NEW.note_type IS NULL OR NEW.source_type IS NULL
            BEGIN
              UPDATE knowledge_notes
              SET title=COALESCE(NEW.title, NEW.topic),
                  category=COALESCE(NEW.category, NEW.tags),
                  note=COALESCE(NEW.note, NEW.summary),
                  content=COALESCE(NEW.content, NEW.summary),
                  note_type=COALESCE(NEW.note_type, NEW.category, NEW.tags),
                  source_type=COALESCE(NEW.source_type, NEW.note_type, NEW.category, NEW.tags)
              WHERE id=NEW.id;
            END;

            CREATE TRIGGER IF NOT EXISTS trg_knowledge_notes_alias_after_update
            AFTER UPDATE OF topic, tags, summary, title, category, note, content, note_type, source_type ON knowledge_notes
            FOR EACH ROW
            WHEN NEW.title IS NULL OR NEW.category IS NULL OR NEW.note IS NULL OR NEW.content IS NULL OR NEW.note_type IS NULL OR NEW.source_type IS NULL
            BEGIN
              UPDATE knowledge_notes
              SET title=COALESCE(NEW.title, NEW.topic),
                  category=COALESCE(NEW.category, NEW.tags),
                  note=COALESCE(NEW.note, NEW.summary),
                  content=COALESCE(NEW.content, NEW.summary),
                  note_type=COALESCE(NEW.note_type, NEW.category, NEW.tags),
                  source_type=COALESCE(NEW.source_type, NEW.note_type, NEW.category, NEW.tags)
              WHERE id=NEW.id;
            END;

            CREATE TRIGGER IF NOT EXISTS trg_knowledge_sources_path_after_insert
            AFTER INSERT ON knowledge_sources
            FOR EACH ROW
            WHEN NEW.path IS NULL OR NEW.url IS NULL
            BEGIN
              UPDATE knowledge_sources
              SET path=COALESCE(NEW.path, NEW.url_or_reference),
                  url=COALESCE(NEW.url, NEW.url_or_reference)
              WHERE id=NEW.id;
            END;

            CREATE TRIGGER IF NOT EXISTS trg_knowledge_sources_path_after_update
            AFTER UPDATE OF url_or_reference, path, url ON knowledge_sources
            FOR EACH ROW
            WHEN NEW.path IS NULL OR NEW.url IS NULL
            BEGIN
              UPDATE knowledge_sources
              SET path=COALESCE(NEW.path, NEW.url_or_reference),
                  url=COALESCE(NEW.url, NEW.url_or_reference)
              WHERE id=NEW.id;
            END;

            CREATE TRIGGER IF NOT EXISTS trg_strategy_rules_alias_after_insert
            AFTER INSERT ON strategy_rules
            FOR EACH ROW
            WHEN NEW.category IS NULL OR NEW.source_id IS NULL OR NEW.rule_text IS NULL OR NEW.is_active IS NULL OR NEW.name IS NULL OR NEW.status IS NULL OR NEW.asset_class IS NULL
            BEGIN
              UPDATE strategy_rules
              SET category=COALESCE(NEW.category, NEW.rule_type),
                  source_id=COALESCE(NEW.source_id, NEW.source_basis),
                  rule_text=COALESCE(NEW.rule_text, NEW.description),
                  is_active=COALESCE(NEW.is_active, NEW.enabled),
                  name=COALESCE(NEW.name, NEW.rule_name),
                  status=COALESCE(NEW.status, NEW.implementation_status, CASE WHEN NEW.enabled=1 THEN 'active' ELSE 'inactive' END),
                  asset_class=COALESCE(NEW.asset_class, 'equity_etf_process')
              WHERE id=NEW.id;
            END;

            CREATE TRIGGER IF NOT EXISTS trg_strategy_rules_alias_after_update
            AFTER UPDATE OF rule_name, rule_type, description, source_basis, implementation_status, enabled, name, status, asset_class, category, source_id, rule_text, is_active ON strategy_rules
            FOR EACH ROW
            WHEN NEW.category IS NULL OR NEW.source_id IS NULL OR NEW.rule_text IS NULL OR NEW.is_active IS NULL OR NEW.name IS NULL OR NEW.status IS NULL OR NEW.asset_class IS NULL
            BEGIN
              UPDATE strategy_rules
              SET category=COALESCE(NEW.category, NEW.rule_type),
                  source_id=COALESCE(NEW.source_id, NEW.source_basis),
                  rule_text=COALESCE(NEW.rule_text, NEW.description),
                  is_active=COALESCE(NEW.is_active, NEW.enabled),
                  name=COALESCE(NEW.name, NEW.rule_name),
                  status=COALESCE(NEW.status, NEW.implementation_status, CASE WHEN NEW.enabled=1 THEN 'active' ELSE 'inactive' END),
                  asset_class=COALESCE(NEW.asset_class, 'equity_etf_process')
              WHERE id=NEW.id;
            END;
            """
        )
        con.commit()
    return changed


def ensure_postgres_compatibility_aliases() -> list[str]:
    """Apply non-destructive Postgres aliases used by ad-hoc diagnostics.

    LLM-authored operational probes occasionally use common column names from
    earlier SQLite/context examples. Keep nullable mirror columns plus triggers
    so those probes fail less often without changing canonical write paths.
    """
    sql = r"""
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS scanner_run_id BIGINT;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS status TEXT;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS company_name TEXT;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS scanner_type TEXT;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS signal TEXT;
    UPDATE scanner_results
    SET scanner_run_id=COALESCE(scanner_run_id, run_id),
        status=COALESCE(status, CASE WHEN liquidity_pass IS FALSE THEN 'filtered' ELSE 'observed' END),
        company_name=COALESCE(company_name, notes->>'company_name', notes->>'company'),
        scanner_type=COALESCE(scanner_type, notes->>'scanner_type', notes->>'signal', notes->>'lead_type'),
        signal=COALESCE(signal, notes->>'signal', notes->>'scanner_type', scanner_type)
    WHERE scanner_run_id IS NULL OR status IS NULL OR company_name IS NULL OR scanner_type IS NULL OR signal IS NULL;

    ALTER TABLE scanner_runs ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
    ALTER TABLE scanner_runs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
    ALTER TABLE scanner_runs ADD COLUMN IF NOT EXISTS mode TEXT;
    UPDATE scanner_runs
    SET started_at=COALESCE(started_at, run_time),
        mode=COALESCE(mode, data_source)
    WHERE started_at IS NULL OR mode IS NULL;

    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS summary TEXT;
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS error_message TEXT;
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS payload JSONB;
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS agent TEXT;
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS assigned_agent TEXT;
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS source_table TEXT;
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS source_id TEXT;
    UPDATE agent_tasks SET agent=agent_name WHERE agent IS NULL;
    UPDATE agent_tasks SET assigned_agent=agent_name WHERE assigned_agent IS NULL;
    UPDATE agent_tasks SET summary=description WHERE summary IS NULL AND description IS NOT NULL;
    UPDATE agent_tasks
    SET error_message=COALESCE(error_message, summary, description)
    WHERE status='blocked' AND error_message IS NULL;
    UPDATE agent_tasks
    SET source_table=COALESCE(source_table, payload->>'source_table', 'agent_tasks'),
        source_id=COALESCE(source_id, payload->>'source_id', source_fingerprint, id::text)
    WHERE source_table IS NULL OR source_id IS NULL;
    UPDATE agent_tasks
    SET payload = jsonb_strip_nulls(jsonb_build_object(
        'id', id,
        'agent_name', agent_name,
        'agent', agent,
        'assigned_agent', assigned_agent,
        'task_type', task_type,
        'title', title,
        'description', description,
        'status', status,
        'priority', priority,
        'source_fingerprint', source_fingerprint,
        'topic_tags', topic_tags,
        'ticker_symbols', ticker_symbols,
        'depends_on', depends_on,
        'supersedes', supersedes,
        'created_at', created_at,
        'updated_at', updated_at,
        'summary', summary,
        'error_message', error_message,
        'source_table', source_table,
        'source_id', source_id
    ))
    WHERE payload IS NULL;

    ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
    ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS result_summary TEXT;
    -- Compatibility mirror for read-only ops probes that inspect agent_runs
    -- directly and expect the linked task type there. Canonical task type
    -- lives on agent_tasks.task_type and agent_runs.task_id is the join key.
    ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS task_type TEXT;
    UPDATE agent_runs SET completed_at=ended_at WHERE completed_at IS NULL AND ended_at IS NOT NULL;
    UPDATE agent_runs SET result_summary=summary WHERE result_summary IS NULL AND summary IS NOT NULL;
    UPDATE agent_runs ar
    SET task_type=at.task_type
    FROM agent_tasks at
    WHERE ar.task_id = at.id
      AND ar.task_type IS NULL;

    -- Compatibility mirror for ad-hoc/read-only probes that expect a
    -- resolved/final URL column. Canonical writes use agent_artifacts.source_url.
    ALTER TABLE agent_artifacts ADD COLUMN IF NOT EXISTS source_final_url TEXT;
    UPDATE agent_artifacts
    SET source_final_url = source_url
    WHERE source_final_url IS NULL AND source_url IS NOT NULL;

    CREATE OR REPLACE FUNCTION wolfy_sync_agent_artifacts_aliases()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.source_final_url IS NULL THEN
        NEW.source_final_url := NEW.source_url;
      END IF;
      RETURN NEW;
    END;
    $$;
    DROP TRIGGER IF EXISTS trg_agent_artifacts_aliases_biu ON agent_artifacts;
    CREATE TRIGGER trg_agent_artifacts_aliases_biu
      BEFORE INSERT OR UPDATE OF source_url, source_final_url ON agent_artifacts
      FOR EACH ROW EXECUTE FUNCTION wolfy_sync_agent_artifacts_aliases();

    -- Compatibility mirror for ad-hoc/read-only probes. Canonical titles live
    -- on agent_artifacts.title or knowledge_chunks.metadata.
    ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS title TEXT;
    UPDATE knowledge_chunks kc
    SET title = COALESCE(kc.title, kc.metadata->>'title', kc.metadata->>'source_title', aa.title, kc.source_table || ':' || kc.source_id)
    FROM agent_artifacts aa
    WHERE kc.artifact_id = aa.id
      AND kc.title IS NULL;
    UPDATE knowledge_chunks
    SET title = COALESCE(title, metadata->>'title', metadata->>'source_title', source_table || ':' || source_id)
    WHERE title IS NULL;

    CREATE OR REPLACE FUNCTION wolfy_sync_knowledge_chunks_aliases()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.title IS NULL THEN
        SELECT COALESCE(NEW.metadata->>'title', NEW.metadata->>'source_title', aa.title, NEW.source_table || ':' || NEW.source_id)
        INTO NEW.title
        FROM agent_artifacts aa
        WHERE aa.id = NEW.artifact_id;
        IF NEW.title IS NULL THEN
          NEW.title := COALESCE(NEW.metadata->>'title', NEW.metadata->>'source_title', NEW.source_table || ':' || NEW.source_id);
        END IF;
      END IF;
      RETURN NEW;
    END;
    $$;
    DROP TRIGGER IF EXISTS trg_knowledge_chunks_aliases_biu ON knowledge_chunks;
    CREATE TRIGGER trg_knowledge_chunks_aliases_biu
      BEFORE INSERT OR UPDATE OF artifact_id, source_table, source_id, metadata, title ON knowledge_chunks
      FOR EACH ROW EXECUTE FUNCTION wolfy_sync_knowledge_chunks_aliases();

    ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS company_name TEXT;
    ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS scanner_type TEXT;
    ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS scanner_run_id BIGINT;
    ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS market_context JSONB;
    ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS score DOUBLE PRECISION;
    ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS evidence_quality NUMERIC(5,3);
    ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS rationale TEXT;
    ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS summary TEXT;
    UPDATE alpha_leads
    SET company_name=COALESCE(company_name, raw_payload->>'company_name', raw_payload->>'company'),
        scanner_type=COALESCE(scanner_type, raw_payload->>'scanner_type', raw_payload->>'signal', raw_payload->>'lead_type', lead_type),
        scanner_run_id=COALESCE(scanner_run_id,
          CASE WHEN (raw_payload->>'scanner_run_id') ~ '^[0-9]+$' THEN (raw_payload->>'scanner_run_id')::bigint END,
          CASE WHEN (raw_payload->>'scanner_run') ~ '^[0-9]+$' THEN (raw_payload->>'scanner_run')::bigint END,
          CASE WHEN (raw_payload->>'run_id') ~ '^[0-9]+$' THEN (raw_payload->>'run_id')::bigint END),
        market_context=COALESCE(market_context, raw_payload->'market_context'),
        rationale=COALESCE(rationale, thesis, raw_payload->>'rationale', raw_payload->>'summary'),
        summary=COALESCE(summary, raw_payload->>'summary', thesis, title),
        score=COALESCE(score,
          CASE WHEN (raw_payload->>'score') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (raw_payload->>'score')::double precision END,
          CASE WHEN (raw_payload->>'scanner_score') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (raw_payload->>'scanner_score')::double precision END,
          evidence_quality_score::double precision),
        evidence_quality=COALESCE(evidence_quality, evidence_quality_score)
    WHERE company_name IS NULL OR scanner_type IS NULL OR scanner_run_id IS NULL OR market_context IS NULL OR score IS NULL OR evidence_quality IS NULL OR rationale IS NULL OR summary IS NULL;

    ALTER TABLE recommendation_reviews
      ALTER COLUMN recommendation_id TYPE BIGINT USING recommendation_id::bigint;

    DROP VIEW IF EXISTS alpha_search_leads;
    CREATE VIEW alpha_search_leads AS
    SELECT
      id, sqlite_id, report_id, created_at, updated_at, ticker, lead_type, title,
      thesis, rationale, summary, status, evidence_quality_score AS score,
      evidence_quality_score, evidence_quality, evidence_count, highest_source_quality,
      suspicious_action, suspicious_flags, catalyst_window, social_context,
      filing_context, insider_context, complete_ticket, recommendation_id,
      next_research_question, company_name, scanner_type, scanner_run_id, market_context,
      raw_payload, source_fingerprint
    FROM alpha_leads;

    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS type TEXT;
    UPDATE agent_tasks
    SET type=task_type
    WHERE type IS NULL;

    DROP VIEW IF EXISTS strategy_rules;
    CREATE VIEW strategy_rules AS
    SELECT
      id::bigint AS id,
      name,
      name AS title,
      NULL::text AS ticker,
      name AS rule_name,
      status,
      status AS scope,
      status AS implementation_status,
      setup_type AS rule_type,
      ARRAY[]::text[] AS ticker_symbols,
      ARRAY[setup_type, status]::text[] AS topic_tags,
      notes AS description,
      notes AS summary,
      notes AS body,
      COALESCE(params, '{}'::jsonb) AS metadata,
      COALESCE(params->>'source','postgres.strategies') AS source_basis,
      (status IN ('approved','candidate')) AS enabled,
      (status IN ('approved','active','candidate')) AS is_active,
      NULL::timestamptz AS created_at,
      NULL::timestamptz AS updated_at,
      'equity_etf_process'::text AS asset_class,
      setup_type AS category,
      id::text AS source_id,
      notes AS rule_text
    FROM strategies
    UNION ALL
    SELECT
      ('1000000000'::bigint + source_id::bigint) AS id,
      btrim(regexp_replace(split_part(content, E'\n', 1), '^Rule:\s*', '')) AS name,
      btrim(regexp_replace(split_part(content, E'\n', 1), '^Rule:\s*', '')) AS title,
      NULL::text AS ticker,
      btrim(regexp_replace(split_part(content, E'\n', 1), '^Rule:\s*', '')) AS rule_name,
      'active'::text AS status,
      'active'::text AS scope,
      'active'::text AS implementation_status,
      NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '') AS rule_type,
      ARRAY[]::text[] AS ticker_symbols,
      ARRAY_REMOVE(ARRAY['sqlite.strategy_rules', NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '')], NULL)::text[] AS topic_tags,
      btrim(regexp_replace(regexp_replace(content, E'^Rule:[^\n]*\nType:[^\n]*\nDescription:\s*', ''), E'\n+', ' ', 'g')) AS description,
      btrim(regexp_replace(regexp_replace(content, E'^Rule:[^\n]*\nType:[^\n]*\nDescription:\s*', ''), E'\n+', ' ', 'g')) AS summary,
      btrim(regexp_replace(regexp_replace(content, E'^Rule:[^\n]*\nType:[^\n]*\nDescription:\s*', ''), E'\n+', ' ', 'g')) AS body,
      metadata AS metadata,
      'sqlite.strategy_rules'::text AS source_basis,
      true AS enabled,
      true AS is_active,
      created_at AS created_at,
      created_at AS updated_at,
      'equity_etf_process'::text AS asset_class,
      NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '') AS category,
      source_id AS source_id,
      btrim(regexp_replace(regexp_replace(content, E'^Rule:[^\n]*\nType:[^\n]*\nDescription:\s*', ''), E'\n+', ' ', 'g')) AS rule_text
    FROM knowledge_chunks
    WHERE source_table='sqlite.strategy_rules' AND source_id ~ '^[0-9]+$';

    CREATE OR REPLACE FUNCTION wolfy_sync_scanner_results_aliases()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.scanner_run_id IS NULL THEN
        NEW.scanner_run_id := NEW.run_id;
      END IF;
      IF NEW.status IS NULL THEN
        IF NEW.liquidity_pass IS FALSE THEN
          NEW.status := 'filtered';
        ELSE
          NEW.status := 'observed';
        END IF;
      END IF;
      IF NEW.company_name IS NULL THEN
        NEW.company_name := COALESCE(NEW.notes->>'company_name', NEW.notes->>'company');
      END IF;
      IF NEW.scanner_type IS NULL THEN
        NEW.scanner_type := COALESCE(NEW.notes->>'scanner_type', NEW.notes->>'signal', NEW.notes->>'lead_type');
      END IF;
      IF NEW.signal IS NULL THEN
        NEW.signal := COALESCE(NEW.notes->>'signal', NEW.notes->>'scanner_type', NEW.scanner_type);
      END IF;
      RETURN NEW;
    END;
    $$;
    DROP TRIGGER IF EXISTS trg_scanner_results_aliases_biu ON scanner_results;
    CREATE TRIGGER trg_scanner_results_aliases_biu
      BEFORE INSERT OR UPDATE OF run_id, scanner_run_id, liquidity_pass, status, notes, company_name, scanner_type, signal ON scanner_results
      FOR EACH ROW EXECUTE FUNCTION wolfy_sync_scanner_results_aliases();

    CREATE OR REPLACE FUNCTION wolfy_sync_scanner_runs_aliases()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.started_at IS NULL THEN
        NEW.started_at := NEW.run_time;
      END IF;
      IF NEW.mode IS NULL THEN
        NEW.mode := NEW.data_source;
      END IF;
      RETURN NEW;
    END;
    $$;
    DROP TRIGGER IF EXISTS trg_scanner_runs_aliases_biu ON scanner_runs;
    CREATE TRIGGER trg_scanner_runs_aliases_biu
      BEFORE INSERT OR UPDATE OF run_time, started_at, data_source, mode ON scanner_runs
      FOR EACH ROW EXECUTE FUNCTION wolfy_sync_scanner_runs_aliases();

    CREATE OR REPLACE FUNCTION wolfy_sync_agent_tasks_aliases()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.type IS NULL THEN
        NEW.type := NEW.task_type;
      END IF;
      IF NEW.agent IS NULL THEN
        NEW.agent := NEW.agent_name;
      END IF;
      IF NEW.assigned_agent IS NULL THEN
        NEW.assigned_agent := NEW.agent_name;
      END IF;
      IF NEW.summary IS NULL THEN
        NEW.summary := NEW.description;
      END IF;
      IF NEW.status = 'blocked' AND NEW.error_message IS NULL THEN
        NEW.error_message := COALESCE(NEW.summary, NEW.description);
      END IF;
      IF NEW.payload IS NULL THEN
        NEW.payload := jsonb_strip_nulls(jsonb_build_object(
          'id', NEW.id,
          'agent_name', NEW.agent_name,
          'agent', NEW.agent,
          'assigned_agent', NEW.assigned_agent,
          'task_type', NEW.task_type,
          'type', NEW.type,
          'title', NEW.title,
          'description', NEW.description,
          'status', NEW.status,
          'priority', NEW.priority,
          'source_fingerprint', NEW.source_fingerprint,
          'topic_tags', NEW.topic_tags,
          'ticker_symbols', NEW.ticker_symbols,
          'depends_on', NEW.depends_on,
          'supersedes', NEW.supersedes,
          'created_at', NEW.created_at,
          'updated_at', NEW.updated_at,
          'summary', NEW.summary,
          'error_message', NEW.error_message,
          'source_table', NEW.source_table,
          'source_id', NEW.source_id
        ));
      END IF;
      IF NEW.source_table IS NULL THEN
        NEW.source_table := COALESCE(NEW.payload->>'source_table', 'agent_tasks');
      END IF;
      IF NEW.source_id IS NULL THEN
        NEW.source_id := COALESCE(NEW.payload->>'source_id', NEW.source_fingerprint, NEW.id::text);
      END IF;
      RETURN NEW;
    END;
    $$;
    DROP TRIGGER IF EXISTS trg_agent_tasks_aliases_biu ON agent_tasks;
    CREATE TRIGGER trg_agent_tasks_aliases_biu
      BEFORE INSERT OR UPDATE OF agent_name, agent, assigned_agent, task_type, type, description, summary, error_message, status, payload, source_table, source_id ON agent_tasks
      FOR EACH ROW EXECUTE FUNCTION wolfy_sync_agent_tasks_aliases();

    CREATE OR REPLACE FUNCTION wolfy_sync_agent_runs_aliases()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.completed_at IS NULL THEN
        NEW.completed_at := NEW.ended_at;
      END IF;
      IF NEW.ended_at IS NULL THEN
        NEW.ended_at := NEW.completed_at;
      END IF;
      IF NEW.result_summary IS NULL THEN
        NEW.result_summary := NEW.summary;
      END IF;
      IF NEW.summary IS NULL THEN
        NEW.summary := NEW.result_summary;
      END IF;
      IF NEW.task_type IS NULL AND NEW.task_id IS NOT NULL THEN
        SELECT at.task_type INTO NEW.task_type
        FROM agent_tasks at
        WHERE at.id = NEW.task_id;
      END IF;
      RETURN NEW;
    END;
    $$;
    DROP TRIGGER IF EXISTS trg_agent_runs_aliases_biu ON agent_runs;
    CREATE TRIGGER trg_agent_runs_aliases_biu
      BEFORE INSERT OR UPDATE OF task_id, task_type, ended_at, completed_at, summary, result_summary ON agent_runs
      FOR EACH ROW EXECUTE FUNCTION wolfy_sync_agent_runs_aliases();

    CREATE OR REPLACE FUNCTION wolfy_sync_alpha_leads_aliases()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.company_name IS NULL THEN
        NEW.company_name := COALESCE(NEW.raw_payload->>'company_name', NEW.raw_payload->>'company');
      END IF;
      IF NEW.scanner_type IS NULL THEN
        NEW.scanner_type := COALESCE(NEW.raw_payload->>'scanner_type', NEW.raw_payload->>'signal', NEW.raw_payload->>'lead_type', NEW.lead_type);
      END IF;
      IF NEW.scanner_run_id IS NULL THEN
        NEW.scanner_run_id := COALESCE(
          CASE WHEN (NEW.raw_payload->>'scanner_run_id') ~ '^[0-9]+$' THEN (NEW.raw_payload->>'scanner_run_id')::bigint END,
          CASE WHEN (NEW.raw_payload->>'scanner_run') ~ '^[0-9]+$' THEN (NEW.raw_payload->>'scanner_run')::bigint END,
          CASE WHEN (NEW.raw_payload->>'run_id') ~ '^[0-9]+$' THEN (NEW.raw_payload->>'run_id')::bigint END
        );
      END IF;
      IF NEW.market_context IS NULL THEN
        NEW.market_context := NEW.raw_payload->'market_context';
      END IF;
      IF NEW.score IS NULL THEN
        NEW.score := COALESCE(
          CASE WHEN (NEW.raw_payload->>'score') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (NEW.raw_payload->>'score')::double precision END,
          CASE WHEN (NEW.raw_payload->>'scanner_score') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (NEW.raw_payload->>'scanner_score')::double precision END,
          NEW.evidence_quality_score::double precision
        );
      END IF;
      IF NEW.evidence_quality IS NULL THEN
        NEW.evidence_quality := NEW.evidence_quality_score;
      END IF;
      RETURN NEW;
    END;
    $$;
    DROP TRIGGER IF EXISTS trg_alpha_leads_aliases_biu ON alpha_leads;
    CREATE TRIGGER trg_alpha_leads_aliases_biu
      BEFORE INSERT OR UPDATE OF raw_payload, lead_type, evidence_quality_score, evidence_quality, company_name, scanner_type, scanner_run_id, market_context, score ON alpha_leads
      FOR EACH ROW EXECUTE FUNCTION wolfy_sync_alpha_leads_aliases();
    """
    code, out = run(['psql', '-d', 'wolfy', '-v', 'ON_ERROR_STOP=1', '-q', '-c', sql], timeout=90)
    if code != 0:
        return [f'FAILED_POSTGRES_ALIAS_COMPAT {out[-1000:]}']
    return []


def main() -> int:
    reports: list[str] = []
    reports.extend(sync_scripts())
    reports.extend(ensure_script_modes())
    reports.extend(ensure_sqlite_compatibility_aliases())
    reports.extend(ensure_postgres_compatibility_aliases())

    checks = [
        ('postgres_guard', [str(WOLFY / 'check_postgres_requirements.py')], None),
        # Do not run test_agent_coordination_smoke.py here: it is a DB-mutating
        # smoke test and creates synthetic blocked Sentinel tasks on every
        # autorepair tick. Keep recurring repair checks idempotent/read-only or
        # explicitly productive.
        ('stale_coordination_cleanup', ['python3', str(WOLFY / 'cleanup_stale_agent_coordination.py')], None),
        ('embedding_sync', ['python3', str(WOLFY / 'embed_knowledge_chunks.py')], None),
        ('usage_snapshot', ['python3', str(WOLFY / 'capture_usage_snapshot.py')], None),
    ]
    for label, cmd, cwd in checks:
        code, out = run(cmd, cwd=cwd)
        if code != 0:
            reports.append(f'FAILED {label}: {out[-1000:]}')
        elif out and any(word in out.lower() for word in ('error', 'failed', 'blocked', 'missing')):
            reports.append(f'CHECK_OUTPUT {label}: {out[-1000:]}')

    if reports:
        print('Mike safe autorepair report:')
        for item in reports:
            print(f'- {item}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
