from wolfy_tiered_universe import parse_index_members, _risk_allowed, TIER_RULES


def test_parse_index_members_reads_first_wikitable_symbols():
    html = '''
    <table class="wikitable sortable" id="constituents">
      <tr><th>Symbol</th><th>Security</th></tr>
      <tr><td><a>AAA</a></td><td>Alpha Corp</td></tr>
      <tr><td><a>BBB.B</a></td><td>Beta Class B</td></tr>
    </table>
    '''
    members = parse_index_members(html, "large_cap", "fixture")
    assert [m.symbol for m in members] == ["AAA", "BBB.B"]
    assert members[0].tier == "large_cap"
    assert members[0].name == "Alpha Corp"


def test_risk_allowed_blocks_spac_and_leveraged_products():
    assert _risk_allowed("AAPL", "Apple Inc.")[0] is True
    assert _risk_allowed("TEST", "Test Acquisition Corp Class A")[0] is False
    assert _risk_allowed("XYZ", "Leveraged 2X Daily XYZ ETF", is_etf=True)[0] is False


def test_tier_rules_cover_blue_mid_small_and_etf():
    for tier in ["blue_chip", "large_cap", "mid_cap", "small_cap", "etf_core"]:
        assert tier in TIER_RULES
        assert TIER_RULES[tier]["min_price"] > 0
        assert TIER_RULES[tier]["min_avg_dollar_vol"] > 0
    assert TIER_RULES["small_cap"]["max_position_risk_multiplier"] < TIER_RULES["blue_chip"]["max_position_risk_multiplier"]
