"""The recurring sweep schedule must be explicit and closed by default."""

import pytest

from farm.sweep import sweep


def test_no_completed_grid_is_open_for_recurring_search():
    assert sweep.recurring_grids() == []


def test_recurring_grid_must_exist(monkeypatch):
    monkeypatch.setattr(sweep, "OPEN_RECURRING_GRIDS", {"not_registered": "charter-v1"})
    with pytest.raises(ValueError, match="missing from GRIDS"):
        sweep.recurring_grids()


def test_recurring_grid_requires_versioned_charter(monkeypatch):
    monkeypatch.setattr(sweep, "OPEN_RECURRING_GRIDS", {"concentration": ""})
    with pytest.raises(ValueError, match="need a charter version"):
        sweep.recurring_grids()


def test_recurring_grid_rejects_shell_unsafe_charter(monkeypatch):
    monkeypatch.setattr(sweep, "OPEN_RECURRING_GRIDS", {"concentration": "version one"})
    with pytest.raises(ValueError, match="need a charter version"):
        sweep.recurring_grids()


@pytest.mark.parametrize("version", [".", "..", ".hidden", "trailing."])
def test_recurring_grid_rejects_unsafe_path_component(monkeypatch, version):
    monkeypatch.setattr(sweep, "OPEN_RECURRING_GRIDS", {"concentration": version})
    with pytest.raises(ValueError, match="need a charter version"):
        sweep.recurring_grids()


def test_queue_dispatch_rejects_closed_or_stale_charter(con):
    with pytest.raises(ValueError, match="no longer open"):
        sweep.run_job(
            {"grid": "concentration", "charter_version": "charter-v1"},
            con,
        )


def test_queue_dispatch_rejects_legacy_unversioned_sweep(con):
    with pytest.raises(ValueError, match="require a charter_version"):
        sweep.run_job({"grid": "concentration"}, con)


def test_queue_dispatch_rejects_execution_overrides(monkeypatch, con):
    monkeypatch.setattr(sweep, "OPEN_RECURRING_GRIDS", {"concentration": "charter-v1"})
    with pytest.raises(ValueError, match="unsupported parameters"):
        sweep.run_job(
            {"grid": "concentration", "charter_version": "charter-v1", "limit": 1},
            con,
        )


def test_versioned_sweep_uses_isolated_output(monkeypatch, con, tmp_path):
    monkeypatch.setattr(sweep, "OPEN_RECURRING_GRIDS", {"concentration": "charter-v2"})
    monkeypatch.setattr(sweep, "expand", lambda _name: [])
    monkeypatch.setattr(sweep, "_bench_book", lambda _con: {"id": "ew_benchmark"})
    result_dirs = []

    def fake_run_book(_con, _config_id, **kwargs):
        result_dirs.append(kwargs["results_dir"])

    monkeypatch.setattr(sweep.runner, "run_book", fake_run_book)
    monkeypatch.setattr(sweep, "rank", lambda *args, **kwargs: kwargs)

    result = sweep.run_sweep(
        con,
        "concentration",
        out_root=tmp_path,
        charter_version="charter-v2",
    )
    expected = tmp_path / "concentration" / "charters" / "charter-v2" / "results"
    assert result_dirs == [expected]
    assert result["charter_version"] == "charter-v2"
