#!/usr/bin/env python3
"""Silent watchdog for Hermes/Wolfy model usage-limit events.

Runs as a cron no_agent job. Prints an alert only when it detects a new
quota/rate-limit/usage-exhaustion event today; otherwise prints nothing.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

HOME = Path('/root/.hermes')
STATE_PATH = HOME / 'wolfy' / 'usage_limit_watchdog_state.json'
LOG_DIR = HOME / 'logs'

# LLM-driven Wolfy desk jobs are useful only while the provider can actually
# answer. During a provider usage-limit window, let script-only scanners and
# watchdogs keep collecting state, but pause these LLM jobs so Discord does not
# get repeated quota-failure reports. The watchdog resumes them automatically
# once auth no longer reports a limit.
LLM_JOBS_TO_GATE = {
    'ba183091b5c0': 'Wolfy twice-daily stock research report',
    'a739dac0d264': 'Clerky four-hour Wolfy activity report',
    '07253dc09350': 'Jonah 20-minute autonomous knowledge builder',
    'ce017fe2f3fb': 'Sentinel post-Wolfy recommendation reviewer',
    'de6f05f10cb5': 'Yang post-Sentinel technical entry/exit analyst',
    '4452bdae4553': 'Wolfy separate Alpha Search Report',
    'fdfd5b53b5d5': 'Mike autonomous environment repair loop',
    '92f31b95fccc': 'Wolfy daily optimization planner and implementer',
}
PAUSE_REASON = 'auto-paused by Wolfy usage-limit watchdog; script-only jobs continue'

# Avoid bare "429" because timestamps/char counts can contain 429. Require actual error context.
PATTERN = re.compile(
    r'(insufficient[_ -]?quota|quota exceeded|daily limit|usage limit|rate limit|ratelimit|too many requests|http\s*429|status\s*429|error.*429|429.*error|exhausted|payment / credit error|credit error|billing error)',
    re.I,
)
AUTH_LIMIT_PATTERN = re.compile(
    r'(usage_limit_reached|rate-limited|rate limited|insufficient[_ -]?quota|quota exceeded|daily limit|too many requests|status\s*429|\(429\)|credit error|billing error)',
    re.I,
)


def run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=30)
    except Exception:
        return ''


def run_status(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=45)
        return proc.returncode, proc.stdout.strip()
    except Exception as exc:
        return 1, str(exc)


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {'seen': []}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True))


def today_strings() -> list[str]:
    now = datetime.now()
    return [now.strftime('%Y-%m-%d'), now.strftime('%b %d'), now.strftime('%B %d')]


def scan_logs() -> list[str]:
    hits: list[str] = []
    today = today_strings()
    for path in list(LOG_DIR.glob('*.log')) + [HOME / 'cron.log']:
        if not path.exists() or not path.is_file():
            continue
        try:
            lines = path.read_text(errors='replace').splitlines()[-3000:]
        except Exception:
            continue
        for line in lines:
            if PATTERN.search(line) and (any(t in line for t in today) or not re.match(r'\d{4}-\d{2}-\d{2}', line)):
                hits.append(f'{path.name}: {line[-500:]}')
    return hits


def scan_insights() -> str:
    # The production Wolfy cron jobs live under the default profile even when
    # Mike runs diagnostics from the mike profile. Pin insights to default so
    # usage context reflects the jobs that are actually consuming quota.
    return run(['hermes', '--profile', 'default', 'insights', '--days', '1'])[-2200:]


def auth_limit_active() -> tuple[bool, str]:
    """Return whether the configured LLM credential pool is currently limited.

    The production Wolfy profile currently uses openai-codex. Listing every
    auth provider also probes the unrelated Copilot env credential; a classic
    GITHUB_TOKEN is valid for GitHub API access but unsupported by Copilot, and
    Hermes logs a warning every watchdog tick. Scope this probe to the active
    LLM provider so quota gating stays quiet and does not treat unrelated
    credentials as Wolfy model-health evidence.
    """
    auth = run(['hermes', '--profile', 'default', 'auth', 'list', 'openai-codex'])
    if AUTH_LIMIT_PATTERN.search(auth):
        limited_lines = [line.strip() for line in auth.splitlines() if AUTH_LIMIT_PATTERN.search(line)]
        detail = '; '.join(limited_lines[:4]) or 'Hermes auth reports a provider usage/rate limit.'
        return True, detail
    return False, ''


def log_limit_active() -> tuple[bool, str]:
    """Detect active provider limits from recent Hermes log lines.

    `hermes auth list openai-codex` is sometimes quiet even while Codex API
    calls return `usage_limit_reached` with a future reset timestamp. Treat a
    same-day log line with `resets_at` in the future or positive
    `resets_in_seconds` as active gating evidence so scheduled LLM jobs are
    paused before they repeatedly fail at their next tick.
    """
    now_epoch = int(time.time())
    today = today_strings()
    newest_detail = ''
    newest_reset = 0
    for path in list(LOG_DIR.glob('*.log')) + [HOME / 'cron.log']:
        if not path.exists() or not path.is_file():
            continue
        try:
            lines = path.read_text(errors='replace').splitlines()[-3000:]
        except Exception:
            continue
        for line in lines:
            lower = line.lower()
            if 'usage_limit_reached' not in line and 'usage limit has been reached' not in lower:
                continue
            if not (any(t in line for t in today) or not re.match(r'\d{4}-\d{2}-\d{2}', line)):
                continue
            reset_at_match = re.search(r"resets_at['\"]?:\s*(\d+)", line)
            seconds_match = re.search(r"resets_in_seconds['\"]?:\s*(\d+)", line)
            reset_at = int(reset_at_match.group(1)) if reset_at_match else 0
            seconds = int(seconds_match.group(1)) if seconds_match else 0
            if reset_at > now_epoch or (not reset_at and seconds > 0):
                if reset_at > newest_reset:
                    newest_reset = reset_at
                    newest_detail = line[-500:]
    if newest_detail:
        return True, f'Recent Codex usage-limit log reports reset_at={newest_reset}: {newest_detail}'
    return False, ''


def gate_llm_jobs(state: dict, limited: bool, detail: str) -> list[str]:
    """Pause/resume LLM cron jobs on quota state transitions; return user-visible notices."""
    notices: list[str] = []
    paused_by_watchdog = set(state.get('paused_llm_jobs', []))

    if limited:
        newly_paused = []
        for job_id, name in LLM_JOBS_TO_GATE.items():
            if job_id in paused_by_watchdog:
                continue
            code, output = run_status(['hermes', '--profile', 'default', 'cron', 'pause', job_id])
            if code == 0:
                paused_by_watchdog.add(job_id)
                newly_paused.append(name)
            elif output:
                notices.append(f'Could not pause {name} ({job_id}): {output[-240:]}')
        if newly_paused:
            notices.append(
                '⏸️ Wolfy is usage-limited, so I paused LLM-driven Wolfy/Mike report jobs to stop repeated Discord quota spam. '
                'Script-only scanners, storage/usage watchdogs, embedding sync, and safe autorepair keep running. '
                f'Limit detail: {detail}'
            )
            notices.append('Paused jobs: ' + ', '.join(newly_paused))
        state['limited_active'] = True
        state['limit_detail'] = detail
    else:
        resumed = []
        for job_id in sorted(paused_by_watchdog):
            name = LLM_JOBS_TO_GATE.get(job_id, job_id)
            code, output = run_status(['hermes', '--profile', 'default', 'cron', 'resume', job_id])
            if code == 0:
                resumed.append(name)
            elif output:
                notices.append(f'Could not resume {name} ({job_id}): {output[-240:]}')
        paused_by_watchdog.clear()
        if state.get('limited_active') or resumed:
            notices.append('▶️ Wolfy provider limit appears clear; resumed LLM-driven Wolfy/Mike report jobs. Recommendations/reviews will run on their normal schedules again.')
            if resumed:
                notices.append('Resumed jobs: ' + ', '.join(resumed))
        state['limited_active'] = False
        state['limit_detail'] = ''

    state['paused_llm_jobs'] = sorted(paused_by_watchdog)
    return notices


def main() -> None:
    state = load_state()
    seen = set(state.get('seen', []))
    new_hits = []
    for hit in scan_logs():
        digest = hashlib.sha256(hit.encode()).hexdigest()[:16]
        if digest not in seen:
            seen.add(digest)
            new_hits.append(hit)

    limited, limit_detail = auth_limit_active()
    if not limited:
        limited, limit_detail = log_limit_active()
    notices = gate_llm_jobs(state, limited, limit_detail)

    state['seen'] = sorted(seen)[-5000:]
    state['last_checked_at'] = datetime.now().isoformat(timespec='seconds')
    save_state(state)

    # Stay quiet on repeated known limit hits. Print only on pause/resume
    # transitions or genuinely new log evidence that was not seen before.
    if notices:
        for notice in notices:
            print(notice)

    if not new_hits:
        return

    print('🚨 Wolfy usage-limit watchdog detected a possible LLM usage/quota/rate-limit event today.')
    print('New matching log lines:')
    for h in new_hits[-10:]:
        print(f'- {h}')
    if limited:
        print('\nCurrent action: LLM-driven Wolfy/Mike jobs are gated while the provider is limited; script-only jobs continue silently.')
    else:
        print('\nRecommended response: pause or reduce Jonah cadence, keep no_agent watchdogs running, and wait for provider reset or switch model/provider.')
    ctx = scan_insights()
    if ctx:
        print('\nRecent Hermes usage context:')
        print(ctx)


if __name__ == '__main__':
    main()
