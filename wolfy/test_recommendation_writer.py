from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import threading
import uuid

import pytest

from test_db import provision_test_database, resolve_test_dsn, test_connection


def _insert_test_recommendation(conn, candidate) -> bool:
    notes = {
        "paper_only": True,
        "no_live_execution": True,
        "broker_order_submitted": False,
        "signal_dt": candidate.signal_dt.isoformat(),
        "strategy_name": candidate.strategy_name,
        "sector": candidate.sector,
        "risk_fraction": str(candidate.risk_fraction),
    }
    return conn.execute(
        """
        INSERT INTO recommendations(
            ticker, action, recommendation_type, status, notes
        ) VALUES (%s, 'buy', 'unit_shared_writer', 'paper_candidate', %s::jsonb)
        ON CONFLICT (ticker, (notes->>'signal_dt'), (notes->>'strategy_name'))
          WHERE status IN ('paper_candidate','paper_logged')
            AND notes->>'signal_dt' IS NOT NULL
            AND notes->>'strategy_name' IS NOT NULL
        DO NOTHING
        RETURNING id
        """,
        (candidate.ticker, json.dumps(notes)),
    ).fetchone() is not None


def test_shared_writer_dry_run_is_deterministic_and_never_locks_or_writes():
    from recommendation_writer import RecommendationCandidate, write_ranked_recommendations

    class DryConnection:
        def __init__(self):
            self.statements: list[str] = []

        def execute(self, statement, params=None):
            del params
            self.statements.append(str(statement))
            if "FROM recommendations" in str(statement):
                return self
            raise AssertionError("dry run attempted a lock or write")

        def fetchall(self):
            return []

    conn = DryConnection()
    candidates = [
        RecommendationCandidate("ZZDRYB", "unit", date(2099, 4, 1), "Tech", Decimal("0.05")),
        RecommendationCandidate("ZZDRYA", "unit", date(2099, 4, 1), "Tech", Decimal("0.05")),
    ]
    first = write_ranked_recommendations(
        conn, candidates=candidates, insert_candidate=lambda _candidate: True,
        max_to_write=20, dry_run=True,
    )
    second = write_ranked_recommendations(
        conn, candidates=candidates, insert_candidate=lambda _candidate: True,
        max_to_write=20, dry_run=True,
    )

    assert first == second
    assert [item.ticker for item in first.selected] == ["ZZDRYB", "ZZDRYA"]
    assert first.inserted == 0
    assert all("pg_advisory" not in statement.lower() for statement in conn.statements)


def test_two_real_connections_share_one_lock_and_cannot_race_past_global_caps():
    psycopg = pytest.importorskip("psycopg")
    from recommendation_writer import RecommendationCandidate, write_ranked_recommendations

    provision_test_database()
    dsn = resolve_test_dsn()
    token = uuid.uuid4().hex[:8].upper()
    signal_dt = date(2099, 4, 2)
    tickers = [f"ZZ{token}{index:02d}" for index in range(30)]
    sectors_by_ticker = {
        ticker: (
            "Tech" if index < 8 else
            "Health" if index < 16 else
            "Energy" if index < 24 else
            "Finance"
        )
        for index, ticker in enumerate(tickers)
    }
    sectors = sorted(set(sectors_by_ticker.values()))
    batches = [tickers[:15], [tickers[0], *tickers[15:29]]]
    barrier = threading.Barrier(2)

    def worker(batch: list[str]):
        with psycopg.connect(dsn) as conn:
            assert conn.execute("SELECT current_database()").fetchone()[0] == "wolfy_test"
            candidates = [
                RecommendationCandidate(
                    ticker=ticker,
                    strategy_name=f"unit_shared_{token}",
                    signal_dt=signal_dt,
                    sector=sectors_by_ticker[ticker],
                    risk_fraction=Decimal("0.05"),
                )
                for ticker in batch
            ]
            barrier.wait(timeout=10)
            result = write_ranked_recommendations(
                conn,
                candidates=candidates,
                insert_candidate=lambda candidate: _insert_test_recommendation(conn, candidate),
                max_to_write=20,
                dry_run=False,
            )
            conn.commit()
            return result

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, batches))
        with psycopg.connect(dsn) as conn:
            rows = conn.execute(
                """SELECT ticker, notes->>'sector', (notes->>'risk_fraction')::numeric
                   FROM recommendations
                   WHERE notes->>'strategy_name'=%s
                   ORDER BY ticker""",
                (f"unit_shared_{token}",),
            ).fetchall()
            lock_keys = {result.lock_key for result in results}
            sector_counts = {
                sector: sum(1 for _ticker, row_sector, _risk in rows if row_sector == sector)
                for sector in sectors
            }
            assert len(lock_keys) == 1
            assert sum(result.inserted for result in results) == len(rows)
            assert len(rows) == 20
            assert len({ticker for ticker, _sector, _risk in rows}) == len(rows)
            assert set(sector_counts.values()) == {5}
            assert sum(risk for _ticker, _sector, risk in rows) <= Decimal("1.00")
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute(
                "DELETE FROM recommendations WHERE notes->>'strategy_name'=%s",
                (f"unit_shared_{token}",),
            )
            conn.commit()


def test_pivot_writer_persists_exact_option_and_stock_fallback_with_paper_ledger():
    pytest.importorskip("psycopg")
    from eod_signals import seed_default_strategies
    from instrument_decision import InstrumentDecision
    from portfolio_allocator import AllocationDecision, PortfolioCandidate
    from recommendation_writer import (
        PivotInstrumentRecommendation,
        write_pivot_instrument_recommendations,
    )
    from setup_evaluators import (
        APPROVED_BREAKOUT_STRATEGY_ID,
        APPROVED_BREAKOUT_STRATEGY_VERSION,
    )

    signal_dt = date(2099, 4, 3)
    decision_at = datetime(2099, 4, 4, 1, tzinfo=timezone.utc)
    run_id = uuid.uuid4()
    snapshot_uuid = uuid.uuid4()
    token = uuid.uuid4().hex[:8].upper()
    option_ticker = f"ZZO{token}"
    stock_ticker = f"ZZS{token}"

    def allocation(ticker: str, rank: int) -> AllocationDecision:
        candidate = PortfolioCandidate(
            candidate_id=uuid.uuid4(),
            universe_snapshot_id=snapshot_uuid,
            ticker=ticker,
            strategy_id=APPROVED_BREAKOUT_STRATEGY_ID,
            strategy_version=APPROVED_BREAKOUT_STRATEGY_VERSION,
            sector="Industrials",
            score=Decimal("2.5"),
            entry=Decimal("20"),
            stop=Decimal("19"),
            target=Decimal("22"),
        )
        return AllocationDecision(
            candidate=candidate,
            global_rank=rank,
            sector_rank=rank,
            normalized_score=Decimal("1"),
            risk_fraction=Decimal("0.05"),
            selected=True,
            reason="selected",
        )

    option_allocation = allocation(option_ticker, 1)
    stock_allocation = allocation(stock_ticker, 2)
    chain_snapshot_id = f"ocs_{uuid.uuid4().hex}"
    option_decision = InstrumentDecision(
        candidate_id=option_allocation.candidate.candidate_id,
        ticker=option_ticker,
        decision_at=decision_at,
        chain_snapshot_id=chain_snapshot_id,
        selector_version="unit-selector-v1",
        expression="long_call",
        max_loss=Decimal("400"),
        risk_budget=Decimal("500"),
        option_contracts=2,
        underlying_quantity=None,
        long_leg={"symbol": f"{option_ticker}991231C00020000", "ask": "2.00"},
        short_leg=None,
        fallback_reasons=(),
    )
    stock_decision = InstrumentDecision(
        candidate_id=stock_allocation.candidate.candidate_id,
        ticker=stock_ticker,
        decision_at=decision_at,
        chain_snapshot_id=None,
        selector_version="unit-selector-v1",
        expression="underlying_stock_fallback",
        max_loss=Decimal("500"),
        risk_budget=Decimal("500"),
        option_contracts=0,
        underlying_quantity=Decimal("500"),
        long_leg=None,
        short_leg=None,
        fallback_reasons=("option_chain_unavailable",),
    )

    with test_connection() as conn:
        seed_default_strategies(conn)
        conn.execute(
            """UPDATE strategies SET status='approved',
                      metadata=coalesce(metadata,'{}'::jsonb) ||
                        '{"approval_scope":"paper_only_no_live_execution", "paper_recommendation_approval":true}'::jsonb
                 WHERE name=%s""",
            (APPROVED_BREAKOUT_STRATEGY_ID,),
        )
        conn.execute(
            """INSERT INTO option_chain_snapshots(
                   snapshot_id,ticker,provider,source_url,fetched_at,market_at,
                   available_at,payload_sha256,chain)
               VALUES (%s,%s,'unit-read-only','https://example.invalid/read-only',
                       %s,%s,%s,%s,'[]'::jsonb)""",
            (chain_snapshot_id, option_ticker, decision_at, decision_at,
             decision_at, "a" * 64),
        )
        evaluation_id = conn.execute(
            """INSERT INTO option_structure_evaluations(
                   ticker,signal_dt,strategy_name,underlying_price,technical_target,
                   fetched_at,source,chain,evaluation,selected_structure,snapshot_id,
                   decision_at)
               VALUES (%s,%s,%s,20,22,%s,'unit-read-only','[]'::jsonb,
                       %s::jsonb,'long_call',%s,%s) RETURNING id""",
            (option_ticker, signal_dt, APPROVED_BREAKOUT_STRATEGY_ID,
             decision_at, json.dumps({"selected": {
                 "structure": "long_call",
                 "long_leg": option_decision.long_leg,
                 "short_leg": None,
             }}), chain_snapshot_id, decision_at),
        ).fetchone()[0]
        mismatched_decision = InstrumentDecision(
            candidate_id=option_allocation.candidate.candidate_id,
            ticker=option_ticker,
            decision_at=decision_at,
            chain_snapshot_id=chain_snapshot_id,
            selector_version="unit-selector-v1",
            expression="long_call",
            max_loss=Decimal("400"),
            risk_budget=Decimal("500"),
            option_contracts=2,
            underlying_quantity=None,
            long_leg={"symbol": f"{option_ticker}991231C00025000", "ask": "2.00"},
            short_leg=None,
            fallback_reasons=(),
        )
        with pytest.raises(ValueError, match="legs do not match"):
            write_pivot_instrument_recommendations(
                conn,
                recommendations=[PivotInstrumentRecommendation(
                    run_id, option_allocation, mismatched_decision, evaluation_id
                )],
                signal_dt=signal_dt,
                dry_run=False,
            )
        recommendations = [
            PivotInstrumentRecommendation(run_id, option_allocation, option_decision, evaluation_id),
            PivotInstrumentRecommendation(run_id, stock_allocation, stock_decision, None),
        ]

        first = write_pivot_instrument_recommendations(
            conn, recommendations=recommendations, signal_dt=signal_dt, dry_run=False
        )
        second = write_pivot_instrument_recommendations(
            conn, recommendations=recommendations, signal_dt=signal_dt, dry_run=False
        )
        rows = conn.execute(
            """SELECT r.ticker,r.recommendation_type,r.status,r.notes,
                      pt.instrument,pt.notes
                 FROM recommendations r JOIN paper_trades pt
                   ON pt.recommendation_id=r.id::text
                WHERE r.ticker=ANY(%s) ORDER BY r.ticker""",
            ([option_ticker, stock_ticker],),
        ).fetchall()

    assert first.inserted == 2
    assert first.paper_trades_inserted == 2
    assert second.inserted == 0
    assert second.paper_trades_inserted == 0
    assert [row[1] for row in rows] == ["long_call", "underlying_stock_fallback"]
    assert all(row[2] == "paper_logged" for row in rows)
    option_notes = rows[0][3]
    assert option_notes["candidate_id"] == str(option_allocation.candidate.candidate_id)
    assert option_notes["allocation"]["global_rank"] == 1
    assert option_notes["option_evaluation_id"] == evaluation_id
    assert option_notes["option_chain_snapshot_id"] == chain_snapshot_id
    assert option_notes["max_loss"] == "400"
    assert rows[0][4] == "long_call"
    assert rows[1][3]["fallback_reasons"] == ["option_chain_unavailable"]
    assert rows[1][4] == "underlying_stock_fallback"
    assert all(row[3]["paper_only"] is True for row in rows)
    assert all(row[3]["no_live_execution"] is True for row in rows)
    assert all(row[3]["broker_order_submitted"] is False for row in rows)
    assert all(row[5]["broker_order_submitted"] is False for row in rows)


def test_pivot_writer_rejects_unbound_option_evaluation_before_writing():
    from instrument_decision import InstrumentDecision
    from portfolio_allocator import AllocationDecision, PortfolioCandidate
    from recommendation_writer import PivotInstrumentRecommendation
    from setup_evaluators import APPROVED_BREAKOUT_STRATEGY_ID, APPROVED_BREAKOUT_STRATEGY_VERSION

    candidate = PortfolioCandidate(
        candidate_id=uuid.uuid4(), universe_snapshot_id=uuid.uuid4(), ticker="ZZBIND",
        strategy_id=APPROVED_BREAKOUT_STRATEGY_ID,
        strategy_version=APPROVED_BREAKOUT_STRATEGY_VERSION, sector="Technology",
        score=Decimal("1"), entry=Decimal("10"), stop=Decimal("9"), target=Decimal("12"),
    )
    allocation = AllocationDecision(
        candidate, 1, 1, Decimal("1"), Decimal("0.05"), True, "selected"
    )
    decision = InstrumentDecision(
        candidate.candidate_id, candidate.ticker,
        datetime(2099, 4, 4, tzinfo=timezone.utc), "ocs_missing", "unit-v1",
        "long_call", Decimal("100"), Decimal("500"), 1, None,
        {"symbol": "ZZBIND991231C00010000", "ask": "1.00"}, None, (),
    )

    with pytest.raises(ValueError, match="option_evaluation_id"):
        PivotInstrumentRecommendation(uuid.uuid4(), allocation, decision, None)
