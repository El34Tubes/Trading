import json
import sqlite3

import wolfy_scanner


def ranked_fixture():
    leader_metrics = {
        'date': '2026-06-03', 'close': 100, 'r5': 4, 'r20': 12, 'r60': 20,
        'vs20': 4, 'vs50': 8, 'atr': 3, 'avgvol': 5_000_000, 'hi20': 101, 'lo20': 80,
        'volume_surge_1d_20': 2.5, 'volume_surge_5d_20': 1.7, 'volume_surge_1d_50': 2.2,
        'volume_surge_5d_50': 1.5, 'breakout_20d_pct': 1.2, 'trend_regime': 'bull_50_200',
        'atr_pct': 3.0, 'squeeze_ratio': 0.7, 'squeeze_flag': 1, 'gap_reversal_flag': 'none',
        'extension_penalty': 0, 'liquidity_spread_proxy': 0.08, 'rs_spy_20': 10, 'rs_qqq_20': 7,
        'rank_reasons': 'RS+10.0 vs SPY; volume surge; 20d breakout +1.2%; squeeze',
    }
    thin_metrics = dict(leader_metrics, avgvol=200_000, liquidity_spread_proxy=1.4)
    stale_metrics = dict(leader_metrics, date='2026-05-20')
    return [
        (42.0, 'LEADER', leader_metrics),
        (41.0, 'THIN', thin_metrics),
        (40.0, 'STALE', stale_metrics),
    ]


def test_create_alpha_leads_from_scanner_anomalies_filters_and_persists_handoffs(tmp_path):
    db = tmp_path / 'wolfy.db'

    result = wolfy_scanner.create_alpha_leads_from_scan(
        ranked_fixture(),
        db_path=db,
        run_id=7,
        as_of_date='2026-06-03',
        limit=5,
        create_postgres_tasks=False,
    )

    assert result['leads_seen'] == 1
    assert result['leads_upserted'] == 1
    assert result['handoffs_seen'] == 1

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    leads = con.execute('SELECT * FROM alpha_leads ORDER BY ticker').fetchall()
    assert [row['ticker'] for row in leads] == ['LEADER']
    lead = leads[0]
    assert lead['lead_type'] == 'scanner_anomaly_breakout'
    assert lead['status'] == 'needs_research'
    assert 'watch-only' in lead['next_research_question'].lower()
    assert 'recommendation' not in lead['status']
    payload = json.loads(lead['raw_payload_json'])
    assert payload['signal'] == 'breakout'
    assert payload['risk_flags'] == ['watch_only_no_catalyst']
    assert payload['scanner_run_id'] == 7

    evidence = con.execute('SELECT evidence_type, quote_or_fact FROM alpha_lead_evidence WHERE lead_id=?', (lead['id'],)).fetchall()
    assert len(evidence) == 1
    assert evidence[0]['evidence_type'] == 'scanner_result'
    assert 'volume_surge' in evidence[0]['quote_or_fact']

    handoff = con.execute('SELECT target_agent, task_type, question FROM alpha_handoffs WHERE lead_id=?', (lead['id'],)).fetchone()
    assert handoff['target_agent'] == 'Jonah'
    assert handoff['task_type'] == 'scanner_alpha_research'
    assert 'LEADER' in handoff['question']
    con.close()


def test_persist_scan_expanded_universe_creates_alpha_lead_handoffs(tmp_path, monkeypatch):
    db = tmp_path / 'wolfy.db'
    monkeypatch.setattr(wolfy_scanner, 'persist_scanner_run_postgres', lambda *args, **kwargs: 123)

    run_id = wolfy_scanner.persist_scan(ranked_fixture()[:1], db, 'expanded')

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    assert run_id == 1
    assert con.execute('SELECT COUNT(*) FROM scanner_results').fetchone()[0] == 1
    assert con.execute('SELECT COUNT(*) FROM alpha_leads').fetchone()[0] == 1
    assert con.execute('SELECT COUNT(*) FROM alpha_handoffs').fetchone()[0] == 1
    con.close()


def test_create_alpha_leads_from_scanner_anomalies_dedupes_by_ticker_signal_and_data_date(tmp_path):
    db = tmp_path / 'wolfy.db'

    first = wolfy_scanner.create_alpha_leads_from_scan(
        ranked_fixture(), db_path=db, run_id=7, as_of_date='2026-06-03', create_postgres_tasks=False
    )
    second = wolfy_scanner.create_alpha_leads_from_scan(
        ranked_fixture(), db_path=db, run_id=8, as_of_date='2026-06-03', create_postgres_tasks=False
    )

    assert first['leads_upserted'] == 1
    assert second['leads_upserted'] == 1
    con = sqlite3.connect(db)
    assert con.execute('SELECT COUNT(*) FROM alpha_leads').fetchone()[0] == 1
    assert con.execute('SELECT COUNT(*) FROM alpha_lead_evidence').fetchone()[0] == 1
    assert con.execute('SELECT COUNT(*) FROM alpha_handoffs').fetchone()[0] == 1
    lead_payload = json.loads(con.execute('SELECT raw_payload_json FROM alpha_leads').fetchone()[0])
    assert lead_payload['scanner_run_id'] == 8
    con.close()
