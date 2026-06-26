# Hermes ops remote correction: Trading repository

Session learning: when version-controlling the user's Hermes/Wolfy operations setup, the intended GitHub repository is the Trading repo, not a newly created generic setup repo.

Canonical target:

```text
/root/.hermes -> https://github.com/El34Tubes/Trading.git -> main
```

Workflow when the remote is wrong or missing:

1. Inspect the current local repo and remote:
   ```bash
   cd /root/.hermes
   git remote -v
   git status --short
   git --no-pager log --oneline --decorate -3
   ```
2. Retarget origin to Trading:
   ```bash
   git remote set-url origin https://github.com/El34Tubes/Trading.git
   # or: git remote add origin https://github.com/El34Tubes/Trading.git
   ```
3. Fetch and inspect Trading before pushing:
   ```bash
   git fetch origin main
   git ls-tree --name-only -r origin/main | sed -n '1,120p'
   git rev-list --left-right --count HEAD...origin/main
   git merge-base HEAD origin/main || true
   ```
4. If Trading only has a small independent bootstrap commit, such as a README-only initial commit, preserve it with an unrelated-history merge instead of force-pushing:
   ```bash
   git merge --allow-unrelated-histories --no-edit origin/main
   git push -u origin main
   ```
5. Re-check `git status --short` after the merge/push. Hermes runtime may have produced new source/config changes while the agent was working; if safe, stage, secret-scan, test, commit, and push those as a second snapshot.

Pitfalls:

- Do not create or push to `hermes-setup` when the user means the Trading repository.
- Do not force-push over Trading's existing `main` unless the user explicitly asks; merge unrelated history when the existing remote contains real bootstrap content.
- Keep `.env`, auth files, databases, sessions, logs, caches, LSP/node_modules, and generated runtime payloads ignored before staging.
