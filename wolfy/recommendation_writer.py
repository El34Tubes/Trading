"""Serialized paper-recommendation capacity enforcement.

All Postgres recommendation writers use this module so approved and experimental
paths share one transaction-scoped lock and one post-lock capacity recount.
This module has no broker integration and performs no live actions.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from typing import Callable, Mapping, Sequence
import uuid

from instrument_decision import InstrumentDecision
from portfolio_allocator import AllocationDecision

GLOBAL_RECOMMENDATION_LOCK_KEY = "wolfy:global-paper-recommendations:v1"
MAXIMUM_POSITIONS = 20
MAXIMUM_POSITIONS_PER_SECTOR = 5
RISK_FRACTION_PER_POSITION = Decimal("0.05")
MAXIMUM_AGGREGATE_RISK = Decimal("1.00")
_ACTIVE_STATUSES = ("paper_candidate", "paper_logged")


@dataclass(frozen=True)
class RecommendationCandidate:
    ticker: str
    strategy_name: str
    signal_dt: date
    sector: str
    risk_fraction: Decimal

    def __post_init__(self) -> None:
        ticker = self.ticker.strip().upper() if isinstance(self.ticker, str) else ""
        strategy = self.strategy_name.strip() if isinstance(self.strategy_name, str) else ""
        sector = self.sector.strip() if isinstance(self.sector, str) else ""
        if not ticker or not strategy or not sector or type(self.signal_dt) is not date:
            raise ValueError("recommendation candidate identity fields must be present")
        try:
            risk = Decimal(self.risk_fraction)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("risk_fraction must be a finite decimal") from exc
        if not risk.is_finite() or risk <= 0 or risk > RISK_FRACTION_PER_POSITION:
            raise ValueError("risk_fraction must be positive and no greater than 0.05")
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "strategy_name", strategy)
        object.__setattr__(self, "sector", sector)
        object.__setattr__(self, "risk_fraction", risk)


@dataclass(frozen=True)
class RecommendationWriteResult:
    selected: tuple[RecommendationCandidate, ...]
    inserted: int
    blocked: tuple[tuple[str, str], ...]
    existing_positions: int
    existing_risk: Decimal
    dry_run: bool
    lock_key: str = GLOBAL_RECOMMENDATION_LOCK_KEY


@dataclass(frozen=True)
class UnderlyingFallback:
    """Allocated setup terms for the temporary stock-only shadow slice."""

    candidate_id: uuid.UUID
    ticker: str
    strategy_name: str
    strategy_version: str
    sector: str
    global_rank: int
    entry: Decimal
    stop: Decimal
    target: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, uuid.UUID):
            raise ValueError("candidate_id must be a UUID")
        if type(self.global_rank) is not int or self.global_rank <= 0:
            raise ValueError("global_rank must be a positive integer")
        for field in ("ticker", "strategy_name", "strategy_version", "sector"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{field} must be canonical non-empty text")
        if self.ticker != self.ticker.upper():
            raise ValueError("ticker must be uppercase")
        try:
            entry = Decimal(self.entry)
            stop = Decimal(self.stop)
            target = Decimal(self.target)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("fallback prices must be finite decimals") from exc
        if not all(value.is_finite() for value in (entry, stop, target)):
            raise ValueError("fallback prices must be finite")
        if not 0 < stop < entry < target:
            raise ValueError("fallback terms must satisfy 0 < stop < entry < target")
        object.__setattr__(self, "entry", entry)
        object.__setattr__(self, "stop", stop)
        object.__setattr__(self, "target", target)


@dataclass(frozen=True)
class PivotInstrumentRecommendation:
    """One selected allocation bound to exactly one paper instrument decision."""

    run_id: uuid.UUID
    allocation: AllocationDecision
    instrument: InstrumentDecision
    option_evaluation_id: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, uuid.UUID):
            raise ValueError("run_id must be a UUID")
        if not isinstance(self.allocation, AllocationDecision):
            raise ValueError("allocation must be an AllocationDecision")
        if not self.allocation.selected or self.allocation.reason != "selected":
            raise ValueError("allocation must be selected")
        if self.allocation.risk_fraction != RISK_FRACTION_PER_POSITION:
            raise ValueError("allocation risk_fraction must equal 0.05")
        if not isinstance(self.instrument, InstrumentDecision):
            raise ValueError("instrument must be an InstrumentDecision")
        candidate = self.allocation.candidate
        decision = self.instrument
        if decision.candidate_id != candidate.candidate_id or decision.ticker != candidate.ticker:
            raise ValueError("instrument decision must bind to the allocated candidate")
        if (
            not isinstance(decision.decision_at, datetime)
            or decision.decision_at.tzinfo is None
            or decision.decision_at.utcoffset() is None
        ):
            raise ValueError("instrument decision_at must be timezone-aware")
        if (
            decision.paper_only is not True
            or decision.no_live_execution is not True
            or decision.broker_order_submitted is not False
        ):
            raise ValueError("instrument decision must be paper-only with no broker order")
        max_loss = _finite_positive_decimal(decision.max_loss, "max_loss")
        risk_budget = _finite_positive_decimal(decision.risk_budget, "risk_budget")
        if max_loss > risk_budget:
            raise ValueError("max_loss cannot exceed risk_budget")
        if decision.expression == "underlying_stock_fallback":
            if self.option_evaluation_id is not None:
                raise ValueError("stock fallback cannot bind an option_evaluation_id")
            if (
                decision.option_contracts != 0
                or decision.long_leg is not None
                or decision.short_leg is not None
                or decision.underlying_quantity is None
                or not decision.fallback_reasons
            ):
                raise ValueError("stock fallback decision is malformed")
            _finite_positive_decimal(decision.underlying_quantity, "underlying_quantity")
        elif decision.expression in ("long_call", "call_debit_spread"):
            if type(self.option_evaluation_id) is not int or self.option_evaluation_id <= 0:
                raise ValueError("option_evaluation_id is required for an option expression")
            if (
                type(decision.option_contracts) is not int
                or decision.option_contracts <= 0
                or not isinstance(decision.long_leg, Mapping)
                or not decision.long_leg
                or decision.underlying_quantity is not None
                or decision.fallback_reasons
                or not decision.chain_snapshot_id
            ):
                raise ValueError("option instrument decision is malformed")
            if decision.expression == "long_call" and decision.short_leg is not None:
                raise ValueError("long_call cannot have a short leg")
            if decision.expression == "call_debit_spread" and (
                not isinstance(decision.short_leg, Mapping) or not decision.short_leg
            ):
                raise ValueError("call_debit_spread requires an exact short leg")
            _canonical_json_value(decision.long_leg, "long_leg")
            if decision.short_leg is not None:
                _canonical_json_value(decision.short_leg, "short_leg")
        else:
            raise ValueError("unsupported instrument expression")


@dataclass(frozen=True)
class PivotRecommendationWriteResult:
    selected: tuple[RecommendationCandidate, ...]
    inserted: int
    paper_trades_inserted: int
    blocked: tuple[tuple[str, str], ...]
    existing_positions: int
    existing_risk: Decimal
    dry_run: bool
    broker_orders_created: int = 0


@dataclass(frozen=True, slots=True)
class ProductionPaperScope:
    """Exact paper-only capability minted by the Task 23 release adapter."""

    scope_fingerprint: str
    snapshot_id: uuid.UUID
    strategy_id: str
    strategy_version: str
    paper_only: bool = True
    no_live_execution: bool = True
    broker_execution_enabled: bool = False
    external_delivery_enabled: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.scope_fingerprint, str)
            or len(self.scope_fingerprint) != 64
            or any(ch not in "0123456789abcdef" for ch in self.scope_fingerprint)
            or not isinstance(self.snapshot_id, uuid.UUID)
            or self.strategy_id != "liquid_rs_breakout_close_confirm_1r"
            or self.strategy_version != "approved-2026-08-03"
            or self.paper_only is not True
            or self.no_live_execution is not True
            or self.broker_execution_enabled is not False
            or self.external_delivery_enabled is not False
        ):
            raise ValueError("production paper scope is malformed or unsafe")


def _finite_positive_decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite positive decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite positive decimal") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{field} must be a finite positive decimal")
    return result


def _canonical_json_value(value: object, field: str) -> object:
    """Validate JSON containers and convert only finite Decimals to strings."""
    if value is None or isinstance(value, (str, int)) or type(value) is bool:
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"{field} contains a nonfinite decimal")
        return str(value)
    if isinstance(value, float):
        converted = Decimal(str(value))
        if not converted.is_finite():
            raise ValueError(f"{field} contains a nonfinite number")
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key or key != key.strip():
                raise ValueError(f"{field} contains a noncanonical key")
            result[key] = _canonical_json_value(item, field)
        return result
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item, field) for item in value]
    raise ValueError(f"{field} contains a non-JSON value")


def _safe_existing_risk(notes: Mapping[str, object]) -> Decimal:
    """Treat absent/malformed legacy risk as one full policy risk unit."""
    try:
        risk = Decimal(str(notes.get("risk_fraction", RISK_FRACTION_PER_POSITION)))
    except (InvalidOperation, TypeError, ValueError):
        return RISK_FRACTION_PER_POSITION
    if not risk.is_finite() or risk <= 0 or risk > RISK_FRACTION_PER_POSITION:
        return RISK_FRACTION_PER_POSITION
    return risk


def _active_portfolio(conn) -> tuple[set[str], Counter[str], Decimal]:
    rows = conn.execute(
        """SELECT r.ticker, r.notes
           FROM recommendations r
           WHERE r.status = ANY(%s)
             AND r.notes->>'paper_only'='true'
             AND r.notes->>'no_live_execution'='true'
             AND (
                 r.status='paper_candidate'
                 OR NOT EXISTS (
                     SELECT 1 FROM paper_trades closed_trade
                     WHERE closed_trade.recommendation_id=r.id::text
                       AND lower(closed_trade.status)='closed'
                 )
             )
           UNION ALL
           SELECT pt.ticker, coalesce(r.notes, pt.notes, '{}'::jsonb)
           FROM paper_trades pt
           LEFT JOIN recommendations r ON r.id::text=pt.recommendation_id
           WHERE lower(pt.status) IN ('open','pending','triggered','active')""",
        (list(_ACTIVE_STATUSES),),
    ).fetchall()
    tickers: set[str] = set()
    sectors: Counter[str] = Counter()
    aggregate_risk = Decimal("0")
    for ticker, raw_notes in rows:
        notes = raw_notes if isinstance(raw_notes, Mapping) else {}
        normalized_ticker = str(ticker).strip().upper()
        # A recommendation and its open paper trade are one position.
        if normalized_ticker in tickers:
            continue
        tickers.add(normalized_ticker)
        sector = str(notes.get("sector") or "Unknown").strip() or "Unknown"
        sectors[sector] += 1
        aggregate_risk += _safe_existing_risk(notes)
    return tickers, sectors, min(aggregate_risk, MAXIMUM_AGGREGATE_RISK)


def write_ranked_recommendations(
    conn,
    *,
    candidates: Sequence[RecommendationCandidate],
    insert_candidate: Callable[[RecommendationCandidate], bool],
    max_to_write: int,
    dry_run: bool,
) -> RecommendationWriteResult:
    """Select and optionally insert ranked candidates under shared global caps.

    Candidate order is ranking order and is intentionally preserved. On a real
    write the advisory transaction lock is acquired before the active portfolio
    is recounted and held by PostgreSQL until the caller commits or rolls back.
    A dry run performs only the read and never calls ``insert_candidate``.
    """
    if type(max_to_write) is not int:
        raise TypeError("max_to_write must be an integer")
    if not dry_run and getattr(conn, "autocommit", False):
        raise RuntimeError("shared recommendation writes require an explicit transaction")
    if not dry_run:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (GLOBAL_RECOMMENDATION_LOCK_KEY,),
        )
    active_tickers, sector_counts, aggregate_risk = _active_portfolio(conn)
    existing_positions = len(active_tickers)
    selected: list[RecommendationCandidate] = []
    blocked: list[tuple[str, str]] = []
    write_limit = min(max(0, max_to_write), MAXIMUM_POSITIONS)

    for candidate in candidates:
        if len(selected) >= write_limit:
            blocked.append((candidate.ticker, "writer_limit"))
            continue
        if candidate.ticker in active_tickers:
            blocked.append((candidate.ticker, "duplicate_ticker"))
            continue
        if len(active_tickers) >= MAXIMUM_POSITIONS:
            blocked.append((candidate.ticker, "global_position_cap"))
            continue
        if sector_counts[candidate.sector] >= MAXIMUM_POSITIONS_PER_SECTOR:
            blocked.append((candidate.ticker, "sector_position_cap"))
            continue
        if aggregate_risk + candidate.risk_fraction > MAXIMUM_AGGREGATE_RISK:
            blocked.append((candidate.ticker, "aggregate_risk_cap"))
            continue
        if not dry_run and not insert_candidate(candidate):
            blocked.append((candidate.ticker, "insert_conflict"))
            continue
        selected.append(candidate)
        active_tickers.add(candidate.ticker)
        sector_counts[candidate.sector] += 1
        aggregate_risk += candidate.risk_fraction

    return RecommendationWriteResult(
        selected=tuple(selected),
        inserted=0 if dry_run else len(selected),
        blocked=tuple(blocked),
        existing_positions=existing_positions,
        existing_risk=aggregate_risk - sum((item.risk_fraction for item in selected), Decimal("0")),
        dry_run=dry_run,
    )


def write_underlying_fallback_recommendations(
    conn,
    *,
    fallbacks: Sequence[UnderlyingFallback],
    signal_dt: date,
    dry_run: bool,
) -> RecommendationWriteResult:
    """Persist temporary stock fallback rows only in ``wolfy_test``.

    Task 11 intentionally has no option release surface. Rows are explicit stock
    fallbacks, and the shared writer repeats capacity checks under its global lock.
    """
    if type(signal_dt) is not date:
        raise ValueError("signal_dt must be a date")
    if any(not isinstance(item, UnderlyingFallback) for item in fallbacks):
        raise ValueError("fallbacks must contain UnderlyingFallback values")
    if not dry_run:
        database = conn.execute("SELECT current_database()").fetchone()[0]
        if database != "wolfy_test":
            raise RuntimeError("underlying pivot publication is disabled outside wolfy_test")

    by_identity = {(item.ticker, item.strategy_name): item for item in fallbacks}

    def insert_candidate(candidate: RecommendationCandidate) -> bool:
        item = by_identity[(candidate.ticker, candidate.strategy_name)]
        notes = {
            "paper_only": True,
            "no_live_execution": True,
            "broker_order_submitted": False,
            "signal_dt": signal_dt.isoformat(),
            "candidate_id": str(item.candidate_id),
            "strategy_name": item.strategy_name,
            "strategy_version": item.strategy_version,
            "sector": item.sector,
            "global_rank": item.global_rank,
            "risk_fraction": str(RISK_FRACTION_PER_POSITION),
            "instrument_expression": "underlying_stock_fallback",
            "instrument_reason": "option_engine_not_release_ready",
            "entry": str(item.entry),
            "stop": str(item.stop),
            "target": str(item.target),
            "shadow_only": True,
        }
        return conn.execute(
            """INSERT INTO recommendations(
                   ticker,action,recommendation_type,thesis,setup_type,
                   entry_zone,entry_trigger,stop,target,risk_reward,confidence,
                   position_size_suggestion,holding_period,status,notes)
               VALUES (%s,'buy','underlying_stock_fallback',%s,%s,%s,%s,%s,%s,%s,
                       'shadow',%s,'Up to 10 trading days','paper_candidate',%s::jsonb)
               ON CONFLICT (ticker,(notes->>'signal_dt'),(notes->>'strategy_name'))
                 WHERE status IN ('paper_candidate','paper_logged')
                   AND notes->>'signal_dt' IS NOT NULL
                   AND notes->>'strategy_name' IS NOT NULL
               DO NOTHING RETURNING id""",
            (
                item.ticker,
                f"Paper-only shadow fallback for {item.strategy_name}; no live execution.",
                item.strategy_name,
                str(item.entry),
                f"Paper entry at {item.entry}",
                f"Stop at {item.stop}",
                f"Target at {item.target}",
                str((item.target - item.entry) / (item.entry - item.stop)),
                "Paper risk 5.00% of account; globally capped.",
                json.dumps(notes, sort_keys=True),
            ),
        ).fetchone() is not None

    ranked = [
        RecommendationCandidate(
            ticker=item.ticker,
            strategy_name=item.strategy_name,
            signal_dt=signal_dt,
            sector=item.sector,
            risk_fraction=RISK_FRACTION_PER_POSITION,
        )
        for item in fallbacks
    ]
    return write_ranked_recommendations(
        conn,
        candidates=ranked,
        insert_candidate=insert_candidate,
        max_to_write=MAXIMUM_POSITIONS,
        dry_run=dry_run,
    )


def _validate_pivot_database_bindings(
    conn,
    *,
    item: PivotInstrumentRecommendation,
    signal_dt: date,
) -> None:
    candidate = item.allocation.candidate
    decision = item.instrument
    strategy = conn.execute(
        "SELECT status,metadata FROM strategies WHERE name=%s",
        (candidate.strategy_id,),
    ).fetchone()
    metadata = strategy[1] if strategy and isinstance(strategy[1], Mapping) else {}
    if (
        not strategy
        or strategy[0] != "approved"
        or metadata.get("approval_scope") != "paper_only_no_live_execution"
        or metadata.get("paper_recommendation_approval") is not True
    ):
        raise ValueError("strategy lacks explicit paper-only approval metadata")
    if decision.expression == "underlying_stock_fallback":
        return
    row = conn.execute(
        """SELECT e.ticker,e.signal_dt,e.strategy_name,e.snapshot_id,e.decision_at,
                  e.selected_structure,s.ticker,e.evaluation
             FROM option_structure_evaluations e
             JOIN option_chain_snapshots s ON s.snapshot_id=e.snapshot_id
            WHERE e.id=%s""",
        (item.option_evaluation_id,),
    ).fetchone()
    expected = (
        candidate.ticker,
        signal_dt,
        candidate.strategy_id,
        decision.chain_snapshot_id,
        decision.expression,
        candidate.ticker,
    )
    if row is None or (row[0], row[1], row[2], row[3], row[5], row[6]) != expected:
        raise ValueError("option evaluation is not bound to candidate/strategy/snapshot")
    if (
        not isinstance(row[4], datetime)
        or row[4].tzinfo is None
        or row[4].utcoffset() is None
        or row[4].astimezone(timezone.utc) != decision.decision_at.astimezone(timezone.utc)
    ):
        raise ValueError("option evaluation decision_at mismatch")
    evaluation = row[7] if isinstance(row[7], Mapping) else {}
    selected = evaluation.get("selected")
    if not isinstance(selected, Mapping):
        raise ValueError("option evaluation has no exact selected structure")
    if (
        selected.get("structure") != decision.expression
        or selected.get("long_leg") != _canonical_json_value(decision.long_leg, "long_leg")
        or selected.get("short_leg") != _canonical_json_value(decision.short_leg, "short_leg")
    ):
        raise ValueError("option decision legs do not match bound evaluation")


def write_pivot_instrument_recommendations(
    conn,
    *,
    recommendations: Sequence[PivotInstrumentRecommendation],
    signal_dt: date,
    dry_run: bool,
    production_scope: ProductionPaperScope | None = None,
) -> PivotRecommendationWriteResult:
    """Persist selected exact instruments and their paper ledger rows atomically.

    The shared writer remains authoritative for concurrent portfolio capacity.
    This path has no broker integration and is write-enabled only in ``wolfy_test``
    until the reviewed release/canary gate explicitly changes that boundary.
    """
    if type(signal_dt) is not date:
        raise ValueError("signal_dt must be a date")
    if isinstance(recommendations, (str, bytes)) or not isinstance(recommendations, Sequence):
        raise ValueError("recommendations must be a sequence")
    if any(not isinstance(item, PivotInstrumentRecommendation) for item in recommendations):
        raise ValueError("recommendations must contain PivotInstrumentRecommendation values")
    identities = [
        (item.allocation.candidate.ticker, item.allocation.candidate.strategy_id)
        for item in recommendations
    ]
    if len(set(identities)) != len(identities):
        raise ValueError("recommendations contain duplicate ticker/strategy identities")
    if production_scope is not None:
        for item in recommendations:
            source = item.allocation.candidate
            if (
                source.universe_snapshot_id != production_scope.snapshot_id
                or source.strategy_id != production_scope.strategy_id
                or source.strategy_version != production_scope.strategy_version
            ):
                raise ValueError("recommendation is outside the exact production paper scope")
    if not dry_run:
        database = conn.execute("SELECT current_database()").fetchone()[0]
        permitted = database == "wolfy_test" and production_scope is None
        permitted = permitted or (database == "wolfy" and production_scope is not None)
        if not permitted:
            raise RuntimeError("pivot recommendation publication is disabled for this database/scope")
    for item in recommendations:
        _validate_pivot_database_bindings(conn, item=item, signal_dt=signal_dt)

    items_by_identity = {
        (item.allocation.candidate.ticker, item.allocation.candidate.strategy_id): item
        for item in recommendations
    }
    paper_trades_inserted = 0

    def insert_candidate(candidate: RecommendationCandidate) -> bool:
        nonlocal paper_trades_inserted
        item = items_by_identity[(candidate.ticker, candidate.strategy_name)]
        allocation = item.allocation
        source = allocation.candidate
        decision = item.instrument
        long_leg = _canonical_json_value(decision.long_leg, "long_leg")
        short_leg = _canonical_json_value(decision.short_leg, "short_leg")
        notes = {
            "paper_only": True,
            "no_live_execution": True,
            "broker_order_submitted": False,
            "signal_dt": signal_dt.isoformat(),
            "decision_at": decision.decision_at.isoformat(),
            "run_id": str(item.run_id),
            "candidate_id": str(source.candidate_id),
            "universe_snapshot_id": str(source.universe_snapshot_id),
            "strategy_name": source.strategy_id,
            "strategy_version": source.strategy_version,
            "sector": source.sector,
            "allocation": {
                "global_rank": allocation.global_rank,
                "sector_rank": allocation.sector_rank,
                "normalized_score": str(allocation.normalized_score),
                "risk_fraction": str(allocation.risk_fraction),
            },
            "risk_fraction": str(allocation.risk_fraction),
            "risk_budget": str(decision.risk_budget),
            "max_loss": str(decision.max_loss),
            "instrument_expression": decision.expression,
            "selector_version": decision.selector_version,
            "option_evaluation_id": item.option_evaluation_id,
            "option_chain_snapshot_id": decision.chain_snapshot_id,
            "option_contracts": decision.option_contracts,
            "underlying_quantity": (
                str(decision.underlying_quantity)
                if decision.underlying_quantity is not None
                else None
            ),
            "long_leg": long_leg,
            "short_leg": short_leg,
            "fallback_reasons": list(decision.fallback_reasons),
            "production_release_scope": (
                production_scope.scope_fingerprint if production_scope is not None else None
            ),
            "source_signal": {
                "close": str(source.entry),
                "invalidation": str(source.stop),
                "target": str(source.target),
            },
        }
        inserted = conn.execute(
            """INSERT INTO recommendations(
                   ticker,action,recommendation_type,thesis,setup_type,
                   entry_zone,entry_trigger,stop,target,risk_reward,confidence,
                   position_size_suggestion,holding_period,status,notes)
               VALUES (%s,'buy',%s,%s,%s,%s,%s,%s,%s,%s,'paper',%s,
                       'Up to 10 trading days','paper_candidate',%s::jsonb)
               ON CONFLICT (ticker,(notes->>'signal_dt'),(notes->>'strategy_name'))
                 WHERE status IN ('paper_candidate','paper_logged')
                   AND notes->>'signal_dt' IS NOT NULL
                   AND notes->>'strategy_name' IS NOT NULL
               DO NOTHING RETURNING id""",
            (
                source.ticker,
                decision.expression,
                f"Paper-only {source.strategy_id} via {decision.expression}; no live execution.",
                source.strategy_id,
                str(source.entry),
                f"Paper entry at {source.entry}",
                f"Stop at {source.stop}",
                f"Target at {source.target}",
                str((source.target - source.entry) / (source.entry - source.stop)),
                f"Defined paper risk no greater than {decision.risk_budget}.",
                json.dumps(notes, sort_keys=True),
            ),
        ).fetchone()
        if inserted is None:
            return False
        recommendation_id = inserted[0]
        if decision.expression == "underlying_stock_fallback":
            entry_price = source.entry
            quantity = decision.underlying_quantity
        else:
            entry_price = decision.max_loss / Decimal(decision.option_contracts * 100)
            quantity = Decimal(decision.option_contracts)
        trade_notes = {
            "paper_only": True,
            "no_live_execution": True,
            "broker_order_submitted": False,
            "source_recommendation_id": str(recommendation_id),
            "candidate_id": str(source.candidate_id),
            "run_id": str(item.run_id),
            "strategy_name": source.strategy_id,
            "instrument_expression": decision.expression,
            "max_loss": str(decision.max_loss),
            "risk_budget": str(decision.risk_budget),
            "option_evaluation_id": item.option_evaluation_id,
            "option_chain_snapshot_id": decision.chain_snapshot_id,
            "long_leg": long_leg,
            "short_leg": short_leg,
            "fallback_reasons": list(decision.fallback_reasons),
        }
        conn.execute(
            """INSERT INTO paper_trades(
                   recommendation_id,ticker,entry_date,entry_price,quantity,
                   instrument,stop_price,target_price,status,data_source,notes)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'open',
                       'mid_small_pivot_exact_instrument',%s::jsonb)""",
            (
                str(recommendation_id), source.ticker, signal_dt, entry_price,
                quantity, decision.expression, source.stop, source.target,
                json.dumps(trade_notes, sort_keys=True),
            ),
        )
        conn.execute(
            "UPDATE recommendations SET status='paper_logged' WHERE id=%s",
            (recommendation_id,),
        )
        paper_trades_inserted += 1
        return True

    ranked = [
        RecommendationCandidate(
            ticker=item.allocation.candidate.ticker,
            strategy_name=item.allocation.candidate.strategy_id,
            signal_dt=signal_dt,
            sector=item.allocation.candidate.sector,
            risk_fraction=item.allocation.risk_fraction,
        )
        for item in recommendations
    ]
    base = write_ranked_recommendations(
        conn,
        candidates=ranked,
        insert_candidate=insert_candidate,
        max_to_write=MAXIMUM_POSITIONS,
        dry_run=dry_run,
    )
    return PivotRecommendationWriteResult(
        selected=base.selected,
        inserted=base.inserted,
        paper_trades_inserted=paper_trades_inserted,
        blocked=base.blocked,
        existing_positions=base.existing_positions,
        existing_risk=base.existing_risk,
        dry_run=base.dry_run,
    )
