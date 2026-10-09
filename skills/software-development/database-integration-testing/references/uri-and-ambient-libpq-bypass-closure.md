# URI and Ambient libpq Bypass Closure

## Threat model

A test DSN can appear safe after parsing while still violating a repository's stricter syntax policy, and libpq can consume connection behavior from process environment variables that are absent from the DSN. Validate both sources before any connection, admin-DSN derivation, schema operation, or privileged subprocess.

## Conservative validation sequence

1. Reject ambient libpq connection variables before parsing or connecting.
2. If policy requires explicit keyword DSNs, reject both `postgresql://` and `postgres://` syntax even when the URI resolves to the approved local Unix socket, database, and peer-auth user.
3. Parse the remaining keyword DSN with the driver.
4. Require the exact allowlist: `dbname=<dedicated_test_db>`, `host=<approved Unix socket>`, `user=<approved peer role>`, with no other parsed keys.
5. Re-run the same validator in every directly callable side-effect path, not only the public resolver.

## Ambient-variable coverage

At minimum include target and authentication overrides (`PGHOST`, `PGHOSTADDR`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGPASSFILE`, `PGSERVICE`, `PGSERVICEFILE`), server options (`PGOPTIONS`), TLS variables (`PGSSLMODE`, certificate/key/root/CRL variables, SNI, protocol bounds, negotiation and legacy `PGREQUIRESSL`), and GSS/auth/session-selection variables (`PGGSSENCMODE`, `PGKRBSRVNAME`, `PGGSSLIB`, `PGGSSDELEGATION`, `PGREQUIREAUTH`, `PGREQUIREPEER`, `PGCHANNELBINDING`, `PGTARGETSESSIONATTRS`, load balancing).

Use the installed driver/libpq metadata (for psycopg, `psycopg.pq.Conninfo.get_defaults()`) during development to audit the current environment-variable surface. Keep explicit compatibility entries such as `PGSERVICEFILE` and legacy variables that may not appear in the current build's defaults.

Reject variables by presence, not truthiness: an explicitly empty inherited value is still ambient state and a fail-closed harness should not need to reason about version-specific empty-value semantics.

## TDD matrix

- Parameterize URI cases across remote, localhost TCP, and semantically local Unix-socket forms.
- Parameterize each ambient variable across both DSN resolution and provisioning.
- Monkeypatch `psycopg.connect` to raise and record calls; assert validation raises first and no connection was attempted.
- Directly exercise admin DSN construction, database-creation subprocess fallback, extension subprocess setup, and schema application. Monkeypatch both connection and subprocess entrypoints and assert neither ran.
- Include one valid explicit keyword DSN and one unrelated benign environment variable as positive controls.

## Release verification

After GREEN, rerun the focused harness, the pre-existing targeted integration suite, and the full serial suite. Apply schema twice, run changed-file lint/compile/diff checks, re-audit implicit callers, compare the exact read-only production snapshot checksum, stage explicit files, scan added lines for secrets, and commit only with a clean working tree.
