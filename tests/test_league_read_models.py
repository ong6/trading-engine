"""Tests for league and equity read models."""

from datetime import date, datetime, timedelta

import pytest

from server import league_equity_read_models, league_read_models, read_model_utils
from tests.conftest import insert_bars
from tests.read_model_helpers import liquid_universe, portfolio


def test_league_uses_persisted_capital_and_ranks_returns(con):
    days = [date(2026, 9, day) for day in range(1, 7)]
    liquid_universe(con, ("SPY",))
    insert_bars(con, "SPY", days, close=[100, 101, 102, 103, 104, 105])
    for portfolio_id, ending_equity in (("winner", 120.0), ("loser", 90.0)):
        con.execute(
            "INSERT INTO portfolios "
            "(id, name, strategy, config, created, active, cash, initial_cash, "
            "execution_profile) VALUES (?, ?, 'x', '{}', ?, TRUE, 100, 100, 'baseline_v1')",
            [portfolio_id, portfolio_id.title(), days[0]],
        )
        for offset, day in enumerate(days):
            equity = 100 + (ending_equity - 100) * offset / 5
            con.execute(
                "INSERT INTO sim_equity VALUES (?, ?, ?, 100, 0)",
                [portfolio_id, day, equity],
            )

    result = league_read_models.league(con)

    assert result["as_of"] == days[-1]
    assert result["regime"] == "unknown"
    assert result["reference_notional"] == pytest.approx(39_000.0)
    assert result["ranking_basis"] == "total_return_since_each_portfolio_inception"
    assert result["comparison_basis"] == "SPY_over_each_portfolio_inception_window"
    assert result["evidence_role"] == "operational_only"
    assert "not evidence of profitability" in result["notice"]
    assert result["limit"] == league_read_models.LEAGUE_ROWS_LIMIT
    assert result["matching_count"] == 2
    assert result["truncated"] is False
    assert [row["id"] for row in result["rows"]] == ["winner", "loser"]
    assert [row["rank"] for row in result["rows"]] == [1, 2]
    assert result["rows"][0]["total_ret"] == pytest.approx(0.2)
    assert result["rows"][0]["equity_as_of"] == days[-1]
    assert result["rows"][0]["current"] is True
    assert result["rows"][0]["last5"] == pytest.approx(0.2)
    assert result["rows"][0]["vs_spy"] == pytest.approx(0.15)
    assert league_read_models.equity(con, "winner")["equity"][-1]["equity"] == pytest.approx(120.0)


def test_equity_payload_rejects_unsafe_matching_count():
    with pytest.raises(ValueError, match="public count is invalid"):
        league_equity_read_models._equity_payload(
            "book",
            date(2026, 9, 4),
            [],
            read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1,
        )


def test_bulk_equity_rejects_unsafe_portfolio_matching_count(con):
    with pytest.raises(ValueError, match="public count is invalid"):
        league_equity_read_models.project_equities(
            con,
            [],
            None,
            portfolio_matching_count=read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1,
            portfolio_limit=league_read_models.LEAGUE_ROWS_LIMIT,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("portfolio_id", "bad\tbook", "portfolio identifier"),
        ("date", datetime(2026, 9, 4), "public equity date"),
        ("equity", float("inf"), "public equity value"),
        ("cash", float("nan"), "public equity cash"),
        (
            "n_positions",
            read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1,
            "public count",
        ),
    ],
)
def test_equity_payload_rejects_malformed_public_row(field, value, message):
    row = {
        "portfolio_id": "book",
        "date": date(2026, 9, 4),
        "equity": 39_000.0,
        "cash": 1_000.0,
        "n_positions": 2,
    }
    row[field] = value

    with pytest.raises(ValueError, match=message):
        league_equity_read_models._equity_payload("book", date(2026, 9, 4), [row], 1)


def test_equity_payload_rejects_wrong_book_and_unordered_dates():
    wrong_book = {
        "portfolio_id": "other",
        "date": date(2026, 9, 4),
        "equity": 39_000.0,
        "cash": 1_000.0,
        "n_positions": 2,
    }
    with pytest.raises(ValueError, match="public equity portfolio"):
        league_equity_read_models._equity_payload("book", date(2026, 9, 4), [wrong_book], 1)

    latest = {**wrong_book, "portfolio_id": "book"}
    earlier = {**latest, "date": date(2026, 9, 3)}
    with pytest.raises(ValueError, match="strictly ordered"):
        league_equity_read_models._equity_payload("book", date(2026, 9, 4), [latest, earlier], 2)


def test_equity_payload_accepts_exact_safe_position_count():
    row = {
        "portfolio_id": "book",
        "date": date(2026, 9, 4),
        "equity": 39_000.0,
        "cash": 1_000.0,
        "n_positions": read_model_utils.PUBLIC_SAFE_INTEGER_MAX,
    }

    assert league_equity_read_models._equity_payload("book", date(2026, 9, 4), [row], 1)[
        "equity"
    ] == [row]


def test_equity_projection_rejects_extra_envelope_and_row_fields():
    row = {
        "portfolio_id": "book",
        "date": date(2026, 9, 4),
        "equity": 39_000.0,
        "cash": 1_000.0,
        "n_positions": 2,
    }
    payload = league_equity_read_models._equity_payload("book", date(2026, 9, 4), [row], 1)

    with pytest.raises(ValueError, match="projection shape"):
        league_equity_read_models._validate_equity_projection(
            {**payload, "internal": "not public"}, "book"
        )
    with pytest.raises(ValueError, match="row shape"):
        league_equity_read_models._equity_payload(
            "book", date(2026, 9, 4), [{**row, "internal": "not public"}], 1
        )


def test_bulk_equity_projection_rejects_extra_envelope_and_row_fields(con):
    portfolio(con, "book")
    as_of = date(2026, 9, 4)
    con.execute("INSERT INTO sim_equity VALUES ('book', ?, 39000, 1000, 2)", [as_of])
    payload = league_equity_read_models.project_equities(
        con,
        ["book"],
        as_of,
        portfolio_matching_count=1,
        portfolio_limit=league_read_models.LEAGUE_ROWS_LIMIT,
    )

    with pytest.raises(ValueError, match="projection shape"):
        league_equity_read_models._validate_equities_projection(
            {**payload, "internal": "not public"},
            expected_portfolio_ids=["book"],
            expected_portfolio_limit=league_read_models.LEAGUE_ROWS_LIMIT,
        )
    malformed = {
        **payload,
        "equity_by_portfolio": {
            "book": [
                {
                    **payload["equity_by_portfolio"]["book"][0],
                    "internal": "not public",
                }
            ]
        },
    }
    with pytest.raises(ValueError, match="row shape"):
        league_equity_read_models._validate_equities_projection(
            malformed,
            expected_portfolio_ids=["book"],
            expected_portfolio_limit=league_read_models.LEAGUE_ROWS_LIMIT,
        )


def test_league_projection_rejects_extra_envelope_and_row_fields(con, monkeypatch):
    operational = date(2026, 9, 4)
    portfolio(con, "book")
    con.execute(
        "INSERT INTO sim_equity VALUES ('book', ?, 39000, 39000, 0)",
        [operational],
    )
    monkeypatch.setattr(league_read_models, "latest_prices_date", lambda _con: operational)
    payload = league_read_models.league(con)

    with pytest.raises(ValueError, match="projection shape"):
        league_read_models._validate_league_projection({**payload, "internal": "not public"})
    malformed = {**payload, "rows": [{**payload["rows"][0], "internal": "not public"}]}
    with pytest.raises(ValueError, match="row shape"):
        league_read_models._validate_league_projection(malformed)


def test_league_return_ties_follow_unicode_code_point_order(con, monkeypatch):
    operational = date(2026, 9, 4)
    for portfolio_id in ("\uF900", "\U00010000"):
        portfolio(con, portfolio_id)
        con.execute(
            "INSERT INTO sim_equity VALUES (?, ?, 39000, 39000, 0)",
            [portfolio_id, operational],
        )
    monkeypatch.setattr(league_read_models, "latest_prices_date", lambda _con: operational)
    monkeypatch.setattr(league_read_models, "_spy_return", lambda *_args: 0.0)

    payload = league_read_models.league(con)

    assert [row["id"] for row in payload["rows"]] == ["\uF900", "\U00010000"]
    payload["rows"].reverse()
    payload["rows"][0]["rank"] = 1
    payload["rows"][1]["rank"] = 2
    with pytest.raises(ValueError, match="not ordered"):
        league_read_models._validate_league_projection(payload)


def test_league_reuses_spy_context_for_shared_inception(con, monkeypatch):
    shared_inception = date(2026, 9, 1)
    for portfolio_id in ("one", "two"):
        portfolio(con, portfolio_id)
        con.execute(
            "INSERT INTO sim_equity VALUES (?, DATE '2026-09-04', 100, 100, 0)",
            [portfolio_id],
        )
    monkeypatch.setattr(league_read_models, "latest_prices_date", lambda _con: date(2026, 9, 4))
    calls = []

    def spy_return(_con, inception, as_of):
        calls.append((inception, as_of))
        return 0.01

    monkeypatch.setattr(league_read_models, "_spy_return", spy_return)

    result = league_read_models.league(con)

    assert len(result["rows"]) == 2
    assert calls == [(shared_inception, date(2026, 9, 4))]


def test_league_caps_standings_equity_at_operational_date(con, monkeypatch):
    operational = date(2026, 9, 4)
    future = date(2026, 9, 8)
    portfolio(con, "book")
    con.execute(
        "INSERT INTO sim_equity VALUES ('book', ?, 39000, 39000, 0), ('book', ?, 99999, 99999, 0)",
        [operational, future],
    )
    monkeypatch.setattr(league_read_models, "latest_prices_date", lambda _con: operational)

    result = league_read_models.league(con)

    assert result["as_of"] == operational
    assert result["rows"][0]["equity"] == pytest.approx(39_000)
    assert result["rows"][0]["equity_as_of"] == operational
    assert result["rows"][0]["current"] is True
    equity = league_read_models.equity(con, "book")
    assert equity["as_of"] == operational
    assert equity["matching_count"] == 1
    assert equity["equity"][-1]["date"] == operational


@pytest.mark.parametrize("as_of", [datetime(2026, 9, 4), "2026-09-04"])
def test_league_projections_reject_non_date_as_of(con, monkeypatch, as_of):
    monkeypatch.setattr(league_read_models, "latest_prices_date", lambda _con: as_of)

    with pytest.raises(ValueError, match="league as-of date"):
        league_read_models.league(con)
    with pytest.raises(ValueError, match="league as-of date"):
        league_read_models.equities(con)


def test_league_keeps_stale_active_book_visible_but_unranked(con, monkeypatch):
    stale = date(2026, 9, 3)
    operational = date(2026, 9, 4)
    for portfolio_id in ("current", "stale"):
        portfolio(con, portfolio_id)
    con.execute(
        "INSERT INTO sim_equity VALUES "
        "('current', ?, 39000, 39000, 0), ('stale', ?, 99999, 99999, 0)",
        [operational, stale],
    )
    monkeypatch.setattr(league_read_models, "latest_prices_date", lambda _con: operational)
    comparison_dates = []
    monkeypatch.setattr(
        league_read_models,
        "_spy_return",
        lambda _con, _created, as_of: comparison_dates.append(as_of) or 0.0,
    )

    result = league_read_models.league(con)

    assert [row["id"] for row in result["rows"]] == ["current", "stale"]
    assert [row["rank"] for row in result["rows"]] == [1, None]
    assert [row["current"] for row in result["rows"]] == [True, False]
    assert [row["equity_as_of"] for row in result["rows"]] == [operational, stale]
    assert comparison_dates == [operational, stale]


def test_league_streams_complete_history_into_bounded_statistics(con, monkeypatch):
    days = [date(2026, 8, day) for day in range(1, 8)]
    equities = [100.0, 120.0, 90.0, 95.0, 80.0, 100.0, 110.0]
    portfolio(con, "book")
    con.executemany(
        "INSERT INTO sim_equity VALUES ('book', ?, ?, 100, 0)",
        list(zip(days, equities, strict=True)),
    )
    monkeypatch.setattr(league_read_models, "EQUITY_SCAN_BATCH_SIZE", 2)
    monkeypatch.setattr(league_read_models, "latest_prices_date", lambda _con: days[-1])
    monkeypatch.setattr(league_read_models, "_spy_return", lambda *_args: 0.0)
    monkeypatch.setattr(league_read_models, "regime_label", lambda *_args: "unknown")

    row = league_read_models.league(con)["rows"][0]

    assert row["equity_as_of"] == days[-1]
    assert row["equity"] == pytest.approx(110.0)
    assert row["mdd"] == pytest.approx(80 / 120 - 1)
    assert row["last5"] == pytest.approx(110 / 120 - 1)


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("name", "   ", "portfolio name"),
        ("initial_cash", 0.0, "portfolio initial cash"),
        ("initial_cash", float("inf"), "portfolio initial cash"),
        ("execution_profile", "", "execution profile"),
    ],
)
def test_league_rejects_malformed_active_portfolio_fields(con, monkeypatch, column, value, message):
    operational = date(2026, 9, 4)
    portfolio(con, "book")
    con.execute(f"UPDATE portfolios SET {column} = ? WHERE id = 'book'", [value])
    con.execute(
        "INSERT INTO sim_equity VALUES ('book', ?, 39000, 39000, 0)",
        [operational],
    )
    monkeypatch.setattr(league_read_models, "latest_prices_date", lambda _con: operational)

    with pytest.raises(ValueError, match=message):
        league_read_models.league(con)

    assert con.execute(f"SELECT {column} FROM portfolios WHERE id = 'book'").fetchone()[0] == value


def test_league_ignores_nonpublic_metadata_for_active_book_without_equity(con, monkeypatch):
    portfolio(con, "empty")
    con.execute("UPDATE portfolios SET name = '   ' WHERE id = 'empty'")
    monkeypatch.setattr(league_read_models, "latest_prices_date", lambda _con: date(2026, 9, 4))

    assert league_read_models.league(con)["rows"] == []


@pytest.mark.parametrize("as_of", [datetime(2026, 9, 4), "2026-09-04"])
def test_empty_equity_projections_reject_non_date_as_of(con, as_of):
    portfolio(con, "book")

    with pytest.raises(ValueError, match="equity as-of date"):
        league_equity_read_models.project_equity(con, "book", lambda _con: as_of)
    with pytest.raises(ValueError, match="equity as-of date"):
        league_equity_read_models.project_equities(
            con,
            [],
            as_of,
            portfolio_matching_count=0,
            portfolio_limit=league_read_models.LEAGUE_ROWS_LIMIT,
        )


@pytest.mark.parametrize("equity", [float("nan"), float("inf")])
def test_league_rejects_nonfinite_equity_without_rewriting(con, monkeypatch, equity):
    operational = date(2026, 9, 4)
    portfolio(con, "book")
    con.execute("INSERT INTO sim_equity VALUES ('book', ?, ?, 39000, 0)", [operational, equity])
    monkeypatch.setattr(league_read_models, "latest_prices_date", lambda _con: operational)

    with pytest.raises(ValueError, match="league equity"):
        league_read_models.league(con)

    stored = con.execute("SELECT equity FROM sim_equity WHERE portfolio_id = 'book'").fetchone()[0]
    assert (stored != stored) if equity != equity else stored == equity


def test_league_rejects_nonfinite_derived_returns(con, monkeypatch):
    operational = date(2026, 9, 4)
    portfolio(con, "book")
    con.execute("UPDATE portfolios SET initial_cash = 1e-308 WHERE id = 'book'")
    con.execute("INSERT INTO sim_equity VALUES ('book', ?, 1e308, 39000, 0)", [operational])
    monkeypatch.setattr(league_read_models, "latest_prices_date", lambda _con: operational)

    with pytest.raises(ValueError, match="league total return"):
        league_read_models.league(con)


def test_league_rejects_invalid_comparison_return_and_regime(con, monkeypatch):
    operational = date(2026, 9, 4)
    portfolio(con, "book")
    con.execute("INSERT INTO sim_equity VALUES ('book', ?, 39000, 39000, 0)", [operational])
    monkeypatch.setattr(league_read_models, "latest_prices_date", lambda _con: operational)
    monkeypatch.setattr(league_read_models, "_spy_return", lambda *_args: float("nan"))

    with pytest.raises(ValueError, match="league comparison return"):
        league_read_models.league(con)

    monkeypatch.setattr(league_read_models, "_spy_return", lambda *_args: 0.0)
    monkeypatch.setattr(league_read_models, "regime_label", lambda *_args: "maybe")
    with pytest.raises(ValueError, match="league regime"):
        league_read_models.league(con)


def test_league_recent_return_with_zero_start_is_unavailable(con, monkeypatch):
    days = [date(2026, 9, day) for day in range(1, 7)]
    portfolio(con, "book")
    con.executemany(
        "INSERT INTO sim_equity VALUES ('book', ?, ?, 0, 0)",
        [(day, equity) for day, equity in zip(days, [0, 1, 2, 3, 4, 5], strict=True)],
    )
    monkeypatch.setattr(league_read_models, "latest_prices_date", lambda _con: days[-1])
    monkeypatch.setattr(league_read_models, "_spy_return", lambda *_args: 0.0)

    assert league_read_models.league(con)["rows"][0]["last5"] is None


def test_league_bounds_serialized_rows_after_complete_deterministic_ranking(con, monkeypatch):
    operational = date(2026, 9, 4)
    for portfolio_id, equity in (("z-low", 90), ("a-mid", 110), ("m-high", 120)):
        portfolio(con, portfolio_id)
        con.execute(
            "UPDATE portfolios SET initial_cash = 100 WHERE id = ?",
            [portfolio_id],
        )
        con.execute(
            "INSERT INTO sim_equity VALUES (?, ?, ?, 100, 0)",
            [portfolio_id, operational, equity],
        )
    monkeypatch.setattr(league_read_models, "LEAGUE_ROWS_LIMIT", 2)
    monkeypatch.setattr(league_read_models, "latest_prices_date", lambda _con: operational)
    monkeypatch.setattr(league_read_models, "_spy_return", lambda *_args: 0.0)

    result = league_read_models.league(con)
    bulk = league_read_models.equities(con)

    assert [row["id"] for row in result["rows"]] == ["m-high", "a-mid"]
    assert [row["rank"] for row in result["rows"]] == [1, 2]
    assert result["limit"] == 2
    assert result["matching_count"] == 3
    assert result["truncated"] is True
    assert list(bulk["equity_by_portfolio"]) == ["m-high", "a-mid"]
    assert bulk["portfolio_limit"] == result["limit"]
    assert bulk["portfolio_matching_count"] == result["matching_count"]
    assert bulk["portfolios_truncated"] is result["truncated"]


def test_equity_projection_exposes_only_active_portfolios(con, monkeypatch):
    monkeypatch.setattr(league_read_models, "latest_prices_date", lambda _con: date(2026, 9, 4))
    portfolio(con, "active")
    portfolio(con, "retired", active=False)
    con.execute(
        "INSERT INTO sim_equity VALUES "
        "('active', DATE '2026-09-04', 101, 100, 1), "
        "('retired', DATE '2026-09-04', 99, 100, 1)"
    )

    assert league_read_models.equity(con, "active")["equity"][0]["equity"] == pytest.approx(101)
    assert league_read_models.equity(con, "retired") is None
    assert league_read_models.equity(con, "unknown") is None


@pytest.mark.parametrize("portfolio_id", ["book\nother", " book", "x" * 129])
def test_league_rejects_malformed_active_portfolio_identity(con, monkeypatch, portfolio_id):
    monkeypatch.setattr(league_read_models, "latest_prices_date", lambda _con: date(2026, 9, 4))
    portfolio(con, portfolio_id)
    con.execute(
        "INSERT INTO sim_equity VALUES (?, DATE '2026-09-04', 101, 100, 1)",
        [portfolio_id],
    )

    with pytest.raises(ValueError, match="portfolio identifier is invalid"):
        league_read_models.league(con)
    with pytest.raises(ValueError, match="portfolio identifier is invalid"):
        league_read_models.equities(con)
    assert con.execute("SELECT id FROM portfolios").fetchone()[0] == portfolio_id


def test_single_equity_rejects_malformed_requested_portfolio_identity(con):
    with pytest.raises(ValueError, match="portfolio identifier is invalid"):
        league_read_models.equity(con, " book")


def test_bulk_equity_projection_matches_active_per_book_series(con, monkeypatch):
    monkeypatch.setattr(league_read_models, "latest_prices_date", lambda _con: date(2026, 9, 4))
    portfolio(con, "active")
    portfolio(con, "empty")
    portfolio(con, "retired", active=False)
    con.execute(
        "INSERT INTO sim_equity VALUES "
        "('active', DATE '2026-09-03', 100, 90, 1), "
        "('active', DATE '2026-09-04', 101, 91, 1), "
        "('retired', DATE '2026-09-04', 99, 89, 1)"
    )

    result = league_read_models.equities(con)

    assert result["limit_per_portfolio"] == league_read_models.EQUITY_SERIES_LIMIT
    assert result["as_of"] == date(2026, 9, 4)
    assert list(result["equity_by_portfolio"]) == ["active"]
    assert (
        result["equity_by_portfolio"]["active"]
        == league_read_models.equity(con, "active")["equity"]
    )
    assert result["portfolio_limit"] == league_read_models.LEAGUE_ROWS_LIMIT
    assert result["portfolio_matching_count"] == 1
    assert result["portfolios_truncated"] is False
    assert result["matching_count_by_portfolio"] == {"active": 2}
    assert result["truncated_by_portfolio"] == {"active": False}


def test_equity_projections_bound_each_series_without_changing_totals(con, monkeypatch):
    portfolio(con, "long")
    portfolio(con, "short")
    limit = league_read_models.EQUITY_SERIES_LIMIT
    start = date(2024, 1, 1)
    as_of = start + timedelta(days=limit + 2)
    monkeypatch.setattr(league_read_models, "latest_prices_date", lambda _con: as_of)
    long_rows = [
        ("long", start + timedelta(days=index), 39_000 + index, 1_000, 1)
        for index in range(limit + 3)
    ]
    short_rows = [
        ("short", start + timedelta(days=index), 39_000 + index, 1_000, 1) for index in range(2)
    ]
    con.executemany("INSERT INTO sim_equity VALUES (?, ?, ?, ?, ?)", long_rows + short_rows)

    single = league_read_models.equity(con, "long")
    bulk = league_read_models.equities(con)

    assert single["portfolio_id"] == "long"
    assert single["as_of"] == as_of
    assert single["limit"] == limit
    assert single["matching_count"] == limit + 3
    assert single["truncated"] is True
    assert [row["date"] for row in single["equity"]] == [row[1] for row in long_rows[-limit:]]
    assert bulk["matching_count_by_portfolio"] == {"long": limit + 3, "short": 2}
    assert bulk["as_of"] == as_of
    assert bulk["truncated_by_portfolio"] == {"long": True, "short": False}
    assert bulk["equity_by_portfolio"]["long"] == single["equity"]
    assert bulk["equity_by_portfolio"]["short"] == league_read_models.equity(con, "short")["equity"]
