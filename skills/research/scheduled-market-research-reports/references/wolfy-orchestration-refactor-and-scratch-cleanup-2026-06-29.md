# Wolfy orchestration refactor + scratch cleanup pattern — 2026-06-29

Session pattern worth reusing for Wolfy/Hermes EOD orchestration maintenance.

## Safe orchestration refactor shape

- Keep Hermes cron-facing script filenames stable under `/root/.hermes/scripts/`; cron jobs reference these exact names.
- Move duplicated constants and subprocess construction behind shared Wolfy modules instead of editing each wrapper independently.
- Current implemented modules:
  - `/root/.hermes/wolfy/orchestration_config.py` — `CORE_EOD_UNIVERSE`, `EOD_INGEST_SHARDS`, default EOD source/lookback, `DEPTH_READY_BARS`.
  - `/root/.hermes/wolfy/orchestration_runner.py` — EOD ingest command construction, shard runner, dry-run ingest smoke, deterministic features/signals wrapper, approved-setup dry-run gate.
- Keep wrappers as thin shims:
  - `/root/.hermes/scripts/wolfy_eod_after_close_ingest.py`
  - `/root/.hermes/scripts/wolfy_eod_features_signals.py`
  - `/root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_{1..5}.py`

## Verification pattern

Use no-write/monkeypatch checks before letting cron exercise the refactor:

```bash
python3 -m py_compile \
  /root/.hermes/wolfy/orchestration_config.py \
  /root/.hermes/wolfy/orchestration_runner.py \
  /root/.hermes/scripts/wolfy_eod_after_close_ingest.py \
  /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_1.py \
  /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_2.py \
  /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_3.py \
  /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_4.py \
  /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_5.py \
  /root/.hermes/scripts/wolfy_eod_features_signals.py

python3 -m pytest /root/.hermes/wolfy/test_eod_after_close_ingest_wrapper.py -q
python3 /root/.hermes/scripts/wolfy_eod_after_close_ingest.py --dry-run --source yahoo --tickers SPY --days 5
python3 /root/.hermes/scripts/wolfy_eod_features_signals.py --dry-run --tickers SPY,QQQ,IWM
```

For shard wrappers, monkeypatch/import the wrapper and inspect the constructed command rather than running live market-data pulls.

## Scratch cleanup pattern

Wolfy research creates many ignored one-off probes named `tmp_*`. Safe cleanup sequence:

1. Inspect git state first: `git status --short --untracked-files=all`.
2. Prove the scratch files are not tracked: `git ls-files 'wolfy/tmp_*'` should be empty.
3. Confirm ignore rule for a sample: `git check-ignore -v wolfy/tmp_example.py`.
4. Delete only ignored scratch files, not operational wrappers/docs/tests.
5. Verify count is zero and run the smallest relevant tests.

Do not delete `.curator_backups`, cron-facing wrappers, skill references, or modified operational files just because they are untracked/modified; classify them first.
