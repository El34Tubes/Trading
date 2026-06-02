from __future__ import annotations

import re
from pathlib import Path


MIGRATION = Path(__file__).with_name("migrations") / "20260601_eod_section6_schema.sql"
EXPECTED_TABLES = {
    "config",
    "prices",
    "fundamentals",
    "earnings_calendar",
    "features",
    "strategies",
    "signals",
    "setups",
    "backtests",
    "research_log",
    "positions",
    "trades",
    "runs",
}


def _sql() -> str:
    return MIGRATION.read_text()


def test_eod_section6_migration_exists_and_creates_expected_tables_non_destructively():
    sql = _sql()
    lowered = sql.lower()

    for unsafe in ("drop table", "truncate ", "delete from", "alter table "):
        assert unsafe not in lowered

    created_tables = set(
        re.findall(r"create\s+table\s+if\s+not\s+exists\s+([a-z_][a-z0-9_]*)", lowered)
    )
    assert EXPECTED_TABLES <= created_tables


def test_eod_section6_migration_seeds_only_research_config_and_research_only_strategies():
    sql = _sql()
    lowered = sql.lower()

    for key in (
        "min_dollar_vol",
        "slippage_bps",
        "risk_per_trade",
        "max_portfolio_heat",
        "max_name_weight",
        "max_drawdown_killswitch",
        "max_adv_frac",
    ):
        assert key in lowered

    assert "on conflict (key) do update" in lowered
    assert "status text check (status in ('research_only','candidate','approved','retired'))" in lowered
    assert "pead" in lowered
    assert "trend_volume_vol_regime" in lowered
    assert "sector_cross_sectional_momentum" in lowered
    strategy_seed = re.search(r"insert into strategies.*?on conflict", lowered, re.DOTALL)
    assert strategy_seed is not None
    assert "'approved'" not in strategy_seed.group(0)
    assert lowered.count("research_only") >= 3
