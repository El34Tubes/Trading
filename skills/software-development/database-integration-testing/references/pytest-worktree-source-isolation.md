# Pytest Worktree Source-Path Isolation

Use this recipe when focused tests pass but the full application suite imports modules from a canonical, deployed, sibling, or stale checkout.

## Failure signature

- A focused test passes while the full suite fails.
- A traceback or `module.__file__` points outside the active worktree.
- Earlier tests or scripts prepend another source directory to `sys.path`.
- Removing that path does not repair the run because `sys.modules` retains modules loaded from it.
- Import-time constants such as `DEFAULT_DSN` preserve values from the wrong environment.

This is a two-layer contamination problem: import search order **and** module cache identity.

## Tight deterministic regression

Build a test that deliberately:

1. Removes the worktree source directory from `sys.path`.
2. Inserts the known competing source directory first.
3. Seeds `sys.modules` with synthetic `types.ModuleType` entries whose `__file__` points into the competing tree.
4. Calls the suite's restoration helper.
5. Imports the sensitive modules.
6. Asserts each resolved `__file__` is under the worktree.
7. Parses every import-time DSN constant and asserts the exact dedicated test database identity.

Synthetic modules make RED deterministic without executing code from a production checkout.

## Safe conftest repair

1. Derive the authoritative source path from `Path(__file__).resolve().parent`; do not hardcode a worktree path.
2. Normalize aliases with `Path(entry or os.curdir).resolve()`.
3. Remove all equivalent worktree entries and the known competing checkout, then insert one worktree entry at `sys.path[0]`.
4. Call `importlib.invalidate_caches()`.
5. Inspect only local/import-sensitive top-level module names.
6. Keep modules already loaded from the correct worktree.
7. Evict cached modules only when their resolved `__file__` is under the known competing tree.
8. Fail closed if an import-sensitive local module resolves from an unexpected third location; do not blindly delete arbitrary modules.
9. Re-import required modules and verify their origins.
10. Export the validated test DSN before importing modules that cache configuration constants, then validate those constants.
11. Establish the worktree path before flat imports made by `conftest.py` itself.
12. Restore at pytest configuration time and with an autouse fixture before each test. Restoring after each test further limits pollution from legacy scripts.

Do not reload modules already loaded from the correct worktree. Unnecessary reloads split module identity and can leave stale references in dependent modules.

## Verification and change isolation

- Confirm the regression fails before implementation.
- Run the regression and originally failing focused tests.
- Run the complete application test scope.
- Run changed-file lint, compilation, and diff checks.
- Distinguish the application suite from an unscoped repository-root pytest command that may collect vendored or duplicated test trees; report both precisely.
- If unrelated user changes are present, record their diff checksum before editing, stage only explicit intended files, and verify that checksum afterward.