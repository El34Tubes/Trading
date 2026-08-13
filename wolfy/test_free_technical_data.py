from datetime import date
from decimal import Decimal


class _FakeResponse:
    def __init__(self, text: str):
        self._payload = text.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._payload


def test_compute_options_oriented_features_rewards_contraction_then_expansion():
    from eod_price_features import PriceBar
    from free_technical_data import compute_options_oriented_features

    bars = []
    close = Decimal("100")
    for i in range(30):
        # Wide early ranges, tight base, then a high-volume expansion close.
        width = Decimal("4") if i < 15 else Decimal("1")
        if i == 29:
            close += Decimal("3")
            width = Decimal("4")
        else:
            close += Decimal("0.20")
        volume = 3_000_000 if i == 29 else 1_000_000
        high = close + (Decimal("0.5") if i == 29 else width / 2)
        low = close - (width - Decimal("0.5") if i == 29 else width / 2)
        bars.append(PriceBar("ABC", date.fromordinal(date(2026, 1, 1).toordinal() + i), close - Decimal("0.2"), high, low, close, volume))

    rows = compute_options_oriented_features(bars, realized_vol_window=10, contraction_window=5, baseline_window=20, volume_window=20)
    latest = rows[-1]

    assert latest.ticker == "ABC"
    assert latest.atr_pct is not None and latest.atr_pct > 0
    assert latest.realized_vol_annualized is not None and latest.realized_vol_annualized > 0
    assert latest.pre_breakout_contraction_ratio is not None
    assert latest.pre_breakout_contraction_ratio < Decimal("0.60")
    assert latest.range_expansion_ratio is not None and latest.range_expansion_ratio > Decimal("2")
    assert latest.close_location_value >= Decimal("0.70")
    assert latest.volume_percentile == Decimal("1")
    assert latest.options_volatility_setup is True


def test_compute_options_oriented_features_does_not_reject_high_realized_volatility_by_itself():
    from eod_price_features import PriceBar
    from free_technical_data import compute_options_oriented_features

    bars = []
    close = Decimal("50")
    for i in range(30):
        close += Decimal("3") if i % 2 == 0 else Decimal("-2")
        width = Decimal("8") if i < 24 else Decimal("1")
        if i == 29:
            close += Decimal("6")
            width = Decimal("9")
        high = close + (Decimal("1") if i == 29 else width / 2)
        low = close - (width - Decimal("1") if i == 29 else width / 2)
        bars.append(PriceBar("VOL", date.fromordinal(date(2026, 2, 1).toordinal() + i), close - Decimal("1"), high, low, close, 5_000_000 if i == 29 else 1_000_000))

    latest = compute_options_oriented_features(bars, realized_vol_window=10, contraction_window=5, baseline_window=20, volume_window=20)[-1]
    assert latest.realized_vol_annualized > Decimal("0.50")
    assert latest.options_volatility_setup is True
    assert latest.high_volatility_allowed is True


def test_compute_point_in_time_breadth_uses_only_eligible_rows():
    from free_technical_data import compute_point_in_time_breadth

    rows = [
        {"ticker": "A", "close": 11, "previous_close": 10, "sma20": 9, "sma50": 8, "sma200": 7, "high20": 11, "low20": 7, "eligible": True, "volume": 200},
        {"ticker": "B", "close": 9, "previous_close": 10, "sma20": 10, "sma50": 11, "sma200": 12, "high20": 12, "low20": 9, "eligible": True, "volume": 100},
        {"ticker": "DELISTED", "close": 100, "previous_close": 1, "eligible": False, "volume": 999},
    ]
    result = compute_point_in_time_breadth(rows)
    assert result["eligible_count"] == 2
    assert result["advancers"] == 1
    assert result["decliners"] == 1
    assert result["pct_above_20dma"] == Decimal("0.5")
    assert result["new_20d_high_fraction"] == Decimal("0.5")
    assert result["new_20d_low_fraction"] == Decimal("0.5")
    assert result["up_volume_fraction"] == Decimal("0.6667")


def test_parse_cboe_vix_csv():
    from free_technical_data import parse_cboe_vix_csv

    rows = parse_cboe_vix_csv("DATE,OPEN,HIGH,LOW,CLOSE\n08/11/2026,15.42,15.61,15.23,15.28\n")
    assert rows == [{"observation_date": date(2026, 8, 11), "series": "VIX", "open": Decimal("15.42"), "high": Decimal("15.61"), "low": Decimal("15.23"), "value": Decimal("15.28")}]


def test_parse_cboe_options_daily_html_extracts_only_supported_market_ratios():
    from free_technical_data import parse_cboe_options_daily_html

    html = r'''{\"ratios\":[{\"name\":\"TOTAL PUT/CALL RATIO\",\"value\":\"0.81\"},{\"name\":\"INDEX PUT/CALL RATIO\",\"value\":\"0.90\"},{\"name\":\"EQUITY PUT/CALL RATIO\",\"value\":\"0.63\"},{\"name\":\"SPX + SPXW PUT/CALL RATIO\",\"value\":\"1.15\"},{\"name\":\"UNRELATED\",\"value\":\"9.9\"}]}'''
    rows = parse_cboe_options_daily_html(html, observation_date=date(2026, 8, 11))
    assert {(row["series"], row["value"]) for row in rows} == {
        ("CBOE_TOTAL_PUT_CALL", Decimal("0.81")),
        ("CBOE_INDEX_PUT_CALL", Decimal("0.90")),
        ("CBOE_EQUITY_PUT_CALL", Decimal("0.63")),
        ("CBOE_SPX_PUT_CALL", Decimal("1.15")),
    }


def test_compute_sector_relative_strength_uses_sector_etf_and_spy():
    from free_technical_data import compute_sector_relative_strength

    result = compute_sector_relative_strength(
        ticker="ABC",
        sector="Information Technology",
        stock_return=Decimal("0.12"),
        sector_return=Decimal("0.07"),
        spy_return=Decimal("0.03"),
    )
    assert result["sector_etf"] == "XLK"
    assert result["stock_vs_sector"] == Decimal("0.05")
    assert result["sector_vs_spy"] == Decimal("0.04")
    assert result["sector_confirmation"] is True


def test_parse_finra_consolidated_short_volume_labels_scope_correctly():
    from free_technical_data import parse_finra_short_volume

    rows = parse_finra_short_volume("Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n20260811|AAPL|600|10|1000|B,Q,N\n")
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["finra_off_exchange_short_fraction"] == Decimal("0.6")
    assert rows[0]["short_exempt_fraction"] == Decimal("0.01")
    assert rows[0]["scope"] == "finra_reported_public_trades_not_consolidated_market"


def test_parse_treasury_curve_csv_computes_technical_curve_spreads():
    from free_technical_data import parse_treasury_curve_csv

    rows = parse_treasury_curve_csv('Date,"2 Yr","10 Yr"\n08/11/2026,4.22,4.70\n')
    assert rows[0]["observation_date"] == date(2026, 8, 11)
    assert rows[0]["two_year"] == Decimal("4.22")
    assert rows[0]["ten_year"] == Decimal("4.70")
    assert rows[0]["ten_minus_two"] == Decimal("0.48")


def test_parse_nasdaq_short_interest_preserves_publication_availability():
    from free_technical_data import parse_nasdaq_short_interest

    payload = {"data": {"symbol": "aapl", "shortInterestTable": {"rows": [{"settlementDate": "07/31/2026", "interest": "141,606,163", "avgDailyShareVolume": "58,400,983", "daysToCover": 2.424722}]}}}
    rows = parse_nasdaq_short_interest(payload, published_at=date(2026, 8, 11))
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["settlement_date"] == date(2026, 7, 31)
    assert rows[0]["available_at"] == date(2026, 8, 11)
    assert rows[0]["short_interest"] == Decimal("141606163")
    assert rows[0]["days_to_cover"] == Decimal("2.424722")


def test_free_source_schema_and_upserts_are_idempotent():
    import pytest
    psycopg = pytest.importorskip("psycopg")
    from free_technical_data import ensure_free_technical_schema, store_market_series, store_short_volume

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    with psycopg.connect(dsn) as conn:
        ensure_free_technical_schema(conn)
        store_market_series(conn, [{"observation_date": date(2099, 1, 2), "series": "VIX", "open": Decimal("20"), "high": Decimal("21"), "low": Decimal("19"), "value": Decimal("20.5")}], source="unit-cboe", available_at=date(2099, 1, 2))
        store_market_series(conn, [{"observation_date": date(2099, 1, 2), "series": "VIX", "open": Decimal("20"), "high": Decimal("21"), "low": Decimal("19"), "value": Decimal("20.7")}], source="unit-cboe", available_at=date(2099, 1, 2))
        store_short_volume(conn, [{"observation_date": date(2099, 1, 2), "ticker": "ZZFREE", "short_volume": Decimal("600"), "short_exempt_volume": Decimal("10"), "total_volume": Decimal("1000"), "market": "B,Q,N", "finra_off_exchange_short_fraction": Decimal("0.6"), "short_exempt_fraction": Decimal("0.01"), "scope": "finra_reported_public_trades_not_consolidated_market"}], source="unit-finra", available_at=date(2099, 1, 3))
        vix = conn.execute("SELECT value, source FROM technical_market_series WHERE series='VIX' AND observation_date=DATE '2099-01-02'").fetchone()
        short = conn.execute("SELECT short_fraction, available_at FROM finra_short_volume WHERE ticker='ZZFREE' AND observation_date=DATE '2099-01-02'").fetchone()
        conn.execute("DELETE FROM technical_market_series WHERE series='VIX' AND observation_date=DATE '2099-01-02'")
        conn.execute("DELETE FROM finra_short_volume WHERE ticker='ZZFREE' AND observation_date=DATE '2099-01-02'")
    assert vix == (Decimal("20.7"), "unit-cboe")
    assert short[0] == Decimal("0.6")
    assert short[1].date() == date(2099, 1, 3)
