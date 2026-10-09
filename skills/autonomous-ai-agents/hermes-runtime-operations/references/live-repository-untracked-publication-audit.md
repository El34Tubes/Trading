# Auditing untracked files in a live runtime repository

Use this when a repository is also an active application/profile home and the user wants a no-write classification for public source control.

## Preserve the audit snapshot first

1. Capture `git status --porcelain=v1 -z --untracked-files=all` before inspecting anything.
2. Keep that initial NUL-delimited manifest as the population being classified. Live guardians, sync jobs, or another worker may add ignore rules, stage files, or regenerate profile copies while the audit is running.
3. Record `HEAD`, branch, staged status, and ignored-path rules separately. Do not silently switch from the initial manifest to later `git status` output.
4. Before reporting, recheck status. If paths moved from untracked to staged/ignored, report the concurrent mutation and evaluate the index against the original manifest. Never imply the auditor performed those changes.

## Classification matrix

Assign every initial path exactly once:

- **Commit as source/docs:** canonical source, tests, implementation plans, and canonical root skills/reference documentation.
- **Archive separately:** one-off database probes, task/run-specific research scripts, pasted research notes, raw provider/issuer downloads, extraction sidecars, and source indexes. Preserve privately with provenance/checksums when useful.
- **Exclude as runtime/sensitive:** profile install locks, caches, credentials, scheduler/session state, local databases, and generated profile mirrors.
- **Inspect further:** files with concrete infrastructure names, internal hostnames, account identifiers, uncertain licenses, or mixed source/raw-data content.

Counts across the four groups must equal the initial manifest count.

## Duplicate and generated-copy checks

- Hash every untracked regular file and compare hashes both within the untracked set and against tracked files.
- Prefer one canonical root copy. Profile-scoped skill/script copies that are byte-identical to the canonical root or an already tracked source are generated installation/synchronization artifacts, not additional source.
- Treat hub lock files and installed-skill manifests as runtime metadata unless repository policy explicitly versions them.

## Secret, infrastructure, and license review

- Scan only the initial manifest for private keys, tokens, bearer credentials, credential-bearing DSNs/URLs, webhook URLs, and password assignments. Distinguish placeholders from actual secrets.
- Search documentation for concrete hostnames, IPs, email addresses, account IDs, and deployment names. These may be sensitive operational identifiers even when they are not authentication secrets.
- Check for a repository-root license separately from per-skill frontmatter. A `license: MIT` field in individual skills does not automatically grant a repository-wide license for unrelated scripts/plans.
- Raw public filings are not automatically repository source. Preserve source URLs and provenance, and flag embedded vendor copyright notices or issuer exhibits before redistribution.

## One-off database scripts

Classify by behavior, not filename:

- Parse SQL verbs and connection construction.
- Read-only `SELECT` probes can still expose schema, task IDs, or records when executed and normally belong in a private research archive.
- Highlight scripts containing `INSERT`, `UPDATE`, `DELETE`, `commit()`, or live database defaults. They are operational artifacts, not ordinary reusable tools, unless deliberately generalized and tested.

## Verification and report shape

- Syntax-parse source candidates and run focused tests only when this remains no-write with respect to production state.
- Report concise path groups with counts, generated/raw/license/secret flags, and blockers.
- If the index changed concurrently, state exactly which excluded/inspect-further groups are currently staged so the user does not commit the entire index blindly.
- Do not modify, stage, unstage, ignore, move, or delete files during a classification-only request.