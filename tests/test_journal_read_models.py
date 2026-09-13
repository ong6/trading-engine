"""Tests for discretionary journal and recent league-event projections."""

from copy import deepcopy
from datetime import date, datetime, timezone

import pytest

from server import journal_read_models, read_model_utils
from tests.read_model_helpers import portfolio


def test_journal_rejects_valid_non_array_gate_json(con):
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, gates, status, created_at) VALUES "
        "(1, 'AAA', 'buy', 1, '{}', 'rejected', now()), "
        "(2, 'BBB', 'buy', 1, NULL, 'rejected', now())"
    )

    tickets = journal_read_models.journal(con)["discretionary"]["tickets"]

    assert tickets[0]["id"] == 2
    assert tickets[0]["gates"] == []
    assert "gates_error" not in tickets[0]
    assert tickets[1]["gates"] == []
    assert tickets[1]["gates_error"] == "not-an-array"
    assert "gates_raw" not in tickets[1]
    assert "gates_parse_error" not in tickets[1]


def test_journal_classifies_malformed_gate_json_without_disclosing_source(con):
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, gates, status, created_at) VALUES "
        "(1, 'AAA', 'buy', 1, ?, 'rejected', now())",
        ['[{"name":"first","name":"second"}]'],
    )

    ticket = journal_read_models.journal(con)["discretionary"]["tickets"][0]

    assert ticket["gates"] == []
    assert ticket["gates_error"] == "malformed-json"
    assert "gates_raw" not in ticket
    assert "gates_parse_error" not in ticket


def test_journal_rejects_invalid_gate_entries_without_disclosing_values(con):
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, gates, status, created_at) VALUES "
        "(1, 'AAA', 'buy', 1, ?, 'rejected', now())",
        ['[{"name":"position_size","status":"maybe","detail":{"secret":true}}]'],
    )

    ticket = journal_read_models.journal(con)["discretionary"]["tickets"][0]

    assert ticket["gates"] == []
    assert ticket["gates_error"] == "invalid-entries"
    assert "gates_raw" not in ticket
    assert "gates_parse_error" not in ticket


def test_journal_projects_only_admitted_gate_fields(con):
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, gates, status, created_at) VALUES "
        "(1, 'AAA', 'buy', 1, ?, 'rejected', now())",
        [
            '[{"name":"position_size","status":"pass","detail":"within cap",'
            '"internal":{"secret":true}}]'
        ],
    )

    ticket = journal_read_models.journal(con)["discretionary"]["tickets"][0]

    assert ticket["gates"] == [{"name": "position_size", "status": "pass", "detail": "within cap"}]
    assert "gates_error" not in ticket


def test_journal_bounds_stored_gate_content_without_parsing_it(monkeypatch):
    ticket = {"gates": "x" * (journal_read_models.MAX_STORED_GATES_CHARS + 1)}

    def unexpected_parse(_value):
        raise AssertionError("oversized stored gates must not be parsed")

    monkeypatch.setattr(journal_read_models, "loads_strict", unexpected_parse)

    journal_read_models._parse_ticket_gates(ticket)

    assert ticket == {"gates": [], "gates_error": "invalid-entries"}


def test_journal_bounds_valid_gate_arrays_and_fields():
    too_many = {
        "gates": "["
        + ",".join(
            '{"name":"gate","status":"pass","detail":"ok"}'
            for _ in range(journal_read_models.MAX_PUBLIC_GATES + 1)
        )
        + "]"
    }
    long_detail = {
        "gates": '[{"name":"gate","status":"pass","detail":"'
        + "x" * (journal_read_models.MAX_GATE_DETAIL_CHARS + 1)
        + '"}]'
    }

    journal_read_models._parse_ticket_gates(too_many)
    journal_read_models._parse_ticket_gates(long_detail)

    assert too_many == {"gates": [], "gates_error": "invalid-entries"}
    assert long_detail == {"gates": [], "gates_error": "invalid-entries"}


def test_journal_gate_bounds_count_unicode_code_points():
    exact = {
        "gates": '[{"name":"'
        + "💥" * journal_read_models.MAX_GATE_NAME_CHARS
        + '","status":"pass","detail":"'
        + "💥" * journal_read_models.MAX_GATE_DETAIL_CHARS
        + '"}]'
    }
    oversized = {
        "gates": '[{"name":"'
        + "💥" * (journal_read_models.MAX_GATE_NAME_CHARS + 1)
        + '","status":"pass","detail":"ok"}]'
    }

    journal_read_models._parse_ticket_gates(exact)
    journal_read_models._parse_ticket_gates(oversized)

    assert len(exact["gates"][0]["name"]) == journal_read_models.MAX_GATE_NAME_CHARS
    assert len(exact["gates"][0]["detail"]) == journal_read_models.MAX_GATE_DETAIL_CHARS
    assert oversized == {"gates": [], "gates_error": "invalid-entries"}


def test_journal_bounds_legacy_text_without_rewriting_stored_values(con):
    playbook = "p" * (journal_read_models.PLAYBOOK_MAX_CHARS + 1)
    emotion = "e" * (journal_read_models.EMOTION_MAX_CHARS + 1)
    notes = "n" * (journal_read_models.NOTES_MAX_CHARS + 1)
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, playbook, emotion, notes, gates, status, created_at) "
        "VALUES (1, 'AAA', 'buy', 1, ?, ?, ?, '[]', 'rejected', now())",
        [playbook, emotion, notes],
    )

    ticket = journal_read_models.journal(con)["discretionary"]["tickets"][0]

    assert ticket["playbook"] == playbook[: journal_read_models.PLAYBOOK_MAX_CHARS]
    assert ticket["emotion"] == emotion[: journal_read_models.EMOTION_MAX_CHARS]
    assert ticket["notes"] == notes[: journal_read_models.NOTES_MAX_CHARS]
    assert ticket["detail_truncated"] is True
    assert con.execute(
        "SELECT playbook, emotion, notes FROM disc_tickets WHERE id = 1"
    ).fetchone() == (playbook, emotion, notes)


def test_journal_groups_fills_by_ticket_order(con):
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, gates, status, order_id, created_at) VALUES "
        "(1, 'AAA', 'buy', 1, '[]', 'filled', 10, now()), "
        "(2, 'BBB', 'buy', 1, '[]', 'filled', 20, now()), "
        "(3, 'CCC', 'buy', 1, '[]', 'rejected', NULL, now())"
    )
    con.execute(
        "INSERT INTO sim_fills VALUES "
        "(20, 'discretionary', 'BBB', 'buy', 1, DATE '2026-09-03', 20, 20, 0, 0), "
        "(10, 'discretionary', 'AAA', 'buy', 1, DATE '2026-09-02', 10, 10, 0, 0), "
        "(99, 'unrelated', 'ZZZ', 'buy', 1, DATE '2026-09-04', 99, 99, 0, 0)"
    )

    tickets = journal_read_models.journal(con)["discretionary"]["tickets"]
    fills = {ticket["id"]: ticket["fills"] for ticket in tickets}

    assert [fill["ticker"] for fill in fills[1]] == ["AAA"]
    assert [fill["ticker"] for fill in fills[2]] == ["BBB"]
    assert fills[3] == []
    assert all("order_id" not in fill for ticket_fills in fills.values() for fill in ticket_fills)
    assert all(ticket["fills_limit"] == 100 for ticket in tickets)
    assert all(ticket["fills_matching_count"] in {0, 1} for ticket in tickets)
    assert all(ticket["fills_truncated"] is False for ticket in tickets)


def test_journal_bounds_each_visible_tickets_nested_fills(con, monkeypatch):
    monkeypatch.setattr(journal_read_models, "TICKET_FILLS_LIMIT", 2)
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, gates, status, order_id, created_at) VALUES "
        "(1, 'AAA', 'buy', 3, '[]', 'filled', 10, now())"
    )
    con.execute(
        "INSERT INTO sim_fills VALUES "
        "(10, 'discretionary', 'AAA', 'buy', 1, DATE '2026-09-01', 10, 10, 0, 0), "
        "(10, 'discretionary', 'AAA', 'buy', 1, DATE '2026-09-02', 11, 11, 0, 0), "
        "(10, 'discretionary', 'AAA', 'buy', 1, DATE '2026-09-03', 12, 12, 0, 0)"
    )

    ticket = journal_read_models.journal(con)["discretionary"]["tickets"][0]

    assert ticket["fills_limit"] == 2
    assert ticket["fills_matching_count"] == 3
    assert ticket["fills_truncated"] is True
    assert [fill["fill_date"] for fill in ticket["fills"]] == [
        date(2026, 9, 2),
        date(2026, 9, 3),
    ]


def test_journal_bounds_tickets_and_fetches_only_visible_ticket_fills(con, monkeypatch):
    monkeypatch.setattr(journal_read_models, "DISCRETIONARY_TICKETS_LIMIT", 2)
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, gates, status, order_id, created_at) VALUES "
        "(1, 'OLD', 'buy', 1, '[]', 'filled', 10, TIMESTAMP '2026-09-01 12:00:00'), "
        "(2, 'MID', 'buy', 1, '[]', 'filled', 20, TIMESTAMP '2026-09-02 12:00:00'), "
        "(3, 'NEW', 'buy', 1, '[]', 'filled', 30, TIMESTAMP '2026-09-03 12:00:00')"
    )
    con.execute(
        "INSERT INTO sim_fills VALUES "
        "(10, 'discretionary', 'OLD', 'buy', 1, DATE '2026-09-01', 10, 10, 0, 0), "
        "(20, 'discretionary', 'MID', 'buy', 1, DATE '2026-09-02', 20, 20, 0, 0), "
        "(30, 'discretionary', 'NEW', 'buy', 1, DATE '2026-09-03', 30, 30, 0, 0)"
    )

    discretionary = journal_read_models.journal(con)["discretionary"]

    assert discretionary["tickets_limit"] == 2
    assert discretionary["tickets_matching_count"] == 3
    assert discretionary["tickets_truncated"] is True
    assert [ticket["id"] for ticket in discretionary["tickets"]] == [3, 2]
    assert [ticket["fills"][0]["ticker"] for ticket in discretionary["tickets"]] == [
        "NEW",
        "MID",
    ]


def test_journal_bounds_round_trips_without_limiting_risk_history(con, monkeypatch):
    monkeypatch.setattr(journal_read_models, "ROUND_TRIPS_LIMIT", 2)
    complete_history = [
        {
            "ticker": ticker,
            "qty": 1.0,
            "entry_px": 10.0,
            "exit_px": 11.0,
            "exit_date": date(2026, 9, day),
            "realized_r": 1.0,
        }
        for ticker, day in (("OLD", 1), ("MID", 2), ("NEW", 3))
    ]
    calls = []

    def recent_round_trips(_con, limit):
        calls.append(("streamed-history", limit))
        return list(reversed(complete_history[-limit:])), len(complete_history)

    monkeypatch.setattr(journal_read_models.risk_history, "recent_round_trips", recent_round_trips)

    discretionary = journal_read_models.journal(con)["discretionary"]

    assert calls == [("streamed-history", 2)]
    assert discretionary["round_trips_limit"] == 2
    assert discretionary["round_trips_matching_count"] == 3
    assert discretionary["round_trips_truncated"] is True
    assert [trip["ticker"] for trip in discretionary["round_trips"]] == ["NEW", "MID"]


def test_journal_rejects_unsafe_round_trip_matching_count(con, monkeypatch):
    monkeypatch.setattr(
        journal_read_models.risk_history,
        "recent_round_trips",
        lambda _con, _limit: ([], read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1),
    )

    with pytest.raises(ValueError, match="public count is invalid"):
        journal_read_models.journal(con)


def test_journal_league_events_expose_only_active_portfolios(con):
    portfolio(con, "active")
    portfolio(con, "retired", active=False)
    con.execute(
        "INSERT INTO sim_fills VALUES "
        "(1, 'active', 'LIVE', 'buy', 2, DATE '2026-09-04', 10, 10, 0, 0), "
        "(2, 'retired', 'ARCHIVE', 'buy', 3, DATE '2026-09-04', 20, 20, 0, 0)"
    )

    journal = journal_read_models.journal(con)

    assert [row["portfolio_id"] for row in journal["league_events"]] == ["active"]
    assert journal["league_events_matching_count"] == 1
    assert journal["league_events_truncated"] is False


def test_journal_rejects_malformed_league_event_portfolio_identity(con):
    portfolio_id = "book\tother"
    portfolio(con, portfolio_id)
    con.execute(
        "INSERT INTO sim_fills VALUES (1, ?, 'LIVE', 'buy', 2, DATE '2026-09-04', 10, 10, 0, 0)",
        [portfolio_id],
    )

    with pytest.raises(ValueError, match="portfolio identifier is invalid"):
        journal_read_models.journal(con)
    assert con.execute("SELECT portfolio_id FROM sim_fills").fetchone()[0] == portfolio_id


def test_journal_rejects_malformed_stored_ticker(con):
    ticker = "BAD\tTICKER"
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, gates, status, created_at) VALUES "
        "(1, ?, 'buy', 1, '[]', 'rejected', now())",
        [ticker],
    )

    with pytest.raises(ValueError, match="ticker is invalid"):
        journal_read_models.journal(con)
    assert con.execute("SELECT ticker FROM disc_tickets").fetchone()[0] == ticker


@pytest.mark.parametrize("column", ["id", "order_id"])
def test_journal_rejects_unsafe_ticket_identifier_without_rewriting(con, column):
    unsafe = read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1
    values = {"id": 1, "order_id": 1}
    values[column] = unsafe
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, gates, status, order_id, created_at) "
        "VALUES (?, 'AAA', 'buy', 1, '[]', 'submitted', ?, now())",
        [values["id"], values["order_id"]],
    )

    with pytest.raises(ValueError, match="public identifier is invalid"):
        journal_read_models.journal(con)
    assert con.execute(f"SELECT {column} FROM disc_tickets").fetchone() == (unsafe,)


def test_journal_rejects_unsafe_league_event_identifier_without_rewriting(con):
    unsafe = read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1
    portfolio(con, "active")
    con.execute(
        "INSERT INTO sim_fills VALUES "
        "(?, 'active', 'LIVE', 'buy', 2, DATE '2026-09-04', 10, 10, 0, 0)",
        [unsafe],
    )

    with pytest.raises(ValueError, match="public identifier is invalid"):
        journal_read_models.journal(con)
    assert con.execute("SELECT order_id FROM sim_fills").fetchone() == (unsafe,)


def test_journal_bounds_and_counts_active_league_events(con):
    portfolio(con, "active")
    portfolio(con, "retired", active=False)
    active_fills = [
        (order_id, "active", f"T{order_id}", "buy", 1, date(2026, 9, 4), 10, 10, 0, 0)
        for order_id in range(1, 106)
    ]
    retired_fills = [
        (order_id, "retired", "OLD", "buy", 1, date(2026, 9, 4), 10, 10, 0, 0)
        for order_id in range(10_001, 10_004)
    ]
    con.executemany("INSERT INTO sim_fills VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", active_fills)
    con.executemany("INSERT INTO sim_fills VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", retired_fills)

    journal = journal_read_models.journal(con)

    assert journal["league_events_limit"] == journal_read_models.LEAGUE_EVENTS_LIMIT == 100
    assert journal["league_events_matching_count"] == 105
    assert journal["league_events_truncated"] is True
    assert [event["order_id"] for event in journal["league_events"]] == list(range(105, 5, -1))
    assert all("_matching_count" not in event for event in journal["league_events"])


def _valid_ticket(**overrides):
    ticket = {
        "id": 1,
        "ticker": "AAA",
        "side": "buy",
        "qty": 1.0,
        "entry_ref": 10.0,
        "stop": 9.0,
        "target": 12.0,
        "playbook": "breakout",
        "emotion": None,
        "notes": None,
        "gates": "[]",
        "status": "filled",
        "order_id": 1,
        "created_at": datetime(2026, 9, 4, 12),
    }
    return {**ticket, **overrides}


def _valid_journal_projection():
    return {
        "discretionary": {
            "tickets": [
                {
                    **_valid_ticket(),
                    "gates": [{"name": "position_size", "status": "pass", "detail": "within cap"}],
                    "detail_truncated": False,
                    "fills": [
                        {
                            "ticker": "AAA",
                            "side": "buy",
                            "qty": 1.0,
                            "fill_date": date(2026, 9, 4),
                            "fill_px": 10.0,
                        }
                    ],
                    "fills_limit": 100,
                    "fills_matching_count": 1,
                    "fills_truncated": False,
                }
            ],
            "tickets_limit": 100,
            "tickets_matching_count": 1,
            "tickets_truncated": False,
            "round_trips": [
                {
                    "ticker": "BBB",
                    "qty": 1.0,
                    "entry_px": 10.0,
                    "exit_px": 11.0,
                    "exit_date": date(2026, 9, 4),
                    "realized_r": 1.0,
                }
            ],
            "round_trips_limit": 100,
            "round_trips_matching_count": 1,
            "round_trips_truncated": False,
        },
        "league_events": [
            {
                "order_id": 2,
                "portfolio_id": "book-a",
                "ticker": "CCC",
                "side": "sell",
                "qty": 1.0,
                "fill_date": date(2026, 9, 4),
                "fill_px": 12.0,
            }
        ],
        "league_events_limit": 100,
        "league_events_matching_count": 1,
        "league_events_truncated": False,
    }


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ((), "public journal projection shape is invalid"),
        (("discretionary",), "public discretionary journal shape is invalid"),
        (("discretionary", "tickets", 0), "public journal ticket shape is invalid"),
        (
            ("discretionary", "tickets", 0, "fills", 0),
            "public journal fill shape is invalid",
        ),
        (
            ("discretionary", "round_trips", 0),
            "public journal round-trip shape is invalid",
        ),
        (("league_events", 0), "public journal league-event shape is invalid"),
    ],
)
def test_journal_final_projection_rejects_unreviewed_fields(path, message):
    payload = _valid_journal_projection()
    target = payload
    for key in path:
        target = target[key]
    target["internal"] = "not public"

    with pytest.raises(ValueError, match=message):
        journal_read_models._validate_journal_projection(payload)


def test_journal_final_projection_accepts_only_coherent_gate_errors():
    payload = _valid_journal_projection()
    ticket = payload["discretionary"]["tickets"][0]
    ticket["gates"] = []
    ticket["gates_error"] = "malformed-json"

    journal_read_models._validate_journal_projection(payload)

    invalid_code = deepcopy(payload)
    invalid_code["discretionary"]["tickets"][0]["gates_error"] = "parser-detail"
    with pytest.raises(ValueError, match="public journal gates error is invalid"):
        journal_read_models._validate_journal_projection(invalid_code)

    unnecessary = deepcopy(payload)
    unnecessary["discretionary"]["tickets"][0]["gates"] = [
        {"name": "gate", "status": "pass", "detail": "ok"}
    ]
    with pytest.raises(ValueError, match="public journal gates error is invalid"):
        journal_read_models._validate_journal_projection(unnecessary)


def test_journal_final_projection_rejects_false_ticket_truncation_marker():
    payload = _valid_journal_projection()
    payload["discretionary"]["tickets"][0]["detail_truncated"] = True

    with pytest.raises(ValueError, match="public ticket truncation marker is invalid"):
        journal_read_models._validate_journal_projection(payload)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"side": "hold"}, "public ticket side is invalid"),
        ({"qty": 0}, "public ticket quantity is invalid"),
        ({"qty": float("nan")}, "public ticket quantity is invalid"),
        ({"entry_ref": float("inf")}, "public ticket entry_ref is invalid"),
        ({"stop": float("nan")}, "public ticket stop is invalid"),
        ({"target": float("-inf")}, "public ticket target is invalid"),
        ({"playbook": 1}, "public ticket playbook is invalid"),
        ({"emotion": 1}, "public ticket emotion is invalid"),
        ({"notes": 1}, "public ticket notes is invalid"),
        ({"status": "unknown"}, "public ticket status is invalid"),
        ({"order_id": None}, "public ticket order link is invalid"),
        ({"status": "rejected"}, "public ticket order link is invalid"),
        ({"created_at": date(2026, 9, 4)}, "public ticket timestamp is invalid"),
        (
            {"created_at": datetime(2026, 9, 4, 12, tzinfo=timezone.utc)},
            "public ticket timestamp is invalid",
        ),
    ],
)
def test_journal_rejects_tickets_outside_the_browser_contract(overrides, message):
    with pytest.raises(ValueError, match=message):
        journal_read_models._validate_ticket(_valid_ticket(**overrides))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"ticker": "BBB"}, "public fill ticker is invalid"),
        ({"side": "sell"}, "public fill side is invalid"),
        ({"qty": 0}, "public fill quantity is invalid"),
        ({"fill_date": None}, "public fill date is invalid"),
        ({"fill_px": float("inf")}, "public fill price is invalid"),
    ],
)
def test_journal_rejects_nested_fills_outside_the_browser_contract(overrides, message):
    fill = {
        "ticker": "AAA",
        "side": "buy",
        "qty": 1.0,
        "fill_date": date(2026, 9, 4),
        "fill_px": 10.0,
    }
    fill.update(overrides)

    with pytest.raises(ValueError, match=message):
        journal_read_models._validate_fill(fill, ticker="AAA", side="buy")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("qty", 0, "public round-trip quantity is invalid"),
        ("entry_px", float("nan"), "public round-trip entry price is invalid"),
        ("exit_px", -1, "public round-trip exit price is invalid"),
        ("exit_date", None, "public round-trip exit date is invalid"),
        ("realized_r", float("inf"), "public round-trip realized R is invalid"),
    ],
)
def test_journal_rejects_round_trips_outside_the_browser_contract(field, value, message):
    round_trip = {
        "ticker": "AAA",
        "qty": 1.0,
        "entry_px": 10.0,
        "exit_px": 11.0,
        "exit_date": date(2026, 9, 4),
        "realized_r": 1.0,
    }
    round_trip[field] = value

    with pytest.raises(ValueError, match=message):
        journal_read_models._validate_round_trip(round_trip)


def test_journal_rejects_invalid_stored_ticket_quantity_without_rewriting(con):
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, gates, status, created_at) VALUES "
        "(1, 'AAA', 'buy', ?, '[]', 'rejected', now())",
        [float("nan")],
    )

    with pytest.raises(ValueError, match="public ticket quantity is invalid"):
        journal_read_models.journal(con)
    assert con.execute("SELECT isnan(qty) FROM disc_tickets").fetchone() == (True,)


def test_journal_rejects_invalid_stored_fill_price_without_rewriting(con):
    portfolio(con, "active")
    con.execute(
        "INSERT INTO sim_fills VALUES "
        "(1, 'active', 'AAA', 'buy', 1, DATE '2026-09-04', 10, ?, 0, 0)",
        [float("nan")],
    )

    with pytest.raises(ValueError, match="public fill price is invalid"):
        journal_read_models.journal(con)
    assert con.execute("SELECT isnan(fill_px) FROM sim_fills").fetchone() == (True,)


def test_journal_rejects_fill_that_does_not_match_its_ticket(con):
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, gates, status, order_id, created_at) VALUES "
        "(1, 'AAA', 'buy', 1, '[]', 'filled', 10, now())"
    )
    con.execute(
        "INSERT INTO sim_fills VALUES "
        "(10, 'discretionary', 'BBB', 'buy', 1, DATE '2026-09-04', 10, 10, 0, 0)"
    )

    with pytest.raises(ValueError, match="public fill ticker is invalid"):
        journal_read_models.journal(con)
