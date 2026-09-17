from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
import json
import threading
import uuid

import pytest

from test_db import provision_test_database, resolve_test_dsn


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
