# Mike storage-watchdog cleanup: Docker build cache

Context: a Mike autonomous environment repair run saw Wolfy storage watchdog emit:

```text
Wolfy storage alert:
- Root disk high: 78.1% used, 21.0GB free
```

Triage showed the large reclaimable item was Docker build cache, not Wolfy/Postgres data:

```bash
df -h / /root /root/.hermes
du -h -d 1 /root/.hermes /root/.cache /root/.local /root/.npm 2>/dev/null | sort -h | tail -30
docker system df
```

`docker system df` reported ~43.4GB build cache reclaimable while images/containers/volumes were active and not reclaimable. Safe repair was:

```bash
docker builder prune -af
# optional low-risk package-manager cache cleanup when relevant:
apt-get clean
npm cache clean --force || true
rm -rf /root/.cache/uv /root/.cache/pip /root/.npm/_cacache /root/.npm/_npx
```

Verification:

```bash
df -h /
docker system df
python3 /root/.hermes/scripts/wolfy_storage_watchdog.py
```

Result: root disk improved from ~79% used / 21GB free to ~37% used / 62GB free, and the storage watchdog became silent.

Pitfalls:
- Prefer pruning Docker **builder cache** before touching images, containers, volumes, state snapshots, profile homes, or Wolfy/Postgres data.
- Do not delete `/root/.hermes/state-snapshots`, profile homes, logs, or market data as a first response to disk pressure; inspect sizes first.
- Treat a now-silent storage watchdog after cleanup as the verification signal; report actual before/after disk numbers when there was a real delta.