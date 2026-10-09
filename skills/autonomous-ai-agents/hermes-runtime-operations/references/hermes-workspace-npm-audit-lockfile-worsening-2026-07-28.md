# Hermes workspace npm audit: lockfile-only fix worsened advisories (2026-07-28)

## Context
A Mike autonomous environment triage run saw `hermes doctor` report workspace-only build-tool advisories:

- `web`: 0 critical, 5 high, 0 moderate
- `ui-tui`: 0 critical, 3 high, 0 moderate

These were not runtime blockers. Browser/agent-browser dependencies and Playwright Chromium were healthy.

## Safe remediation attempted
From `/usr/local/lib/hermes-agent`:

```bash
npm audit --workspace web --json > /tmp/hermes-web-audit-before.json || true
npm audit --workspace ui-tui --json > /tmp/hermes-uitui-audit-before.json || true
npm audit fix --package-lock-only --workspace web || true
npm audit --workspace web --json > /tmp/hermes-web-audit-after.json || true
npm audit --workspace ui-tui --json > /tmp/hermes-uitui-audit-after-web.json || true
```

## Result
The lockfile-only fix made the advisory counts worse:

| Workspace | Before | After attempted fix |
|---|---:|---:|
| `web` | 5 high | 7 high |
| `ui-tui` | 3 high | 6 high |

`npm audit fix` also indicated remaining fixes required `--force` / breaking changes (`eslint`, `react-router-dom` downgrade/major behavior). This is not safe to apply autonomously in an ops cron run.

## Correct handling
Immediately revert the lockfile and restore the installed tree:

```bash
git restore package-lock.json
npm ci --ignore-scripts
npm audit --workspace web --json > /tmp/hermes-web-audit-restored.json || true
npm audit --workspace ui-tui --json > /tmp/hermes-uitui-audit-restored.json || true
git status --short
```

Expected restored baseline from this run:

- `web`: 5 high
- `ui-tui`: 3 high
- `git status --short`: clean

## Reporting rule
If the safe audit remediation worsens counts and is reverted cleanly, report it as a residual dependency decision, not as a fixed item. Do not commit or leave lockfile changes that increase advisories. Do not use `npm audit fix --force` autonomously for these workspace advisories.