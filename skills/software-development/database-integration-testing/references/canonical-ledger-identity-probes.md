# Canonical Ledger Identity Probes

Use these rollback-wrapped probes during authoritative PostgreSQL ledger reviews. Green application tests are insufficient because malformed keys may enter through direct SQL or migrations.

## Immutable contract fields outside the identity hash

Some fields, such as `required_stage_names`, may intentionally be excluded from the deterministic run hash while still being immutable for reruns. Verify both conditions independently:

1. Create a run with canonical stages such as `['features']`.
2. Directly update the field to another *valid canonical* value such as `['ranking']` in every nonterminal status.
3. Require the database to reject the update.
4. Retry the original application create call and require idempotent success.

Testing only malformed arrays (empty, duplicate, unsorted, null-containing) proves canonical validation, not immutability. Testing only application rerun mismatch detection is also insufficient because the authoritative row has already drifted.

## Whitespace and empty-key bypass matrix

PostgreSQL `btrim(text)` without a second argument trims ordinary spaces only. Python `str.strip()` removes a broader Unicode whitespace set. If application and database contracts are meant to match, probe at least:

- empty string;
- spaces only;
- leading/trailing ordinary spaces;
- tab (`\t`), newline (`\n`), carriage return (`\r`), and mixed whitespace;
- canonical interior whitespace where allowed.

Apply this matrix to every logical identity/reference field: ticker, strategy/version, dataset, provider, endpoint, parser/schema version, source fingerprint, object reference, stage name/version, and source run IDs.

For direct SQL gate probes, require rejection of `ticker=''`, `' AAPL '`, and space-padded strategy names. For manifests, require rejection of tab/newline-padded dataset/provider/reference fields. Repeat against populated partial-schema migration fixtures so invalid legacy values fail atomically before backfill.

## Exact application/database parity

Define one canonical predicate and reproduce it in both layers. Do not assume `btrim()` equals `strip()`. Options include an explicit SQL whitespace regex or an intentionally narrower application predicate, but tests must compare literal accept/reject behavior over the same vector set.

Keep deterministic identity serialization probes separate from canonical-input probes. For JSON identity parity, cover quotes, backslashes, C0 controls, DEL/C1 controls, BMP Unicode, and astral characters (whose JSON representation uses surrogate pairs). PostgreSQL text cannot represent NUL or lone surrogate code points, so document and test their rejection boundary rather than pretending they are round-trippable values.
