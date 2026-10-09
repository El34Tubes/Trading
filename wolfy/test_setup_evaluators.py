from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from daily_evaluation_ledger import (
    DailyRunIdentity,
    GateEvaluation,
    create_daily_run,
    upsert_gate_evaluation,
)
from setup_evaluators import (
    SetupCandidate,
    SetupContractError,
    SetupEvaluation,
    persist_setup_candidate,
)
from test_db import test_connection

UTC = timezone.utc
DECISION_AT = datetime(2099, 3, 2, 22, tzinfo=UTC)
SNAPSHOT_ID = uuid.UUID("5c7ef9dc-810f-4cc2-83c8-a58754eaef9b")


def _evaluation(**overrides) -> SetupEvaluation:
    values = {
        "ticker": "ZZSETUP",
        "strategy_id": "mid_small_breakout",
        "strategy_version": "1.0.0",
        "sector": "Industrials",
        "passed": True,
        "reason_code_version": 2,
        "reason_codes": ("passed",),
        "terminal_reason": "passed",
        "evaluated_at": DECISION_AT,
        "metrics": {"atr": "1.25"},
        "gate_facts": {"trend": {"passed": True}},
        "source_fingerprint": "a" * 64,
        "provenance": {"feature_row_id": 42},
        "score_components": {"relative_strength": "0.40", "volume": "0.60"},
    }
    values.update(overrides)
    return SetupEvaluation(**values)


def _candidate(**overrides) -> SetupCandidate:
    values = {
        "run_id": uuid.UUID("5e6093b5-9de7-4fe2-9bdb-b21c715a7344"),
        "universe_snapshot_id": SNAPSHOT_ID,
        "gate_evaluation_id": 1,
        "ticker": "ZZSETUP",
        "strategy_id": "mid_small_breakout",
        "strategy_version": "1.0.0",
        "sector": "Industrials",
        "score": "1.00",
        "score_components": {"relative_strength": "0.40", "volume": "0.60"},
        "entry": "10.00",
        "stop": "9.00",
        "target": "12.00",
        "facts_hash": "b" * 64,
    }
    values.update(overrides)
    return SetupCandidate(**values)


def test_setup_contract_is_immutable_and_normalizes_finite_decimals():
    evaluation = _evaluation()
    candidate = _candidate()

    assert evaluation.score_components == {
        "relative_strength": Decimal("0.40"),
        "volume": Decimal("0.60"),
    }
    assert candidate.score == Decimal("1.00")
    assert candidate.entry == Decimal("10.00")
    with pytest.raises((AttributeError, TypeError)):
        candidate.score = Decimal("2")  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        {"ticker": "zzsetup"},
        {"strategy_id": " strategy "},
        {"strategy_version": ""},
        {"sector": "\tIndustrials"},
        {"passed": 1},
        {"reason_code_version": 1, "reason_codes": ("reclaim_not_confirmed",), "terminal_reason": "reclaim_not_confirmed", "passed": False},
        {"reason_codes": ("passed", "trend_failed")},
        {"evaluated_at": datetime(2099, 3, 2, 22)},
        {"metrics": []},
        {"gate_facts": {"bad": float("nan")}},
        {"score_components": {}},
        {"score_components": {"component": True}},
        {"score_components": {"component": float("inf")}},
        {"source_fingerprint": "short"},
    ],
)
def test_setup_evaluation_fails_closed_on_malformed_contract(overrides):
    with pytest.raises(SetupContractError):
        _evaluation(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"run_id": "not-a-uuid"},
        {"universe_snapshot_id": "not-a-uuid"},
        {"gate_evaluation_id": True},
        {"gate_evaluation_id": 0},
        {"ticker": " zzsetup "},
        {"strategy_id": ""},
        {"strategy_version": "v1\n"},
        {"sector": ""},
        {"score": True},
        {"score": "NaN"},
        {"score_components": {"volume": "0.59", "relative_strength": "0.40"}},
        {"entry": 0},
        {"stop": "10.00"},
        {"target": "10.00"},
        {"facts_hash": "B" * 64},
    ],
)
def test_setup_candidate_fails_closed_on_malformed_or_nondeterministic_values(overrides):
    with pytest.raises(SetupContractError):
        _candidate(**overrides)


def _seed_persistence_contract(conn):
    conn.execute(
        """INSERT INTO recommendation_universe_snapshots(
               snapshot_id,signal_dt,decision_at,policy_version,source_fingerprint,
               included_count,excluded_count)
             VALUES (%s,%s,%s,'mid-small-v1',%s,1,0)
             ON CONFLICT (snapshot_id) DO NOTHING""",
        (SNAPSHOT_ID, date(2099, 3, 2), DECISION_AT, "c" * 64),
    )
    conn.execute(
        """INSERT INTO recommendation_universe_members(
               snapshot_id,ticker,sector,included,reason_codes,identity_observation_ids,
               risk_observation_ids,denylist_observation_ids,market_cap_observation_id,
               market_cap,bar_observation_ids,close,average_dollar_volume,
               source_evidence,facts_hash)
             VALUES (%s,'ZZSETUP','Industrials',true,
                     ARRAY['eligible_mid_small_us_common_stock'],ARRAY['identity-1'],
                     ARRAY[]::text[],ARRAY[]::text[],'cap-1',1000000000,
                     ARRAY['bar-1'],10,10000000,'{}'::jsonb,%s)
             ON CONFLICT (snapshot_id,ticker) DO NOTHING""",
        (SNAPSHOT_ID, "d" * 64),
    )
    run = create_daily_run(
        conn,
        DailyRunIdentity(
            target_session=date(2099, 3, 2),
            evaluator_name="multi-strategy-setup-contract",
            evaluator_version="1.0.0",
            universe_snapshot_id=str(SNAPSHOT_ID),
        ),
    )
    gate_id = upsert_gate_evaluation(
        conn,
        run.run_id,
        GateEvaluation(
            ticker="ZZSETUP",
            strategy="mid_small_breakout",
            passed=True,
            reason_code_version=2,
            reason_codes=("passed",),
            terminal_reason="passed",
            evaluated_at=DECISION_AT,
            metrics={},
            gate_facts={"trend": {"passed": True}},
            source_fingerprint="e" * 64,
            provenance={"strategy_version": "1.0.0"},
        ),
    )
    return run, gate_id


def test_candidate_persists_once_linked_to_run_snapshot_strategy_and_terminal_gate():
    with test_connection() as conn:
        run, gate_id = _seed_persistence_contract(conn)
        candidate = _candidate(run_id=run.run_id, gate_evaluation_id=gate_id)

        first = persist_setup_candidate(conn, candidate)
        second = persist_setup_candidate(conn, candidate)
        row = conn.execute(
            """SELECT run_id,universe_snapshot_id,gate_evaluation_id,ticker,
                      strategy_id,strategy_version,sector,score,score_components,
                      entry,stop,target,facts_hash
                 FROM setup_candidates WHERE candidate_id=%s""",
            (first,),
        ).fetchone()

        assert first == second
        assert row[:7] == (
            run.run_id,
            SNAPSHOT_ID,
            gate_id,
            "ZZSETUP",
            "mid_small_breakout",
            "1.0.0",
            "Industrials",
        )
        assert row[7] == Decimal("1.00")
        assert row[8] == {"relative_strength": "0.40", "volume": "0.60"}
        assert row[9:] == (Decimal("10.00"), Decimal("9.00"), Decimal("12.00"), "b" * 64)


def test_candidate_rejects_run_snapshot_gate_or_member_binding_mismatch():
    with test_connection() as conn:
        run, gate_id = _seed_persistence_contract(conn)
        valid = _candidate(run_id=run.run_id, gate_evaluation_id=gate_id)

        for changed in (
            replace(valid, universe_snapshot_id=uuid.uuid4()),
            replace(valid, gate_evaluation_id=gate_id + 1),
            replace(valid, ticker="ZZOTHER"),
            replace(valid, strategy_id="other_strategy"),
            replace(valid, sector="Technology"),
        ):
            with pytest.raises(SetupContractError):
                persist_setup_candidate(conn, changed)
        assert conn.execute("SELECT count(*) FROM setup_candidates WHERE run_id=%s", (run.run_id,)).fetchone() == (0,)


def test_candidate_requires_a_passed_terminal_gate_and_conflicting_rerun_is_rejected():
    with test_connection() as conn:
        run, gate_id = _seed_persistence_contract(conn)
        candidate = _candidate(run_id=run.run_id, gate_evaluation_id=gate_id)
        persist_setup_candidate(conn, candidate)

        with pytest.raises(SetupContractError, match="immutable"):
            persist_setup_candidate(conn, replace(candidate, target=Decimal("13.00")))

        conn.execute(
            """UPDATE setup_gate_evaluations
                  SET passed=false,reason_codes=ARRAY['trend_failed'],
                      terminal_reason='trend_failed',failed_gates='[\"trend_failed\"]'::jsonb
                WHERE id=%s""",
            (gate_id,),
        )
        with pytest.raises(SetupContractError, match="passed terminal gate"):
            persist_setup_candidate(conn, candidate)
