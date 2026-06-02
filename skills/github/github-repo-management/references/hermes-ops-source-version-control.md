# Hermes operations source version-control bootstrap

Use this when the user wants "all Hermes source" or "not just one agent" under GitHub version control.

## Recommended shape

Prefer one private monorepo rooted at the Hermes home, e.g. `/root/.hermes`, rather than one repo per profile/agent. This preserves cross-agent history for:

- top-level safe Hermes config and scripts
- `wolfy/` source code and tests
- `profiles/<name>/` source/config/scripts/skills that define agent behavior
- `skills/` library content
- `cron/jobs.json` and Kanban board config

Do not commit runtime state, secrets, memory, sessions, databases, generated reports, caches, logs, auth files, or browser/npm/playwright caches.

## Bootstrap pattern

1. Inventory nested git repos before initializing the root repo.
2. If an agent-specific nested repo already exists and the user wants a unified repo, move its `.git` directory aside as a local backup before staging, e.g. `wolfy/.git.local-backup-YYYYmmddHHMMSS`. Ignore that backup.
3. Create a root `.gitignore` that blocks:
   - `.env`, `auth.json`, credential/token/key files
   - `state.db*`, `kanban.db*`, `*.db`, `*.sqlite*`
   - `logs/`, `sessions/`, `memories/`, caches, locks, pids
   - profile runtime homes and profile state DBs
   - generated research/report payloads and source transcripts
4. Stage the safe source/config/docs/test files.
5. Run a staged-file secret scan before committing. Allow documented placeholder examples like `ghp_xx...xxxx` or `sk-xxx...xxxx`; fail on real-looking PATs, private keys, and API keys.
6. Commit locally before attempting network operations.
7. If GitHub token cannot create repos, create a local `git bundle` backup so the source history is still portable while auth is fixed.
8. Only push to the intended private repo. If token permissions allow reading unrelated repos but not repo creation, do not use those unrelated repos as fallbacks.

## GitHub token pitfall

A fine-grained PAT may successfully authenticate to `/user` and list a few accessible repos but still fail `POST /user/repos` with:

`Resource not accessible by personal access token`

Correct fixes:

- manually create the empty private repo and grant the token Contents read/write on that repo, or
- use a classic PAT with `repo` scope for initial bootstrap.

Then set `origin` and push `main`.