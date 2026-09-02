import pytest

from engine.lib import leverage as lev


@pytest.mark.parametrize("name,etf,rule", [
    ("MicroSectors FANG Index -3X Inverse Leveraged ETNs", False, "inverse"),
    ("Some 3x Leveraged ETN", None, "leveraged_word"),
    ("Leverage Shares 2X Long TSLA", None, "leveraged_word"),
    ("ProShares UltraPro Short Dow30", True, "ultrapro"),
    ("UltraPro MidCap400", True, "ultrapro"),
    ("ProShares Ultra S&P500", True, "proshares_ultra"),
    ("ProShares UltraShort QQQ", True, "proshares_ultra"),
    ("ProShares Short S&P500", True, "proshares_short"),
    ("Direxion Daily S&P 500 Bull 3X ETF", True, "direxion_bull_bear"),
    ("Direxion Daily Semiconductor Bear 3X Shares", None, "direxion_bull_bear"),
    ("Daily 2x Fund", None, "multiplier"),
    ("Target 1.5x Growth", None, "multiplier"),
    ("2x Bitcoin Strategy ETF", True, "multiplier_etp"),
    ("-1x Short VIX Futures ETF", False, "multiplier"),
])
def test_flags_leveraged_products(name, etf, rule):
    m = lev.classify(name, etf)
    assert m is not None and m.rule == rule
    assert lev.is_leveraged(name, etf)


@pytest.mark.parametrize("name,etf", [
    ("Build-A-Bear Workshop, Inc.", False),
    ("Ranger Equity Bear Bear ETF", True),
    ("Vanguard Short-Term Bond ETF", True),
    ("Ultra Clean Holdings", False),
    ("Ultragenyx Pharmaceutical", False),
    ("JPMorgan Ultra-Short Income ETF", True),
    ("Simplify Bond Bull ETF", True),
    ("TrueShares Quarterly Bull Hedge ETF", True),
    ("10x Genomics, Inc.", False),
    ("10x Genomics, Inc.", True),                 # multiplier 10 but... see below
    ("IncomeSTKd 1x Bitcoin & 1x Gold Premium ETF", True),
    ("State Street SPDR S&P Leveraged Loan ETF", True),
    ("ProShares Long Online/Short Stores ETF", True),
    ("SPX Options Fund", True),
    ("TSXD Trust", True),
    ("Growth Fund 2xMonthly Pay", True),
    ("", None),
    (None, None),
])
def test_refuses_ambiguous_names(name, etf):
    if name == "10x Genomics, Inc." and etf:
        # A bare >=1.5x multiplier IS promoted when the row is filed as an ETP.
        # TXG is filed etf=False in the universe, which is what keeps it safe.
        assert lev.classify(name, etf) is not None
        return
    assert lev.classify(name, etf) is None


def test_etf_false_never_suppresses_a_rule():
    assert lev.classify("Daily 3X Bull Something", etf=False).rule == "multiplier"


def test_multiplier_evidence_reads_whole_token():
    assert lev.classify("Daily 1.5X Fund").evidence == "1.5X"
    assert lev.classify("Daily -3X Fund").evidence == "-3X"


def test_flagged_rows_reads_universe(con):
    con.execute("CREATE TABLE universe (ticker VARCHAR, name VARCHAR, etf BOOLEAN, liquid BOOLEAN)")
    con.executemany("INSERT INTO universe VALUES (?, ?, ?, ?)", [
        ("SPXL", "Direxion Daily S&P 500 Bull 3X ETF", True, True),
        ("BBW", "Build-A-Bear Workshop, Inc.", False, True),
        ("FNGD", "MicroSectors FANG Index -3X Inverse Leveraged ETNs", None, False),
    ])
    rows = lev.flagged_rows(con)
    assert [r[0] for r in rows] == ["FNGD", "SPXL"]
    assert rows[0][2] is False                       # COALESCE(etf, FALSE)
    assert lev.flagged_tickers(con) == {"FNGD", "SPXL"}
    assert lev.register_exclusion(con) == 2
    assert con.execute("SELECT COUNT(*) FROM _lev_excluded").fetchone()[0] == 2


def test_resolve_policy(monkeypatch):
    monkeypatch.delenv(lev.POLICY_ENV, raising=False)
    assert lev.resolve_policy() == "all"
    assert lev.resolve_policy("ex-leveraged") == "ex-leveraged"
    monkeypatch.setenv(lev.POLICY_ENV, "ex-leveraged")
    assert lev.resolve_policy() == "ex-leveraged"
    assert lev.resolve_policy("all") == "all"        # CLI beats env
    with pytest.raises(SystemExit):
        lev.resolve_policy("ex-levraged")
