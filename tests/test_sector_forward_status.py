"""Tests for sector forward-evidence status."""

import json
import sys
from datetime import date

import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    sector_forward_status,
)
from sim.strategies.configs import config_by_id


def _forward_payload(**override):
    payload = {
        "schema_version": 2,
        "status": "ACCUMULATING",
        "paper_only": True,
        "automatic_action": "none",
        "observation": {
            "first_shared_date": "2026-09-04",
            "window_start": "2026-09-04",
            "as_of": "2026-09-04",
            "eligible_after": "2027-09-04",
            "shared_sessions_available": 1,
            "shared_sessions_in_window": 1,
            "equity_sha256": canonical_sha256(
                [["2026-09-04", 41_742.09372396311, 40_163.91313403321]]
            ),
            "forward_ledger_sha256": canonical_sha256(
                {
                    "orders": [],
                    "fills": [],
                    "fill_costs": [],
                    "execution_attempts": [],
                    "settlements": [],
                }
            ),
            "mature": False,
        },
        "metrics": {"excess_return": 0.0, "drawdown_improvement": 0.0},
        "candidate": {
            "portfolio_id": sector_forward_status.forward_monitor.CANDIDATE_ID,
            "config_sha256": sector_forward_status.forward_monitor.EXPECTED_CONFIG_SHA256[
                sector_forward_status.forward_monitor.CANDIDATE_ID
            ],
            "initial_cash": sector_forward_status.forward_monitor.EXPECTED_INITIAL_CASH,
            "execution_profile": sector_forward_status.forward_monitor.EXPECTED_EXECUTION_PROFILE,
        },
        "control": {
            "portfolio_id": sector_forward_status.forward_monitor.CONTROL_ID,
            "config_sha256": sector_forward_status.forward_monitor.EXPECTED_CONFIG_SHA256[
                sector_forward_status.forward_monitor.CONTROL_ID
            ],
            "initial_cash": sector_forward_status.forward_monitor.EXPECTED_INITIAL_CASH,
            "execution_profile": sector_forward_status.forward_monitor.EXPECTED_EXECUTION_PROFILE,
        },
        "frozen_runtime": {
            "observation_start": sector_forward_status.forward_monitor.OBSERVATION_START.isoformat(),
            "fill_model": sector_forward_status.forward_monitor.EXPECTED_FILL_MODEL_VERSION,
            "execution_profile_sha256": sector_forward_status.forward_monitor.EXPECTED_PROFILE_SHA256,
            "runtime_contract_version": sector_forward_status.forward_monitor.RUNTIME_CONTRACT_VERSION,
            "runtime_contract_sha256": sector_forward_status.forward_monitor.EXPECTED_RUNTIME_CONTRACT_SHA256,
            "superseded_runtime_contract_sha256": (
                sector_forward_status.forward_monitor.SUPERSEDED_RUNTIME_CONTRACT_SHA256
            ),
            "runtime_contract_migration": (
                sector_forward_status.forward_monitor.RUNTIME_CONTRACT_MIGRATION
            ),
            "baseline_state": sector_forward_status.forward_monitor.EXPECTED_BASELINE_STATE,
            "baseline_state_sha256": sector_forward_status.forward_monitor.EXPECTED_BASELINE_STATE_SHA256,
        },
    }
    payload.update(override)
    return payload


def test_forward_review_status_projects_safe_fields(tmp_path):
    path = tmp_path / "sector_momentum.json"
    path.write_text(json.dumps(_forward_payload()))
    assert sector_forward_status.status(path, date(2026, 9, 4)) == {
        "status": "ACCUMULATING",
        "paper_only": True,
        "automatic_action": "none",
        "report_schema_version": 2,
        "runtime_contract_version": sector_forward_status.forward_monitor.RUNTIME_CONTRACT_VERSION,
        "runtime_contract_sha256": (
            sector_forward_status.forward_monitor.EXPECTED_RUNTIME_CONTRACT_SHA256
        ),
        "as_of": "2026-09-04",
        "eligible_after": "2027-09-04",
        "shared_sessions": 1,
        "minimum_shared_sessions": sector_forward_status.forward_monitor.MIN_SHARED_SESSIONS,
        "mature": False,
        "excess_return": 0.0,
        "drawdown_improvement": 0.0,
    }


def test_forward_review_status_fails_closed_on_bad_json(tmp_path):
    path = tmp_path / "sector_momentum.json"
    path.write_text("not json")
    assert sector_forward_status.status(path) == {
        "status": "INVALID",
        "paper_only": True,
        "automatic_action": "none",
    }


def test_forward_review_status_fails_closed_on_duplicate_json_key(tmp_path):
    path = tmp_path / "sector_momentum.json"
    payload = json.dumps(_forward_payload()).replace(
        '"status": "ACCUMULATING"',
        '"status": "ACCUMULATING", "status": "CONTINUE"',
        1,
    )
    path.write_text(payload)

    assert sector_forward_status.status(path) == {
        "status": "INVALID",
        "paper_only": True,
        "automatic_action": "none",
    }


def test_forward_review_status_fails_closed_when_missing(tmp_path):
    assert sector_forward_status.status(tmp_path / "missing.json") == {
        "status": "INVALID",
        "paper_only": True,
        "automatic_action": "none",
    }


@pytest.mark.parametrize(
    "override",
    [
        {"status": "PROMOTE"},
        {"paper_only": False},
        {"automatic_action": "activate"},
        {"status": "CONTINUE"},
        {"metrics": {"excess_return": float("nan"), "drawdown_improvement": 0.0}},
        {"schema_version": 1},
    ],
)
def test_forward_review_status_rejects_unsafe_valid_json(tmp_path, override):
    path = tmp_path / "sector_momentum.json"
    path.write_text(json.dumps(_forward_payload(**override)))
    assert sector_forward_status.status(path) == {
        "status": "INVALID",
        "paper_only": True,
        "automatic_action": "none",
    }


def test_forward_review_status_rejects_stale_report(tmp_path):
    path = tmp_path / "sector_momentum.json"
    path.write_text(json.dumps(_forward_payload()))
    assert sector_forward_status.status(path, date(2026, 9, 8)) == {
        "status": "INVALID",
        "paper_only": True,
        "automatic_action": "none",
    }


def test_forward_review_status_fails_closed_without_live_price_watermark(con, tmp_path):
    path = tmp_path / "sector_momentum.json"
    path.write_text(json.dumps(_forward_payload()))
    assert sector_forward_status.status(path, None, con) == {
        "status": "INVALID",
        "paper_only": True,
        "automatic_action": "none",
    }


def _setup_live_sector_forward(con):
    for portfolio_id in (
        sector_forward_status.forward_monitor.CANDIDATE_ID,
        sector_forward_status.forward_monitor.CONTROL_ID,
    ):
        config = config_by_id(portfolio_id)
        state = sector_forward_status.forward_monitor.EXPECTED_BASELINE_STATE[portfolio_id]
        con.execute(
            "INSERT INTO portfolios "
            "(id, name, strategy, config, created, active, cash, initial_cash, "
            "execution_profile) VALUES (?, ?, ?, ?, DATE '2026-09-04', TRUE, ?, "
            "39000, 'baseline_v1')",
            [portfolio_id, config["name"], config["strategy"], json.dumps(config), state["cash"]],
        )
        con.execute(
            "INSERT INTO sim_equity VALUES (?, DATE '2026-09-04', ?, ?, ?)",
            [portfolio_id, state["equity"], state["cash"], state["n_positions"]],
        )
        for ticker, qty, avg_cost, close in state["positions"]:
            con.execute(
                "INSERT OR IGNORE INTO prices "
                "(ticker, date, open, high, low, close, volume) "
                "VALUES (?, DATE '2026-09-04', ?, ?, ?, ?, 1000000)",
                [ticker, close, close, close, close],
            )
            con.execute(
                "INSERT INTO sim_positions VALUES (?, ?, ?, ?)",
                [portfolio_id, ticker, qty, avg_cost],
            )


def test_forward_review_status_matches_live_equity_hash(con, tmp_path):
    path = tmp_path / "sector_momentum.json"
    _setup_live_sector_forward(con)
    path.write_text(json.dumps(sector_forward_status.forward_monitor.evaluate(con), default=str))
    assert sector_forward_status.status(path, date(2026, 9, 4), con)["status"] == "ACCUMULATING"

    con.execute(
        "UPDATE sim_equity SET equity = equity + 1 WHERE portfolio_id = ? AND date = ?",
        [sector_forward_status.forward_monitor.CANDIDATE_ID, date(2026, 9, 4)],
    )
    assert sector_forward_status.status(path, date(2026, 9, 4), con) == {
        "status": "INVALID",
        "paper_only": True,
        "automatic_action": "none",
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(status="CONTINUE"),
        lambda payload: payload["metrics"].update(excess_return=0.25),
        lambda payload: payload["observation"].update(window_start="2026-09-05"),
        lambda payload: payload["observation"].update(eligible_after="2026-09-04"),
        lambda payload: payload["observation"].update(as_of="20260904"),
        lambda payload: payload["observation"].update(eligible_after="2027-W35-6"),
    ],
)
def test_forward_review_status_rejects_report_rewrites(con, tmp_path, mutate):
    path = tmp_path / "sector_momentum.json"
    _setup_live_sector_forward(con)
    payload = sector_forward_status.forward_monitor.evaluate(con)
    mutate(payload)
    path.write_text(json.dumps(payload, default=str))
    assert sector_forward_status.status(path, date(2026, 9, 4), con)["status"] == "INVALID"


def test_forward_review_status_rejects_live_registration_change(con, tmp_path):
    path = tmp_path / "sector_momentum.json"
    _setup_live_sector_forward(con)
    path.write_text(json.dumps(sector_forward_status.forward_monitor.evaluate(con), default=str))
    con.execute(
        "UPDATE portfolios SET execution_profile = 'cost_2x_v1' WHERE id = ?",
        [sector_forward_status.forward_monitor.CANDIDATE_ID],
    )
    assert sector_forward_status.status(path, date(2026, 9, 4), con)["status"] == "INVALID"


def test_forward_review_status_fails_closed_for_deep_live_evaluation(monkeypatch, tmp_path):
    payload = _forward_payload()
    path = tmp_path / "sector_momentum.json"
    path.write_text(json.dumps(payload))
    live = _forward_payload()
    nested = live["metrics"]
    for _ in range(sys.getrecursionlimit() * 2):
        nested["nested"] = {}
        nested = nested["nested"]
    monkeypatch.setattr(sector_forward_status.forward_monitor, "evaluate", lambda _con: live)

    assert sector_forward_status.status(path, date(2026, 9, 4), object()) == {
        "status": "INVALID",
        "paper_only": True,
        "automatic_action": "none",
    }
