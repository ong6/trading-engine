"""P16 construction dry-run never invents missing calibration evidence."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import duckdb
import numpy as np
import pytest

from engine.lib import db
from server import p16_book_store, p16_runner
from sim.schema import init_sim_schema
from tests.conftest import insert_bars, record_p16_calibration

REGISTRATION = "a" * 64


def test_calibration_unavailable_without_a_valid_p15_origin(con):
    result = p16_runner.calibrate(
        con, market_date=date(2026, 9, 25),
        generated_at=datetime(2026, 9, 28, 15, tzinfo=timezone.utc),
    )
    assert result["status"] == "calibration_unavailable"
    assert result["selected_lambda"] is None
    assert [row["status"] for row in result["books"]] == [
        "core_collecting", "core_collecting",
    ]


def test_calibration_risk_snapshot_uses_retained_scoring_cutoff(con, monkeypatch):
    cutoff = datetime(2026, 9, 25, 20, tzinfo=timezone.utc)
    monkeypatch.setattr(p16_runner.p16_eval_inputs, "load_origin", lambda *_args, **_kwargs: {
        "scoring_information_cutoff_at": "2026-09-25T20:00:00Z",
    })

    def inspect_cutoff(_con, _origin, observed_cutoff):
        assert observed_cutoff == cutoff
        raise ValueError("checked")

    monkeypatch.setattr(p16_runner, "_snapshot", inspect_cutoff)
    result = p16_runner.calibrate(
        con, market_date=date(2026, 9, 25),
        generated_at=datetime(2026, 9, 28, 15, tzinfo=timezone.utc),
    )
    assert result["status"] == "calibration_unavailable"
    assert result["reason"] == "checked"


def test_calibration_uses_every_retained_snapshot_for_each_book(con, monkeypatch):
    dates = [date(2026, 9, 24), date(2026, 9, 25)]
    cutoffs = {
        dates[0]: "2026-09-24T20:00:00Z",
        dates[1]: "2026-09-25T20:00:00Z",
    }
    monkeypatch.setattr(p16_runner, "_calibration_dates", lambda *_args: dates)
    monkeypatch.setattr(
        p16_runner.p16_eval_inputs, "load_origin",
        lambda _con, *, market_date, report_cutoff: {
            "market_date": market_date.isoformat(),
            "scoring_information_cutoff_at": cutoffs[market_date],
        },
    )

    def snapshot(_con, origin, cutoff):
        index = dates.index(date.fromisoformat(origin["market_date"]))
        assert cutoff.isoformat() == cutoffs[dates[index]].replace("Z", "+00:00")
        values = {
            "alpha_h5": np.array([0.001, 0.002]),
            "covariance_h5": np.eye(2) * 0.001,
            "beta": np.ones(2),
        }
        return {
            "market_date": dates[index], "tickers": ["AAA", "BBB"],
            "sectors": ["a", "b"], "risk": {"champion": values, "rule": values},
            "risk_sha256": str(index + 1) * 64,
            "score_sha256": str(index + 3) * 64,
            "cost_per_turnover": 0.001 + index * 0.001,
            "calibration_manifest": {"snapshot_sha256": str(index + 5) * 64},
        }

    def calibrate(cases):
        assert len(cases) == 4
        assert [row["book_id"] for row in cases] == [
            "p16_construct_ai", "p16_construct_rule",
            "p16_construct_ai", "p16_construct_rule",
        ]
        return {
            "status": "target_unattainable_on_grid", "selected_lambda": None,
            "selected_at_grid_endpoint": None, "grid_bounds": [0.1, 1000.0],
            "curve": [],
        }

    monkeypatch.setattr(p16_runner, "_snapshot", snapshot)
    monkeypatch.setattr(p16_runner.p16_calibration, "calibrate_lambda", calibrate)

    result = p16_runner.calibrate(
        con, market_date=dates[-1],
        generated_at=datetime(2026, 9, 26, 12, tzinfo=timezone.utc),
    )

    assert result["snapshot_dates"] == [item.isoformat() for item in dates]
    assert result["risk_snapshot_sha256s"] == ["1" * 64, "2" * 64]
    assert result["cost_per_turnover"] == 0.002


def test_construct_targets_composes_gates_solver_planner_store_and_queue(con, monkeypatch):
    signal_date = date(2024, 7, 15)
    cutoff = datetime(2026, 9, 27, 16, tzinfo=timezone.utc)
    calibration = record_p16_calibration(con, REGISTRATION, cutoff)
    instances = p16_book_store.initialize_contracts(
        con, registration_sha256=REGISTRATION, activation_date=None,
        calibration_sha256=calibration, created_at=cutoff,
    )
    for ticker in ("AAA", "BBB", "SPY"):
        insert_bars(con, ticker, [signal_date], open_=100, high=101, low=99, close=100)
    con.execute("UPDATE prices SET fetched_at=?", [cutoff.replace(tzinfo=None)])
    decisions = [
        {"ticker": "AAA", "champion_score": 2.0, "rule_score": -1.0,
         "champion_score_available": True, "tradeable": True,
         "entry_gate_reason": "eligible", "atr_14": 2.0},
        {"ticker": "BBB", "champion_score": 1.0, "rule_score": -2.0,
         "champion_score_available": True, "tradeable": False,
         "entry_gate_reason": "earnings_within_5_sessions", "atr_14": 2.0},
    ]
    monkeypatch.setattr(p16_runner.p16_eval_inputs, "load_origin", lambda *_args, **_kwargs: {
        "scoring_information_cutoff_at": cutoff.isoformat(),
        "decision_rows": decisions, "held_decision_rows": [],
    })
    rng = np.random.default_rng(7)
    spy = rng.normal(0, 0.01, 120)
    stocks = spy[:, None] + rng.normal(0, 0.01, (120, 2))
    monkeypatch.setattr(p16_runner, "_snapshot", lambda *_args, **_kwargs: {
        "market_date": signal_date, "tickers": ["AAA", "BBB"],
        "sectors": ["a", "b"], "stock_returns": stocks, "spy_returns": spy,
        "risk_sha256": "b" * 64, "score_sha256": "c" * 64,
    })
    monkeypatch.setattr(p16_runner.p16_transfer, "_trailing_ics", lambda *_args: {
        "status": "available", "reason": None,
        "values": {"champion": 0.03, "rule": 0.02},
        "vectors": {"champion": [0.03] * 60, "rule": [0.02] * 60},
        "source_sha256": "d" * 64,
    })

    def solve(*_args, **kwargs):
        assert kwargs["upper_limits"] == [0.1, 0.0]
        weights = np.array([0.1, 0.0, 0.9])
        return {
            "status": "converged", "weights": weights,
            "continuous_weights": weights.copy(), "tracking_error": 0.05,
            "sector_status": "available", "sector_coverage": 1.0,
        }

    monkeypatch.setattr(p16_runner.p16_optimizer, "solve", solve)

    result = p16_runner.construct_targets(
        con, registration_sha256=REGISTRATION, signal_date=signal_date,
        information_cutoff_at=cutoff, recorded_at=cutoff,
    )

    assert result["status"] == "completed"
    assert all(row["queued"] > 0 for row in result["books"])
    assert con.execute("SELECT COUNT(*) FROM p16_construct_targets").fetchone() == (2,)
    assert con.execute(
        "SELECT COUNT(*) FROM p16_book_windows WHERE status='completed'",
    ).fetchone() == (2,)
    assert {row[0] for row in con.execute(
        "SELECT DISTINCT ticker FROM p16_order_intents WHERE side='buy'",
    ).fetchall()} == {"AAA", "SPY"}
    assert con.execute(
        "SELECT COUNT(*) FROM portfolios WHERE id IN (?,?) AND active", instances,
    ).fetchone() == (0,)


def test_construct_targets_queues_stop_exits_while_ic_is_collecting(con, monkeypatch):
    signal_date = date(2024, 7, 15)
    entry_date = date(2024, 7, 12)
    cutoff = datetime(2026, 9, 27, 16, tzinfo=timezone.utc)
    calibration = record_p16_calibration(con, REGISTRATION, cutoff)
    instances = p16_book_store.initialize_contracts(
        con, registration_sha256=REGISTRATION, activation_date=None,
        calibration_sha256=calibration, created_at=cutoff,
    )
    insert_bars(con, "AAA", [signal_date], open_=90, high=91, low=89, close=90)
    con.execute("UPDATE prices SET fetched_at=?", [cutoff.replace(tzinfo=None)])
    for order_id, instance in enumerate(instances, start=1):
        con.execute(
            "INSERT INTO sim_fills VALUES (?,?,?,?,?,?,?,?,?,?)",
            [order_id, instance, "AAA", "buy", 5, entry_date, 100, 100, 0, 0],
        )
        con.execute(
            "INSERT INTO sim_positions VALUES (?,?,?,?)", [instance, "AAA", 5, 100],
        )
        con.execute("UPDATE portfolios SET cash=9500 WHERE id=?", [instance])
        con.execute(
            "INSERT INTO p16_position_rules VALUES (?,?,?,?,?,?,?,?,?)",
            [instance, "AAA", str(order_id), order_id, entry_date, 2.0, 95.0,
             "open", None],
        )
    monkeypatch.setattr(p16_runner.p16_eval_inputs, "load_origin", lambda *_args, **_kwargs: {
        "scoring_information_cutoff_at": cutoff.isoformat(),
        "input_snapshot_sha256": "f" * 64,
        "decision_rows": [], "held_decision_rows": [],
    })
    monkeypatch.setattr(p16_runner.p16_transfer, "_trailing_ics", lambda *_args: {
        "status": "unavailable", "reason": "fewer_than_60_mature_origins",
        "values": {}, "source_sha256": "e" * 64,
    })
    monkeypatch.setattr(
        p16_runner, "_snapshot",
        lambda *_args, **_kwargs: pytest.fail("risk must not be required for mandatory exits"),
    )

    result = p16_runner.construct_targets(
        con, registration_sha256=REGISTRATION, signal_date=signal_date,
        information_cutoff_at=cutoff, recorded_at=cutoff,
    )

    assert result["status"] == "core_collecting"
    assert [row["queued"] for row in result["books"]] == [1, 1]
    assert con.execute(
        "SELECT COUNT(*) FROM p16_construct_targets "
        "WHERE solver_status='core_collecting' AND banded_json IS NULL",
    ).fetchone() == (2,)
    assert con.execute(
        "SELECT COUNT(*) FROM p16_book_windows WHERE status='completed' "
        "AND reason='mandatory_exits_only:fewer_than_60_mature_origins'",
    ).fetchone() == (2,)
    assert con.execute(
        "SELECT DISTINCT ticker,side,order_role,rounded_qty FROM p16_order_intents",
    ).fetchall() == [("AAA", "sell", "stop", 5.0)]


def test_copied_store_dry_run_leaves_source_unchanged(tmp_path):
    database = tmp_path / "market.duckdb"
    con = duckdb.connect(str(database))
    db.init_schema(con)
    init_sim_schema(con)
    con.close()
    before = database.read_bytes()

    result = p16_runner.dry_run(
        database, generated_at=datetime(2026, 9, 27, 16, tzinfo=timezone.utc),
        lock_path=tmp_path / "nightly.lock",
    )

    assert result["status"] == "completed" and result["dry_run"] is True
    assert result["source_database_modified"] is False
    assert result["calibration"]["status"] == "calibration_unavailable"
    assert result["calibration"]["reason"] == "no_valid_p15_origin"
    assert database.read_bytes() == before


def test_copied_store_dry_run_retains_successful_calibration_and_constructs(
    tmp_path, monkeypatch,
):
    database = tmp_path / "market.duckdb"
    con = duckdb.connect(str(database))
    db.init_schema(con)
    init_sim_schema(con)
    con.close()
    before = database.read_bytes()
    generated = datetime(2026, 9, 27, 16, tzinfo=timezone.utc)
    market_date = date(2026, 9, 25)
    monkeypatch.setattr(p16_runner, "_latest_origin", lambda _con: market_date)

    def calibrated(copied_con, **_kwargs):
        digest = record_p16_calibration(copied_con, REGISTRATION, generated)
        return json.loads(copied_con.execute(
            "SELECT payload_json FROM p16_calibrations WHERE calibration_sha256=?",
            [digest],
        ).fetchone()[0])

    def constructed(copied_con, **kwargs):
        assert kwargs["registration_sha256"] == REGISTRATION
        assert copied_con.execute(
            "SELECT COUNT(*) FROM p16_book_contracts",
        ).fetchone() == (2,)
        assert copied_con.execute(
            "SELECT COUNT(*) FROM portfolios WHERE active",
        ).fetchone() == (0,)
        return {"status": "completed", "books": [], "execution_authority": "none"}

    monkeypatch.setattr(p16_runner, "calibrate", calibrated)
    monkeypatch.setattr(p16_runner, "construct_targets", constructed)

    result = p16_runner.dry_run(
        database, generated_at=generated, registration_sha256=REGISTRATION,
        lock_path=tmp_path / "nightly.lock",
    )

    assert result["retained_calibration_sha256"] == result["calibration"][
        "calibration_sha256"
    ]
    assert len(result["book_instances"]) == 2
    assert result["construction"]["status"] == "completed"
    assert result["source_database_modified"] is False
    assert database.read_bytes() == before
