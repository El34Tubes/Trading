# Wolfy Alpha Search pipeline: no-subcommand status smoke

Session date: 2026-06-04

## Context

During a Mike autonomous environment triage run, the recent-error tail showed the Wolfy separate Alpha Search Report cron had triggered an agent/tool invocation of:

```bash
python3 /root/.hermes/wolfy/alpha_search_pipeline.py
```

The CLI originally required an explicit subcommand (`init`, `status`, `template`, or `record`), so a bare invocation exited with argparse code 2 and produced usage noise in ops logs. The cron job itself still reported `ok`, but this is avoidable noise and can confuse triage.

## Durable fix pattern

For small operational helper CLIs that agents may use as smoke tests, make a bare invocation safe and non-mutating instead of failing. In this case:

- Changed `alpha_search_pipeline.py` from `add_subparsers(dest="cmd", required=True)` to `add_subparsers(dest="cmd")`.
- Added an `args.cmd is None` branch that prints the same JSON as `status_snapshot(DEFAULT_DB)`.
- Kept mutating actions (`init`, `record`) behind explicit subcommands.
- Added regression coverage: `test_cli_without_subcommand_is_non_mutating_status_smoke` validates that bare CLI output is parseable JSON with `counts` and `required_sections`.

## Verification commands

Run from `/root/.hermes/wolfy`:

```bash
python3 alpha_search_pipeline.py >/tmp/alpha_status.json
python3 -m json.tool /tmp/alpha_status.json >/dev/null
python3 alpha_search_pipeline.py status >/tmp/alpha_status2.json
python3 -m json.tool /tmp/alpha_status2.json >/dev/null
python3 -m pytest test_alpha_search_pipeline.py test_postgres_primary_pipeline.py -q
```

Expected result from the targeted tests after the fix: `9 passed`.

## Generalizable lesson

Do not encode the transient argparse failure as “Alpha Search is broken.” The reusable ops lesson is: for cron-facing helper CLIs that are likely to be probed by agents, provide a safe default read-only/status behavior for bare invocations and test it.