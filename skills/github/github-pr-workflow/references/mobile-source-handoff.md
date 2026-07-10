# Mobile source-code handoff via GitHub

Use this when a user wants source code on a phone and Discord/email attachments are awkward or too large.

## Preferred path

1. Treat the handoff as a safe operational source snapshot, not a raw archive dump.
2. Verify repo/root and remote:
   - `git rev-parse --show-toplevel`
   - `git remote -v`
   - `git status --short`
3. Stage only source/config/docs/tests that are safe for version control. Do not stage runtime state, caches, databases, credentials, sessions, generated reports, or skill usage/curator state.
4. Run staged path and staged text scans before committing.
5. Run the smallest relevant verification suite.
6. Commit and push to the canonical GitHub remote.
7. Verify the pushed remote ref matches local `HEAD` with `git ls-remote origin refs/heads/main`.
8. Give the user the GitHub repo URL and commit SHA. On a phone, GitHub browser/app is usually easier than multipart Discord attachments.

## If attachments are still needed

For large ZIPs, split into small parts and include both a checksum file and a reassembly README. Verify locally before sending:

```bash
split -b 8M -d -a 2 source.zip source.zip.part-
sha256sum source.zip source.zip.part-* > SHA256SUMS.txt
cat source.zip.part-* > /tmp/reassembled.zip
cmp -s source.zip /tmp/reassembled.zip
python3 - <<'PY'
import zipfile
with zipfile.ZipFile('/tmp/reassembled.zip') as z:
    bad = z.testzip()
    assert bad is None, bad
PY
```

Tell the user that GitHub is the recommended route for phone access when the latest source is already in a repo or can be safely pushed.
