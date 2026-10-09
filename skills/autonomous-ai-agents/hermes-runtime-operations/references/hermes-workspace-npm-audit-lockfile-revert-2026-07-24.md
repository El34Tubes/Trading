# Hermes workspace npm audit lockfile-revert pitfall — 2026-07-24

Context: Mike ops cron saw `hermes doctor` warnings for Hermes Agent workspace-only npm advisories:

- `web workspace deps`: 5 high advisories
- `ui-tui workspace deps`: 3 high advisories

Safe checks performed:

```bash
cd /usr/local/lib/hermes-agent/web && npm audit --json
cd /usr/local/lib/hermes-agent/ui-tui && npm audit --json
cd /usr/local/lib/hermes-agent && git status --short package.json package-lock.json
```

A lockfile-only remediation attempt was tried:

```bash
cd /usr/local/lib/hermes-agent
npm audit fix --package-lock-only --workspace web
```

Then a root override/lockfile attempt was tried for non-breaking transitive advisories:

```json
"overrides": {
  "brace-expansion": "^5.0.8",
  "js-yaml": "^4.3.0",
  "postcss": "^8.5.18"
}
```

and regenerated with:

```bash
npm install --package-lock-only --ignore-scripts
```

Observed result: doctor/audit got worse, not better:

- `web` increased to 7 high advisories
- `ui-tui` increased to 6 high advisories
- remaining fixes still required breaking dependency changes such as ESLint 10.x or React Router downgrade/semver-major changes

Correct operational response:

1. Revert the attempted `package.json` / `package-lock.json` changes immediately:
   ```bash
   cd /usr/local/lib/hermes-agent
   git checkout -- package.json package-lock.json
   ```
2. Re-run `hermes doctor` and confirm the advisory count returns to the known baseline.
3. Report the advisories as build-tool/dependency-decision items, not runtime breakage.
4. Do **not** apply `npm audit fix --force` or force React Router / ESLint semver-breaking changes autonomously from Mike ops.

Takeaway: for Hermes Agent workspace npm advisories, lockfile-only fixes are still safe to try, but verify immediately and revert if the advisory count increases or the remaining fix path becomes semver-breaking. The useful lesson is the revert/verification pattern, not a durable claim that npm audit fixes never work.