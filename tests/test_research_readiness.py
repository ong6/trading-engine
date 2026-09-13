"""Research-data admission gates must be measurable and non-promotional."""

from copy import deepcopy
from datetime import date, datetime, timedelta

import pytest

from server import (
    fundamentals_readiness,
    intraday_readiness,
    main,
    read_model_utils,
    readiness_common,
    research_readiness,
    stock_readiness,
)


@pytest.mark.parametrize("value", [-1, True, 1.5, read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1])
def test_readiness_count_rejects_invalid_sql_aggregate(value):
    with pytest.raises(ValueError, match="public count is invalid"):
        readiness_common.count(value)


@pytest.mark.parametrize(
    ("module", "field", "value"),
    [
        (stock_readiness, "MIN_SHARED_DATES", 0),
        (stock_readiness, "MIN_CALENDAR_DAYS", read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1),
        (fundamentals_readiness, "MIN_NAMES_PER_SNAPSHOT", True),
        (intraday_readiness, "MIN_TICKERS_PER_INTERVAL", -1),
        (intraday_readiness, "MIN_SESSION_COVERAGE_FRACTION", float("nan")),
        (intraday_readiness, "MIN_SESSION_COVERAGE_FRACTION", 1.1),
    ],
)
def test_invalid_gate_constants_fail_before_projection(con, monkeypatch, module, field, value):
    monkeypatch.setattr(module, field, value)

    with pytest.raises(ValueError, match="public"):
        module.assess(con)


def test_family_validation_rejects_contradictory_coverage(con):
    _init_inputs(con)
    result = research_readiness.assess(con)

    malformed_span = deepcopy(result["families"]["stock_selection"])
    malformed_span["qualifying_calendar_span_days"] = 1
    with pytest.raises(ValueError, match="span contradicts"):
        stock_readiness.validate(malformed_span)

    malformed_input = deepcopy(result["families"]["fundamentals"])
    malformed_input["input_status"] = "missing"
    malformed_input["missing_tables"] = ["invented"]
    with pytest.raises(ValueError, match="missing-table diagnostics"):
        fundamentals_readiness.validate(malformed_input)

    extra_interval = deepcopy(result["families"]["intraday"])
    extra_interval["observed_sessions"]["tick"] = 0
    with pytest.raises(ValueError, match="observed_sessions intervals"):
        intraday_readiness.validate(extra_interval)


def test_top_level_validation_rejects_invented_readiness_summary(con):
    result = research_readiness.assess(con)
    result["ready_families"] = ["stock_selection"]

    with pytest.raises(ValueError, match="summary contradicts"):
        research_readiness.validate(result)


@pytest.mark.parametrize(
    ("target", "field", "message"),
    [
        ("top", "internal", "research-readiness fields"),
        ("stock_selection", "internal", "stock-readiness fields"),
        ("fundamentals", "internal", "fundamentals-readiness fields"),
        ("intraday", "internal", "intraday-readiness fields"),
    ],
)
def test_readiness_validation_rejects_unreviewed_fields(con, target, field, message):
    result = research_readiness.assess(con)
    owner = result if target == "top" else result["families"][target]
    owner[field] = "not public"

    with pytest.raises(ValueError, match=message):
        research_readiness.validate(result)


@pytest.mark.parametrize(
    ("target", "field"),
    [
        ("top", "notice"),
        ("stock_selection", "limitation"),
        ("fundamentals", "usable_observation_rule"),
        ("intraday", "limitation"),
    ],
)
def test_readiness_validation_rejects_blank_explanations(con, target, field):
    result = research_readiness.assess(con)
    owner = result if target == "top" else result["families"][target]
    owner[field] = "   "

    with pytest.raises(ValueError, match="invalid"):
        research_readiness.validate(result)


def _init_inputs(con):
    con.execute("CREATE TABLE universe_snapshot (snapshot_date DATE, ticker VARCHAR)")
    con.execute("CREATE TABLE screen_results (run_date DATE, ticker VARCHAR)")
    con.execute(
        "CREATE TABLE fundamentals (ticker VARCHAR, as_of DATE, quote_type VARCHAR, "
        "market_cap DOUBLE, trailing_pe DOUBLE, price_to_book DOUBLE, ev_to_ebitda DOUBLE)"
    )
    con.execute("CREATE TABLE intraday_prices (ticker VARCHAR, ts TIMESTAMP, interval VARCHAR)")


def _set_limits(monkeypatch, *, observations=3, span_days=2, names=1):
    monkeypatch.setattr(stock_readiness, "MIN_SHARED_DATES", observations)
    monkeypatch.setattr(stock_readiness, "MIN_CALENDAR_DAYS", span_days)
    monkeypatch.setattr(stock_readiness, "MIN_NAMES_PER_DATE", names)
    monkeypatch.setattr(fundamentals_readiness, "MIN_SNAPSHOTS", observations)
    monkeypatch.setattr(fundamentals_readiness, "MIN_CALENDAR_DAYS", span_days)
    monkeypatch.setattr(fundamentals_readiness, "MIN_NAMES_PER_SNAPSHOT", names)
    monkeypatch.setattr(intraday_readiness, "MIN_SESSIONS", observations)
    monkeypatch.setattr(intraday_readiness, "MIN_CALENDAR_DAYS", span_days)
    monkeypatch.setattr(intraday_readiness, "MIN_TICKERS_PER_INTERVAL", names)
    monkeypatch.setattr(intraday_readiness, "MIN_SESSION_COVERAGE_FRACTION", 0.001)


def _insert_complete_dates(con, dates, tickers=("A",)):
    con.executemany(
        "INSERT INTO universe_snapshot VALUES (?, ?)",
        [(day, ticker) for day in dates for ticker in tickers],
    )
    con.executemany(
        "INSERT INTO screen_results VALUES (?, ?)",
        [(day, ticker) for day in dates for ticker in tickers],
    )
    con.executemany(
        "INSERT INTO fundamentals VALUES (?, ?, 'EQUITY', 1000000, 10, NULL, NULL)",
        [(ticker, day) for day in dates for ticker in tickers],
    )
    con.executemany(
        "INSERT INTO intraday_prices VALUES (?, ?, ?)",
        [
            (ticker, datetime.combine(day, datetime.min.time()), interval)
            for day in dates
            for interval in intraday_readiness.REQUIRED_INTERVALS
            for ticker in tickers
        ],
    )


def test_missing_inputs_wait_without_implying_an_edge(con):
    result = research_readiness.assess(con)

    assert result["purpose"] == "candidate_admission_only"
    assert result["paper_only"] is True
    assert result["automatic_action"] == "none"
    assert result["ready_families"] == []
    assert {value["status"] for value in result["families"].values()} == {"WAITING"}
    assert {value["input_status"] for value in result["families"].values()} == {"missing"}
    assert "not evidence of profitability" in result["notice"]


def test_existing_empty_inputs_report_zero_and_wait(con):
    _init_inputs(con)

    result = research_readiness.assess(con)
    families = result["families"]

    assert result["schema_version"] == 10
    assert result["ready_families"] == []
    assert {value["input_status"] for value in families.values()} == {"ready"}
    assert families["stock_selection"]["minimum_observed_names_per_date"] == 0
    assert families["stock_selection"]["qualifying_shared_dates"] == 0
    assert families["fundamentals"]["minimum_observed_names_per_snapshot"] == 0
    assert families["fundamentals"]["qualifying_snapshots"] == 0
    assert families["intraday"]["minimum_observed_names_per_session"] == {"1m": 0, "5m": 0}
    assert families["intraday"]["qualifying_sessions"] == {"1m": 0, "5m": 0}


def test_legacy_fundamentals_shape_fails_closed(con):
    con.execute("CREATE TABLE fundamentals (ticker VARCHAR, as_of DATE)")

    result = fundamentals_readiness.assess(con)

    assert result["status"] == "WAITING"
    assert result["input_status"] == "invalid-schema"
    assert result["missing_tables"] == []
    assert result["missing_columns"] == {
        "fundamentals": [
            "ev_to_ebitda",
            "market_cap",
            "price_to_book",
            "quote_type",
            "trailing_pe",
        ]
    }
    assert result["incompatible_columns"] == {}
    assert result["observed_snapshots"] == 0
    assert result["qualifying_snapshots"] == 0


def test_legacy_stock_and_intraday_shapes_fail_closed(con):
    con.execute("CREATE TABLE universe_snapshot (snapshot_date DATE)")
    con.execute("CREATE TABLE screen_results (ticker VARCHAR)")
    con.execute("CREATE TABLE intraday_prices (ticker VARCHAR, ts TIMESTAMP)")

    result = research_readiness.assess(con)

    assert result["ready_families"] == []
    stock = result["families"]["stock_selection"]
    assert stock["status"] == "WAITING"
    assert stock["input_status"] == "invalid-schema"
    assert stock["missing_columns"] == {
        "screen_results": ["run_date"],
        "universe_snapshot": ["ticker"],
    }
    intraday = result["families"]["intraday"]
    assert intraday["status"] == "WAITING"
    assert intraday["input_status"] == "invalid-schema"
    assert intraday["missing_columns"] == {"intraday_prices": ["interval"]}
    assert intraday["incompatible_columns"] == {}


def test_incompatible_input_types_fail_closed_with_exact_diagnostics(con):
    con.execute("CREATE TABLE universe_snapshot (snapshot_date VARCHAR, ticker INTEGER)")
    con.execute("CREATE TABLE screen_results (run_date VARCHAR, ticker INTEGER)")
    con.execute(
        "CREATE TABLE fundamentals (ticker INTEGER, as_of VARCHAR, quote_type INTEGER, "
        "market_cap VARCHAR, trailing_pe VARCHAR, price_to_book VARCHAR, ev_to_ebitda VARCHAR)"
    )
    con.execute("CREATE TABLE intraday_prices (ticker INTEGER, ts VARCHAR, interval INTEGER)")

    result = research_readiness.assess(con)

    assert result["ready_families"] == []
    stock = result["families"]["stock_selection"]
    assert stock["status"] == "WAITING"
    assert stock["input_status"] == "invalid-schema"
    assert stock["missing_columns"] == {}
    assert stock["incompatible_columns"] == {
        "screen_results": {"run_date": "VARCHAR", "ticker": "INTEGER"},
        "universe_snapshot": {"snapshot_date": "VARCHAR", "ticker": "INTEGER"},
    }
    fundamentals = result["families"]["fundamentals"]
    assert fundamentals["status"] == "WAITING"
    assert fundamentals["input_status"] == "invalid-schema"
    assert fundamentals["incompatible_columns"]["fundamentals"] == {
        "as_of": "VARCHAR",
        "ev_to_ebitda": "VARCHAR",
        "market_cap": "VARCHAR",
        "price_to_book": "VARCHAR",
        "quote_type": "INTEGER",
        "ticker": "INTEGER",
        "trailing_pe": "VARCHAR",
    }
    intraday = result["families"]["intraday"]
    assert intraday["status"] == "WAITING"
    assert intraday["input_status"] == "invalid-schema"
    assert intraday["incompatible_columns"] == {
        "intraday_prices": {"interval": "INTEGER", "ticker": "INTEGER", "ts": "VARCHAR"}
    }


def test_attached_or_shadow_schema_tables_do_not_satisfy_readiness_inputs(con):
    con.execute("CREATE SCHEMA shadow")
    con.execute("CREATE TABLE shadow.universe_snapshot (snapshot_date DATE, ticker VARCHAR)")
    con.execute("CREATE TABLE shadow.screen_results (run_date DATE, ticker VARCHAR)")
    con.execute(
        "CREATE TABLE shadow.fundamentals (ticker VARCHAR, as_of DATE, quote_type VARCHAR, "
        "market_cap DOUBLE, trailing_pe DOUBLE, price_to_book DOUBLE, ev_to_ebitda DOUBLE)"
    )
    con.execute(
        "CREATE TABLE shadow.intraday_prices (ticker VARCHAR, ts TIMESTAMP, interval VARCHAR)"
    )

    result = research_readiness.assess(con)

    assert result["ready_families"] == []
    assert {family["input_status"] for family in result["families"].values()} == {"missing"}
    assert result["families"]["stock_selection"]["missing_tables"] == [
        "screen_results",
        "universe_snapshot",
    ]
    assert result["families"]["fundamentals"]["missing_tables"] == ["fundamentals"]
    assert result["families"]["intraday"]["missing_tables"] == ["intraday_prices"]
    assert all(family["incompatible_columns"] == {} for family in result["families"].values())


def test_coverage_counts_are_point_in_time_and_interval_specific(con):
    _init_inputs(con)
    con.executemany(
        "INSERT INTO universe_snapshot VALUES (?, ?)",
        [(date(2024, 1, 2), "A"), (date(2024, 1, 3), "A"), (date(2024, 1, 4), "B")],
    )
    con.executemany(
        "INSERT INTO screen_results VALUES (?, ?)",
        [(date(2024, 1, 2), "A"), (date(2024, 1, 3), "A"), (date(2024, 1, 5), "A")],
    )
    con.executemany(
        "INSERT INTO fundamentals VALUES (?, ?, 'EQUITY', 1000000, 10, NULL, NULL)",
        [("A", date(2024, 1, 2)), ("B", date(2024, 1, 2)), ("A", date(2024, 1, 9))],
    )
    con.executemany(
        "INSERT INTO intraday_prices VALUES (?, ?, ?)",
        [
            ("A", datetime(2024, 1, 2, 14, 30), "1m"),
            ("A", datetime(2024, 1, 2, 14, 35), "5m"),
            ("A", datetime(2024, 1, 3, 14, 30), "5m"),
        ],
    )

    families = research_readiness.assess(con)["families"]

    assert families["stock_selection"]["observed_shared_dates"] == 2
    assert families["stock_selection"]["minimum_observed_names_per_date"] == 1
    assert families["stock_selection"]["qualifying_shared_dates"] == 0
    assert families["stock_selection"]["qualifying_calendar_span_days"] == 0
    assert families["fundamentals"]["observed_snapshots"] == 2
    assert families["fundamentals"]["minimum_observed_names_per_snapshot"] == 1
    assert families["fundamentals"]["qualifying_snapshots"] == 0
    assert families["fundamentals"]["qualifying_calendar_span_days"] == 0
    assert families["intraday"]["observed_sessions"] == {"1m": 1, "5m": 2}
    assert families["intraday"]["minimum_observed_names_per_session"] == {"1m": 1, "5m": 1}
    assert families["intraday"]["minimum_usable_names_per_session"] == {"1m": 0, "5m": 0}
    assert families["intraday"]["qualifying_sessions"] == {"1m": 0, "5m": 0}
    assert families["intraday"]["qualifying_calendar_span_days"] == {"1m": 0, "5m": 0}


def test_fundamentals_breadth_counts_only_usable_equity_rows(con, monkeypatch):
    _init_inputs(con)
    day = date(2024, 1, 2)
    con.executemany(
        "INSERT INTO fundamentals VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("GOOD", day, "EQUITY", 1_000_000, 12, None, None),
            ("ETF", day, "ETF", 1_000_000, 12, None, None),
            ("NO_CAP", day, "EQUITY", None, 12, None, None),
            ("NO_VALUE", day, "EQUITY", 1_000_000, None, None, None),
        ],
    )
    monkeypatch.setattr(fundamentals_readiness, "MIN_NAMES_PER_SNAPSHOT", 1)
    monkeypatch.setattr(fundamentals_readiness, "MIN_SNAPSHOTS", 1)
    monkeypatch.setattr(fundamentals_readiness, "MIN_CALENDAR_DAYS", 1)

    result = fundamentals_readiness.assess(con)

    assert result["observed_snapshots"] == 1
    assert result["minimum_observed_names_per_snapshot"] == 1
    assert "quote_type=EQUITY" in result["usable_observation_rule"]


def test_fundamentals_breadth_rejects_nonfinite_values_but_allows_negative_ratios(con, monkeypatch):
    _init_inputs(con)
    day = date(2024, 1, 2)
    con.executemany(
        "INSERT INTO fundamentals VALUES (?, ?, 'EQUITY', ?, ?, ?, ?)",
        [
            ("NEGATIVE", day, 1_000_000, -5.0, None, None),
            ("INF_CAP", day, float("inf"), 10.0, None, None),
            ("NAN_VALUE", day, 1_000_000, float("nan"), None, None),
            ("INF_VALUE", day, 1_000_000, None, float("inf"), None),
            ("ZERO_CAP", day, 0.0, 10.0, None, None),
        ],
    )
    monkeypatch.setattr(fundamentals_readiness, "MIN_NAMES_PER_SNAPSHOT", 1)
    monkeypatch.setattr(fundamentals_readiness, "MIN_SNAPSHOTS", 1)
    monkeypatch.setattr(fundamentals_readiness, "MIN_CALENDAR_DAYS", 1)

    result = fundamentals_readiness.assess(con)

    assert result["minimum_observed_names_per_snapshot"] == 1
    assert result["qualifying_snapshots"] == 1
    assert result["numeric_rule"] == "finite_positive_market_cap_and_finite_valuation"


def test_observation_count_without_elapsed_time_is_not_ready(con, monkeypatch):
    _init_inputs(con)
    dates = [date(2024, 1, 2) + timedelta(days=offset) for offset in range(3)]
    _insert_complete_dates(con, dates)
    _set_limits(monkeypatch, observations=3, span_days=30, names=1)

    result = research_readiness.assess(con)

    assert result["ready_families"] == []
    assert {family["status"] for family in result["families"].values()} == {"WAITING"}


def test_observation_count_without_required_breadth_is_not_ready(con, monkeypatch):
    _init_inputs(con)
    dates = [date(2024, 1, 2) + timedelta(days=offset) for offset in range(3)]
    _insert_complete_dates(con, dates, tickers=("A",))
    _set_limits(monkeypatch, observations=3, span_days=2, names=2)

    result = research_readiness.assess(con)

    assert result["ready_families"] == []
    assert result["families"]["stock_selection"]["qualifying_shared_dates"] == 0
    assert result["families"]["fundamentals"]["qualifying_snapshots"] == 0
    assert result["families"]["intraday"]["qualifying_sessions"] == {"1m": 0, "5m": 0}


def test_stock_breadth_counts_same_date_ticker_intersection(con, monkeypatch):
    _init_inputs(con)
    day = date(2024, 1, 2)
    con.executemany("INSERT INTO universe_snapshot VALUES (?, ?)", [(day, "A"), (day, "B")])
    con.executemany("INSERT INTO screen_results VALUES (?, ?)", [(day, "B"), (day, "C")])
    monkeypatch.setattr(stock_readiness, "MIN_NAMES_PER_DATE", 2)
    monkeypatch.setattr(stock_readiness, "MIN_SHARED_DATES", 1)
    monkeypatch.setattr(stock_readiness, "MIN_CALENDAR_DAYS", 1)

    result = stock_readiness.assess(con)

    assert result["observed_shared_dates"] == 1
    assert result["minimum_observed_names_per_date"] == 1
    assert result["breadth_rule"] == "same_date_ticker_intersection"
    assert result["qualifying_shared_dates"] == 0
    assert result["status"] == "WAITING"


def test_intraday_breadth_excludes_fragmentary_ticker_sessions(con, monkeypatch):
    _init_inputs(con)
    con.executemany(
        "INSERT INTO intraday_prices VALUES (?, ?, ?)",
        [
            (ticker, datetime(2024, 1, 2, 14, minute), interval)
            for ticker in ("A", "B")
            for interval in intraday_readiness.REQUIRED_INTERVALS
            for minute in ((30, 31) if ticker == "A" else (30,))
        ],
    )
    monkeypatch.setattr(intraday_readiness, "MIN_TICKERS_PER_INTERVAL", 2)
    monkeypatch.setattr(
        intraday_readiness,
        "_session_bar_expectations",
        lambda first, last: [(first, interval, 2) for interval in ("1m", "5m")],
    )

    result = intraday_readiness.assess(con)

    assert result["observed_sessions"] == {"1m": 1, "5m": 1}
    assert result["minimum_observed_names_per_session"] == {"1m": 2, "5m": 2}
    assert result["minimum_usable_names_per_session"] == {"1m": 1, "5m": 1}
    assert result["qualifying_sessions"] == {"1m": 0, "5m": 0}
    assert result["status"] == "WAITING"


def test_intraday_exchange_schedule_is_cached_by_observed_date_range():
    intraday_readiness._session_bar_expectations.cache_clear()
    try:
        first = intraday_readiness._session_bar_expectations(date(2024, 11, 29), date(2024, 11, 29))
        second = intraday_readiness._session_bar_expectations(
            date(2024, 11, 29), date(2024, 11, 29)
        )

        assert first == ((date(2024, 11, 29), "1m", 210), (date(2024, 11, 29), "5m", 42))
        assert second is first
        assert intraday_readiness._session_bar_expectations.cache_info().hits == 1
    finally:
        intraday_readiness._session_bar_expectations.cache_clear()


def test_intraday_breadth_accepts_substantial_early_close_coverage(con, monkeypatch):
    _init_inputs(con)
    con.executemany(
        "INSERT INTO intraday_prices VALUES (?, ?, ?)",
        [
            (ticker, datetime(2024, 11, 29, 14, 30) + timedelta(minutes=minute), interval)
            for ticker, bars in (("A", 10), ("B", 8), ("FRAGMENT", 2))
            for interval in intraday_readiness.REQUIRED_INTERVALS
            for minute in range(bars)
        ],
    )
    monkeypatch.setattr(intraday_readiness, "MIN_TICKERS_PER_INTERVAL", 2)
    monkeypatch.setattr(
        intraday_readiness,
        "_session_bar_expectations",
        lambda first, last: [(first, interval, 10) for interval in ("1m", "5m")],
    )

    result = intraday_readiness.assess(con)

    assert result["minimum_observed_names_per_session"] == {"1m": 3, "5m": 3}
    assert result["minimum_usable_names_per_session"] == {"1m": 2, "5m": 2}
    assert result["qualifying_sessions"] == {"1m": 1, "5m": 1}


def test_intraday_breadth_rejects_globally_truncated_session(con, monkeypatch):
    _init_inputs(con)
    con.executemany(
        "INSERT INTO intraday_prices VALUES (?, ?, ?)",
        [
            (ticker, datetime(2024, 1, 2, 14, 30), interval)
            for ticker in ("A", "B")
            for interval in intraday_readiness.REQUIRED_INTERVALS
        ],
    )
    monkeypatch.setattr(intraday_readiness, "MIN_TICKERS_PER_INTERVAL", 2)
    monkeypatch.setattr(
        intraday_readiness,
        "_session_bar_expectations",
        lambda first, last: [(first, interval, 2) for interval in ("1m", "5m")],
    )

    result = intraday_readiness.assess(con)

    assert result["minimum_usable_names_per_session"] == {"1m": 0, "5m": 0}
    assert result["qualifying_sessions"] == {"1m": 0, "5m": 0}


def test_intraday_breadth_rejects_dates_absent_from_exchange_schedule(con, monkeypatch):
    _init_inputs(con)
    con.executemany(
        "INSERT INTO intraday_prices VALUES (?, ?, ?)",
        [
            (ticker, datetime(2024, 1, 6, 14, minute), interval)
            for ticker in ("A", "B")
            for interval in intraday_readiness.REQUIRED_INTERVALS
            for minute in (30, 31)
        ],
    )
    monkeypatch.setattr(intraday_readiness, "MIN_TICKERS_PER_INTERVAL", 2)

    result = intraday_readiness.assess(con)

    assert result["observed_sessions"] == {"1m": 1, "5m": 1}
    assert result["minimum_usable_names_per_session"] == {"1m": 0, "5m": 0}
    assert result["qualifying_sessions"] == {"1m": 0, "5m": 0}


def test_early_thin_date_does_not_poison_later_qualifying_history(con, monkeypatch):
    _init_inputs(con)
    _insert_complete_dates(con, [date(2023, 12, 1)], tickers=("A",))
    qualifying_dates = [date(2024, 1, 2) + timedelta(days=offset) for offset in range(3)]
    _insert_complete_dates(con, qualifying_dates, tickers=("A", "B"))
    _set_limits(monkeypatch, observations=3, span_days=2, names=2)

    result = research_readiness.assess(con)
    families = result["families"]

    assert result["ready_families"] == ["fundamentals", "intraday", "stock_selection"]
    assert families["stock_selection"]["minimum_observed_names_per_date"] == 1
    assert families["stock_selection"]["qualifying_shared_dates"] == 3
    assert families["stock_selection"]["qualifying_first_date"] == "2024-01-02"
    assert families["fundamentals"]["qualifying_snapshots"] == 3
    assert families["intraday"]["qualifying_sessions"] == {"1m": 3, "5m": 3}


def test_ready_means_ready_for_charter_only(con, monkeypatch):
    _init_inputs(con)
    start = date(2024, 1, 2)
    dates = [start + timedelta(days=offset) for offset in range(3)]
    _insert_complete_dates(con, dates)
    _set_limits(monkeypatch)

    result = research_readiness.assess(con)

    assert result["ready_families"] == ["fundamentals", "intraday", "stock_selection"]
    assert {value["status"] for value in result["families"].values()} == {"READY_FOR_CHARTER"}
    assert result["automatic_action"] == "none"


def test_endpoint_closes_connection_and_returns_projection(monkeypatch):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    con = Connection()
    expected = {"purpose": "candidate_admission_only"}
    monkeypatch.setattr(main, "read_con", lambda: con)
    monkeypatch.setattr(main.readiness, "assess", lambda actual: expected if actual is con else {})

    assert main.research_readiness() == expected
    assert con.closed is True
