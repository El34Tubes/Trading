# Database-backed test isolation in delegated implementation

Use this checklist whenever a plan task adds or migrates integration tests against a stateful database.

## Pre-flight gate

1. Create a dedicated test database/schema; reject the production database name.
2. Validate the complete endpoint contract, not only parsed `dbname`:
   - reject remote hosts, URI/URL DSNs, passwords, service files, SSL/GSS options, and unsafe users unless the project explicitly supports them;
   - reject dangerous ambient client variables (`PGPASSWORD`, `PGPASSFILE`, `PGSERVICE*`, `PGSSL*`, `PGHOST*`, `PGUSER`, `PGDATABASE`, connection options) before any connection or subprocess;
   - apply the same validator to admin, provisioning, extension, migration, and ordinary test paths.
3. Export the test application DSN **before provisioning or importing modules that cache DSNs at module scope**. Add a regression that every cached default points to the test database.
4. Provision schema idempotently and serialize concurrent provisioning with an advisory lock or equivalent.

## Fixture isolation

- Use collision-resistant names and dates outside production history.
- A rollback context only protects writes made through that same transaction. Production code may open and commit through separate connections (dual-write loggers, scanners, compatibility pipelines); redirect those defaults too and explicitly delete committed test rows in `finally`.
- Assert dynamic fixture residue is zero after tests.
- Keep tests for production configuration defaults pure and read-only; temporary environment overrides must restore safely.

## Authoritative database contracts

When the database is the durable ledger or safety boundary, Python validation is not sufficient:

- Mirror canonical enums, one-of rules, hash formats, non-empty strings, sorted/unique arrays, and cross-field consistency in database constraints or triggers.
- Probe direct SQL as an adversary. Test both `INSERT` and `UPDATE`; an `UPDATE OF status` trigger does not protect a direct insert already marked terminal/published.
- For terminal states such as `published`, make the database verify all prerequisite rows and complete metadata regardless of which application helper performs the write.
- Derive enum/reason taxonomies from the accepted plan or versioned contract verbatim. Do not invent near-synonyms that make later phases incompatible.
- Test empty and whitespace-only references separately from null, and enforce exact-one-of source hash versus immutable object reference at the database layer.

## Verification gate

Before and after the focused and full serial suites, compute a read-only production invariant covering relevant table counts and critical approved/governed rows, including status, authorization metadata, and verdicts. Prefer a deterministic checksum over canonical serialization. A changed invariant is an abort gate: do not guess, delete, or repair rows until provenance is established.

Search for indirect write paths, not just literal production DSNs: default connection helpers, module-level constants, SQLite-to-Postgres compatibility writers, logger side effects, and subprocesses.

## Review prompts

Require the independent reviewer to probe:

- production-like endpoints that still use the test DB name;
- local-looking URI DSNs;
- ambient client-library overrides;
- import ordering and cached module defaults;
- writes made by separate internally opened connections;
- cleanup, concurrency, environment restoration, SQL/subprocess safety, and schema idempotency.

Do not accept self-reported test isolation without these adversarial probes.