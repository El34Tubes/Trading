# Source tarball export pattern

Use this when the user asks for a tarball/archive of source code from a repo root, especially when the working tree has useful uncommitted source changes.

## Goal

Create a cloneable/source-review archive that includes tracked files plus untracked non-ignored source files, while excluding runtime data, secrets, local databases, caches, telemetry, and backup blobs.

## Pattern

```bash
cd /path/to/repo
outdir=/root/source_export
mkdir -p "$outdir"
manifest="$outdir/source_manifest.txt"

# Include tracked + untracked non-ignored files, respecting .gitignore.
git ls-files -co --exclude-standard > "$manifest"

# Filter obvious runtime/secrets/noise from the manifest before archiving.
python3 - <<'PY'
from pathlib import Path
manifest = Path('/root/source_export/source_manifest.txt')
patterns = (
    '.env', '.env.', 'state.db', '.sqlite', '.db', '.pyc', '__pycache__/',
)
blocked_prefixes = (
    'skills/.curator_backups/',
)
blocked_exact = {
    'skills/.usage.json',
}
kept, removed = [], []
for line in manifest.read_text().splitlines():
    p = line.strip()
    if not p:
        continue
    lower = p.lower()
    bad = p in blocked_exact or any(p.startswith(pref) for pref in blocked_prefixes)
    bad = bad or any(tok in lower for tok in patterns)
    (removed if bad else kept).append(p)
manifest.write_text('\n'.join(kept) + '\n')
Path('/root/source_export/excluded_from_source_manifest.txt').write_text('\n'.join(removed) + '\n')
print({'kept': len(kept), 'excluded': len(removed)})
PY

# Safety scan names before creating the archive.
if grep -Ein '(^|/)(\.env|.*secret.*|.*credential.*|.*token.*|state\.db|.*\.db|.*\.sqlite)$' "$manifest"; then
  echo 'Refusing to archive: manifest contains likely secret/runtime files' >&2
  exit 2
fi

stamp=$(date +%Y%m%d_%H%M%S)
tarball="$outdir/source-${stamp}.tar.gz"
tar --sort=name --mtime='UTC 2026-06-30' --owner=0 --group=0 --numeric-owner \
  -czf "$tarball" --transform='s,^,Project/,' -T "$manifest"
sha256sum "$tarball" > "${tarball}.sha256"

# Verify count, sample contents, sensitive filenames, and checksum.
tar -tzf "$tarball" | wc -l
tar -tzf "$tarball" | sed -n '1,20p'
if tar -tzf "$tarball" | grep -Ein '(^|/)(\.env|.*secret.*|.*credential.*|.*token.*|state\.db|.*\.db|.*\.sqlite)$'; then
  echo 'WARNING: possible sensitive/runtime name found' >&2
  exit 3
fi
sha256sum -c "${tarball}.sha256"
```

## Notes

- Prefer `git ls-files -co --exclude-standard` over `tar .` so ignored runtime data and local secrets do not get swept in.
- Include untracked non-ignored files when the user asks for the current working source, because active work may not be committed yet.
- Exclude skill usage telemetry and curator backups unless the user explicitly asks for operational state.
- Put a single top-level directory in the archive with `--transform='s,^,Project/,'` so extraction is clean.
- Always produce and verify a `.sha256` file.
