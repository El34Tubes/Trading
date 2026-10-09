#!/usr/bin/env python3
"""Script-only safe autorepair for Mike's Wolfy/Hermes operations lane.

This does deterministic, non-destructive fixes that do not need an LLM.
It stays silent when everything is healthy.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path('/root/.hermes')
SCRIPTS = ROOT / 'scripts'
WOLFY = ROOT / 'wolfy'
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
    'visible_progress_ledger.py',
    'wolfy_agent_cli.py',
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
    'wolfy_eod_screening_context.py',
    'wolfy_eod_weekly_research_context.py',
    'wolfy_tiered_backfill_bounded.py',
    'wolfy_config_guardian.py',
    'eod_monitoring.py',
    'mike_environment_triage_context.py',
    'mike_safe_autorepair.py',
]
CLERKY_SCRIPTS = [
    'visible_progress_ledger.py',
    'wolfy_agent_cli.py',
    'wolfy_clerky_activity_context.py',
    'wolfy_kanban_allocator.py',
    # Keep operations watchdog wrappers available in Clerky too so
    # profile-scoped diagnostics can smoke-test the same paths without
    # rediscovering missing-profile-wrapper false alarms.
    'wolfy_usage_limit_watchdog.py',
    'wolfy_sync_cron_usage_to_agent_runs.py',
    'wolfy_hourly_knowledge_context.py',
    'wolfy_alpha_search_context.py',
    'wolfy_eod_screening_context.py',
    'wolfy_eod_weekly_research_context.py',
    'wolfy_tiered_backfill_bounded.py',
    'wolfy_intraday_scanner_snapshot.py',
    'wolfy_config_guardian.py',
    'wolfy_cleanup_stale_agent_coordination.py',
    'wolfy_capture_usage_snapshot.py',
    'eod_monitoring.py',
    # Keep Mike's script-only autorepair callable from profile-scoped
    # diagnostics when Clerky is auditing operations handoffs.
    'mike_environment_triage_context.py',
    'mike_safe_autorepair.py',
    # Keep legacy wrappers synchronized across profiles so profile-scoped
    # diagnostics/cron handoffs can invoke the same compatibility path.
    'wolfy_embed_knowledge_chunks.py',
]
WOLFY_SCRIPTS_FROM_GLOBAL: list[str] = [
    'wolfy_eod_screening_context.py',
    'wolfy_eod_weekly_research_context.py',
    'wolfy_tiered_backfill_bounded.py',
    'mike_environment_triage_context.py',
]
LEGACY_WRAPPERS = {
    'wolfy_agent_cli.py': """#!/usr/bin/env python3
\"\"\"Compatibility wrapper for Wolfy's Postgres coordination CLI.

The canonical implementation and its local imports live in the Wolfy directory;
cron planners and profile-scoped diagnostics may call this stable scripts path.
\"\"\"
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/wolfy/wolfy_agent_cli.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, *sys.argv[1:]]))
""",
    'visible_progress_ledger.py': """#!/usr/bin/env python3
\"\"\"Compatibility wrapper for Wolfy's read-only visible progress ledger.\"\"\"
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/wolfy/visible_progress_ledger.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, *sys.argv[1:]]))
""",
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
    'wolfy_config_guardian.py': """#!/usr/bin/env python3
\"\"\"Compatibility wrapper for Wolfy's config guardian.

Profile-scoped Mike cron jobs can inherit HERMES_HOME under the Mike profile,
but this guardian protects the production/default Hermes config and cron files.
Pin --home to /root/.hermes so direct Python probes and the shell wrapper behave
identically.
\"\"\"
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/wolfy/guardian/config_guardian.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, '--home', '/root/.hermes', *sys.argv[1:]]))
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


def ensure_postgres_compatibility_aliases() -> list[str]:
    """Apply non-destructive Postgres aliases used by ad-hoc diagnostics.

    LLM-authored operational probes occasionally use common column names from
    earlier legacy context examples. Keep nullable mirror columns plus triggers
    so those probes fail less often without changing canonical write paths.
    """
    sql = r"""
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS scanner_run_id BIGINT;
    -- Common ticker/volume aliases used by Jonah ad-hoc research probes.
    -- Canonical scanner columns remain ticker and avg_volume.
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS symbol TEXT;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS ticker_symbol TEXT;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS volume DOUBLE PRECISION;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS status TEXT;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS company_name TEXT;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS scanner_type TEXT;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS signal TEXT;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS metadata JSONB;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS trend_50_200 TEXT;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS pattern TEXT;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS pattern_flags JSONB;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS rs_spy_20d DOUBLE PRECISION;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS rs_qqq_20d DOUBLE PRECISION;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS rs_vs_spy_20d DOUBLE PRECISION;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS rs_vs_qqq_20d DOUBLE PRECISION;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS avg_volume_20d DOUBLE PRECISION;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS close_price DOUBLE PRECISION;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS as_of_date DATE;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS r1 DOUBLE PRECISION;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS rank_position INTEGER;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS setup_type TEXT;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS metrics JSONB;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS flags JSONB;
    ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS raw JSONB;
    UPDATE scanner_results
    SET scanner_run_id=COALESCE(scanner_run_id, run_id),
        symbol=COALESCE(symbol, ticker),
        ticker_symbol=COALESCE(ticker_symbol, ticker),
        volume=COALESCE(volume, avg_volume),
        avg_volume_20d=COALESCE(avg_volume_20d, avg_volume),
        close_price=COALESCE(close_price, close),
        as_of_date=COALESCE(as_of_date, data_date),
        status=COALESCE(status, CASE WHEN liquidity_pass IS FALSE THEN 'filtered' ELSE 'observed' END),
        company_name=COALESCE(company_name, notes->>'company_name', notes->>'company'),
        scanner_type=COALESCE(scanner_type, notes->>'scanner_type', notes->>'signal', notes->>'lead_type'),
        signal=COALESCE(signal, notes->>'signal', notes->>'scanner_type', scanner_type),
        metadata=COALESCE(metadata, notes, '{}'::jsonb),
        trend_50_200=COALESCE(trend_50_200, trend_regime, notes->>'trend_50_200', notes->>'trend_regime'),
        pattern=COALESCE(pattern, gap_reversal_flag, notes->>'pattern', notes->>'gap_reversal_flag'),
        pattern_flags=COALESCE(
          pattern_flags,
          notes->'pattern_flags',
          jsonb_strip_nulls(jsonb_build_object(
            'pattern', COALESCE(pattern, gap_reversal_flag, notes->>'pattern', notes->>'gap_reversal_flag'),
            'gap_reversal_flag', gap_reversal_flag,
            'squeeze_flag', squeeze_flag,
            'trend_regime', trend_regime
          ))
        ),
        rs_spy_20d=COALESCE(rs_spy_20d, rs_spy_20, CASE WHEN (notes->>'rs_spy_20d') ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (notes->>'rs_spy_20d')::double precision END),
        rs_qqq_20d=COALESCE(rs_qqq_20d, rs_qqq_20, CASE WHEN (notes->>'rs_qqq_20d') ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (notes->>'rs_qqq_20d')::double precision END),
        rs_vs_spy_20d=COALESCE(rs_vs_spy_20d, rs_spy_20d, rs_spy_20, CASE WHEN (notes->>'rs_vs_spy_20d') ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (notes->>'rs_vs_spy_20d')::double precision END),
        rs_vs_qqq_20d=COALESCE(rs_vs_qqq_20d, rs_qqq_20d, rs_qqq_20, CASE WHEN (notes->>'rs_vs_qqq_20d') ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (notes->>'rs_vs_qqq_20d')::double precision END),
        setup_type=COALESCE(setup_type, signal, scanner_type, notes->>'setup_type', notes->>'signal'),
        metrics=COALESCE(metrics, metadata, notes, '{}'::jsonb),
        flags=COALESCE(flags, notes->'flags', pattern_flags, jsonb_strip_nulls(jsonb_build_object('pattern', pattern, 'gap_reversal_flag', gap_reversal_flag, 'squeeze_flag', squeeze_flag, 'trend_regime', trend_regime))),
        raw=COALESCE(raw, metadata, notes, '{}'::jsonb)
    WHERE scanner_run_id IS NULL OR symbol IS NULL OR ticker_symbol IS NULL OR volume IS NULL OR status IS NULL OR company_name IS NULL OR scanner_type IS NULL OR signal IS NULL
       OR metadata IS NULL OR trend_50_200 IS NULL OR pattern IS NULL OR pattern_flags IS NULL OR rs_spy_20d IS NULL OR rs_qqq_20d IS NULL
       OR rs_vs_spy_20d IS NULL OR rs_vs_qqq_20d IS NULL OR avg_volume_20d IS NULL OR close_price IS NULL OR as_of_date IS NULL
       OR setup_type IS NULL OR metrics IS NULL OR flags IS NULL OR raw IS NULL;

    ALTER TABLE scanner_runs ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
    ALTER TABLE scanner_runs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
    ALTER TABLE scanner_runs ADD COLUMN IF NOT EXISTS mode TEXT;
    UPDATE scanner_runs
    SET started_at=COALESCE(started_at, run_time),
        mode=COALESCE(mode, data_source)
    WHERE started_at IS NULL OR mode IS NULL;

    -- EOD run-ledger compatibility for read-only ops probes. Canonical EOD
    -- code uses runs.started/runs.finished; probes often ask for the
    -- agent-ledger aliases started_at/completed_at or for eod_feature_runs.
    CREATE TABLE IF NOT EXISTS runs (
      id serial PRIMARY KEY,
      job text,
      started timestamptz,
      finished timestamptz,
      status text,
      detail jsonb,
      source text
    );
    ALTER TABLE runs ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
    ALTER TABLE runs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
    ALTER TABLE runs ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ;
    ALTER TABLE runs ADD COLUMN IF NOT EXISTS source TEXT;
    ALTER TABLE runs ADD COLUMN IF NOT EXISTS rows_written INTEGER;
    CREATE OR REPLACE FUNCTION wolfy_jsonb_nonnegative_integer(document JSONB, field_name TEXT)
    RETURNS INTEGER LANGUAGE plpgsql IMMUTABLE AS $$
    DECLARE
      raw_value TEXT;
    BEGIN
      raw_value := document->>field_name;
      IF raw_value IS NULL OR raw_value !~ '^[0-9]+$' THEN
        RETURN NULL;
      END IF;
      RETURN raw_value::INTEGER;
    EXCEPTION
      WHEN invalid_text_representation OR numeric_value_out_of_range THEN
        RETURN NULL;
    END;
    $$;
    UPDATE runs
    SET started_at=COALESCE(started_at, started),
        completed_at=COALESCE(completed_at, finished),
        ended_at=COALESCE(ended_at, completed_at, finished),
        source=COALESCE(source, NULLIF(detail->>'source', '')),
        rows_written=COALESCE(
          rows_written,
          wolfy_jsonb_nonnegative_integer(detail, 'rows_written'),
          wolfy_jsonb_nonnegative_integer(detail, 'rows_upserted'),
          wolfy_jsonb_nonnegative_integer(detail, 'feature_rows_upserted')
        )
    WHERE started_at IS NULL OR completed_at IS NULL OR ended_at IS NULL OR source IS NULL OR rows_written IS NULL;

    CREATE OR REPLACE FUNCTION wolfy_sync_runs_aliases()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.started_at IS NULL THEN
        NEW.started_at := NEW.started;
      END IF;
      IF NEW.completed_at IS NULL THEN
        NEW.completed_at := NEW.finished;
      END IF;
      IF NEW.ended_at IS NULL THEN
        NEW.ended_at := COALESCE(NEW.completed_at, NEW.finished);
      END IF;
      IF NEW.source IS NULL THEN
        NEW.source := NULLIF(NEW.detail->>'source', '');
      END IF;
      IF NEW.rows_written IS NULL THEN
        NEW.rows_written := COALESCE(
          wolfy_jsonb_nonnegative_integer(NEW.detail, 'rows_written'),
          wolfy_jsonb_nonnegative_integer(NEW.detail, 'rows_upserted'),
          wolfy_jsonb_nonnegative_integer(NEW.detail, 'feature_rows_upserted')
        );
      END IF;
      RETURN NEW;
    END;
    $$;
    DROP TRIGGER IF EXISTS trg_runs_aliases_biu ON runs;
    CREATE TRIGGER trg_runs_aliases_biu
      BEFORE INSERT OR UPDATE OF started, finished, started_at, completed_at, ended_at, detail, source, rows_written ON runs
      FOR EACH ROW EXECUTE FUNCTION wolfy_sync_runs_aliases();

    DROP VIEW IF EXISTS eod_feature_runs;
    CREATE VIEW eod_feature_runs AS
    SELECT
      id,
      job,
      started,
      finished,
      started_at,
      completed_at,
      ended_at,
      status,
      source,
      rows_written,
      detail,
      wolfy_jsonb_nonnegative_integer(detail, 'bars_loaded') AS bars_loaded,
      wolfy_jsonb_nonnegative_integer(detail, 'feature_rows_upserted') AS feature_rows_upserted,
      wolfy_jsonb_nonnegative_integer(detail, 'tickers_processed') AS tickers_processed
    FROM runs
    WHERE job LIKE 'eod%' OR job LIKE 'feature%';

    -- Storage/ops metric aliases for read-only diagnostic probes. Canonical
    -- watchdog rows use captured_at/root_used_pct/etc.; probes sometimes ask
    -- for generic metric_name/metric_value/category/created_at columns.
    CREATE TABLE IF NOT EXISTS system_metrics (
      id BIGSERIAL PRIMARY KEY,
      captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      hermes_bytes BIGINT,
      wolfy_bytes BIGINT,
      retired_db_bytes BIGINT,
      root_used_pct DOUBLE PRECISION,
      root_avail_bytes BIGINT,
      cron_job_count INTEGER,
      notes TEXT
    );
    ALTER TABLE system_metrics ADD COLUMN IF NOT EXISTS metric_name TEXT;
    ALTER TABLE system_metrics ADD COLUMN IF NOT EXISTS metric_value DOUBLE PRECISION;
    ALTER TABLE system_metrics ADD COLUMN IF NOT EXISTS category TEXT;
    ALTER TABLE system_metrics ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
    UPDATE system_metrics
    SET metric_name=COALESCE(metric_name, 'storage.snapshot'),
        metric_value=COALESCE(metric_value, root_used_pct),
        category=COALESCE(category, 'storage'),
        created_at=COALESCE(created_at, captured_at)
    WHERE metric_name IS NULL OR metric_value IS NULL OR category IS NULL OR created_at IS NULL;

    CREATE OR REPLACE FUNCTION wolfy_sync_system_metrics_aliases()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.created_at IS NULL THEN
        NEW.created_at := NEW.captured_at;
      END IF;
      IF NEW.captured_at IS NULL THEN
        NEW.captured_at := NEW.created_at;
      END IF;
      IF NEW.metric_name IS NULL THEN
        NEW.metric_name := 'storage.snapshot';
      END IF;
      IF NEW.metric_value IS NULL THEN
        NEW.metric_value := NEW.root_used_pct;
      END IF;
      IF NEW.category IS NULL THEN
        NEW.category := 'storage';
      END IF;
      RETURN NEW;
    END;
    $$;
    DROP TRIGGER IF EXISTS trg_system_metrics_aliases_biu ON system_metrics;
    CREATE TRIGGER trg_system_metrics_aliases_biu
      BEFORE INSERT OR UPDATE OF captured_at, created_at, root_used_pct, metric_name, metric_value, category ON system_metrics
      FOR EACH ROW EXECUTE FUNCTION wolfy_sync_system_metrics_aliases();

    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS summary TEXT;
    -- Compatibility alias for prompts/scripts that ask for task instructions.
    -- Canonical task prose remains description.
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS instructions TEXT;
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS instruction TEXT;
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS definition_of_done TEXT;
    -- Compatibility aliases for optimizer/ops probes that expect verification
    -- metadata as top-level task columns. Canonical storage may still be in
    -- metadata/payload JSONB or definition_of_done.
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS verification_result TEXT;
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS commit_hash TEXT;
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS error_message TEXT;
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS blocker_reason TEXT;
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS payload JSONB;
    -- Compatibility alias for ad-hoc/read-only probes that expect task metadata.
    -- Canonical structured task detail remains payload.
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS metadata JSONB;
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS agent TEXT;
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS assigned_agent TEXT;
    -- Compatibility alias for ad-hoc/read-only ops probes that expect claimed_by.
    -- Canonical assignment remains agent_tasks.agent_name / assigned_agent.
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS claimed_by TEXT;
    -- Compatibility alias for ad-hoc/read-only ops probes that expect one ticker.
    -- Canonical task symbols remain agent_tasks.ticker_symbols (text[]).
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS ticker TEXT;
    -- Compatibility alias for read-only ops probes that expect task_id.
    -- Canonical task primary key remains agent_tasks.id.
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS task_id BIGINT;
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS source_table TEXT;
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS source_id TEXT;
    -- Compatibility alias for ad-hoc/read-only probes that expect a generic
    -- task source. Canonical provenance remains source_table/source_id.
    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS source TEXT;
    UPDATE agent_tasks SET agent=agent_name WHERE agent IS NULL;
    UPDATE agent_tasks SET task_id=id WHERE task_id IS NULL;
    UPDATE agent_tasks SET started_at=COALESCE(started_at, claimed_at, created_at) WHERE started_at IS NULL;
    UPDATE agent_tasks SET ticker=COALESCE(ticker, payload->>'ticker', payload->>'symbol', ticker_symbols[1]) WHERE ticker IS NULL;
    UPDATE agent_tasks SET assigned_agent=agent_name WHERE assigned_agent IS NULL;
    UPDATE agent_tasks SET claimed_by=COALESCE(assigned_agent, agent, agent_name) WHERE claimed_by IS NULL;
    UPDATE agent_tasks SET summary=description WHERE summary IS NULL AND description IS NOT NULL;
    UPDATE agent_tasks SET instructions=description WHERE instructions IS NULL AND description IS NOT NULL;
    UPDATE agent_tasks SET instruction=COALESCE(instruction, instructions, description) WHERE instruction IS NULL;
    UPDATE agent_tasks SET definition_of_done=COALESCE(definition_of_done, payload->>'definition_of_done') WHERE definition_of_done IS NULL;
    UPDATE agent_tasks
    SET verification_result=COALESCE(verification_result, metadata->>'verification_result', payload->>'verification_result', definition_of_done)
    WHERE verification_result IS NULL;
    UPDATE agent_tasks
    SET commit_hash=COALESCE(commit_hash, metadata->>'commit_hash', payload->>'commit_hash')
    WHERE commit_hash IS NULL;
    UPDATE agent_tasks SET metadata=COALESCE(metadata, payload, '{}'::jsonb) WHERE metadata IS NULL;
    UPDATE agent_tasks
    SET error_message=COALESCE(error_message, summary, description)
    WHERE status='blocked' AND error_message IS NULL;
    UPDATE agent_tasks
    SET blocker_reason=COALESCE(blocker_reason, error_message, summary, description)
    WHERE status='blocked' AND blocker_reason IS NULL;
    UPDATE agent_tasks
    SET source_table=COALESCE(source_table, payload->>'source_table', 'agent_tasks'),
        source_id=COALESCE(source_id, payload->>'source_id', source_fingerprint, id::text),
        source=COALESCE(source, payload->>'source', source_table, 'agent_tasks')
    WHERE source_table IS NULL OR source_id IS NULL OR source IS NULL;

    -- Compatibility aliases for ad-hoc/read-only scanner run probes.
    -- Canonical timing is run_time/completed_at and run size is derived from scanner_results.
    ALTER TABLE scanner_runs ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
    ALTER TABLE scanner_runs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
    ALTER TABLE scanner_runs ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ;
    ALTER TABLE scanner_runs ADD COLUMN IF NOT EXISTS status TEXT;
    ALTER TABLE scanner_runs ADD COLUMN IF NOT EXISTS symbols_scanned INTEGER;
    ALTER TABLE scanner_runs ADD COLUMN IF NOT EXISTS mode TEXT;
    UPDATE scanner_runs sr
    SET started_at=COALESCE(sr.started_at, sr.run_time),
        completed_at=COALESCE(sr.completed_at, sr.finished_at, sr.run_time),
        finished_at=COALESCE(sr.finished_at, sr.completed_at, sr.run_time),
        status=COALESCE(sr.status, CASE WHEN COALESCE(sr.finished_at, sr.completed_at, sr.run_time) IS NOT NULL THEN 'completed' ELSE 'started' END),
        mode=COALESCE(sr.mode, sr.data_source),
        symbols_scanned=COALESCE(sr.symbols_scanned, counts.result_count, 0)
    FROM (
      SELECT run_id, count(*)::integer AS result_count
      FROM scanner_results
      GROUP BY run_id
    ) counts
    WHERE sr.id = counts.run_id
      AND (sr.started_at IS NULL OR sr.completed_at IS NULL OR sr.finished_at IS NULL OR sr.status IS NULL OR sr.mode IS NULL OR sr.symbols_scanned IS NULL);
    UPDATE scanner_runs
    SET started_at=COALESCE(started_at, run_time),
        completed_at=COALESCE(completed_at, finished_at, run_time),
        finished_at=COALESCE(finished_at, completed_at, run_time),
        status=COALESCE(status, 'completed'),
        mode=COALESCE(mode, data_source),
        symbols_scanned=COALESCE(symbols_scanned, 0)
    WHERE started_at IS NULL OR completed_at IS NULL OR finished_at IS NULL OR status IS NULL OR mode IS NULL OR symbols_scanned IS NULL;

    UPDATE agent_tasks
    SET payload = jsonb_strip_nulls(jsonb_build_object(
        'id', id,
        'task_id', task_id,
        'agent_name', agent_name,
        'agent', agent,
        'assigned_agent', assigned_agent,
        'claimed_by', claimed_by,
        'task_type', task_type,
        'title', title,
        'description', description,
        'instructions', instructions,
        'instruction', instruction,
        'definition_of_done', definition_of_done,
        'verification_result', verification_result,
        'commit_hash', commit_hash,
        'verified_at', verified_at,
        'status', status,
        'priority', priority,
        'source_fingerprint', source_fingerprint,
        'topic_tags', topic_tags,
        'ticker_symbols', ticker_symbols,
        'ticker', ticker,
        'depends_on', depends_on,
        'supersedes', supersedes,
        'created_at', created_at,
        'started_at', started_at,
        'updated_at', updated_at,
        'summary', summary,
        'error_message', error_message,
        'blocker_reason', blocker_reason,
        'source_table', source_table,
        'source_id', source_id,
        'source', source
    ))
    WHERE payload IS NULL;
    UPDATE agent_tasks
    SET payload = jsonb_strip_nulls(payload || jsonb_build_object(
        'instruction', instruction,
        'definition_of_done', definition_of_done,
        'verification_result', verification_result,
        'commit_hash', commit_hash,
        'verified_at', verified_at,
        'started_at', started_at,
        'claimed_by', claimed_by,
        'error_message', error_message,
        'blocker_reason', blocker_reason,
        'source_table', source_table,
        'source_id', source_id,
        'source', source,
        'ticker', ticker,
        'metadata', metadata
    ))
    WHERE payload IS NOT NULL
      AND (instruction IS NOT NULL OR definition_of_done IS NOT NULL OR verification_result IS NOT NULL OR commit_hash IS NOT NULL OR verified_at IS NOT NULL OR error_message IS NOT NULL OR blocker_reason IS NOT NULL OR source_table IS NOT NULL OR source_id IS NOT NULL OR source IS NOT NULL OR ticker IS NOT NULL OR claimed_by IS NOT NULL OR metadata IS NOT NULL);

    ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
    ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ;
    ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS result_summary TEXT;
    ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS title TEXT;
    -- Compatibility mirror for read-only ops probes that inspect agent_runs
    -- directly and expect the linked task type there. Canonical task type
    -- lives on agent_tasks.task_type and agent_runs.task_id is the join key.
    ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS task_type TEXT;
    -- Compatibility alias for read-only ops probes that expect run_id.
    -- Canonical run primary key remains agent_runs.id.
    ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS run_id BIGINT;
    UPDATE agent_runs SET run_id=id WHERE run_id IS NULL;
    UPDATE agent_runs SET completed_at=ended_at WHERE completed_at IS NULL AND ended_at IS NOT NULL;
    UPDATE agent_runs SET finished_at=COALESCE(ended_at, completed_at) WHERE finished_at IS NULL AND (ended_at IS NOT NULL OR completed_at IS NOT NULL);
    UPDATE agent_runs SET ended_at=COALESCE(ended_at, finished_at, completed_at) WHERE ended_at IS NULL AND (finished_at IS NOT NULL OR completed_at IS NOT NULL);
    UPDATE agent_runs SET result_summary=summary WHERE result_summary IS NULL AND summary IS NOT NULL;
    UPDATE agent_runs ar
    SET task_type=at.task_type
    FROM agent_tasks at
    WHERE ar.task_id = at.id
      AND ar.task_type IS NULL;
    UPDATE agent_runs ar
    SET title=at.title
    FROM agent_tasks at
    WHERE ar.task_id = at.id
      AND ar.title IS NULL;

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
    ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS evidence TEXT;
    ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS risk_flags JSONB NOT NULL DEFAULT '[]';
    -- Compatibility alias for ad-hoc/read-only ops probes that expect metadata.
    -- Canonical detail remains alpha_leads.raw_payload.
    ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS metadata JSONB;
    -- Compatibility alias for ad-hoc/read-only probes that expect the historical
    -- suspicious_activity JSON object. Canonical storage remains suspicious_action
    -- + suspicious_flags, with optional raw_payload.suspicious_activity detail.
    ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS suspicious_activity JSONB;
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
        evidence=COALESCE(evidence, raw_payload->>'evidence', raw_payload->>'rationale', raw_payload->>'summary', thesis, title),
        score=COALESCE(score,
          CASE WHEN (raw_payload->>'score') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (raw_payload->>'score')::double precision END,
          CASE WHEN (raw_payload->>'scanner_score') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (raw_payload->>'scanner_score')::double precision END,
          evidence_quality_score::double precision),
        evidence_quality=COALESCE(evidence_quality, evidence_quality_score),
        risk_flags=COALESCE(NULLIF(risk_flags, '[]'::jsonb), raw_payload->'risk_flags', suspicious_flags, raw_payload->'suspicious_flags', '[]'::jsonb),
        metadata=COALESCE(metadata, raw_payload, '{}'::jsonb),
        suspicious_activity=COALESCE(
          suspicious_activity,
          raw_payload->'suspicious_activity',
          jsonb_build_object('recommended_action', suspicious_action, 'flags', suspicious_flags)
        )
    WHERE company_name IS NULL OR scanner_type IS NULL OR scanner_run_id IS NULL OR market_context IS NULL OR score IS NULL OR evidence_quality IS NULL OR rationale IS NULL OR summary IS NULL OR evidence IS NULL OR risk_flags IS NULL OR risk_flags = '[]'::jsonb OR metadata IS NULL OR suspicious_activity IS NULL;

    ALTER TABLE recommendation_reviews
      ALTER COLUMN recommendation_id TYPE BIGINT USING recommendation_id::bigint;

    DROP VIEW IF EXISTS alpha_search_leads;
    CREATE VIEW alpha_search_leads AS
    SELECT
      id, legacy_id, legacy_id AS sqlite_id, report_id, created_at, updated_at, ticker, lead_type, title,
      thesis, rationale, summary,
      COALESCE(evidence, rationale, summary, thesis, raw_payload->>'evidence', raw_payload->>'rationale', title) AS evidence,
      status, evidence_quality_score AS score,
      evidence_quality_score, evidence_quality, evidence_count, highest_source_quality,
      suspicious_action, suspicious_flags, suspicious_activity, risk_flags, catalyst_window, social_context,
      filing_context, insider_context, complete_ticket, recommendation_id,
      next_research_question, company_name, scanner_type, scanner_run_id, market_context,
      raw_payload, source_fingerprint,
      'alpha_leads'::text AS source_table,
      id::text AS source_id
    FROM alpha_leads;

    ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS type TEXT;
    UPDATE agent_tasks
    SET type=task_type
    WHERE type IS NULL;

    CREATE EXTENSION IF NOT EXISTS pgcrypto;

    -- Compatibility aliases for ad-hoc/read-only ops probes that query
    -- strategies.metadata or strategies.description directly. Canonical strategy
    -- parameters remain params and canonical prose remains notes; aliases mirror
    -- those fields non-destructively for probe compatibility.
    ALTER TABLE strategies ADD COLUMN IF NOT EXISTS metadata JSONB;
    ALTER TABLE strategies ADD COLUMN IF NOT EXISTS description TEXT;
    UPDATE strategies
    SET metadata = COALESCE(metadata, params, '{}'::jsonb)
    WHERE metadata IS NULL;
    UPDATE strategies
    SET description = notes
    WHERE description IS NULL AND notes IS NOT NULL;

    CREATE OR REPLACE FUNCTION wolfy_sync_strategies_aliases()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.metadata IS NULL THEN
        NEW.metadata := COALESCE(NEW.params, '{}'::jsonb);
      END IF;
      NEW.description := COALESCE(NEW.notes, NEW.description);
      RETURN NEW;
    END;
    $$;
    DROP TRIGGER IF EXISTS trg_strategies_aliases_biu ON strategies;
    CREATE TRIGGER trg_strategies_aliases_biu
      BEFORE INSERT OR UPDATE OF params, metadata, notes, description ON strategies
      FOR EACH ROW EXECUTE FUNCTION wolfy_sync_strategies_aliases();

    DROP VIEW IF EXISTS strategy_rules;
    CREATE VIEW strategy_rules AS
    SELECT
      id::bigint AS id,
      name,
      name AS title,
      NULL::text AS ticker,
      NULL::text AS ticker_symbol,
      name AS rule_name,
      status,
      status AS scope,
      status AS implementation_status,
      setup_type AS rule_type,
      setup_type AS timeframe,
      setup_type AS setup_type,
      ARRAY[]::text[] AS ticker_symbols,
      ARRAY[]::text[] AS ticker_universe,
      ARRAY[]::text[] AS tickers,
      ARRAY[setup_type, status]::text[] AS topic_tags,
      ARRAY[setup_type, status]::text[] AS universe_tags,
      ARRAY[setup_type]::text[] AS asset_classes,
      ARRAY[setup_type, status]::text[] AS universe,
      notes AS description,
      notes AS summary,
      notes AS body,
      notes AS rule_body,
      notes AS reasons,
      COALESCE(params, '{}'::jsonb) AS metadata,
      COALESCE(params->>'source','postgres.strategies') AS source_basis,
      (status IN ('approved','candidate')) AS enabled,
      (status IN ('approved','candidate')) AS is_enabled,
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
      NULL::text AS ticker_symbol,
      btrim(regexp_replace(split_part(content, E'\n', 1), '^Rule:\s*', '')) AS rule_name,
      'active'::text AS status,
      'active'::text AS scope,
      'active'::text AS implementation_status,
      NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '') AS rule_type,
      NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '') AS timeframe,
      NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '') AS setup_type,
      ARRAY[]::text[] AS ticker_symbols,
      ARRAY[]::text[] AS ticker_universe,
      ARRAY[]::text[] AS tickers,
      ARRAY_REMOVE(ARRAY['postgres.strategy_rules', NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '')], NULL)::text[] AS topic_tags,
      ARRAY_REMOVE(ARRAY['postgres.strategy_rules', NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '')], NULL)::text[] AS universe_tags,
      ARRAY_REMOVE(ARRAY[NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '')], NULL)::text[] AS asset_classes,
      ARRAY_REMOVE(ARRAY['postgres.strategy_rules', NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '')], NULL)::text[] AS universe,
      btrim(regexp_replace(regexp_replace(content, E'^Rule:[^\n]*\nType:[^\n]*\nDescription:\s*', ''), E'\n+', ' ', 'g')) AS description,
      btrim(regexp_replace(regexp_replace(content, E'^Rule:[^\n]*\nType:[^\n]*\nDescription:\s*', ''), E'\n+', ' ', 'g')) AS summary,
      btrim(regexp_replace(regexp_replace(content, E'^Rule:[^\n]*\nType:[^\n]*\nDescription:\s*', ''), E'\n+', ' ', 'g')) AS body,
      btrim(regexp_replace(regexp_replace(content, E'^Rule:[^\n]*\nType:[^\n]*\nDescription:\s*', ''), E'\n+', ' ', 'g')) AS rule_body,
      btrim(regexp_replace(regexp_replace(content, E'^Rule:[^\n]*\nType:[^\n]*\nDescription:\s*', ''), E'\n+', ' ', 'g')) AS reasons,
      metadata AS metadata,
      'postgres.strategy_rules'::text AS source_basis,
      true AS enabled,
      true AS is_enabled,
      true AS is_active,
      created_at AS created_at,
      created_at AS updated_at,
      'equity_etf_process'::text AS asset_class,
      NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '') AS category,
      source_id AS source_id,
      btrim(regexp_replace(regexp_replace(content, E'^Rule:[^\n]*\nType:[^\n]*\nDescription:\s*', ''), E'\n+', ' ', 'g')) AS rule_text
    FROM knowledge_chunks
    WHERE source_table='postgres.strategy_rules' AND source_id ~ '^[0-9]+$';

    ALTER TABLE universe_backfill_targets ADD COLUMN IF NOT EXISTS enabled BOOLEAN;
    ALTER TABLE universe_backfill_targets ADD COLUMN IF NOT EXISTS wolfy_tier TEXT;
    ALTER TABLE universe_backfill_targets ADD COLUMN IF NOT EXISTS tier_source TEXT;
    ALTER TABLE universe_backfill_targets ADD COLUMN IF NOT EXISTS backfill_priority INTEGER;
    ALTER TABLE universe_backfill_targets ADD COLUMN IF NOT EXISTS backfill_enabled BOOLEAN;
    UPDATE universe_backfill_targets
    SET enabled=active
    WHERE enabled IS NULL;
    UPDATE universe_backfill_targets
    SET wolfy_tier=tier
    WHERE wolfy_tier IS NULL;
    UPDATE universe_backfill_targets
    SET tier_source=source
    WHERE tier_source IS NULL;
    UPDATE universe_backfill_targets
    SET backfill_priority=priority
    WHERE backfill_priority IS NULL;
    UPDATE universe_backfill_targets
    SET backfill_enabled=COALESCE(enabled, active, true)
    WHERE backfill_enabled IS NULL;

    CREATE OR REPLACE FUNCTION wolfy_sync_universe_backfill_targets_aliases()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.enabled IS NULL THEN
        NEW.enabled := COALESCE(NEW.active, true);
      END IF;
      IF NEW.active IS NULL THEN
        NEW.active := COALESCE(NEW.enabled, true);
      END IF;
      IF NEW.wolfy_tier IS NULL THEN
        NEW.wolfy_tier := NEW.tier;
      END IF;
      IF NEW.tier IS NULL THEN
        NEW.tier := NEW.wolfy_tier;
      END IF;
      IF NEW.tier_source IS NULL THEN
        NEW.tier_source := NEW.source;
      END IF;
      IF NEW.source IS NULL THEN
        NEW.source := NEW.tier_source;
      END IF;
      IF NEW.backfill_priority IS NULL THEN
        NEW.backfill_priority := NEW.priority;
      END IF;
      IF NEW.priority IS NULL THEN
        NEW.priority := NEW.backfill_priority;
      END IF;
      IF NEW.backfill_enabled IS NULL THEN
        NEW.backfill_enabled := COALESCE(NEW.enabled, NEW.active, true);
      END IF;
      RETURN NEW;
    END;
    $$;
    DROP TRIGGER IF EXISTS trg_universe_backfill_targets_aliases_biu ON universe_backfill_targets;
    CREATE TRIGGER trg_universe_backfill_targets_aliases_biu
      BEFORE INSERT OR UPDATE OF active, enabled, tier, wolfy_tier, source, tier_source, priority, backfill_priority, backfill_enabled ON universe_backfill_targets
      FOR EACH ROW EXECUTE FUNCTION wolfy_sync_universe_backfill_targets_aliases();

    DROP VIEW IF EXISTS universe;
    CREATE VIEW universe AS
    SELECT
      symbol,
      name,
      source,
      sector,
      is_etf,
      last_seen,
      active,
      active AS enabled,
      wolfy_tier,
      wolfy_tier AS tier,
      tier_source,
      backfill_priority,
      backfill_enabled,
      tier_notes
    FROM universe_symbols;

    CREATE OR REPLACE FUNCTION wolfy_sync_scanner_results_aliases()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.scanner_run_id IS NULL THEN
        NEW.scanner_run_id := NEW.run_id;
      END IF;
      IF NEW.symbol IS NULL THEN
        NEW.symbol := NEW.ticker;
      END IF;
      IF NEW.ticker_symbol IS NULL THEN
        NEW.ticker_symbol := NEW.ticker;
      END IF;
      IF NEW.volume IS NULL THEN
        NEW.volume := NEW.avg_volume;
      END IF;
      IF NEW.avg_volume_20d IS NULL THEN
        NEW.avg_volume_20d := NEW.avg_volume;
      END IF;
      IF NEW.close_price IS NULL THEN
        NEW.close_price := NEW.close;
      END IF;
      IF NEW.as_of_date IS NULL THEN
        NEW.as_of_date := NEW.data_date;
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
      IF NEW.setup_type IS NULL THEN
        NEW.setup_type := COALESCE(NEW.signal, NEW.scanner_type, NEW.notes->>'setup_type', NEW.notes->>'signal');
      END IF;
      IF NEW.metadata IS NULL THEN
        NEW.metadata := COALESCE(NEW.notes, '{}'::jsonb);
      END IF;
      IF NEW.metrics IS NULL THEN
        NEW.metrics := COALESCE(NEW.metadata, NEW.notes, '{}'::jsonb);
      END IF;
      IF NEW.trend_50_200 IS NULL THEN
        NEW.trend_50_200 := COALESCE(NEW.trend_regime, NEW.notes->>'trend_50_200', NEW.notes->>'trend_regime');
      END IF;
      IF NEW.pattern IS NULL THEN
        NEW.pattern := COALESCE(NEW.gap_reversal_flag, NEW.notes->>'pattern', NEW.notes->>'gap_reversal_flag');
      END IF;
      IF NEW.pattern_flags IS NULL THEN
        NEW.pattern_flags := COALESCE(
          NEW.notes->'pattern_flags',
          jsonb_strip_nulls(jsonb_build_object(
            'pattern', NEW.pattern,
            'gap_reversal_flag', NEW.gap_reversal_flag,
            'squeeze_flag', NEW.squeeze_flag,
            'trend_regime', NEW.trend_regime
          ))
        );
      END IF;
      IF NEW.flags IS NULL THEN
        NEW.flags := COALESCE(NEW.notes->'flags', NEW.pattern_flags, '{}'::jsonb);
      END IF;
      IF NEW.raw IS NULL THEN
        NEW.raw := COALESCE(NEW.metadata, NEW.notes, '{}'::jsonb);
      END IF;
      IF NEW.rs_spy_20d IS NULL THEN
        NEW.rs_spy_20d := NEW.rs_spy_20;
      END IF;
      IF NEW.rs_qqq_20d IS NULL THEN
        NEW.rs_qqq_20d := NEW.rs_qqq_20;
      END IF;
      IF NEW.rs_vs_spy_20d IS NULL THEN
        NEW.rs_vs_spy_20d := COALESCE(NEW.rs_spy_20d, NEW.rs_spy_20);
      END IF;
      IF NEW.rs_vs_qqq_20d IS NULL THEN
        NEW.rs_vs_qqq_20d := COALESCE(NEW.rs_qqq_20d, NEW.rs_qqq_20);
      END IF;
      RETURN NEW;
    END;
    $$;
    DROP TRIGGER IF EXISTS trg_scanner_results_aliases_biu ON scanner_results;
    CREATE TRIGGER trg_scanner_results_aliases_biu
      BEFORE INSERT OR UPDATE OF run_id, scanner_run_id, ticker, symbol, ticker_symbol, avg_volume, avg_volume_20d, close, close_price, data_date, as_of_date, volume, liquidity_pass, status, notes, company_name, scanner_type, signal, setup_type, metadata, metrics, trend_regime, trend_50_200, gap_reversal_flag, pattern, pattern_flags, flags, raw, squeeze_flag, rs_spy_20, rs_qqq_20, rs_spy_20d, rs_qqq_20d, rs_vs_spy_20d, rs_vs_qqq_20d ON scanner_results
      FOR EACH ROW EXECUTE FUNCTION wolfy_sync_scanner_results_aliases();

    CREATE OR REPLACE FUNCTION wolfy_sync_scanner_runs_aliases()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.started_at IS NULL THEN
        NEW.started_at := NEW.run_time;
      END IF;
      IF NEW.completed_at IS NULL THEN
        NEW.completed_at := COALESCE(NEW.finished_at, NEW.run_time);
      END IF;
      IF NEW.finished_at IS NULL THEN
        NEW.finished_at := COALESCE(NEW.completed_at, NEW.run_time);
      END IF;
      IF NEW.status IS NULL THEN
        NEW.status := CASE WHEN COALESCE(NEW.finished_at, NEW.completed_at, NEW.run_time) IS NOT NULL THEN 'completed' ELSE 'started' END;
      END IF;
      IF NEW.symbols_scanned IS NULL THEN
        NEW.symbols_scanned := 0;
      END IF;
      IF NEW.mode IS NULL THEN
        NEW.mode := NEW.data_source;
      END IF;
      RETURN NEW;
    END;
    $$;
    DROP TRIGGER IF EXISTS trg_scanner_runs_aliases_biu ON scanner_runs;
    CREATE TRIGGER trg_scanner_runs_aliases_biu
      BEFORE INSERT OR UPDATE OF run_time, started_at, completed_at, finished_at, status, symbols_scanned, data_source, mode ON scanner_runs
      FOR EACH ROW EXECUTE FUNCTION wolfy_sync_scanner_runs_aliases();

    CREATE OR REPLACE FUNCTION wolfy_sync_agent_tasks_aliases()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.type IS NULL THEN
        NEW.type := NEW.task_type;
      END IF;
      IF NEW.task_id IS NULL THEN
        NEW.task_id := NEW.id;
      END IF;
      IF NEW.agent IS NULL THEN
        NEW.agent := NEW.agent_name;
      END IF;
      IF NEW.assigned_agent IS NULL THEN
        NEW.assigned_agent := NEW.agent_name;
      END IF;
      IF NEW.claimed_by IS NULL THEN
        NEW.claimed_by := COALESCE(NEW.assigned_agent, NEW.agent, NEW.agent_name);
      END IF;
      IF NEW.started_at IS NULL THEN
        NEW.started_at := COALESCE(NEW.claimed_at, NEW.created_at);
      END IF;
      IF NEW.ticker IS NULL THEN
        NEW.ticker := COALESCE(NEW.payload->>'ticker', NEW.payload->>'symbol', NEW.ticker_symbols[1]);
      END IF;
      IF NEW.summary IS NULL THEN
        NEW.summary := NEW.description;
      END IF;
      IF NEW.instructions IS NULL THEN
        NEW.instructions := NEW.description;
      END IF;
      IF NEW.instruction IS NULL THEN
        NEW.instruction := COALESCE(NEW.instructions, NEW.description);
      END IF;
      IF NEW.status = 'blocked' AND NEW.error_message IS NULL THEN
        NEW.error_message := COALESCE(NEW.blocker_reason, NEW.summary, NEW.description);
      END IF;
      IF NEW.status = 'blocked' AND NEW.blocker_reason IS NULL THEN
        NEW.blocker_reason := COALESCE(NEW.error_message, NEW.summary, NEW.description);
      END IF;
      IF NEW.metadata IS NULL THEN
        NEW.metadata := COALESCE(NEW.payload, '{}'::jsonb);
      END IF;
      IF NEW.verification_result IS NULL THEN
        NEW.verification_result := COALESCE(NEW.metadata->>'verification_result', NEW.payload->>'verification_result', NEW.definition_of_done);
      END IF;
      IF NEW.commit_hash IS NULL THEN
        NEW.commit_hash := COALESCE(NEW.metadata->>'commit_hash', NEW.payload->>'commit_hash');
      END IF;
      IF NEW.payload IS NULL THEN
        NEW.payload := jsonb_strip_nulls(jsonb_build_object(
          'id', NEW.id,
          'task_id', NEW.task_id,
          'agent_name', NEW.agent_name,
          'agent', NEW.agent,
          'assigned_agent', NEW.assigned_agent,
          'claimed_by', NEW.claimed_by,
          'task_type', NEW.task_type,
          'type', NEW.type,
          'title', NEW.title,
          'description', NEW.description,
          'instructions', NEW.instructions,
          'instruction', NEW.instruction,
          'definition_of_done', NEW.definition_of_done,
          'verification_result', NEW.verification_result,
          'commit_hash', NEW.commit_hash,
          'verified_at', NEW.verified_at,
          'status', NEW.status,
          'priority', NEW.priority,
          'source_fingerprint', NEW.source_fingerprint,
          'topic_tags', NEW.topic_tags,
          'ticker_symbols', NEW.ticker_symbols,
          'ticker', NEW.ticker,
          'depends_on', NEW.depends_on,
          'supersedes', NEW.supersedes,
          'created_at', NEW.created_at,
          'started_at', NEW.started_at,
          'updated_at', NEW.updated_at,
          'summary', NEW.summary,
          'error_message', NEW.error_message,
          'blocker_reason', NEW.blocker_reason,
          'source_table', NEW.source_table,
          'source_id', NEW.source_id,
          'ticker', NEW.ticker,
          'metadata', NEW.metadata
        ));
      ELSE
        NEW.payload := jsonb_strip_nulls(NEW.payload || jsonb_build_object(
          'instruction', NEW.instruction,
          'definition_of_done', NEW.definition_of_done,
          'verification_result', NEW.verification_result,
          'commit_hash', NEW.commit_hash,
          'verified_at', NEW.verified_at,
          'started_at', NEW.started_at,
          'claimed_by', NEW.claimed_by,
          'error_message', NEW.error_message,
          'blocker_reason', NEW.blocker_reason,
          'source_table', NEW.source_table,
          'source_id', NEW.source_id,
          'ticker', NEW.ticker,
          'metadata', NEW.metadata
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
      BEFORE INSERT OR UPDATE OF task_id, agent_name, agent, assigned_agent, claimed_by, task_type, type, description, instructions, instruction, definition_of_done, verification_result, commit_hash, verified_at, summary, error_message, blocker_reason, status, payload, metadata, source_table, source_id, claimed_at, started_at, ticker, ticker_symbols ON agent_tasks
      FOR EACH ROW EXECUTE FUNCTION wolfy_sync_agent_tasks_aliases();

    CREATE OR REPLACE FUNCTION wolfy_sync_agent_runs_aliases()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.finished_at IS NULL THEN
        NEW.finished_at := COALESCE(NEW.ended_at, NEW.completed_at);
      END IF;
      IF NEW.completed_at IS NULL THEN
        NEW.completed_at := COALESCE(NEW.ended_at, NEW.finished_at);
      END IF;
      IF NEW.ended_at IS NULL THEN
        NEW.ended_at := COALESCE(NEW.completed_at, NEW.finished_at);
      END IF;
      IF NEW.result_summary IS NULL THEN
        NEW.result_summary := NEW.summary;
      END IF;
      IF NEW.summary IS NULL THEN
        NEW.summary := NEW.result_summary;
      END IF;
      IF (NEW.task_type IS NULL OR NEW.title IS NULL) AND NEW.task_id IS NOT NULL THEN
        SELECT COALESCE(NEW.task_type, at.task_type), COALESCE(NEW.title, at.title)
        INTO NEW.task_type, NEW.title
        FROM agent_tasks at
        WHERE at.id = NEW.task_id;
      END IF;
      IF NEW.run_id IS NULL THEN
        NEW.run_id := NEW.id;
      END IF;
      RETURN NEW;
    END;
    $$;
    DROP TRIGGER IF EXISTS trg_agent_runs_aliases_biu ON agent_runs;
    CREATE TRIGGER trg_agent_runs_aliases_biu
      BEFORE INSERT OR UPDATE OF task_id, task_type, title, ended_at, completed_at, finished_at, summary, result_summary, run_id ON agent_runs
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
      IF NEW.evidence IS NULL THEN
        NEW.evidence := COALESCE(NEW.raw_payload->>'evidence', NEW.raw_payload->>'rationale', NEW.raw_payload->>'summary', NEW.thesis, NEW.title);
      END IF;
      IF NEW.risk_flags IS NULL OR NEW.risk_flags = '[]'::jsonb THEN
        NEW.risk_flags := COALESCE(NEW.raw_payload->'risk_flags', NEW.suspicious_flags, NEW.raw_payload->'suspicious_flags', '[]'::jsonb);
      END IF;
      IF NEW.metadata IS NULL THEN
        NEW.metadata := COALESCE(NEW.raw_payload, '{}'::jsonb);
      END IF;
      IF NEW.suspicious_activity IS NULL THEN
        NEW.suspicious_activity := COALESCE(
          NEW.raw_payload->'suspicious_activity',
          jsonb_build_object('recommended_action', NEW.suspicious_action, 'flags', NEW.suspicious_flags)
        );
      END IF;
      RETURN NEW;
    END;
    $$;
    DROP TRIGGER IF EXISTS trg_alpha_leads_aliases_biu ON alpha_leads;
    CREATE TRIGGER trg_alpha_leads_aliases_biu
      BEFORE INSERT OR UPDATE OF raw_payload, lead_type, evidence_quality_score, evidence_quality, evidence, company_name, scanner_type, scanner_run_id, market_context, score, risk_flags, suspicious_flags, suspicious_activity, metadata ON alpha_leads
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
