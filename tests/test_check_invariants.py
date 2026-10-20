"""check_invariants CLI: published-snapshot refusal, read-only run, publish, exit codes."""

from __future__ import annotations

import json
import os
from pathlib import Path

import duckdb
import pytest

from tools import check_invariants
from tools.invariants import registry

SNAPSHOT = "market-20261020T035412271772Z.duckdb"
SHA = "0" * 64


@pytest.fixture
def engine(tmp_path):
    """An engine checkout with a live store, a published snapshot and result files."""
    store = tmp_path / "store"
    (store / "snapshots").mkdir(parents=True)
    (store / "pit").mkdir()
    for path in (store / "market.duckdb", store / "pit" / "sec-bulk.duckdb"):
        duckdb.connect(str(path)).close()
    snapshot = store / "snapshots" / SNAPSHOT
    con = duckdb.connect(str(snapshot))
    con.execute("CREATE TABLE prices (ticker VARCHAR, date DATE, open DOUBLE, high DOUBLE, "
                "low DOUBLE, close DOUBLE, volume BIGINT, fetched_at TIMESTAMP)")
    con.execute("INSERT INTO prices VALUES ('AAA', '2026-10-16', 10, 11, 9, 10, 100, "
                "'2026-10-17 02:00:00')")
    con.close()
    _manifest(snapshot)
    (store / "snapshots" / "market-latest.duckdb").symlink_to(SNAPSHOT)
    results = tmp_path / "data" / "reports" / "walkforward" / "results"
    results.mkdir(parents=True)
    (results / "alpha.json").write_text('{"sharpe": 1.0}')
    return tmp_path


def _manifest(path: Path, **override) -> None:
    payload = {"schema_version": 1, "snapshot": path.name, "sha256": SHA,
               "as_of": "2026-10-20T03:55:13+00:00", "row_counts": {},
               "size_bytes": path.stat().st_size, "source_data_commit": None, **override}
    path.with_suffix(".json").write_text(json.dumps(payload))


def _baseline(tmp_path, *entries) -> Path:
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"schema_version": 1, "exceptions": list(entries)}))
    return path


def _main(engine, *args) -> int:
    return check_invariants.main(["--engine-root", str(engine), "--only", "ohlc_geometry",
                                  "--only", "walkforward_results_finite",
                                  "--baseline", str(_baseline(engine)), *args])


@pytest.fixture
def no_connect(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("a refused path must never be opened")
    monkeypatch.setattr(duckdb, "connect", refuse)


def test_check_invariants_refuses_live_store(engine, tmp_path, no_connect):
    store = engine / "store"
    snapshots = store / "snapshots"
    os.link(store / "market.duckdb", snapshots / "market-20261020T050000000000Z.duckdb")
    (snapshots / "market-20261020T060000000000Z.duckdb").symlink_to(store / "market.duckdb")
    (store / "pit" / "market-20261020T070000000000Z.duckdb").symlink_to(
        store / "pit" / "sec-bulk.duckdb")
    for name in ("market-20261020T050000000000Z.duckdb",
                 "market-20261020T060000000000Z.duckdb"):
        target = snapshots / name
        target.with_suffix(".json").write_text(json.dumps({
            "schema_version": 1, "snapshot": name, "sha256": SHA,
            "as_of": "2026-10-20T05:00:00+00:00"}))
    published = tmp_path / "published.json"
    for path in (store / "market.duckdb", store / "pit" / "sec-bulk.duckdb",
                 snapshots / "market-20261020T050000000000Z.duckdb",
                 snapshots / "market-20261020T060000000000Z.duckdb",
                 store / "pit" / "market-20261020T070000000000Z.duckdb",
                 engine / "missing.duckdb"):
        assert _main(engine, "--snapshot", str(path), "--publish", str(published)) == 3, path
        result = json.loads(published.read_text())
        assert result["status"] == "error" and result["error"].startswith("refused:")
        assert str(engine) not in published.read_text()


@pytest.mark.parametrize("manifest", [
    {"snapshot": "market-20261020T000000000000Z.duckdb"},
    {"schema_version": 2},
    {"sha256": "not-a-sha"},
    {"size_bytes": 1},
    {"as_of": "2026-10-20T03:55:13"},
])
def test_snapshot_needs_a_manifest_that_describes_it(engine, no_connect, manifest):
    _manifest(engine / "store" / "snapshots" / SNAPSHOT, **manifest)
    assert _main(engine, "--snapshot", "latest") == 3


def test_snapshot_without_a_manifest_or_latest_link_is_refused(engine, no_connect):
    (engine / "store" / "snapshots" / "market-latest.duckdb").unlink()
    assert _main(engine, "--snapshot", "latest") == 3
    (engine / "store" / "snapshots" / SNAPSHOT).with_suffix(".json").unlink()
    assert _main(engine, "--snapshot", str(engine / "store" / "snapshots" / SNAPSHOT)) == 3


def test_published_snapshot_runs_read_only_with_bounded_resources(engine, tmp_path,
                                                                   monkeypatch):
    opened = []
    original = duckdb.connect

    def record(database, *args, **kwargs):
        opened.append((database, kwargs))
        return original(database, *args, **kwargs)

    monkeypatch.setattr(duckdb, "connect", record)
    published = tmp_path / "out" / "invariants.json"

    assert _main(engine, "--snapshot", "latest", "--publish", str(published)) == 0

    [(database, kwargs)] = opened
    assert Path(database).name == SNAPSHOT
    assert kwargs["read_only"] is True
    assert kwargs["config"]["threads"] == "2" and kwargs["config"]["memory_limit"] == "2GB"
    assert not Path(kwargs["config"]["temp_directory"]).exists()
    result = json.loads(published.read_text())
    assert result["status"] == "pass" and result["mode"] == "shadow"
    assert result["snapshot"] == {"name": SNAPSHOT, "sha256": SHA,
                                  "as_of": "2026-10-20T03:55:13+00:00",
                                  "source_data_commit": None}
    assert result["invariants"]["ohlc_geometry"]["facts"]["bars"] == 1
    assert sorted(os.listdir(engine / "store" / "snapshots")) == sorted(
        [SNAPSHOT, SNAPSHOT.replace(".duckdb", ".json"), "market-latest.duckdb"])


def test_regressions_exit_two_only_with_gate(engine, tmp_path):
    results = engine / "data" / "reports" / "walkforward" / "results"
    (results / "beta.json").write_text('{"sharpe": NaN}')
    published = tmp_path / "invariants.json"

    assert _main(engine, "--snapshot", "latest", "--publish", str(published)) == 0
    assert json.loads(published.read_text())["status"] == "regression"
    assert _main(engine, "--snapshot", "latest", "--gate") == 2

    entry = {"invariant": "walkforward_results_finite", "class": "nonfinite",
             "owner": "orchestrator", "reason": "zero-volatility fold", "expires": "2999-01-01"}
    assert check_invariants.main([
        "--engine-root", str(engine), "--snapshot", "latest", "--gate",
        "--only", "walkforward_results_finite", "--baseline",
        str(_baseline(tmp_path, entry))]) == 0


def test_cannot_evaluate_exits_three_even_in_shadow(engine, tmp_path):
    (engine / "data" / "reports" / "walkforward" / "results" / "alpha.json").unlink()
    (engine / "data" / "reports" / "walkforward" / "results").rmdir()
    assert _main(engine, "--snapshot", "latest") == 3
    bad = tmp_path / "bad-baseline.json"
    bad.write_text('{"schema_version": 1, "exceptions": [{"invariant": "ohlc_geometry"}]}')
    assert check_invariants.main(["--engine-root", str(engine), "--snapshot", "latest",
                                  "--baseline", str(bad)]) == 3


def test_committed_baseline_is_valid_and_owned():
    entries = registry.load_baseline()
    assert entries and all(entry["owner"] and entry["reason"] and entry["ref"]
                           for entry in entries)


def test_every_invariant_is_registered_once_in_report_order():
    names = registry.ordered_names()
    assert names == [
        "ohlc_geometry", "one_split_basis_per_ticker", "split_recorded_vs_restated",
        "fee_row_per_fill", "equity_per_active_book", "closeouts_once", "publication_order",
        "preopen_not_voided", "experiment_results_finite", "walkforward_results_finite"]
