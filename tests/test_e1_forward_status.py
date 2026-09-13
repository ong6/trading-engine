"""Tests for E1 forward-evidence status."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from server import (
    e1_forward_status,
)
from tests.conftest import insert_bars


def _setup_e1_forward(con, tmp_path, monkeypatch):
    monkeypatch.setattr(e1_forward_status.e1_monitor, "REPORTS_DIR", tmp_path)
    cfg = e1_forward_status.e1_monitor.load_forward_config("e1-spy-monday", None)[0]
    dates = [date(2026, 4, 1) + timedelta(days=i) for i in range(125)]
    dates = [d for d in dates if d.weekday() < 5]
    insert_bars(con, "SPY", dates, open_=100.0, close=101.0, volume=1_000_000)
    e1_forward_status.e1_monitor.E.ensure_results_table(con)
    e1_forward_status.e1_monitor.ensure_forward_columns(con)
    monday = date(2026, 7, 20)
    trade = e1_forward_status.e1_monitor.compute_trade(con, "SPY", monday, 100.0, 101.0)
    phash = e1_forward_status.e1_monitor.params_hash_for(cfg)
    e1_forward_status.e1_monitor.append_oos_rows(
        con,
        cfg,
        phash,
        [trade],
        datetime(2026, 7, 20, 22, tzinfo=timezone.utc),
    )
    oos = e1_forward_status.e1_monitor.load_oos_series(con, cfg, phash)
    e1_forward_status.e1_monitor._write_checkpoint(cfg, phash, oos)
    return cfg, monday


def test_e1_forward_status_projects_valid_record(con, tmp_path, monkeypatch):
    _cfg, monday = _setup_e1_forward(con, tmp_path, monkeypatch)

    assert e1_forward_status.status(
        con,
        monday,
        datetime(2026, 7, 21, tzinfo=timezone.utc),
    ) == {
        "status": "ACCUMULATING",
        "paper_only": True,
        "automatic_action": "none",
        "checkpoint_schema_version": e1_forward_status.e1_monitor.CHECKPOINT_SCHEMA_VERSION,
        "runtime_contract_version": e1_forward_status.e1_monitor.RUNTIME_CONTRACT_VERSION,
        "runtime_contract_sha256": (e1_forward_status.e1_monitor.EXPECTED_RUNTIME_CONTRACT_SHA256),
        "observations": 1,
        "target_observations": 40,
        "remaining_observations": 39,
        "sample_end": "2027-05-10",
        "latest_trade_date": "2026-07-20",
        "mean_net_return": pytest.approx(0.00798201798201803),
        "t_stat": None,
    }


def test_e1_forward_status_fails_closed_on_runtime_contract_mismatch(con, tmp_path, monkeypatch):
    _cfg, monday = _setup_e1_forward(con, tmp_path, monkeypatch)
    checkpoint = e1_forward_status.e1_monitor.checkpoint_path(_cfg)
    payload = json.loads(checkpoint.read_text())
    payload["runtime_contract_sha256"] = "changed"
    checkpoint.write_text(json.dumps(payload))

    assert e1_forward_status.status(
        con,
        monday,
        datetime(2026, 7, 21, tzinfo=timezone.utc),
    ) == {
        "status": "INVALID",
        "paper_only": True,
        "automatic_action": "none",
    }


def test_e1_forward_status_fails_closed_on_duplicate_checkpoint_key(con, tmp_path, monkeypatch):
    cfg, monday = _setup_e1_forward(con, tmp_path, monkeypatch)
    checkpoint = e1_forward_status.e1_monitor.checkpoint_path(cfg)
    payload = checkpoint.read_text().replace(
        '"paper_only": true',
        '"paper_only": true, "paper_only": true',
        1,
    )
    checkpoint.write_text(payload)

    assert e1_forward_status.status(
        con,
        monday,
        datetime(2026, 7, 21, tzinfo=timezone.utc),
    ) == {
        "status": "INVALID",
        "paper_only": True,
        "automatic_action": "none",
    }


def test_e1_forward_status_fails_closed_without_checkpoint(con, tmp_path, monkeypatch):
    _cfg, monday = _setup_e1_forward(con, tmp_path, monkeypatch)
    e1_forward_status.e1_monitor.checkpoint_path(_cfg).unlink()

    assert e1_forward_status.status(
        con,
        monday,
        datetime(2026, 7, 21, tzinfo=timezone.utc),
    ) == {
        "status": "INVALID",
        "paper_only": True,
        "automatic_action": "none",
    }


def test_e1_forward_status_rejects_noncanonical_oos_start(con, tmp_path, monkeypatch):
    cfg, monday = _setup_e1_forward(con, tmp_path, monkeypatch)
    malformed = {**cfg, "oos_start": "20260720"}
    parsed_values = []
    strict_iso_date = e1_forward_status.iso_date

    def record_iso_date(value, message):
        parsed_values.append(value)
        return strict_iso_date(value, message)

    monkeypatch.setattr(
        e1_forward_status.e1_monitor,
        "load_forward_config",
        lambda *_args: (malformed, tmp_path / "e1-spy-monday.forward.json"),
    )
    monkeypatch.setattr(e1_forward_status.e1_monitor, "params_hash_for", lambda _cfg: "hash")
    monkeypatch.setattr(e1_forward_status.e1_monitor, "load_oos_series", lambda *_args: [])
    monkeypatch.setattr(
        e1_forward_status.e1_monitor,
        "_validate_checkpoint",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(e1_forward_status, "iso_date", record_iso_date)

    assert e1_forward_status.status(
        con,
        monday,
        datetime(2026, 7, 21, tzinfo=timezone.utc),
    ) == {
        "status": "INVALID",
        "paper_only": True,
        "automatic_action": "none",
    }
    assert parsed_values == ["20260720"]


def test_e1_forward_status_fails_closed_when_checkpoint_lags(con, tmp_path, monkeypatch):
    cfg, monday = _setup_e1_forward(con, tmp_path, monkeypatch)
    next_monday = monday + timedelta(days=7)
    trade = e1_forward_status.e1_monitor.compute_trade(con, "SPY", next_monday, 100.0, 101.0)
    e1_forward_status.e1_monitor.append_oos_rows(
        con,
        cfg,
        e1_forward_status.e1_monitor.params_hash_for(cfg),
        [trade],
        datetime(2026, 7, 27, 22, tzinfo=timezone.utc),
    )

    assert e1_forward_status.status(
        con,
        next_monday,
        datetime(2026, 7, 28, tzinfo=timezone.utc),
    ) == {
        "status": "INVALID",
        "paper_only": True,
        "automatic_action": "none",
    }


def test_e1_forward_status_fails_closed_on_tampered_record(con, tmp_path, monkeypatch):
    cfg, monday = _setup_e1_forward(con, tmp_path, monkeypatch)
    con.execute(
        "UPDATE experiment_results SET net_ret=net_ret+0.01 WHERE experiment_id=? AND trade_date=?",
        [cfg["id"], monday],
    )

    assert e1_forward_status.status(
        con,
        monday,
        datetime(2026, 7, 21, tzinfo=timezone.utc),
    ) == {
        "status": "INVALID",
        "paper_only": True,
        "automatic_action": "none",
    }


def test_e1_forward_status_allows_current_unsettled_monday(con, tmp_path, monkeypatch):
    _cfg, monday = _setup_e1_forward(con, tmp_path, monkeypatch)
    next_monday = monday + timedelta(days=7)

    status = e1_forward_status.status(
        con,
        next_monday,
        datetime(2026, 7, 27, 20, tzinfo=timezone.utc),
    )

    assert status["status"] == "ACCUMULATING"
    assert status["observations"] == 1
