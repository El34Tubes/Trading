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
from datetime import datetime
from pathlib import Path

HOME = Path('/root/.hermes')
STATE_PATH = HOME / 'wolfy' / 'usage_limit_watchdog_state.json'
LOG_DIR = HOME / 'logs'
# Avoid bare "429" because timestamps/char counts can contain 429. Require actual error context.
PATTERN = re.compile(
    r'(insufficient[_ -]?quota|quota exceeded|daily limit|usage limit|rate limit|ratelimit|too many requests|http\s*429|status\s*429|error.*429|429.*error|exhausted|payment / credit error|credit error|billing error)',
    re.I,
)


def run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=30)
    except Exception:
        return ''


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
    return run(['hermes', 'insights', '--days', '1'])[-2200:]


def main() -> None:
    state = load_state()
    seen = set(state.get('seen', []))
    new_hits = []
    for hit in scan_logs():
        digest = hashlib.sha256(hit.encode()).hexdigest()[:16]
        if digest not in seen:
            seen.add(digest)
            new_hits.append(hit)

    state['seen'] = sorted(seen)[-500:]
    state['last_checked_at'] = datetime.now().isoformat(timespec='seconds')
    save_state(state)

    if not new_hits:
        return

    print('🚨 Wolfy usage-limit watchdog detected a possible LLM usage/quota/rate-limit event today.')
    print('New matching log lines:')
    for h in new_hits[-10:]:
        print(f'- {h}')
    print('\nRecommended response: pause or reduce Jonah cadence, keep no_agent watchdogs running, and wait for provider reset or switch model/provider.')
    ctx = scan_insights()
    if ctx:
        print('\nRecent Hermes usage context:')
        print(ctx)


if __name__ == '__main__':
    main()
