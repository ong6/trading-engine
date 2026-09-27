"""Production transfer coefficients use active risk and exclude SPY from primary TC."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import duckdb

from engine.lib import db
from server import p16_book_store, p16_store, p16_transfer
from sim import nyse

REGISTRATION = "a" * 64
CUTOFF = datetime(2026, 9, 28, 15, tzinfo=timezone.utc)


def _sessions(through: date, count: int) -> list[date]:
    values, current = [], through
    while len(values) < count:
        if nyse.is_session(current):
            values.append(current)
        current -= timedelta(days=1)
    return list(reversed(values))


def _database():
    con = duckdb.connect(":memory:")
    db.init_schema(con)
    p16_book_store.init_schema(con)
    signal_date = date(2026, 9, 25)
    sessions = _sessions(signal_date, 61)
    rows = []
    for index, session in enumerate(sessions):
        for ticker, slope in (("SPY", 1.0), ("AAA", 1.01), ("BBB", 0.99), ("CCC", 1.02)):
            close = 100 + slope * index + (0.2 if ticker == "BBB" and index % 2 else 0)
            rows.append((ticker, session, close, close, close, close, 1_000_000,
                         "test", CUTOFF.replace(tzinfo=None)))
    con.executemany("INSERT INTO prices VALUES (?,?,?,?,?,?,?,?,?)", rows)
    con.execute("""CREATE TABLE agent_evaluation_traces (
        id BIGINT, policy_id VARCHAR, market_date DATE, terminal_status VARCHAR,
        completed_at TIMESTAMP)""")
    con.execute("""CREATE TABLE agent_evaluation_decisions (
        id BIGINT, trace_id BIGINT, ticker VARCHAR, decision_payload VARCHAR)""")
    con.execute(
        "INSERT INTO agent_evaluation_traces VALUES (1,'p15-scoring-v1',?,'completed',?)",
        [signal_date, CUTOFF.replace(tzinfo=None)],
    )
    for index, ticker in enumerate(("AAA", "BBB", "CCC"), 1):
        payload = {"ticker": ticker, "expected_excess_bp_5": index * 10,
                   "baseline_rank": 4 - index}
        con.execute(
            "INSERT INTO agent_evaluation_decisions VALUES (?,?,?,?)",
            [index, 1, ticker, json.dumps(payload)],
        )
    instances = p16_book_store.initialize_contracts(
        con, registration_sha256=REGISTRATION, activation_date=None,
        risk_aversion=5, cost_per_turnover=0.0005, created_at=CUTOFF,
    )
    holding_date = nyse.next_session(signal_date)
    for ticker, open_px in (("SPY", 161.0), ("AAA", 162.0), ("BBB", 160.0), ("CCC", 163.0)):
        con.execute(
            "INSERT INTO prices VALUES (?,?,?,?,?,?,?,?,?)",
            [ticker, holding_date, open_px, open_px, open_px, open_px, 1_000_000,
             "test", CUTOFF.replace(tzinfo=None)],
        )
    for book_id in (*p16_transfer.BOOK_POLICIES.keys(),):
        if book_id.startswith("p16_"):
            continue
        con.execute(
            "INSERT INTO portfolios VALUES (?,?,'noop','{}',?,TRUE,0,10000,'baseline_v1')",
            [book_id, book_id, signal_date],
        )
    for instance in instances:
        con.execute("UPDATE portfolios SET active=TRUE,cash=0 WHERE id=?", [instance])
    all_instances = [*filter(lambda value: value.startswith("p15_"),
                             p16_transfer.BOOK_POLICIES), *instances]
    for instance in all_instances:
        con.executemany(
            "INSERT INTO sim_positions VALUES (?,?,?,?)",
            [(instance, "AAA", 10, 100), (instance, "BBB", 10, 100),
             (instance, "CCC", 7.5, 100), (instance, "SPY", 72.5, 100)],
        )
        con.execute(
            "INSERT INTO sim_equity VALUES (?,?,?,?,4)",
            [instance, holding_date, 10_000.0, 0.0],
        )
    return con, signal_date, holding_date


def test_producer_emits_all_five_books_with_spy_excluded_primary():
    con, signal_date, holding_date = _database()
    result = p16_transfer.produce(
        con, registration_sha256=REGISTRATION, signal_date=signal_date,
        holding_date=holding_date, information_cutoff_at=CUTOFF,
        trailing_ic={"champion": 0.03, "rule": 0.02},
    )
    assert [row["book_id"] for row in result["books"]] == list(
        p16_transfer.BOOK_POLICIES,
    )
    assert all(row["status"] == "available" for row in result["books"])
    assert all(row["primary_instruments"] == "stocks_only_spy_and_cash_excluded"
               for row in result["books"])
    assert all(row["sigma_basis"] == "stock_minus_spy_daily_return_sd60_ddof1"
               for row in result["books"])
    assert result["books"][1]["tc_diagonal"] > 0
    artifact = p16_store.record_transfer(
        con, registration_sha256=REGISTRATION, market_date=signal_date,
        information_cutoff_at=CUTOFF, recorded_at=CUTOFF, payload=result,
    )
    assert len(artifact) == 64


def test_held_name_without_same_vintage_score_makes_primary_unavailable():
    con, signal_date, holding_date = _database()
    instance = f"p16_construct_ai@sha256:{REGISTRATION}"
    con.execute("INSERT INTO sim_positions VALUES (?, 'ZZZ', 1, 10)", [instance])
    con.execute(
        "INSERT INTO prices VALUES ('ZZZ',?,10,10,10,10,100,'test',?)",
        [holding_date, CUTOFF.replace(tzinfo=None)],
    )
    result = p16_transfer.produce(
        con, registration_sha256=REGISTRATION, signal_date=signal_date,
        holding_date=holding_date, information_cutoff_at=CUTOFF,
        trailing_ic={"champion": 0.03, "rule": 0.02},
    )
    row = next(item for item in result["books"] if item["book_id"] == "p16_construct_ai")
    assert row["status"] == "unavailable"
    assert row["reason"] == "held_name_missing_score_or_risk"


def test_rule_score_is_negative_baseline_rank_and_nonpositive_ic_is_unavailable():
    con, signal_date, holding_date = _database()
    result = p16_transfer.produce(
        con, registration_sha256=REGISTRATION, signal_date=signal_date,
        holding_date=holding_date, information_cutoff_at=CUTOFF,
        trailing_ic={"champion": 0.03, "rule": -0.01},
    )
    rule = next(item for item in result["books"] if item["book_id"] == "p15_rule_control")
    assert rule["status"] == "unavailable"
    assert rule["reason"] == "nonpositive_trailing_ic"
    assert rule["tc_diagonal"] is None
