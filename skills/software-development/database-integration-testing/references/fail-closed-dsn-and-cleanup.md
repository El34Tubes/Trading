# Fail-Closed PostgreSQL Test Isolation Patterns

## Complete DSN validation

Parsing only `dbname` is insufficient: `dbname=app_test host=prod-db password=...` still targets production infrastructure. Parsing can also erase policy-relevant syntax: a local-looking URI such as `postgresql://root@/app_test?host=/var/run/postgresql` may normalize to the same parameters as an approved keyword DSN. Validate the raw DSN form first, then parse and apply an exact allowlist. If the contract is keyword-only, reject all PostgreSQL URI schemes before parsing—even when they resolve locally.

Ambient libpq configuration is part of the effective connection target even when it is absent from the DSN. Fail closed before any connection when dangerous overrides are present, or run every driver/subprocess call with a deliberately sanitized environment. Audit at least `PGPASSWORD`, `PGPASSFILE`, `PGSERVICE`, `PGSERVICEFILE`, `PGSSLMODE`, `PGHOST`, `PGHOSTADDR`, `PGPORT`, `PGUSER`, `PGDATABASE`, and `PGOPTIONS`. Apply the same rule to normal test connections, admin database creation, extension installation, schema application, and subprocesses.

A conservative local policy can require:

- `dbname` equals the dedicated test database;
- `host` equals an explicit Unix socket such as `/var/run/postgresql`;
- `user` equals a known peer-auth test user;
- no keys beyond `dbname`, `host`, and `user`.

Negative tests should include keyword and URI forms for remote hostnames, public/private IPs, TCP localhost, passwords, service names, SSL options, `hostaddr`, unsafe users, and extra connection options. Test one valid local peer-auth keyword DSN as the positive control.

If the contract forbids URI syntax, check the raw string before parsing. For example, both of these may parse to the same `{user, dbname, host}` mapping as an approved keyword DSN and therefore evade a parsed-only allowlist:

```text
postgresql://root@/app_test?host=/var/run/postgresql
postgresql:///app_test?host=/var/run/postgresql&user=root
```

Add explicit negative tests for semantically local URIs; testing only remote or credential-bearing URIs leaves this gap invisible.

Also validate the effective libpq environment. A clean-looking keyword DSN may still be affected by `PGPASSWORD`, `PGPASSFILE`, `PGSERVICE`, `PGSERVICEFILE`, `PGHOSTADDR`, `PGSSLMODE`, or `PGOPTIONS`. Depending on the harness contract, either fail closed when these are present or construct the connection under a sanitized, explicit environment. Apply this rule to both test-database and admin connections.

A deterministic validator probe should print `ACCEPT` or `REJECT` for each prohibited raw DSN and each ambient-variable case. This catches the common false assurance where the normal suite passes because no test exercises the parser-canonicalization boundary.

Validate before constructing an admin DSN. Only after raw syntax, parsed parameters, and ambient settings all pass may code replace `dbname` with `postgres` to check/create the dedicated database.

## Cleanup independently committed writes

Generate a unique namespace, future date, ticker, and strategy/note identity per test. Wrap the write and assertions in `try/finally`.

Cleanup by unique identity, not solely by a returned ID:

```python
fixture = future_fixture("recommendation")
try:
    result = helper_that_commits(ticket_for(fixture))
    assert persisted(result)
finally:
    with connect(test_dsn) as conn:
        assert current_database(conn) == TEST_DB
        conn.execute(
            "DELETE FROM recommendations WHERE ticker=%s AND thesis=%s",
            (fixture.ticker, FIXTURE_THESIS),
        )
        conn.commit()

assert count_fixture_rows(fixture) == 0
```

This remains safe if the helper commits and then raises before returning an ID.

## Read-only production invariants

Use database-enforced read-only mode for every production invariant connection and assert it:

```python
with psycopg.connect(
    production_dsn,
    options="-c default_transaction_read_only=on",
) as conn:
    assert conn.execute("SHOW transaction_read_only").fetchone()[0] == "on"
    assert conn.execute("SELECT current_database()").fetchone()[0] == PROD_DB
```

Capture table counts plus named governance rows: status, latest verdict, full metadata, approval scope, and recommendation authorization fields. Serialize nested state with sorted keys and compare before/after checksums, while also printing a readable summary.

## Verification order

1. Capture production baseline read-only.
2. Run focused RED/GREEN tests.
3. Run the state-mutating suite serially.
4. Run the full relevant suite serially.
5. Apply schema twice.
6. Prove unique and legacy static fixture rows are absent from the test DB.
7. Re-capture production baseline read-only and compare exact serialization/checksum.
8. Run changed-file lint, compile, diff, and added-line security checks.
9. Stage explicit files, verify no unstaged files, and commit without pushing unless requested.
