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
from lead_promotion_gate import promote_alpha_leads
from wolfy_postgres_pipeline import fallback_warning, latest_scanner_freshness

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


def _sqlite_scanner_freshness(con, expected_close: dt.date, expected_close_ts: dt.datetime) -> dict:
    """Compatibility scanner freshness for unit tests/legacy fixture DBs."""
    status = {
        'status': 'scanner_stale',
        'action_gate': 'no_trade',
        'latest_run_id': None,
        'latest_run_time': None,
        'latest_data_date': None,
        'expected_market_close_date': expected_close.isoformat(),
        'expected_market_close_timestamp_utc': expected_close_ts.isoformat(),
        'candidate_count': 0,
        'reason': 'no SQLite scanner run found',
    }
    row = con.execute(
        """
        SELECT sr.id, sr.run_time, max(res.data_date), count(res.id)
        FROM scanner_runs sr
        LEFT JOIN scanner_results res ON res.run_id = sr.id
        GROUP BY sr.id, sr.run_time
        ORDER BY sr.run_time DESC, sr.id DESC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return status
    status.update(
        latest_run_id=row[0],
        latest_run_time=row[1],
        latest_data_date=row[2],
        candidate_count=int(row[3] or 0),
    )
    latest_data_date = _parse_date(status['latest_data_date'])
    latest_run_time = _parse_sqlite_utc_datetime(status['latest_run_time'])
    if status['candidate_count'] <= 0 or latest_data_date is None:
        status['reason'] = 'latest SQLite scanner run produced no usable scanner_results rows'
        return status
    if latest_data_date < expected_close:
        status['reason'] = f'latest scanner data_date {latest_data_date.isoformat()} is older than expected market close {expected_close.isoformat()}'
        return status
    if latest_run_time is None:
        status['reason'] = 'latest SQLite scanner run_time could not be parsed'
        return status
    if latest_run_time < expected_close_ts:
        status['reason'] = f'latest scanner run_time {latest_run_time.isoformat()} is before expected market close timestamp {expected_close_ts.isoformat()}'
        return status
    status['status'] = 'fresh'
    status['action_gate'] = 'recommendations_allowed'
    status['reason'] = f'latest SQLite scanner data_date covers expected market close {expected_close.isoformat()}'
    return status


def get_scanner_freshness(con=None, now: dt.datetime | None = None) -> dict:
    """Postgres scanner freshness gate, with explicit SQLite fixture compatibility."""
    expected_close = latest_available_market_close_date(now)
    expected_close_ts = latest_available_market_close_datetime(now)
    if con is not None:
        return _sqlite_scanner_freshness(con, expected_close, expected_close_ts)
    status = {
        'status': 'scanner_stale',
        'action_gate': 'no_trade',
        'latest_run_id': None,
        'latest_run_time': None,
        'latest_data_date': None,
        'expected_market_close_date': expected_close.isoformat(),
        'expected_market_close_timestamp_utc': expected_close_ts.isoformat(),
        'candidate_count': 0,
        'reason': 'no Postgres scanner run found',
    }
    try:
        pg = latest_scanner_freshness()
    except Exception as e:
        status['reason'] = f'Postgres scanner freshness unavailable: {type(e).__name__}: {e}'
        return status
    status.update(
        latest_run_id=pg.get('latest_run_id'),
        latest_run_time=pg.get('latest_run_time'),
        latest_data_date=pg.get('latest_data_date'),
        candidate_count=int(pg.get('candidate_count') or 0),
    )
    latest_data_date = _parse_date(status['latest_data_date'])
    latest_run_time = _parse_sqlite_utc_datetime(status['latest_run_time'])
    if status['candidate_count'] <= 0 or latest_data_date is None:
        status['reason'] = 'latest Postgres scanner run produced no usable scanner_results rows'
        return status
    if latest_data_date < expected_close:
        status['reason'] = f'latest scanner data_date {latest_data_date.isoformat()} is older than expected market close {expected_close.isoformat()}'
        return status
    if latest_run_time is None:
        status['reason'] = 'latest Postgres scanner run_time could not be parsed'
        return status
    if latest_run_time < expected_close_ts:
        status['reason'] = f'latest scanner run_time {latest_run_time.isoformat()} is before expected market close timestamp {expected_close_ts.isoformat()}'
        return status
    status['status'] = 'fresh'
    status['action_gate'] = 'recommendations_allowed'
    status['reason'] = f'latest Postgres scanner data_date covers expected market close {expected_close.isoformat()}'
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


def run_promotion_gate_dry_run(db_path: str | Path = DB, limit: int = 12) -> dict:
    """Evaluate alpha leads without writes so the report can see promotion readiness."""
    try:
        return promote_alpha_leads(db_path, dry_run=True, limit=limit)
    except Exception as e:
        return {
            'summary': {'evaluated': 0, 'pending_review': 0, 'watch_only': 0, 'live_writes': 0, 'dry_run': True},
            'decisions': [],
            'error': f'{type(e).__name__}: {e}',
        }


def format_promotion_gate_result(result: dict) -> list[str]:
    summary = result.get('summary') or {}
    lines = [
        'Promotion gate dry-run: '
        f"evaluated={summary.get('evaluated', 0)} "
        f"pending_review={summary.get('pending_review', 0)} "
        f"watch_only={summary.get('watch_only', 0)} "
        f"live_writes={summary.get('live_writes', 0)} "
        f"dry_run={summary.get('dry_run', True)}"
    ]
    if result.get('error'):
        lines.append(f"Promotion gate error: {result['error']} -- report no trade until the gate can be evaluated.")
    decisions = result.get('decisions') or []
    if int(summary.get('pending_review') or 0) <= 0:
        if decisions:
            lines.append('Promotion gate: no complete ticket/no-trade; report why each lead remains watch-only instead of forcing a trade.')
        else:
            lines.append('Promotion gate: no evaluated leads/no-trade; scanner leads remain leads until a complete promotion ticket exists.')
    else:
        lines.append('Promotion gate: complete ticket(s) found; only live-write through lead_promotion_gate.py/recommendation_logger.py may create pending_review rows for Sentinel.')
    for decision in decisions[:8]:
        ticker = decision.get('ticker') or 'UNKNOWN'
        classification = decision.get('classification') or decision.get('target_status') or 'unknown'
        notes = decision.get('validation_notes') or []
        reason = '; '.join(str(n) for n in notes) if notes else 'complete ticket candidate'
        lines.append(f"- {ticker} {classification} reasons={reason}")
    return lines


def _recommendation_columns(con: sqlite3.Connection) -> set[str]:
    try:
        return {row[1] for row in con.execute('PRAGMA table_info(recommendations)').fetchall()}
    except sqlite3.Error:
        return set()


def get_recommendation_buckets(con: sqlite3.Connection, limit_per_bucket: int = 6) -> dict[str, list[sqlite3.Row]]:
    cols = _recommendation_columns(con)
    if not cols:
        return {'pending_review': [], 'sentinel_approved': [], 'watch_only': []}
    order_col = 'timestamp' if 'timestamp' in cols else ('created_at' if 'created_at' in cols else 'id')
    buckets = {
        'pending_review': ("lower(status) = 'pending_review'", 'ASC'),
        'sentinel_approved': ("lower(status) = 'approved'", 'DESC'),
        'watch_only': ("lower(status) IN ('watching','watch_only','watchlist_only')", 'DESC'),
    }
    result: dict[str, list[sqlite3.Row]] = {}
    for name, (where, direction) in buckets.items():
        result[name] = con.execute(
            f"SELECT * FROM recommendations WHERE {where} ORDER BY {order_col} {direction}, id {direction} LIMIT ?",
            (int(limit_per_bucket),),
        ).fetchall()
    return result


def _row_value(row: sqlite3.Row, key: str, default: str = '') -> str:
    try:
        value = row[key]
    except (KeyError, IndexError):
        value = default
    return '' if value is None else str(value)


def format_recommendation_bucket(name: str, rows: list[sqlite3.Row]) -> list[str]:
    headers = {
        'pending_review': 'Pending_review candidates awaiting Sentinel:',
        'sentinel_approved': 'Sentinel-approved paper candidates:',
        'watch_only': 'Watch-only ideas:',
    }
    lines = [headers.get(name, f'{name}:')]
    if not rows:
        lines.append('- none')
        return lines
    for r in rows:
        lines.append(
            f"- id={_row_value(r, 'id')} {_row_value(r, 'ticker')} "
            f"status={_row_value(r, 'status')} action={_row_value(r, 'action')} "
            f"setup={_row_value(r, 'setup_type')} entry={_row_value(r, 'entry_trigger') or _row_value(r, 'entry_zone')} "
            f"stop={_row_value(r, 'stop')} target={_row_value(r, 'target')} "
            f"rr={_row_value(r, 'risk_reward')} confidence={_row_value(r, 'confidence')} "
            f"thesis={_row_value(r, 'thesis')[:220]}"
        )
    return lines


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


def _pg_fetch_dicts(cur, sql: str, params: tuple = ()) -> list[dict]:
    cur.execute(sql, params)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def main() -> None:
    scanner_refresh = run_scanner_before_report()
    scanner_freshness = get_scanner_freshness(None)
    try:
        postgres_scanner_freshness = latest_scanner_freshness()
    except Exception as e:
        postgres_scanner_freshness = {'backend': 'postgres', 'status': 'unavailable', 'warning': fallback_warning('scanner_results', f'{type(e).__name__}: {e}')}

    counts: dict[str, int] = {}
    scanner: list[dict] = []
    rules: list[dict] = []
    insider_leads: list[dict] = []
    recommendation_buckets = {'pending_review': [], 'sentinel_approved': [], 'watch_only': []}
    alpha_summary = {'evaluated': 0, 'pending_review': 0, 'watch_only': 0, 'live_writes': 0, 'dry_run': True}

    with psycopg.connect(PG_DSN) as pg, pg.cursor() as cur:
        for table in ['recommendations','paper_trades','scanner_runs','scanner_results','strategy_rules','knowledge_chunks','alpha_leads','alpha_handoffs']:
            try:
                cur.execute(f'SELECT COUNT(*) FROM {table}')
                counts[table] = int(cur.fetchone()[0])
            except Exception:
                pg.rollback()
        scanner = _pg_fetch_dicts(cur, """
            SELECT sr.* FROM scanner_results sr
            JOIN (SELECT max(id) AS run_id FROM scanner_runs) latest ON latest.run_id=sr.run_id
            ORDER BY sr.score DESC LIMIT 20
        """)
        for status, bucket in [('pending_review','pending_review'), ('approved','sentinel_approved'), ('watch_only','watch_only')]:
            recommendation_buckets[bucket] = _pg_fetch_dicts(cur, """
                SELECT id, created_at, ticker, action, recommendation_type, status, thesis,
                       entry_trigger, stop, target, risk_reward, confidence
                FROM recommendations
                WHERE status=%s
                ORDER BY created_at DESC
                LIMIT 6
            """, (status,))
        try:
            rules = _pg_fetch_dicts(cur, """
                SELECT title AS rule_name, artifact_type AS rule_type, left(body, 260) AS description
                FROM agent_artifacts
                WHERE artifact_type='strategy_rule'
                ORDER BY updated_at DESC LIMIT 18
            """)
        except Exception:
            pg.rollback()
            rules = []
        try:
            insider_leads = _pg_fetch_dicts(cur, """
                SELECT ticker_symbols[1] AS ticker, updated_at AS evaluated_at, freshness AS status,
                       round((confidence*100)::numeric, 1) AS score, title AS recommended_use,
                       body AS positive_factors, '' AS risk_flags,
                       0 AS open_market_buy_count, 0 AS distinct_buyers, 0 AS total_buy_value,
                       '' AS role_quality, '' AS materiality_label, '' AS liquidity_label
                FROM agent_artifacts
                WHERE artifact_type='insider_buying_lead'
                ORDER BY updated_at DESC LIMIT 8
            """)
        except Exception:
            pg.rollback()
            insider_leads = []
        try:
            cur.execute("SELECT count(*) FILTER (WHERE complete_ticket), count(*) FILTER (WHERE status IN ('needs_research','watchlist','new')) FROM alpha_leads")
            pending, watch = cur.fetchone()
            alpha_summary.update(evaluated=counts.get('alpha_leads', 0), pending_review=int(pending or 0), watch_only=int(watch or 0))
        except Exception:
            pg.rollback()

    run_id = start_run(len(scanner))
    print('Wolfy twice-daily report context')
    print('Wolfy DB=Postgres primary; SQLite retired for live report context')
    print_eod_governance()
    print(f'Pre-report scanner run: {scanner_refresh}')
    print(f'Postgres scanner freshness: {postgres_scanner_freshness}')
    if postgres_scanner_freshness.get('warning'):
        print(postgres_scanner_freshness['warning'])
    print(format_scanner_freshness(scanner_freshness))
    print('Postgres counts: ' + ', '.join(f'{k}={v}' for k, v in counts.items()))
    print(f'Postgres agent run: AGENT_RUN_ID={run_id}')
    print('Promotion gate summary: ' + ' '.join(f'{k}={v}' for k, v in alpha_summary.items()))
    print(f'After report/recommendation DB writes, run: python3 {CLI} run-finish --run-id {run_id} --status completed --records-created <N> --summary "<Wolfy report/recommendation summary>"')
    print(f'If blocked, run: python3 {CLI} run-finish --run-id {run_id} --status blocked --error-message "<specific blocker>" --summary "<specific blocker>"')
    print('User constraints: Robinhood-tradable only; no shorts; options allowed but defined-risk preferred; max 3 concurrent paper positions; $5,000 paper account; stops required; PDT-aware; avoid foreign manipulation/government-interference risk.')
    print('Authority: Wolfy may create pending_review recommendations only from EOD closing-data/deterministic-signal support; Wolfy does not self-approve; Sentinel reviews next, Yang handles technical entry/exit after alpha is identified.')
    print('Report taxonomy: scanner leads are discovery only; promotion-gate complete tickets become pending_review recommendations for Sentinel; Sentinel-approved rows are paper-candidate inputs; watching/watch_only rows are explicitly non-actionable watch-only ideas.')
    for bucket_name in ('pending_review', 'sentinel_approved', 'watch_only'):
        for line in format_recommendation_bucket(bucket_name, recommendation_buckets[bucket_name]):
            print(line)
    if scanner:
        print('Latest scanner candidates:')
        for s in scanner:
            print(f"- {s['ticker']}: score={s['score']} close={s['close']} r5={s['r5']} r20={s['r20']} r60={s['r60']} vs20={s['vs20']} vs50={s['vs50']} atr={s['atr']} avg_vol={s['avg_volume']} high20={s['high20']} low20={s['low20']} liq={s['liquidity_pass']}")
    else:
        print('Latest scanner candidates: none; run scanner before making fresh ticker claims.')
    if insider_leads:
        print('Qualified insider-buying support leads (not standalone triggers):')
        for lead in insider_leads:
            print(f"- {lead['ticker']}: score={lead['score']} use={lead['recommended_use']} positives={str(lead['positive_factors'])[:240]} risks={lead['risk_flags']}")
    print('Active strategy/risk rules:')
    for r in rules:
        print(f"- {r['rule_name']} [{r['rule_type']}]: {r['description']}")
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
    print('Required output: concise report separating FACT vs JUDGMENT. Use Postgres only. If scanner freshness action_gate=no_trade or current context is not EOD closing-data backed, say scanner_stale/no-trade/EOD-only and create no actionable recommendations. If no actionable setup, say watchlist/no-trade and still finish the run.')


if __name__ == '__main__':
    main()
