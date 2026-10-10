"""Production transfer coefficients use active risk and exclude SPY from primary TC."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import duckdb
import pytest

from engine.lib import db
from engine.lib.provenance import canonical_sha256
from server import p16_book_store, p16_store, p16_transfer
from sim import nyse, p15_books
from tests.conftest import record_p16_calibration

REGISTRATION = "a" * 64
CUTOFF = datetime(2026, 9, 28, 15, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _validated_inputs(monkeypatch):
    scores = {
        "AAA": {"champion": 10.0, "rule": -3.0},
        "BBB": {"champion": 20.0, "rule": -2.0},
        "CCC": {"champion": 30.0, "rule": -1.0},
    }
    monkeypatch.setattr(p16_transfer, "_score_snapshot", lambda *_args, **_kwargs: {
        "scores": scores, "score_sha256": canonical_sha256(scores),
        "input_snapshot_sha256": "e" * 64,
        "scoring_cutoff": CUTOFF.replace(tzinfo=None),
    })
    monkeypatch.setattr(p16_transfer, "_trailing_ics", lambda *_args, **_kwargs: {
        "status": "available", "reason": None,
        "values": {"champion": 0.03, "rule": 0.02},
        "origin_dates": ["2026-09-01"] * 60, "source_sha256": "d" * 64,
    })


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
    p15_books.init_schema(con)
    signal_date = date(2026, 9, 25)
    sessions = _sessions(signal_date, 121)
    rows = []
    for index, session in enumerate(sessions):
        for ticker, slope in (("SPY", 1.0), ("AAA", 1.01), ("BBB", 0.99), ("CCC", 1.02)):
            close = 100 + slope * index + (0.2 if ticker == "BBB" and index % 2 else 0)
            rows.append((ticker, session, close, close + 1, close - 1, close, 1_000_000,
                         "test", CUTOFF.replace(tzinfo=None)))
    con.executemany(
        "INSERT INTO prices "
        "(ticker,date,open,high,low,close,volume,source,fetched_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)", rows,
    )
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
        calibration_sha256=record_p16_calibration(con, REGISTRATION, CUTOFF),
        created_at=CUTOFF,
    )
    holding_date = nyse.next_session(signal_date)
    signal_cutoff = datetime(2026, 9, 25, 20, tzinfo=timezone.utc)
    for ticker, open_px in (("SPY", 200.0), ("AAA", 202.0), ("BBB", 198.0), ("CCC", 203.0)):
        con.execute(
            "INSERT INTO prices "
            "(ticker,date,open,high,low,close,volume,source,fetched_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [ticker, holding_date, open_px, open_px + 1, open_px - 1, open_px, 1_000_000,
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
        con.execute("UPDATE portfolios SET active=TRUE,cash=1000 WHERE id=?", [instance])
    all_instances = [*filter(lambda value: value.startswith("p15_"),
                             p16_transfer.BOOK_POLICIES), *instances]
    order_id = 1
    for instance in all_instances:
        con.execute("UPDATE portfolios SET cash=1000 WHERE id=?", [instance])
        con.executemany(
            "INSERT INTO sim_positions VALUES (?,?,?,?)",
            [(instance, "AAA", 5, 200), (instance, "BBB", 5, 200),
             (instance, "CCC", 5, 200), (instance, "SPY", 30, 200)],
        )
        for ticker, quantity in (("AAA", 5), ("BBB", 5), ("CCC", 5), ("SPY", 30)):
            con.execute(
                "INSERT INTO sim_fills VALUES (?,?,?,?,?,?,?,?,?,?)",
                [order_id, instance, ticker, "buy", quantity, holding_date,
                 200, 200, 0, 0],
            )
            if instance.startswith("p16_"):
                intent_id = canonical_sha256([instance, ticker, order_id])
                fill_body = {
                    "intent_id": intent_id, "order_id": order_id,
                    "book_instance_id": instance, "ticker": ticker, "side": "buy",
                    "qty": float(quantity), "fill_date": holding_date.isoformat(),
                    "open_px": 200.0, "fill_px": 200.0, "slippage_bps": 0.0,
                    "cost_bps": 0.0, "execution_profile": "baseline_v1",
                    "median_dollar_vol": None, "participation": None,
                    "impact_bps": 0.0, "fee_bps": 0.0, "source_sha256": "f" * 64,
                }
                con.execute(
                    "INSERT INTO p16_book_fills VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [*fill_body.values(), canonical_sha256(fill_body)],
                )
            else:
                con.execute(
                    "INSERT INTO p15_book_fills VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [order_id, order_id, instance, ticker, "buy", quantity, holding_date,
                     200, 200, 0, 0, "baseline_v1", None, None, 0, 0],
                )
            order_id += 1
        if instance.startswith("p16_"):
            p16_book_store.claim_window(
                con, book_instance_id=instance, market_date=holding_date,
                information_cutoff_at=signal_cutoff, risk_sha256="b" * 64,
                score_sha256="c" * 64, previous_state_sha256=None,
                target_sha256="f" * 64, started_at=signal_cutoff,
            )
            p16_book_store.append_state(
                con, book_instance_id=instance, market_date=holding_date,
                peak_equity=10_000, entry_halted=False, equity=10_000, cash=1_000,
                spy_mark=200, stock_marks={"AAA": 202, "BBB": 198, "CCC": 203},
                position_state_sha256=canonical_sha256({
                    "cash": 1_000.0,
                    "positions": {
                        ticker: {"qty": float(quantity), "avg_cost": 200.0}
                        for ticker, quantity in (
                            ("AAA", 5), ("BBB", 5), ("CCC", 5), ("SPY", 30)
                        )
                    },
                }),
                previous_state_sha256=None, recorded_at=CUTOFF,
            )
            p16_book_store.complete_window(
                con, book_instance_id=instance, market_date=holding_date,
                status="completed", reason=None, completed_at=CUTOFF,
            )
        else:
            con.execute(
                "INSERT INTO p15_book_windows VALUES (?,?,?,?,?,?,?)",
                [instance, holding_date, 10_000, 1_000, 4, "[]",
                 CUTOFF.replace(tzinfo=None)],
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
    )
    assert [row["book_id"] for row in result["books"]] == list(
        p16_transfer.BOOK_POLICIES,
    )
    assert all(row["status"] == "available" for row in result["books"])
    assert all(row["primary_instruments"] == "stocks_only_spy_and_cash_excluded"
               for row in result["books"])
    assert all(row["sigma_basis"] == "stock_minus_spy_daily_return_sd60_ddof1"
               for row in result["books"])
    assert all(row["ex_ante_tracking_error"] >= 0 for row in result["books"])
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
        "INSERT INTO sim_fills VALUES (999,?,'ZZZ','buy',1,?,10,10,0,0)",
        [instance, holding_date],
    )
    intent_id = canonical_sha256([instance, "ZZZ", 999])
    fill_body = {
        "intent_id": intent_id, "order_id": 999, "book_instance_id": instance,
        "ticker": "ZZZ", "side": "buy", "qty": 1.0,
        "fill_date": holding_date.isoformat(), "open_px": 10.0, "fill_px": 10.0,
        "slippage_bps": 0.0, "cost_bps": 0.0, "execution_profile": "baseline_v1",
        "median_dollar_vol": None, "participation": None, "impact_bps": 0.0,
        "fee_bps": 0.0, "source_sha256": "f" * 64,
    }
    con.execute(
        "INSERT INTO p16_book_fills VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [*fill_body.values(), canonical_sha256(fill_body)],
    )
    positions = {
        ticker: {"qty": float(quantity), "avg_cost": cost}
        for ticker, quantity, cost in (
            ("AAA", 5, 200.0), ("BBB", 5, 200.0), ("CCC", 5, 200.0),
            ("SPY", 30, 200.0), ("ZZZ", 1, 10.0),
        )
    }
    con.execute(
        "UPDATE p16_book_state SET cash=990,position_state_sha256=? "
        "WHERE book_instance_id=? AND market_date=?",
        [canonical_sha256({"cash": 990.0, "positions": positions}), instance, holding_date],
    )
    con.execute(
        "INSERT INTO prices "
        "(ticker,date,open,high,low,close,volume,source,fetched_at) "
        "VALUES ('ZZZ',?,10,11,9,10,100,'test',?)",
        [holding_date, CUTOFF.replace(tzinfo=None)],
    )
    result = p16_transfer.produce(
        con, registration_sha256=REGISTRATION, signal_date=signal_date,
        holding_date=holding_date, information_cutoff_at=CUTOFF,
    )
    row = next(item for item in result["books"] if item["book_id"] == "p16_construct_ai")
    assert row["status"] == "unavailable"
    assert row["reason"] == "held_name_missing_score_or_risk"


def test_rule_score_is_negative_baseline_rank_and_nonpositive_ic_is_unavailable(monkeypatch):
    con, signal_date, holding_date = _database()
    monkeypatch.setattr(p16_transfer, "_trailing_ics", lambda *_args, **_kwargs: {
        "status": "available", "reason": None,
        "values": {"champion": 0.03, "rule": 0.0},
        "origin_dates": ["2026-09-01"] * 60, "source_sha256": "d" * 64,
    })
    result = p16_transfer.produce(
        con, registration_sha256=REGISTRATION, signal_date=signal_date,
        holding_date=holding_date, information_cutoff_at=CUTOFF,
    )
    rule = next(item for item in result["books"] if item["book_id"] == "p15_rule_control")
    assert rule["status"] == "unavailable"
    assert rule["reason"] == "nonpositive_trailing_ic"
    assert rule["tc_diagonal"] is None


def test_transfer_rejects_non_next_session_and_ignores_later_mutable_state():
    con, signal_date, holding_date = _database()
    first = p16_transfer.produce(
        con, registration_sha256=REGISTRATION, signal_date=signal_date,
        holding_date=holding_date, information_cutoff_at=CUTOFF,
    )
    instance = f"p16_construct_ai@sha256:{REGISTRATION}"
    con.execute("UPDATE sim_positions SET qty=qty*9 WHERE portfolio_id=?", [instance])
    con.execute("UPDATE portfolios SET cash=17 WHERE id=?", [instance])
    con.execute(
        "INSERT INTO sim_fills VALUES (9999,?,'AAA','buy',2,?,200,200,0,0)",
        [instance, holding_date],
    )
    con.execute(
        "INSERT INTO sim_dividends VALUES (?,'AAA',?,5,1,5)",
        [instance, holding_date],
    )
    db.init_actions_schema(con)
    con.execute(
        "INSERT INTO split_adjustments "
        "(ticker,ex_date,ratio,outcome,applied_at) VALUES ('AAA',?,2,'applied',?)",
        [holding_date, (CUTOFF + timedelta(minutes=1)).replace(tzinfo=None)],
    )
    second = p16_transfer.produce(
        con, registration_sha256=REGISTRATION, signal_date=signal_date,
        holding_date=holding_date, information_cutoff_at=CUTOFF,
    )
    assert first == second
    with pytest.raises(ValueError, match="next session"):
        p16_transfer.produce(
            con, registration_sha256=REGISTRATION, signal_date=signal_date,
            holding_date=signal_date, information_cutoff_at=CUTOFF,
        )
