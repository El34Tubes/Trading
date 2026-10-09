# Import-Time DSN Ordering Regression

## Failure pattern

A pytest hook intended to isolate database writes can still cache a production DSN when it calls provisioning before exporting the test DSN:

```python
_test_dsn = provision_test_database()  # schema code imports application modules
os.environ["APP_DSN"] = _test_dsn      # too late
```

Provisioning often imports schema helpers from application modules. If those modules define `DEFAULT_DSN = os.environ.get(...)`, both the constant and function defaults bound from it retain the old value for the rest of the process.

## Safe bootstrap sequence

```python
_original_dsn = os.environ.get("APP_DSN", MISSING)
_test_dsn = resolve_test_dsn()          # validation only; no schema imports
os.environ["APP_DSN"] = _test_dsn
try:
    provision_test_database()
except BaseException:
    restore_original_dsn()
    raise
```

Restore the original value in normal test-session teardown as well. Keep the resolver's import graph free of schema/application modules.

## Strict TDD regression

Run the regression in a fresh pytest process. Import every module known to cache the environment-derived DSN, parse each value with the driver's DSN parser, and assert exact database identity:

```python
def test_schema_modules_cache_only_the_isolated_test_dsn():
    modules = (module_a, module_b, module_c)
    for module in modules:
        database = conninfo_to_dict(module.DEFAULT_DSN).get("dbname")
        assert database == TEST_DATABASE_NAME
        assert database != PRODUCTION_DATABASE_NAME
```

For APIs with defaults bound at definition time (for example, `dsn=DEFAULT_DSN`), inspect or exercise an implicit call as well. The expected RED is that at least one cached value resolves to production—not an import error or mocked failure.

## Verification

1. Focused regression: RED before change, GREEN after.
2. Focused database/schema suites.
3. Full relevant pytest suite serially.
4. Static audit: conftest imports no affected schema module before export, and export text/order precedes provisioning.
5. Apply schema twice to prove idempotency.
6. Compare read-only production invariants and deterministic metadata checksum before/after.
7. Run changed-file lint, compile, and diff checks.

Do not patch module constants unless an unavoidable plugin or conftest dependency imports them before the hook. Prefer fixing the import/bootstrap order; if patching is unavoidable, track every original value and restore it at teardown.
