"""Tests for market screen and candidate read models."""

from datetime import date

import pytest

from server import market_read_models, read_model_utils
from tests.conftest import insert_bars
from tests.read_model_helpers import liquid_universe, screen_table


def test_screen_counts_and_orders_passers(con):
    screen_table(con)
    day = date(2026, 9, 4)
    rows = [
        (day, "LOW", 10, 70, 7, True, 0.1, 0.2, 0.3, -0.1, False, False, False),
        (day, "HIGH", 20, 90, 8, True, 0.2, 0.3, 0.4, -0.05, True, True, True),
        (day, "FAIL", 5, 20, 3, False, -0.1, -0.2, 0.1, -0.4, False, False, True),
    ]
    con.executemany(
        "INSERT INTO screen_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
    )

    result = market_read_models.screen(con)

    assert result["run_date"] == day
    assert (result["n_total"], result["n_passing"], result["n_new_today"]) == (3, 2, 1)
    assert result["results_page"] == 1
    assert result["results_offset"] == 0
    assert result["results_limit"] == market_read_models.SCREEN_RESULTS_LIMIT
    assert result["results_matching_count"] == 2
    assert result["results_total_pages"] == 1
    assert result["results_new_today"] == 1
    assert result["results_truncated"] is False
    assert result["results_has_previous"] is False
    assert result["results_has_next"] is False
    assert [row["ticker"] for row in result["results"]] == ["HIGH", "LOW"]
    assert market_read_models.screen(con, date(2026, 9, 3)) is None


@pytest.mark.parametrize("column", range(3))
def test_screen_payload_rejects_unsafe_public_counts(column):
    header = [1, 1, 1]
    header[column] = read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1

    with pytest.raises(ValueError, match="public count is invalid"):
        market_read_models._screen_payload(date(2026, 9, 4), 1, tuple(header), [])


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("n_passing", 2, "screen counts are inconsistent"),
        ("n_new_today", 2, "new-today count is inconsistent"),
        ("results_offset", 1, "screen pagination is inconsistent"),
        ("results_has_next", True, "pagination flags are inconsistent"),
        ("results_new_today", 1, "screen page count is inconsistent"),
    ],
)
def test_screen_projection_rejects_incoherent_assembled_fields(field, value, message):
    result = market_read_models._screen_payload(date(2026, 9, 4), 1, (1, 0, 0), [])
    result[field] = value

    with pytest.raises(ValueError, match=message):
        market_read_models._validate_screen_projection(result)


def test_screen_projection_rejects_duplicate_or_unordered_rows():
    row = {
        "run_date": date(2026, 9, 4),
        "ticker": "AAA",
        "close": 100.0,
        "rs_rank": 90,
        "template_score": 8,
        "passes_template": True,
        "dist_50d": 0.1,
        "dist_200d": 0.2,
        "off_52w_low": 0.3,
        "off_52w_high": -0.1,
        "base_tight": False,
        "vol_dryup": False,
        "new_today": False,
        "universe_policy": "all",
    }
    payload = market_read_models._screen_payload(
        date(2026, 9, 4), 1, (2, 2, 0), [row, {**row, "ticker": "BBB"}]
    )
    payload["results"][1]["ticker"] = "AAA"

    with pytest.raises(ValueError, match="not unique and ordered"):
        market_read_models._validate_screen_projection(payload)


def test_screen_ticker_ties_follow_unicode_code_point_order(con):
    screen_table(con)
    day = date(2026, 9, 4)
    con.executemany(
        "INSERT INTO screen_results VALUES "
        "(?, ?, 10, 90, 8, TRUE, 0.1, 0.2, 0.3, -0.1, FALSE, FALSE, FALSE)",
        [(day, "\uF900"), (day, "\U00010000")],
    )

    result = market_read_models.screen(con)

    assert [row["ticker"] for row in result["results"]] == ["\uF900", "\U00010000"]
    result["results"].reverse()
    with pytest.raises(ValueError, match="not unique and ordered"):
        market_read_models._validate_screen_projection(result)


@pytest.mark.parametrize("limit", [0, True, read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1])
def test_screen_rejects_invalid_page_limit(con, monkeypatch, limit):
    monkeypatch.setattr(market_read_models, "SCREEN_RESULTS_LIMIT", limit)

    with pytest.raises(ValueError, match="page must be positive"):
        market_read_models.screen(con)


def test_latest_screen_can_be_capped_at_operational_date(con):
    screen_table(con)
    operational = date(2026, 9, 4)
    future = date(2026, 9, 8)
    rows = [
        (operational, "CURRENT", 10, 70, 7, True, 0.1, 0.2, 0.3, -0.1, False, False, False),
        (future, "PARTIAL", 20, 90, 8, True, 0.2, 0.3, 0.4, -0.05, True, True, True),
    ]
    con.executemany(
        "INSERT INTO screen_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
    )

    assert market_read_models.screen(con)["run_date"] == future
    current = market_read_models.screen(con, through=operational)
    assert current["run_date"] == operational
    assert [row["ticker"] for row in current["results"]] == ["CURRENT"]


def test_screen_pages_all_passers_with_stable_full_counts(con, monkeypatch):
    screen_table(con)
    monkeypatch.setattr(market_read_models, "SCREEN_RESULTS_LIMIT", 2)
    day = date(2026, 9, 4)
    screen_rows = [
        (day, "AAA", 10, 99, 8, True, 0.1, 0.2, 0.3, -0.1, False, False, True),
        (day, "BBB", 10, 99, 8, True, 0.1, 0.2, 0.3, -0.1, False, False, False),
        (day, "CCC", 10, 98, 8, True, 0.1, 0.2, 0.3, -0.1, False, False, True),
        (day, "DDD", 10, 97, 8, True, 0.1, 0.2, 0.3, -0.1, False, False, False),
        (day, "FAIL", 10, 96, 7, False, 0.1, 0.2, 0.3, -0.1, False, False, False),
    ]
    con.executemany(
        "INSERT INTO screen_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        screen_rows,
    )

    first = market_read_models.screen(con, day, page=1)
    second = market_read_models.screen(con, day, page=2)
    third = market_read_models.screen(con, day, page=3)

    assert [row["ticker"] for row in first["results"]] == ["AAA", "BBB"]
    assert [row["ticker"] for row in second["results"]] == ["CCC", "DDD"]
    assert third["results"] == []
    assert [page["n_passing"] for page in (first, second, third)] == [4, 4, 4]
    assert [page["n_new_today"] for page in (first, second, third)] == [2, 2, 2]
    assert [page["results_new_today"] for page in (first, second, third)] == [1, 1, 0]
    assert [page["results_total_pages"] for page in (first, second, third)] == [2, 2, 2]
    assert [page["results_offset"] for page in (first, second, third)] == [0, 2, 4]
    assert [page["results_has_previous"] for page in (first, second, third)] == [
        False,
        True,
        True,
    ]
    assert [page["results_has_next"] for page in (first, second, third)] == [True, False, False]
    assert all(page["results_truncated"] for page in (first, second, third))


@pytest.mark.parametrize(
    "page",
    [0, -1, True, 1.5, read_model_utils.PUBLIC_SAFE_INTEGER_MAX],
)
def test_screen_rejects_invalid_or_unsafe_page(con, page):
    with pytest.raises(ValueError, match="page must be positive"):
        market_read_models.screen(con, page=page)


def test_screen_projects_explicit_columns_and_legacy_policy_default(con):
    screen_table(con)
    day = date(2026, 9, 4)
    con.execute(
        "INSERT INTO screen_results VALUES "
        "(?, 'AAA', 20, 90, 8, TRUE, .2, .3, .4, -.05, TRUE, TRUE, TRUE)",
        [day],
    )
    con.execute("ALTER TABLE screen_results ADD COLUMN internal_secret VARCHAR")
    con.execute("UPDATE screen_results SET internal_secret = 'not public'")

    row = market_read_models.screen(con)["results"][0]

    assert set(row) == {
        "run_date",
        "ticker",
        "close",
        "rs_rank",
        "template_score",
        "passes_template",
        "dist_50d",
        "dist_200d",
        "off_52w_low",
        "off_52w_high",
        "base_tight",
        "vol_dryup",
        "new_today",
        "universe_policy",
    }
    assert row["universe_policy"] == "all"
    assert "internal_secret" not in row


def test_screen_rejects_malformed_stored_ticker_without_rewriting(con):
    screen_table(con)
    ticker = "BAD\nTICKER"
    con.execute(
        "INSERT INTO screen_results VALUES "
        "(DATE '2026-09-04', ?, 20, 90, 8, TRUE, .2, .3, .4, -.05, TRUE, TRUE, TRUE)",
        [ticker],
    )

    with pytest.raises(ValueError, match="ticker is invalid"):
        market_read_models.screen(con)
    assert con.execute("SELECT ticker FROM screen_results").fetchone()[0] == ticker


def test_screen_rejects_invalid_stored_numeric_without_rewriting(con):
    screen_table(con)
    con.execute(
        "INSERT INTO screen_results VALUES "
        "(DATE '2026-09-04', 'AAA', 0, 90, 8, TRUE, .2, .3, .4, -.05, TRUE, TRUE, TRUE)"
    )

    with pytest.raises(ValueError, match="public screen close is invalid"):
        market_read_models.screen(con)
    assert con.execute("SELECT close FROM screen_results").fetchone()[0] == 0


def test_screen_projects_stored_universe_policy(con):
    screen_table(con)
    day = date(2026, 9, 4)
    con.execute(
        "INSERT INTO screen_results VALUES "
        "(?, 'AAA', 20, 90, 8, TRUE, .2, .3, .4, -.05, TRUE, TRUE, TRUE)",
        [day],
    )
    con.execute("ALTER TABLE screen_results ADD COLUMN universe_policy VARCHAR DEFAULT 'all'")
    con.execute("UPDATE screen_results SET universe_policy = 'ex-leveraged'")

    row = market_read_models.screen(con)["results"][0]

    assert row["universe_policy"] == "ex-leveraged"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("close", 0, "public screen close is invalid"),
        ("close", float("nan"), "public screen close is invalid"),
        ("rs_rank", 1.5, "public identifier is invalid"),
        ("rs_rank", 100, "public screen rank is invalid"),
        ("template_score", -1, "public count is invalid"),
        ("template_score", 9, "public screen score is invalid"),
        ("passes_template", 1, "public screen boolean is invalid"),
        ("dist_50d", float("inf"), "public screen dist_50d is invalid"),
        ("universe_policy", "unknown", "public screen universe policy is invalid"),
    ],
)
def test_screen_result_rejects_values_outside_the_browser_contract(field, value, message):
    result = {
        "run_date": date(2026, 9, 4),
        "ticker": "AAA",
        "close": 100.0,
        "rs_rank": 90,
        "template_score": 8,
        "passes_template": True,
        "dist_50d": 0.1,
        "dist_200d": 0.2,
        "off_52w_low": 0.3,
        "off_52w_high": -0.1,
        "base_tight": False,
        "vol_dryup": False,
        "new_today": True,
        "universe_policy": "all",
    }
    result[field] = value

    with pytest.raises(ValueError, match=message):
        market_read_models._validate_screen_result(result, passing_only=True)


def test_candidate_uses_only_real_bars_through_operational_date(con):
    screen_table(con)
    old = date(2026, 9, 3)
    operational = date(2026, 9, 4)
    partial = date(2026, 9, 8)
    liquid_universe(con, ("SPY",))
    insert_bars(con, "SPY", [operational], open_=99, close=100)
    insert_bars(con, "AAA", [old], open_=9, high=10, low=9, close=10)
    insert_bars(con, "AAA", [operational], open_=20, close=20, volume=0)
    insert_bars(con, "AAA", [partial], open_=29, close=30)
    con.execute(
        "INSERT INTO screen_results VALUES "
        "(?, 'AAA', 10, 70, 7, TRUE, .1, .2, .3, -.1, FALSE, FALSE, FALSE), "
        "(?, 'AAA', 30, 99, 8, TRUE, .2, .3, .4, -.05, TRUE, TRUE, TRUE)",
        [old, partial],
    )

    result = market_read_models.candidate(con, "AAA")

    assert result["as_of"] == operational
    assert result["latest_close_date"] == old
    assert result["latest_close"] == pytest.approx(10)
    assert [bar["date"] for bar in result["bars"]] == [old, operational]
    assert result["screen"]["run_date"] == old


def test_candidate_rejects_malformed_ticker_before_database_access():
    class NoDatabase:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("database should not be accessed")

    with pytest.raises(ValueError, match="ticker is invalid"):
        market_read_models.candidate(NoDatabase(), " BAD")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("open", 0, "public candidate open is invalid"),
        ("high", float("inf"), "public candidate high is invalid"),
        ("low", float("nan"), "public candidate low is invalid"),
        ("close", -1, "public candidate close is invalid"),
        ("volume", -1, "public candidate volume is invalid"),
    ],
)
def test_candidate_bars_reject_invalid_numeric_values(field, value, message):
    bar = {
        "date": date(2026, 9, 4),
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 1_000,
    }
    bar[field] = value

    with pytest.raises(ValueError, match=message):
        market_read_models._validate_candidate_bars([bar], date(2026, 9, 4))


def test_candidate_bars_require_ordered_dates_and_valid_ohlc_geometry():
    bars = [
        {
            "date": date(2026, 9, 4),
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 1_000,
        },
        {
            "date": date(2026, 9, 4),
            "open": 100.0,
            "high": 99.0,
            "low": 98.0,
            "close": 101.0,
            "volume": 1_000,
        },
    ]

    with pytest.raises(ValueError, match="public candidate bar date is invalid"):
        market_read_models._validate_candidate_bars(bars, date(2026, 9, 4))
    bars[1]["date"] = date(2026, 9, 5)
    with pytest.raises(ValueError, match="public candidate OHLC geometry is invalid"):
        market_read_models._validate_candidate_bars(bars, date(2026, 9, 5))


def test_candidate_latest_quote_must_match_a_valid_bar():
    bars = [
        {
            "date": date(2026, 9, 4),
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 1_000,
        }
    ]

    with pytest.raises(ValueError, match="public candidate quote does not match bars"):
        market_read_models._validate_latest_quote((date(2026, 9, 4), 100.0), bars, date(2026, 9, 4))


def test_candidate_projection_rejects_incoherent_envelope():
    bar = {
        "date": date(2026, 9, 4),
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 1_000,
    }
    valid = {
        "ticker": "AAA",
        "as_of": date(2026, 9, 4),
        "n_bars": 1,
        "bars": [bar],
        "latest_close_date": date(2026, 9, 4),
        "latest_close": 101.0,
        "screen": None,
    }
    market_read_models._validate_candidate_projection(valid, "AAA")

    for change, message in (
        ({"n_bars": 2}, "bar count is inconsistent"),
        ({"latest_close": None}, "quote is incomplete"),
        ({"internal": "not public"}, "projection shape is invalid"),
    ):
        malformed = {**valid, **change}
        with pytest.raises(ValueError, match=message):
            market_read_models._validate_candidate_projection(malformed, "AAA")

    malformed_bar = {**valid, "bars": [{**bar, "internal": "not public"}]}
    with pytest.raises(ValueError, match="bar shape is invalid"):
        market_read_models._validate_candidate_projection(malformed_bar, "AAA")


@pytest.mark.parametrize("limit", [0, True, 251])
def test_candidate_rejects_invalid_bar_limit_before_database_access(monkeypatch, limit):
    class NoDatabase:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("database should not be accessed")

    monkeypatch.setattr(market_read_models, "CANDIDATE_BARS_LIMIT", limit)
    with pytest.raises(ValueError, match="candidate bar limit|public identifier"):
        market_read_models.candidate(NoDatabase(), "AAA")
