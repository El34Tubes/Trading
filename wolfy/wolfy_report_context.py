#!/usr/bin/env python3
"""Print context for Wolfy's twice-daily trade-research report and start a Postgres run ledger row."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
import sqlite3
import subprocess
from zoneinfo import ZoneInfo

try:
    import psycopg
except Exception:
    psycopg = None

from wolfy_agent_coordination import connect, finish_agent_run, start_agent_run
from insider_buying import ensure_insider_tables
from eod_governance import print_eod_governance

DB = Path('/root/.hermes/wolfy/wolfy.db')
PG_DSN = 'dbname=wolfy user=root host=/var/run/postgresql'
CLI = Path('/root/.hermes/wolfy/wolfy_agent_cli.py')
SYNC = Path('/root/.hermes/wolfy/sync_sqlite_to_postgres.py')
SCANNER = Path('/root/.hermes/wolfy/wolfy_scanner.py')
NY_TZ = ZoneInfo('America/New_York')


def sync_postgres() -> str:
    try:
        return subprocess.check_output(['python3', str(SYNC)], text=True, stderr=subprocess.STDOUT, timeout=45).strip()
    except Exception as e:
        return f'failed: {type(e).__name__}: {e}'


def run_scanner_before_report(timeout: int = 180) -> str:
    """Run the Yahoo daily scanner so report context cannot use an old run silently."""
    try:
        output = subprocess.check_output(
            ['python3', str(SCANNER)],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        tail = output.strip().splitlines()[-1:] or ['no output']
        return 'ok: ' + tail[0]
    except Exception as e:
        return f'failed: {type(e).__name__}: {e}'


def _previous_business_day(day: dt.date) -> dt.date:
    day = day - dt.timedelta(days=1)
    while day.weekday() >= 5:
        day = day - dt.timedelta(days=1)
    return day


def latest_available_market_close_date(now: dt.datetime | None = None) -> dt.date:
    """Return the latest expected US market close date using NY weekday/4pm logic.

    This intentionally avoids pretending to know holiday sessions without a market-calendar
    dependency. The gate is still conservative for normal report times: 8am ET expects the
    prior business day's daily bars, and 8pm ET expects same-day bars.
    """
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    now_et = now.astimezone(NY_TZ)
    today = now_et.date()
    if today.weekday() >= 5:
        return _previous_business_day(today)
    if now_et.time() < dt.time(16, 0):
        return _previous_business_day(today)
    return today


def latest_available_market_close_datetime(now: dt.datetime | None = None) -> dt.datetime:
    close_date = latest_available_market_close_date(now)
    return dt.datetime.combine(close_date, dt.time(16, 0), tzinfo=NY_TZ).astimezone(dt.timezone.utc)


def _parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_sqlite_utc_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).replace('T', ' ')
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def get_scanner_freshness(con: sqlite3.Connection, now: dt.datetime | None = None) -> dict:
    expected_close = latest_available_market_close_date(now)
    expected_close_ts = latest_available_market_close_datetime(now)
    row = con.execute(
        """
        SELECT r.id AS latest_run_id,
               r.run_time AS latest_run_time,
               COUNT(sr.id) AS candidate_count,
               MAX(sr.data_date) AS latest_data_date
        FROM scanner_runs r
        LEFT JOIN scanner_results sr ON sr.run_id = r.id
        WHERE r.id = (SELECT MAX(id) FROM scanner_runs)
        GROUP BY r.id, r.run_time
        """
    ).fetchone()
    status = {
        'status': 'scanner_stale',
        'action_gate': 'no_trade',
        'latest_run_id': None,
        'latest_run_time': None,
        'latest_data_date': None,
        'expected_market_close_date': expected_close.isoformat(),
        'expected_market_close_timestamp_utc': expected_close_ts.isoformat(),
        'candidate_count': 0,
        'reason': 'no scanner run found',
    }
    if row is None:
        return status

    candidate_count = int(row['candidate_count'] or 0)
    latest_data_date = _parse_date(row['latest_data_date'])
    latest_run_time = _parse_sqlite_utc_datetime(row['latest_run_time'])
    status.update(
        latest_run_id=row['latest_run_id'],
        latest_run_time=row['latest_run_time'],
        latest_data_date=row['latest_data_date'],
        candidate_count=candidate_count,
    )
    if candidate_count <= 0 or latest_data_date is None:
        status['reason'] = 'latest scanner run produced no usable scanner_results rows'
        return status
    if latest_data_date < expected_close:
        status['reason'] = f'latest scanner data_date {latest_data_date.isoformat()} is older than expected market close {expected_close.isoformat()}'
        return status
    if latest_run_time is None:
        status['reason'] = 'latest scanner run_time could not be parsed'
        return status
    if latest_run_time < expected_close_ts:
        status['reason'] = f'latest scanner run_time {latest_run_time.isoformat()} is before expected market close timestamp {expected_close_ts.isoformat()}'
        return status

    status['status'] = 'fresh'
    status['action_gate'] = 'recommendations_allowed'
    status['reason'] = f'latest scanner data_date covers expected market close {expected_close.isoformat()}'
    return status


def format_scanner_freshness(status: dict) -> str:
    line = (
        'Scanner freshness: '
        f"status={status['status']} "
        f"action_gate={status['action_gate']} "
        f"latest_run_id={status['latest_run_id']} "
        f"latest_run_time={status['latest_run_time']} "
        f"latest_data_date={status['latest_data_date']} "
        f"expected_market_close_date={status['expected_market_close_date']} "
        f"expected_market_close_timestamp_utc={status['expected_market_close_timestamp_utc']} "
        f"candidate_count={status['candidate_count']} "
        f"reason={status['reason']}"
    )
    if status.get('action_gate') == 'no_trade':
        line += ' -- Wolfy must not create actionable recommendations; report scanner_stale/no-trade until fresh scanner data exists.'
    return line


def start_run(candidate_count: int) -> int:
    with connect(PG_DSN) as conn:
        return start_agent_run(
            conn,
            agent_name='Wolfy',
            role='analyst_recommender',
            job_id='wolfy-twice-daily-report',
            status='started',
            summary=f'Wolfy twice-daily context loaded with {candidate_count} scanner candidates.',
        )


def main() -> None:
    scanner_refresh = run_scanner_before_report()
    ensure_insider_tables(DB)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    counts = {t: con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ['reports','recommendations','paper_trades','scanner_runs','scanner_results','strategy_rules','knowledge_notes','insider_transactions','insider_leads']}
    scanner = con.execute(
        """
        SELECT sr.* FROM scanner_results sr
        JOIN (SELECT max(id) AS run_id FROM scanner_runs) latest ON latest.run_id=sr.run_id
        ORDER BY sr.score DESC LIMIT 20
        """
    ).fetchall()
    scanner_freshness = get_scanner_freshness(con)
    rules = con.execute("SELECT rule_name, rule_type, description FROM strategy_rules WHERE enabled=1 ORDER BY id DESC LIMIT 18").fetchall()
    insider_leads = con.execute(
        """
        SELECT ticker, evaluated_at, status, score, recommended_use, open_market_buy_count,
               distinct_buyers, total_buy_value, role_quality, materiality_label,
               liquidity_label, risk_flags, positive_factors
        FROM insider_leads
        WHERE status='qualified'
        ORDER BY evaluated_at DESC, score DESC LIMIT 8
        """
    ).fetchall()
    recs = con.execute("SELECT * FROM recommendations ORDER BY timestamp DESC, id DESC LIMIT 10").fetchall()
    con.close()

    run_id = start_run(len(scanner))
    print('Wolfy twice-daily report context')
    print(f'SQLite DB={DB}')
    print_eod_governance()
    print(f'Pre-report scanner run: {scanner_refresh}')
    print(format_scanner_freshness(scanner_freshness))
    print('SQLite counts: ' + ', '.join(f'{k}={v}' for k, v in counts.items()))
    print(f'Postgres sync: {sync_postgres()}')
    print(f'Postgres agent run: AGENT_RUN_ID={run_id}')
    print(f'After report/recommendation DB writes, run: python3 {CLI} run-finish --run-id {run_id} --status completed --records-created <N> --summary "<Wolfy report/recommendation summary>"')
    print(f'If blocked, run: python3 {CLI} run-finish --run-id {run_id} --status blocked --error-message "<specific blocker>" --summary "<specific blocker>"')
    print('User constraints: Robinhood-tradable only; no shorts; options allowed but defined-risk preferred; max 3 concurrent paper positions; $5,000 paper account; stops required; PDT-aware; avoid foreign manipulation/government-interference risk.')
    print('Insider-buying discipline: SEC Form 4 open-market buys can support a thesis only; ignore awards/exercises/conversions/sales as bullish evidence and require independent setup, liquidity, fundamentals, Yang technicals, and Sentinel review.')
    print('Authority: Wolfy may create pending_review recommendations only from EOD closing-data/deterministic-signal support; Wolfy does not self-approve; Sentinel reviews next, Yang handles technical entry/exit after alpha is identified.')
    if scanner:
        print('Latest scanner candidates:')
        for s in scanner:
            print(f"- {s['ticker']}: score={s['score']} close={s['close']} r5={s['r5']} r20={s['r20']} r60={s['r60']} vs20={s['vs20']} vs50={s['vs50']} atr={s['atr']} avg_vol={s['avg_volume']} high20={s['high20']} low20={s['low20']} liq={s['liquidity_pass']}")
    else:
        print('Latest scanner candidates: none; run scanner before making fresh ticker claims.')
    if recs:
        print('Recent recommendations:')
        for r in recs:
            print(f"- id={r['id']} {r['ticker']} {r['action']} status={r['status']} confidence={r['confidence']} thesis={r['thesis']}")
    if insider_leads:
        print('Qualified insider-buying support leads (not standalone triggers):')
        for lead in insider_leads:
            print(f"- {lead['ticker']}: score={lead['score']} use={lead['recommended_use']} buys={lead['open_market_buy_count']} buyers={lead['distinct_buyers']} value={lead['total_buy_value']} role={lead['role_quality']} materiality={lead['materiality_label']} liquidity={lead['liquidity_label']} positives={lead['positive_factors']} risks={lead['risk_flags']}")
    print('Active strategy/risk rules:')
    for r in rules:
        print(f"- {r['rule_name']} [{r['rule_type']}]: {r['description']}")
    if psycopg is not None:
        try:
            with psycopg.connect(PG_DSN) as pg, pg.cursor() as cur:
                cur.execute("SELECT status, count(*) FROM agent_runs WHERE agent_name='Wolfy' GROUP BY status ORDER BY status")
                rows = cur.fetchall()
                if rows:
                    print('Postgres Wolfy agent_runs: ' + ', '.join(f'{s}={c}' for s, c in rows))
        except Exception as e:
            print(f'Postgres run table unavailable: {type(e).__name__}: {e}')
    if scanner_freshness.get('action_gate') == 'no_trade':
        print('Freshness gate: scanner_stale/no-trade. Do not create actionable recommendations or pending_review trade tickets from stale scanner data.')
    print('Required output: concise report separating FACT vs JUDGMENT. If scanner freshness action_gate=no_trade or current context is not EOD closing-data backed, say scanner_stale/no-trade/EOD-only and create no actionable recommendations. If creating actionable trade ideas, insert rows into SQLite recommendations with status=pending_review only when approved-strategy plus deterministic signal/setup support exists; complete the Postgres run with records_created count. If no actionable setup, say watchlist/no-trade and still finish the run.')


if __name__ == '__main__':
    main()
