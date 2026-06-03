# Configuration repository snapshot workflow

Use this when the user asks to put an operational setup directory (for example a Hermes home/profile, research-desk scripts, cron definitions, or other dotfile-like setup) under Git/GitHub version control.

## Durable pattern

1. Identify the actual setup repo/root before staging:
   - `git -C <dir> rev-parse --show-toplevel`
   - `git -C <dir> remote -v`
   - `git -C <dir> status --short`
2. Inspect or create `.gitignore` before `git add -A`.
3. Exclude secrets and generated/runtime state first:
   - `.env`, `.env.*`, auth/token/credential files, SSH/private keys
   - databases and WAL/SHM files
   - sessions, memories, logs, caches, lock files, pid/process files
   - node_modules/LSP installs, package caches, generated reports, temp files
4. Stage only after ignore rules are in place.
5. Run two safety checks before committing:
   - staged path scan for forbidden filenames/dirs
   - staged text scan for concrete token/API-key/password assignments
6. Run the smallest relevant verification suite for newly staged code, if any.
7. Commit with a conventional message.
8. If no GitHub remote exists, create a private repository via the GitHub API or `gh`, add `origin`, push, and verify `origin/main` matches `HEAD`.

## Notes

- Prefer private GitHub repositories for operational setup snapshots unless the user explicitly asks for public.
- Do not commit live runtime state just because the user says "everything". Interpret that as "all safe source/configuration artifacts" and protect secrets/runtime data automatically.
- If `gh` is unavailable but GitHub HTTPS auth/token is configured, use `curl` against `POST /user/repos` and then `git push`.
- Store the resulting remote in memory only if it is a durable setup repo the user will expect future sessions to reuse.
