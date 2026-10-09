# Hermes workspace npm audit + TUI test pitfalls (2026-07-22)

Context: Mike ops run where `hermes doctor` flagged `web workspace deps` and `ui-tui workspace deps` with two high build-tool advisories. The fix path cleared doctor warnings but exposed two important verification pitfalls.

## Useful sequence

```bash
cd /usr/local/lib/hermes-agent

# Confirm doctor-scoped issue first.
hermes doctor

# Inspect workspace-specific advisories, not only root audit.
(cd web && npm audit --json)
(cd ui-tui && npm audit --json)

# Safe first repair for doctor's web/ui-tui warnings.
# Either run in each workspace dir...
(cd web && npm audit fix --package-lock-only)
(cd ui-tui && npm audit fix --package-lock-only)

# ...or from the monorepo root with explicit workspace scoping.
npm audit fix --package-lock-only --workspace ui-tui
npm audit fix --package-lock-only --workspace web

# Re-check the specific surfaces.
(cd web && npm audit --json)
(cd ui-tui && npm audit --json)
# or: npm audit --workspace ui-tui && npm audit --workspace web
hermes doctor
```

In the first observed run, this updated only the root monorepo `package-lock.json` and cleared Hermes Doctor's web/ui-tui warnings. `npm audit --omit=dev --json` was already clean, confirming these were build/dev tooling advisories rather than runtime/browser-tool failures.

In a later run, the same lockfile-only workspace repair cleared `ui-tui` completely but left `web` with React Router advisories whose published npm fix required `npm audit fix --force` and a breaking/downgrade move to `react-router-dom@7.11.0`. Treat that as a remaining advisory requiring a deliberate dependency decision, not as a safe autonomous runtime repair.

## Pitfalls

- Do not conflate doctor's `web workspace deps` / `ui-tui workspace deps` warnings with root-level `npm audit` output. The root monorepo audit may include desktop/dev-tool advisories that Hermes Doctor does not flag.
- Running `npm install` at the repo root can fix missing optional native bindings but can also surface unrelated root-level audit advisories. Treat those separately.
- If Vitest fails with missing `@rolldown/binding-linux-x64-gnu`, run:
  ```bash
  cd /usr/local/lib/hermes-agent
  npm install
  ```
- Before running `ui-tui` tests that import `@hermes/ink`, build the local package first:
  ```bash
  cd /usr/local/lib/hermes-agent/ui-tui
  npm run build --prefix packages/hermes-ink
  npm test
  ```
- `npm test -- --runInBand` is a Jest habit and fails under Vitest with `Unknown option --runInBand`.
- If full `ui-tui` tests then fail on source-level assertions unrelated to npm security (for example status bar/virtual height expectation mismatches), do not commit a lockfile-only audit repair as fully verified. Report the exact residual test failures and leave the change uncommitted unless a focused maintainer decision is made.

## Verification shape from the run

- `hermes doctor`: web/ui-tui workspace deps became `✓ ... no known vulnerabilities`.
- `(cd web && npm audit --json)`: `total: 0` vulnerabilities.
- `(cd ui-tui && npm audit --json)`: `total: 0` vulnerabilities.
- `web` tests passed: 10 files / 67 tests.
- `ui-tui` tests started after `npm install` + hermes-ink build, but had 3 source-level failures unrelated to the npm advisory repair.
