from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal


def _cleanup(conn, ticker: str, strategy_names: list[str] | None = None) -> None:
    strategy_names = strategy_names or []
    conn.execute("DELETE FROM eod_monitoring_events WHERE ticker=%s", (ticker,))
    conn.execute("DELETE FROM setups WHERE ticker=%s", (ticker,))
    conn.execute("DELETE FROM positions WHERE ticker=%s", (ticker,))
    conn.execute("DELETE FROM earnings_calendar WHERE ticker=%s", (ticker,))
    conn.execute("DELETE FROM prices WHERE ticker=%s", (ticker,))
    if strategy_names:
        conn.execute("DELETE FROM research_log WHERE hypothesis LIKE 'monthly revalidation:%'")
        conn.execute("DELETE FROM backtests WHERE strategy_id IN (SELECT id FROM strategies WHERE name = ANY(%s))", (strategy_names,))
        conn.execute("DELETE FROM strategies WHERE name = ANY(%s)", (strategy_names,))


def test_preopen_monitoring_flags_invalidation_and_event_landmines_without_promoting():
    import psycopg
    from eod_monitoring import ensure_monitoring_schema, run_preopen_monitoring

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    ticker = "ZZMON"
    today = date(2026, 6, 3)
    with psycopg.connect(dsn) as conn:
        ensure_monitoring_schema(conn)
        _cleanup(conn, ticker)
        conn.execute(
            "INSERT INTO prices(ticker, dt, close) VALUES (%s,%s,%s)",
            (ticker, today - timedelta(days=1), Decimal("9.50")),
        )
        conn.execute(
            "INSERT INTO earnings_calendar(ticker, event_dt, session, confirmed) VALUES (%s,%s,'bmo',true)",
            (ticker, today),
        )
        setup_id = conn.execute(
            """
            INSERT INTO setups(created_dt, for_session, ticker, direction, invalidation, thesis, status)
            VALUES (%s,%s,%s,'long',%s,'unit monitor setup','pending_review') RETURNING id
            """,
            (today - timedelta(days=1), today, ticker, Decimal("10.00")),
        ).fetchone()[0]
        position_id = conn.execute(
            """
            INSERT INTO positions(ticker, opened, risk_amount, invalidation, status)
            VALUES (%s,%s,%s,%s,'open') RETURNING id
            """,
            (ticker, today - timedelta(days=2), Decimal("50"), Decimal("10.00")),
        ).fetchone()[0]

        result = run_preopen_monitoring(conn, as_of=today)
        setup_status = conn.execute("SELECT status FROM setups WHERE id=%s", (setup_id,)).fetchone()[0]
        position_status = conn.execute("SELECT status FROM positions WHERE id=%s", (position_id,)).fetchone()[0]
        events = conn.execute(
            "SELECT object_type, object_id, action, reason FROM eod_monitoring_events WHERE ticker=%s ORDER BY id",
            (ticker,),
        ).fetchall()
        _cleanup(conn, ticker)

    assert result["setups_flagged"] == 1
    assert result["positions_flagged"] == 1
    assert setup_status == "rejected"
    assert position_status == "flagged"
    assert {(row[0], row[1], row[2]) for row in events} == {("setup", setup_id, "rejected"), ("position", position_id, "flagged")}
    assert all("invalidation" in row[3] and "earnings" in row[3] for row in events)


def test_monthly_revalidation_demotes_stale_or_failed_approved_strategies_only():
    import psycopg
    from eod_monitoring import ensure_monitoring_schema, run_monthly_strategy_revalidation

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    as_of = date(2026, 6, 30)
    stale = "unit_stale_approved"
    fresh = "unit_fresh_approved"
    failed = "unit_failed_approved"
    with psycopg.connect(dsn) as conn:
        ensure_monitoring_schema(conn)
        _cleanup(conn, "ZZREV", [stale, fresh, failed])
        conn.execute(
            "INSERT INTO strategies(name, setup_type, status, latest_oos_verdict, last_validated, notes) VALUES (%s,'unit','approved',true,%s,'stale')",
            (stale, as_of - timedelta(days=45)),
        )
        conn.execute(
            "INSERT INTO strategies(name, setup_type, status, latest_oos_verdict, last_validated, notes) VALUES (%s,'unit','approved',true,%s,'fresh')",
            (fresh, as_of - timedelta(days=10)),
        )
        conn.execute(
            "INSERT INTO strategies(name, setup_type, status, latest_oos_verdict, last_validated, notes) VALUES (%s,'unit','approved',false,%s,'failed')",
            (failed, as_of - timedelta(days=5)),
        )

        result = run_monthly_strategy_revalidation(conn, as_of=as_of, stale_after_days=31)
        statuses = dict(conn.execute("SELECT name, status FROM strategies WHERE name = ANY(%s)", ([stale, fresh, failed],)).fetchall())
        research_rows = conn.execute(
            "SELECT hypothesis, outcome, promoted FROM research_log WHERE hypothesis = ANY(%s) ORDER BY id",
            ([f"monthly revalidation:{stale}", f"monthly revalidation:{failed}"],),
        ).fetchall()
        _cleanup(conn, "ZZREV", [stale, fresh, failed])

    assert result["strategies_demoted"] >= 2
    assert statuses == {stale: "candidate", fresh: "approved", failed: "candidate"}
    assert len(research_rows) == 2
    assert all(row[1] == "demoted_to_candidate" and row[2] is False for row in research_rows)
