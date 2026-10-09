# Slow `hermes doctor` inside deterministic ops collectors

## Failure signature

A scheduled triage collector reports:

```text
ERROR: TimeoutExpired: Command '['hermes', 'doctor']' timed out after 90 seconds
```

Do not infer that Doctor or Hermes is broken. A full Doctor run can legitimately exceed a collector's generic timeout because it performs connectivity, browser, package, workspace-audit, and profile checks.

## Safe diagnosis

1. Run the exact command directly with a bounded but larger timeout (for example 180 seconds).
2. If it completes and reports normal findings, classify the incident as a **collector timeout**, not a Doctor failure.
3. Keep credential gaps and workspace build-tool advisories separate from runtime breakage; do not run `doctor --fix` merely because the wrapper timed out.

## Durable repair pattern

Give the collector's command runner a per-probe timeout while retaining a conservative default:

```python
def run(label, cmd, cwd=None, max_chars=6000, timeout=90):
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
    )

run("hermes doctor", ["hermes", "doctor"], timeout=180)
```

Do not globally increase every probe timeout. Long limits on all probes can make the pre-run script exceed the scheduler's total script budget and hide genuinely stuck helpers.

## Wrapper synchronization and verification

When the collector is mirrored across Wolfy/global/profile paths:

1. Patch the canonical global source first.
2. Run the deterministic autorepair/sync twice; the second run should be silent.
3. Compile every synchronized copy.
4. Compare copies byte-for-byte when they are intended to be identical.
5. Unit-smoke the runner with a stubbed `subprocess.run` and assert that the explicit timeout reaches the subprocess call.
6. Re-run standalone `hermes doctor` with the same larger bound and record its actual warnings.

This repairs the false timeout without weakening the bounds on the rest of the scheduled triage workflow.
