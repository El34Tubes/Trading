"""Immutable Postgres provenance for deterministic option-structure research."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence

DEFAULT_DSN = os.environ.get("WOLFY_POSTGRES_DSN", "dbname=wolfy user=root host=/var/run/postgresql")
_OCC = re.compile(r"^([A-Z0-9.]{1,6})\s*(\d{6})([CP])(\d{8})$")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _canonical_ticker(value: Any) -> str:
    ticker = _nonempty(value, "ticker").upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", ticker):
        raise ValueError("ticker is not canonical")
    return ticker


def _payload(chain: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    if isinstance(chain, (str, bytes, bytearray, Mapping)) or not isinstance(chain, Sequence):
        raise ValueError("chain must be a sequence of mappings")
    normalized: list[dict[str, Any]] = []
    for contract in chain:
        if not isinstance(contract, Mapping):
            raise ValueError("chain must be a sequence of mappings")
        normalized.append(dict(contract))
    if not normalized:
        raise ValueError("chain must not be empty")
    canonical = _json(normalized)
    return normalized, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _contract_underlying(contract: Mapping[str, Any]) -> str | None:
    explicit = contract.get("underlying") or contract.get("underlying_symbol")
    if explicit is not None:
        return _canonical_ticker(explicit)
    symbol = str(contract.get("symbol") or "").replace(" ", "").upper()
    match = _OCC.fullmatch(symbol)
    return match.group(1) if match else None


def ensure_options_research_schema(conn) -> None:
    """Apply the idempotent Task-3 schema only on the caller's selected database."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS option_chain_snapshots (
          snapshot_id text PRIMARY KEY,
          ticker text NOT NULL,
          provider text NOT NULL,
          source_url text NOT NULL,
          fetched_at timestamptz NOT NULL,
          market_at timestamptz NOT NULL,
          available_at timestamptz NOT NULL,
          payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
          chain jsonb NOT NULL CHECK (jsonb_typeof(chain)='array'),
          paper_only boolean NOT NULL DEFAULT true CHECK (paper_only),
          created_at timestamptz NOT NULL DEFAULT now(),
          CHECK (market_at <= fetched_at),
          CHECK (fetched_at <= available_at)
        )
    """)
    conn.execute("ALTER TABLE option_chain_snapshots DROP CONSTRAINT IF EXISTS option_chain_snapshots_ticker_payload_sha256_key")
    conn.execute("""
        CREATE OR REPLACE FUNCTION wolfy_reject_option_snapshot_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'option chain snapshots are append-only';
        END
        $$
    """)
    conn.execute("""
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_trigger
            WHERE tgname='trg_option_chain_snapshots_immutable'
              AND tgrelid='option_chain_snapshots'::regclass
          ) THEN
            CREATE TRIGGER trg_option_chain_snapshots_immutable
              BEFORE UPDATE OR DELETE ON option_chain_snapshots
              FOR EACH ROW EXECUTE FUNCTION wolfy_reject_option_snapshot_mutation();
          END IF;
        END $$
    """)
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
    conn.execute("ALTER TABLE option_structure_evaluations ADD COLUMN IF NOT EXISTS snapshot_id text REFERENCES option_chain_snapshots(snapshot_id)")
    conn.execute("ALTER TABLE option_structure_evaluations ADD COLUMN IF NOT EXISTS decision_at timestamptz")
    conn.execute("ALTER TABLE option_structure_evaluations ADD COLUMN IF NOT EXISTS source_signal_id bigint")
    conn.execute("ALTER TABLE option_structure_evaluations ADD COLUMN IF NOT EXISTS run_id bigint")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_option_structure_evaluations_signal ON option_structure_evaluations(signal_dt DESC, ticker)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_option_structure_evaluations_snapshot ON option_structure_evaluations(snapshot_id)")


def store_options_structure_evaluation(
    conn,
    *,
    ticker: str,
    signal_dt: date,
    strategy_name: str,
    underlying_price: Decimal,
    technical_target: Decimal,
    decision_at: datetime,
    fetched_at: datetime,
    market_at: datetime,
    available_at: datetime,
    provider: str,
    source_url: str,
    chain: Sequence[Mapping[str, Any]],
    evaluation: Mapping[str, Any],
    snapshot_id: str | None = None,
    source_signal_id: int | None = None,
    run_id: int | None = None,
) -> dict[str, Any]:
    """Persist one immutable chain snapshot and its ticker-bound evaluation."""
    ensure_options_research_schema(conn)
    symbol = _canonical_ticker(ticker)
    strategy = _nonempty(strategy_name, "strategy_name")
    provider_name = _nonempty(provider, "provider")
    source = _nonempty(source_url, "source_url")
    decision = _aware(decision_at, "decision_at")
    fetched = _aware(fetched_at, "fetched_at")
    market = _aware(market_at, "market_at")
    available = _aware(available_at, "available_at")
    if market > fetched or fetched > available:
        raise ValueError("snapshot times must satisfy market_at <= fetched_at <= available_at")
    if available > decision:
        raise ValueError("available_at must not be after decision_at")
    if not isinstance(evaluation, Mapping):
        raise ValueError("evaluation must be a mapping")
    evaluation_ticker = evaluation.get("ticker")
    if evaluation_ticker is None or _canonical_ticker(evaluation_ticker) != symbol:
        raise ValueError("evaluation ticker mismatch")
    normalized_chain, payload_sha256 = _payload(chain)
    for contract in normalized_chain:
        underlying = _contract_underlying(contract)
        if underlying is not None and underlying != symbol:
            raise ValueError("OCC underlying mismatch")
    identity_material = _json({
        "ticker": symbol,
        "provider": provider_name,
        "source_url": source,
        "fetched_at": fetched.isoformat(),
        "market_at": market.isoformat(),
        "available_at": available.isoformat(),
        "payload_sha256": payload_sha256,
    })
    identity = snapshot_id or f"ocs_{hashlib.sha256(identity_material.encode()).hexdigest()}"
    identity = _nonempty(identity, "snapshot_id")
    selected = evaluation.get("selected") if isinstance(evaluation.get("selected"), Mapping) else None
    selected_structure = str(selected.get("structure")) if selected else None

    inserted = conn.execute(
        """INSERT INTO option_chain_snapshots(
               snapshot_id,ticker,provider,source_url,fetched_at,market_at,available_at,
               payload_sha256,chain,paper_only)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,true)
             ON CONFLICT(snapshot_id) DO NOTHING RETURNING snapshot_id""",
        (identity, symbol, provider_name, source, fetched, market, available,
         payload_sha256, _json(normalized_chain)),
    ).fetchone()
    if inserted is None:
        existing = conn.execute(
            """SELECT ticker,provider,source_url,fetched_at,market_at,available_at,payload_sha256
               FROM option_chain_snapshots WHERE snapshot_id=%s""",
            (identity,),
        ).fetchone()
        expected = (symbol, provider_name, source, fetched, market, available, payload_sha256)
        if existing != expected:
            raise ValueError("snapshot identity refers to different payload or provenance")

    row = conn.execute(
        """INSERT INTO option_structure_evaluations(
             ticker,signal_dt,strategy_name,underlying_price,technical_target,
             fetched_at,source,chain,evaluation,selected_structure,
             snapshot_id,decision_at,source_signal_id,run_id,
             paper_only,no_live_execution,broker_order_submitted)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,true,true,false)
           ON CONFLICT(ticker,signal_dt,strategy_name) DO NOTHING
           RETURNING id""",
        (symbol, signal_dt, strategy, underlying_price, technical_target, fetched,
         source, _json(normalized_chain), _json(dict(evaluation)), selected_structure,
         identity, decision, source_signal_id, run_id),
    ).fetchone()
    if row is None:
        existing = conn.execute(
            """SELECT id,snapshot_id,decision_at,evaluation,source_signal_id,run_id
               FROM option_structure_evaluations
               WHERE ticker=%s AND signal_dt=%s AND strategy_name=%s""",
            (symbol, signal_dt, strategy),
        ).fetchone()
        if existing is None or existing[1:] != (
            identity, decision, json.loads(_json(dict(evaluation))), source_signal_id, run_id
        ):
            raise ValueError("evaluation identity refers to different provenance or evaluation")
        evaluation_id = int(existing[0])
    else:
        evaluation_id = int(row[0])
    return {
        "evaluation_id": evaluation_id,
        "snapshot_id": identity,
        "payload_sha256": payload_sha256,
        "selected_structure": selected_structure,
        "ticker": symbol,
        "strategy_name": strategy,
        "decision_at": decision.isoformat(),
    }
