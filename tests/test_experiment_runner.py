"""Frozen execution assumptions for the append-only E1 forward experiment."""
import json
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import pytest

from farm import experiment_runner
from tests.conftest import insert_bars


def _config():
    return experiment_runner.load_forward_config("e1-spy-monday", None)[0]


def _trade(con, d=date(2026, 7, 20), open_px=100.0, close_px=101.0):
    history = [d - timedelta(days=i) for i in range(90, 0, -1)]
    insert_bars(con, "SPY", history, open_=100.0, close=100.0, volume=1_000_000)
    return experiment_runner.compute_trade(con, "SPY", d, open_px, close_px)


def _append(con, cfg, trade, *, run_at=None):
    experiment_runner.E.ensure_results_table(con)
    experiment_runner.ensure_forward_columns(con)
    phash = experiment_runner.params_hash_for(cfg)
    experiment_runner.append_oos_rows(
        con,
        cfg,
        phash,
        [trade],
        run_at or datetime(2026, 7, 20, 22, tzinfo=timezone.utc),
    )
    return phash


def test_compute_trade_stamps_frozen_baseline_profile(con):
    trade_date = date(2024, 6, 3)
    history = [trade_date - timedelta(days=i) for i in range(30, 0, -1)]
    insert_bars(con, "SPY", history, open_=100.0, close=100.0, volume=1_000_000)

    trade = experiment_runner.compute_trade(con, "SPY", trade_date, 100.0, 101.0)

    assert trade["slip_bps_side"] == pytest.approx(10.0)
    assert trade["execution_profile"] == "baseline_v1"
    assert trade["execution_profile_sha256"] == (
        experiment_runner.EXPECTED_EXECUTION_PROFILE_SHA256
    )


def test_compute_trade_fails_closed_if_frozen_profile_changes(con, monkeypatch):
    monkeypatch.setattr(experiment_runner, "EXECUTION_PROFILE_SHA256", "changed")

    with pytest.raises(RuntimeError, match="register a new experiment ID"):
        experiment_runner.compute_trade(
            con, "SPY", date(2024, 6, 3), 100.0, 101.0
        )


def test_compute_trade_fails_before_write_if_frozen_cost_changes(con, monkeypatch):
    monkeypatch.setattr(experiment_runner, "slippage_bps_for", lambda *_args: 11.0)

    with pytest.raises(RuntimeError, match="frozen 20bp round-trip cost changed"):
        _trade(con)


def test_load_oos_series_accepts_new_and_legacy_profile_metadata(con):
    cfg = _config()
    trade = _trade(con)
    phash = _append(con, cfg, trade)

    rows = experiment_runner.load_oos_series(con, cfg, phash)
    assert [row["date"] for row in rows] == [trade["date"]]

    con.execute(
        "UPDATE experiment_results SET meta_json = json_merge_patch(meta_json, ?) "
        "WHERE experiment_id = ? AND trade_date = ?",
        ['{"execution_profile":null,"execution_profile_sha256":null}',
         cfg["id"], trade["date"]],
    )
    assert experiment_runner.load_oos_series(con, cfg, phash)[0]["date"] == trade["date"]


def test_load_oos_series_rejects_missing_profile_after_legacy_cutoff(con):
    cfg = _config()
    trade_date = date(2026, 9, 14)
    trade = _trade(con, d=trade_date)
    phash = _append(con, cfg, trade)
    con.execute(
        "UPDATE experiment_results SET meta_json = json_merge_patch(meta_json, ?) "
        "WHERE experiment_id = ? AND trade_date = ?",
        ['{"execution_profile":null,"execution_profile_sha256":null}',
         cfg["id"], trade_date],
    )

    with pytest.raises(ValueError, match="inconsistent execution profile"):
        experiment_runner.load_oos_series(con, cfg, phash)


def test_load_oos_series_rejects_duplicate_trade_date(con):
    cfg = _config()
    trade = _trade(con)
    phash = _append(con, cfg, trade)
    _append(
        con,
        cfg,
        trade,
        run_at=datetime(2026, 7, 21, 22, tzinfo=timezone.utc),
    )

    with pytest.raises(ValueError, match="duplicate or invalid trade date"):
        experiment_runner.load_oos_series(con, cfg, phash)


def test_load_oos_series_rejects_tampered_return(con):
    cfg = _config()
    trade = _trade(con)
    phash = _append(con, cfg, trade)
    con.execute(
        "UPDATE experiment_results SET net_ret=net_ret+0.01 "
        "WHERE experiment_id=? AND trade_date=?",
        [cfg["id"], trade["date"]],
    )

    with pytest.raises(ValueError, match="inconsistent with its frozen registration"):
        experiment_runner.load_oos_series(con, cfg, phash)


def test_checkpoint_rejects_coordinated_rewrite(con, tmp_path, monkeypatch):
    cfg = _config()
    trade = _trade(con)
    phash = _append(con, cfg, trade)
    monkeypatch.setattr(experiment_runner, "REPORTS_DIR", tmp_path)
    rows = experiment_runner.load_oos_series(con, cfg, phash)
    experiment_runner._write_checkpoint(cfg, phash, rows)
    changed_open = 99.0
    changed_gross = trade["close"] / changed_open - 1.0
    changed_net = experiment_runner.net_at_bps(changed_open, trade["close"], 20.0)
    changed_registered = experiment_runner.net_at_bps(
        changed_open, trade["close"], 3.0
    )
    con.execute(
        "UPDATE experiment_results SET gross_ret=?, net_ret=?, mean_ret=?, "
        "meta_json=json_merge_patch(meta_json, ?) "
        "WHERE experiment_id=? AND trade_date=?",
        [changed_gross, changed_net, changed_net,
         json.dumps({"open": changed_open,
                     "net_ret_registered_3bp": changed_registered}),
         cfg["id"], trade["date"]],
    )
    rewritten = experiment_runner.load_oos_series(con, cfg, phash)

    with pytest.raises(ValueError, match="previously published E1 forward prefix changed"):
        experiment_runner._validate_checkpoint(cfg, phash, rewritten)


def test_runtime_contract_hash_covers_e1_dependency(tmp_path):
    for relative in experiment_runner.RUNTIME_CONTRACT_FILES:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((experiment_runner.REPO_ROOT / relative).read_bytes())

    assert experiment_runner._runtime_contract_sha256(tmp_path) == (
        experiment_runner.EXPECTED_RUNTIME_CONTRACT_SHA256
    )
    dependency = tmp_path / "sim" / "fills.py"
    dependency.write_text(dependency.read_text() + "\n# changed\n")
    assert experiment_runner._runtime_contract_sha256(tmp_path) != (
        experiment_runner.EXPECTED_RUNTIME_CONTRACT_SHA256
    )


def test_run_fails_closed_when_runtime_contract_changes(con, monkeypatch):
    monkeypatch.setattr(experiment_runner, "_runtime_contract_sha256", lambda: "changed")

    with pytest.raises(ValueError, match="E1 runtime source changed"):
        experiment_runner.run(con, _config())


def test_runtime_contract_migration_preserves_legacy_prefix(con, tmp_path, monkeypatch):
    cfg = _config()
    trade = _trade(con)
    phash = _append(con, cfg, trade)
    monkeypatch.setattr(experiment_runner, "REPORTS_DIR", tmp_path)
    rows = experiment_runner.load_oos_series(con, cfg, phash)
    legacy = experiment_runner._checkpoint_payload(cfg, phash, rows)
    legacy = {
        key: value
        for key, value in legacy.items()
        if not key.startswith("runtime_contract")
        and key != "superseded_runtime_contract_sha256"
    }
    legacy["schema_version"] = experiment_runner.LEGACY_CHECKPOINT_SCHEMA_VERSION
    monkeypatch.setattr(experiment_runner, "EXPECTED_LEGACY_OBSERVATIONS", 1)
    monkeypatch.setattr(experiment_runner, "EXPECTED_LEGACY_THROUGH", trade["date"].isoformat())
    monkeypatch.setattr(
        experiment_runner,
        "EXPECTED_LEGACY_PREFIX_SHA256",
        legacy["prefix_sha256"],
    )
    experiment_runner.checkpoint_path(cfg).write_text(
        json.dumps(legacy, indent=2, sort_keys=True) + "\n"
    )

    before = experiment_runner.canonical_sha256(experiment_runner._oos_payload(rows))
    migrated = experiment_runner.migrate_runtime_contract(con, cfg)
    after_rows = experiment_runner.load_oos_series(con, cfg, phash)

    assert migrated["schema_version"] == 2
    assert (
        migrated["runtime_contract_version"]
        == experiment_runner.RUNTIME_CONTRACT_VERSION
    )
    assert migrated["runtime_contract_sha256"] == (
        experiment_runner.EXPECTED_RUNTIME_CONTRACT_SHA256
    )
    assert migrated["superseded_runtime_contract_sha256"] == (
        experiment_runner.PRIOR_RUNTIME_CONTRACT_SHA256
    )
    assert migrated["prefix_sha256"] == before
    assert experiment_runner.canonical_sha256(
        experiment_runner._oos_payload(after_rows)
    ) == before


def test_runtime_contract_migration_preserves_prior_v3_prefix(con, tmp_path, monkeypatch):
    cfg = _config()
    trade = _trade(con)
    phash = _append(con, cfg, trade)
    monkeypatch.setattr(experiment_runner, "REPORTS_DIR", tmp_path)
    rows = experiment_runner.load_oos_series(con, cfg, phash)
    prior = experiment_runner._checkpoint_payload(cfg, phash, rows)
    prior.update(
        runtime_contract_version=experiment_runner.PRIOR_RUNTIME_CONTRACT_VERSION,
        runtime_contract_sha256=experiment_runner.PRIOR_RUNTIME_CONTRACT_SHA256,
        runtime_contract_files=list(experiment_runner.PRIOR_RUNTIME_CONTRACT_FILES),
        superseded_runtime_contract_sha256=(
            experiment_runner.PRIOR_SUPERSEDED_RUNTIME_CONTRACT_SHA256
        ),
        runtime_contract_migration=experiment_runner.PRIOR_RUNTIME_CONTRACT_MIGRATION,
    )
    monkeypatch.setattr(experiment_runner, "EXPECTED_LEGACY_OBSERVATIONS", 1)
    monkeypatch.setattr(experiment_runner, "EXPECTED_LEGACY_THROUGH", trade["date"].isoformat())
    monkeypatch.setattr(experiment_runner, "EXPECTED_LEGACY_PREFIX_SHA256", prior["prefix_sha256"])
    experiment_runner.checkpoint_path(cfg).write_text(json.dumps(prior))

    migrated = experiment_runner.migrate_runtime_contract(con, cfg)

    assert (
        migrated["runtime_contract_version"]
        == experiment_runner.RUNTIME_CONTRACT_VERSION
    )
    assert migrated["superseded_runtime_contract_sha256"] == (
        experiment_runner.PRIOR_RUNTIME_CONTRACT_SHA256
    )
    assert migrated["prefix_sha256"] == prior["prefix_sha256"]


def test_runtime_contract_migration_rejects_changed_legacy_prefix(
    con, tmp_path, monkeypatch
):
    cfg = _config()
    trade = _trade(con)
    phash = _append(con, cfg, trade)
    monkeypatch.setattr(experiment_runner, "REPORTS_DIR", tmp_path)
    rows = experiment_runner.load_oos_series(con, cfg, phash)
    legacy = experiment_runner._checkpoint_payload(cfg, phash, rows)
    legacy = {
        key: value
        for key, value in legacy.items()
        if not key.startswith("runtime_contract")
        and key != "superseded_runtime_contract_sha256"
    }
    legacy["schema_version"] = experiment_runner.LEGACY_CHECKPOINT_SCHEMA_VERSION
    monkeypatch.setattr(experiment_runner, "EXPECTED_LEGACY_OBSERVATIONS", 1)
    monkeypatch.setattr(experiment_runner, "EXPECTED_LEGACY_THROUGH", trade["date"].isoformat())
    monkeypatch.setattr(
        experiment_runner,
        "EXPECTED_LEGACY_PREFIX_SHA256",
        legacy["prefix_sha256"],
    )
    legacy["prefix_sha256"] = "changed"
    experiment_runner.checkpoint_path(cfg).write_text(json.dumps(legacy))

    with pytest.raises(ValueError, match="previously published E1 forward prefix changed"):
        experiment_runner.migrate_runtime_contract(con, cfg)


def test_run_caps_record_at_frozen_sample_size(con, tmp_path, monkeypatch):
    cfg = deepcopy(_config())
    cfg["kill_criterion"]["n_oos_mondays"] = 2
    history = [date(2026, 4, 1) + timedelta(days=i) for i in range(130)]
    weekdays = [d for d in history if d.weekday() < 5]
    insert_bars(con, "SPY", weekdays, open_=100.0, close=101.0, volume=1_000_000)
    monkeypatch.setattr(experiment_runner, "REPORTS_DIR", tmp_path)

    result = experiment_runner.run(
        con, cfg, now=datetime(2026, 8, 4, 22, tzinfo=timezone.utc)
    )

    assert result["appended"] == 2
    assert result["n_oos"] == 2
    text = (tmp_path / "e1-spy-monday-forward.md").read_text()
    assert "FINAL FROZEN VERDICT" in text
    assert "Exactly 2 out-of-sample Mondays" in text
    assert "2026-08-03" not in text


def test_run_rejects_missing_real_monday_bar(con, tmp_path, monkeypatch):
    cfg = _config()
    dates = [date(2026, 7, 17) + timedelta(days=i) for i in range(15)]
    dates = [d for d in dates if d.weekday() < 5 and d != date(2026, 7, 20)]
    insert_bars(con, "SPY", dates, open_=100.0, close=101.0, volume=1_000_000)
    monkeypatch.setattr(experiment_runner, "REPORTS_DIR", tmp_path)

    with pytest.raises(ValueError, match="missing required SPY trade bar.*2026-07-20"):
        experiment_runner.run(
            con, cfg, now=datetime(2026, 8, 1, 22, tzinfo=timezone.utc)
        )


def test_frozen_sample_end_is_the_fortieth_nyse_monday():
    cfg = _config()
    end = experiment_runner.frozen_sample_end(cfg)
    assert end == date(2027, 5, 10)
    assert end.weekday() == 0
    assert experiment_runner.nyse.is_session(end)
