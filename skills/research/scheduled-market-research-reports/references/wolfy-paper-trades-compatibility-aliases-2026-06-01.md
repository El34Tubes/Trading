# Wolfy paper_trades compatibility aliases (2026-06-01)

## Context
A Mike autonomous environment triage run found a Wolfy report failure from LLM/generated diagnostic SQL that queried `paper_trades.qty`, `paper_trades.opened_at`, and `paper_trades.closed_at` while the canonical SQLite schema used `quantity`, `entry_date`, and `exit_date`.

The correct lesson is not that the report pipeline is broken. The durable fix is to support compatibility aliases for common trade-ledger column names while keeping the canonical schema intact.

## Safe repair pattern
For `/root/.hermes/wolfy/wolfy.db`, add non-destructive columns if absent:

```sql
ALTER TABLE paper_trades ADD COLUMN qty REAL;
ALTER TABLE paper_trades ADD COLUMN opened_at TEXT;
ALTER TABLE paper_trades ADD COLUMN closed_at TEXT;
UPDATE paper_trades
SET qty=COALESCE(qty, quantity),
    opened_at=COALESCE(opened_at, entry_date),
    closed_at=COALESCE(closed_at, exit_date);
```

Add alias-maintenance triggers so future rows written with canonical fields remain query-compatible:

```sql
CREATE TRIGGER IF NOT EXISTS trg_paper_trades_alias_after_insert
AFTER INSERT ON paper_trades
FOR EACH ROW
WHEN NEW.qty IS NULL OR NEW.opened_at IS NULL OR NEW.closed_at IS NULL
BEGIN
  UPDATE paper_trades
  SET qty=COALESCE(NEW.qty, NEW.quantity),
      opened_at=COALESCE(NEW.opened_at, NEW.entry_date),
      closed_at=COALESCE(NEW.closed_at, NEW.exit_date)
  WHERE id=NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_paper_trades_alias_after_update
AFTER UPDATE OF quantity, entry_date, exit_date, qty, opened_at, closed_at ON paper_trades
FOR EACH ROW
WHEN NEW.qty IS NULL OR NEW.opened_at IS NULL OR NEW.closed_at IS NULL
BEGIN
  UPDATE paper_trades
  SET qty=COALESCE(NEW.qty, NEW.quantity),
      opened_at=COALESCE(NEW.opened_at, NEW.entry_date),
      closed_at=COALESCE(NEW.closed_at, NEW.exit_date)
  WHERE id=NEW.id;
END;
```

Also update `/root/.hermes/wolfy/init_wolfy_db.py` with the same columns/triggers so fresh DBs do not regress.

## Verification commands

```bash
python3 - <<'PY'
import sqlite3
con=sqlite3.connect('/root/.hermes/wolfy/wolfy.db')
rows=con.execute('SELECT id,ticker,status,entry_price,qty,opened_at,closed_at FROM paper_trades LIMIT 5').fetchall()
print('paper_trades_compat_query_ok rows=', len(rows))
PY

python3 /root/.hermes/wolfy/wolfy_report_context.py >/tmp/wolfy_report_context.out
python3 /root/.hermes/wolfy/check_postgres_requirements.py
python3 -m pytest /root/.hermes/wolfy/test_agent_coordination_smoke.py -q
python3 -m pytest /root/.hermes/wolfy/tests/test_embed_knowledge_chunks.py -q
python3 /root/.hermes/wolfy/embed_knowledge_chunks.py
```

If `wolfy_report_context.py` is run only as a smoke test, it starts a Postgres `agent_runs` row. Close that test row with `wolfy_agent_cli.py run-finish --status completed` so it does not remain as a stale `started` run.

## Reporting note
Treat this as a compatibility/schema hardening fix, not a trading-logic change. Do not alter recommendation rules, paper-trading logic, or market-analysis behavior while applying this repair.