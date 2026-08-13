"""Postgres audit ledger for deterministic forward option-structure research."""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence

DEFAULT_DSN = os.environ.get("WOLFY_POSTGRES_DSN", "dbname=wolfy user=root host=/var/run/postgresql")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def ensure_options_research_schema(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS option_structure_evaluations (
          id bigserial PRIMARY KEY,
          ticker text NOT NULL,
          signal_dt date NOT NULL,
          strategy_name text NOT NULL,
          underlying_price numeric NOT NULL,
          technical_target numeric NOT NULL,
          fetched_at timestamptz NOT NULL,
          source text NOT NULL,
          chain jsonb NOT NULL,
          evaluation jsonb NOT NULL,
          selected_structure text,
          paper_only boolean NOT NULL DEFAULT true,
          no_live_execution boolean NOT NULL DEFAULT true,
          broker_order_submitted boolean NOT NULL DEFAULT false,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE(ticker, signal_dt, strategy_name)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_option_structure_evaluations_signal ON option_structure_evaluations(signal_dt DESC, ticker)")


def store_options_structure_evaluation(
    conn, *, ticker: str, signal_dt: date, strategy_name: str,
    underlying_price: Decimal, technical_target: Decimal, fetched_at: datetime,
    source: str, chain: Sequence[Mapping[str, Any]], evaluation: Mapping[str, Any],
) -> dict[str, Any]:
    ensure_options_research_schema(conn)
    selected = evaluation.get("selected") if isinstance(evaluation.get("selected"), Mapping) else None
    selected_structure = str(selected.get("structure")) if selected else None
    row = conn.execute("""
        INSERT INTO option_structure_evaluations(
          ticker,signal_dt,strategy_name,underlying_price,technical_target,
          fetched_at,source,chain,evaluation,selected_structure,
          paper_only,no_live_execution,broker_order_submitted
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,true,true,false)
        ON CONFLICT(ticker,signal_dt,strategy_name) DO UPDATE SET
          underlying_price=EXCLUDED.underlying_price,
          technical_target=EXCLUDED.technical_target,
          fetched_at=EXCLUDED.fetched_at,
          source=EXCLUDED.source,
          chain=EXCLUDED.chain,
          evaluation=EXCLUDED.evaluation,
          selected_structure=EXCLUDED.selected_structure,
          paper_only=true,no_live_execution=true,broker_order_submitted=false,
          updated_at=now()
        RETURNING id
    """, (
        ticker.upper(), signal_dt, strategy_name, underlying_price, technical_target,
        fetched_at, source, _json(list(chain)), _json(dict(evaluation)), selected_structure,
    )).fetchone()
    return {"evaluation_id": int(row[0]), "selected_structure": selected_structure}
