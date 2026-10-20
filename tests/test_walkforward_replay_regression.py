"""Scratch replays never touch live stores, and stale or NaN results never publish."""
from __future__ import annotations

import contextlib
import json
from datetime import date

import duckdb

from engine.accounts.sources import production_sources
from farm.backtest import replay
from farm.walkforward import report, runner
from server import walkforward_artifact_folds
from sim import league
from sim.schema import set_portfolio_account
from tests.conftest import SESSIONS, insert_bars
from tests.test_result_provenance import _ScratchCon


# --------------------------------------------------------------- attaches -- #
def _garbage_sources(tmp_path) -> dict[str, str]:
    garbage = tmp_path / "not-a-database.duckdb"
    garbage.write_bytes(b"this file is not a DuckDB database")
    return {name: str(garbage) for name in (
        "TRADING_ENGINE_FREE_SOURCES_DB",
        "TRADING_ENGINE_MASSIVE_MINUTE_DB",
        "TRADING_ENGINE_SHORT_DATA_DB",
    )}


def _source_errors_table(con) -> bool:
    return con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name='account_source_errors'"
    ).fetchone() is not None


def test_production_sources_attach_nothing_without_account_books(con, tmp_path):
    # A legacy-only store (a walk-forward scratch replay) has nothing to settle.
    # Any ATTACH of these paths would raise or be recorded as a source error.
    with production_sources(con, environ=_garbage_sources(tmp_path)) as short_con:
        assert short_con is None
        assert not _source_errors_table(con)


def test_production_sources_still_attach_for_account_books(con, tmp_path):
    con.execute(
        "INSERT INTO portfolios (id,name,strategy,config,created,active,cash) "
        "VALUES ('acct','acct','none','{}',?,TRUE,1000)", [SESSIONS[0]])
    set_portfolio_account(con, "acct", engine="account", status="active")
    with production_sources(con, environ=_garbage_sources(tmp_path)):
        assert con.execute(
            "SELECT COUNT(*) FROM account_source_errors").fetchone()[0] == 3


def test_walkforward_fold_steps_without_account_phases(con, tmp_path, monkeypatch):
    from engine.lib import db
    db.init_actions_schema(con)
    insert_bars(con, "SPY", SESSIONS[:5], open_=100.0, close=100.0)
    attaches = []
    monkeypatch.setattr(
        league.account_sources, "production_sources",
        lambda *_args, **_kwargs: attaches.append(1) or contextlib.nullcontext(None),
    )
    book = {
        "id": "probe", "name": "probe", "strategy": "spy_benchmark",
        "config": {"id": "probe", "cadence": "monthly"},
        "config_json": json.dumps({"id": "probe", "cadence": "monthly"}),
    }
    fold = runner.protocol.Fold(index=1, train_start=SESSIONS[0],
                                split_date=SESSIONS[2], validate_end=SESSIONS[4])
    runner.run_fold(con, book, fold, SESSIONS[:5], tmp_path, verbose=False,
                    initial_cash=39_000.0, execution_profile="baseline_v1")
    assert con.execute(
        "SELECT COUNT(*) FROM sim_equity WHERE portfolio_id='probe'"
    ).fetchone()[0] == 5
    assert attaches == []


# ------------------------------------------------------- live store handle -- #
def _live_store(path) -> None:
    writer = duckdb.connect(str(path))
    writer.execute("CREATE TABLE prices (ticker VARCHAR, date DATE, close DOUBLE)")
    writer.execute("INSERT INTO prices VALUES ('SPY', DATE '2023-01-03', 1), "
                   "('SPY', DATE '2026-01-02', 2)")
    writer.close()


def _writer_can_open(path) -> bool:
    # In one process DuckDB refuses a writer while a reader of the file is open,
    # which is the same refusal a live writer meets from another process.
    try:
        duckdb.connect(str(path)).close()
    except duckdb.Error:
        return False
    return True


def _walkforward_fixture(monkeypatch, tmp_path, observed: list, live_path):
    monkeypatch.delenv(runner.SHARED_RUN_ENV, raising=False)
    monkeypatch.setattr(runner, "_provenance", lambda _cfg: {})
    monkeypatch.setattr(runner, "data_snapshot", lambda _con: {})
    monkeypatch.setattr(runner, "data_floor", lambda *_args: date(2000, 1, 1))
    monkeypatch.setattr(
        runner.hist_screen, "sessions_between",
        lambda *_args: [date(2023, 1, 3), date(2025, 1, 3), date(2026, 1, 2)],
    )

    def build_scratch(_live, scratch_dir, *_args, **_kwargs):
        path = scratch_dir / "replay.duckdb"
        duckdb.connect(str(path)).close()
        return path

    monkeypatch.setattr(runner, "build_scratch", build_scratch)
    monkeypatch.setattr(
        runner, "run_fold",
        lambda _con, _book, fold, *_args, **_kwargs: observed.append(
            _writer_can_open(live_path)) or {**fold.as_dict(), "status": "inert"},
    )


def _book():
    return {
        "id": "probe", "name": "probe", "strategy": "spy_benchmark",
        "config": {"id": "probe", "cadence": "monthly"},
        "config_json": json.dumps({"id": "probe", "cadence": "monthly"}),
        "created": "2026-01-01", "initial_cash": 39_000.0,
        "execution_profile": "baseline_v1",
        "comparison": {"control_id": "fixture", "protocol": "fixture-v1"},
        "excluded": None,
    }


def test_queue_walkforward_releases_live_reader_before_fold_loop(monkeypatch, tmp_path):
    live_path = tmp_path / "live.duckdb"
    _live_store(live_path)
    observed: list[bool] = []
    _walkforward_fixture(monkeypatch, tmp_path, observed, live_path)
    monkeypatch.setattr(runner, "book_by_id", lambda *_args: _book())
    monkeypatch.setattr(report, "write_reports", lambda **_kwargs: [])

    live = duckdb.connect(str(live_path), read_only=True)
    try:
        runner.run_job({"config_id": "probe", "anchor": "2026-01-03", "n_folds": 1,
                        "results_dir": str(tmp_path / "results"),
                        "scratch_root": str(tmp_path / "scratch")}, live)
    finally:
        live.close()  # the queue child's own close stays harmless
    assert observed == [True]


def test_sequential_drain_writer_is_not_closed_by_walkforward(monkeypatch, tmp_path):
    live_path = tmp_path / "live.duckdb"
    _live_store(live_path)
    observed: list[bool] = []
    _walkforward_fixture(monkeypatch, tmp_path, observed, live_path)
    monkeypatch.setattr(runner, "book_by_id", lambda *_args: _book())
    monkeypatch.setattr(report, "write_reports", lambda **_kwargs: [])

    writer = duckdb.connect(str(live_path))
    try:
        runner.run_job({"config_id": "probe", "anchor": "2026-01-03", "n_folds": 1,
                        "results_dir": str(tmp_path / "results"),
                        "scratch_root": str(tmp_path / "scratch")}, writer)
        assert writer.execute("SELECT COUNT(*) FROM prices").fetchone() == (2,)
    finally:
        writer.close()


def test_backtest_releases_live_reader_before_session_loop(monkeypatch, tmp_path):
    live_path = tmp_path / "live.duckdb"
    _live_store(live_path)
    cfg = {"id": "probe", "name": "probe", "strategy": "spy_benchmark",
           "cadence": "monthly", "active": True}
    monkeypatch.setattr(replay, "config_by_id", lambda *_: cfg)
    monkeypatch.setattr(replay, "registered_config", lambda *_: cfg)
    monkeypatch.setattr(replay, "registered_assumptions",
                        lambda *_: (39_000.0, "baseline_v1"))
    monkeypatch.setattr(replay, "_provenance", lambda _config: {})
    monkeypatch.setattr(replay, "data_snapshot", lambda _con: {})
    monkeypatch.setattr(replay, "resolve_window",
                        lambda *_args, **_kwargs: (date(2026, 1, 1), date(2026, 1, 3), False))
    monkeypatch.setattr(replay.hist_screen, "sessions_between",
                        lambda *_: [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)])
    monkeypatch.setattr(replay, "build_scratch",
                        lambda *_args, **_kwargs: tmp_path / "scratch.duckdb")
    monkeypatch.setattr(replay.db, "connect", lambda *_args, **_kwargs: _ScratchCon())
    steps = []
    monkeypatch.setattr(
        replay.league, "step",
        lambda *_args, **kwargs: steps.append((kwargs, _writer_can_open(live_path))),
    )
    monkeypatch.setattr(replay.stats, "bil_daily_returns", lambda *_: [])
    monkeypatch.setattr(replay.stats, "equity_stats", lambda *_: {"cagr": 0.01})
    monkeypatch.setattr("farm.backtest.report.write_reports", lambda: [])
    monkeypatch.setattr(replay.resources, "write_text_atomic", lambda *_args: None)

    live = duckdb.connect(str(live_path), read_only=True)
    try:
        replay.run_job({"config_id": "probe", "window": "6mo"}, live)
    finally:
        live.close()
    assert [writer_ok for _kwargs, writer_ok in steps] == [True, True, True]
    assert all(kwargs.get("no_accounts") is True for kwargs, _ok in steps)


def _snapshot_store(path) -> None:
    # The columns data_snapshot hashes, so a nightly-style insert would move it.
    writer = duckdb.connect(str(path))
    writer.execute("CREATE TABLE prices (ticker VARCHAR, date DATE, close DOUBLE, "
                   "fetched_at TIMESTAMP)")
    writer.execute("INSERT INTO prices VALUES "
                   "('SPY', DATE '2026-01-02', 2, TIMESTAMP '2026-01-02 22:30:00')")
    writer.close()


def _coherent_grid_cell(con, live_path, kwargs) -> tuple:
    # A grid's cohort signature includes the data snapshot, so every cell must
    # see the same store: the grid keeps its one reader, which is never
    # released mid-grid, and a live writer stays refused between cells.
    assert not kwargs.get("release_live")
    from engine.lib.data_quality import data_snapshot
    return id(con), data_snapshot(con)["sha256"], _writer_can_open(live_path)


def test_sweep_keeps_one_live_reader_so_every_book_shares_a_snapshot(
        monkeypatch, tmp_path):
    from farm.sweep import sweep
    live_path = tmp_path / "live.duckdb"
    _snapshot_store(live_path)
    observed = []
    monkeypatch.setattr(sweep, "expand", lambda _name: [{"id": "cand-a"}, {"id": "cand-b"}])
    monkeypatch.setattr(sweep, "_bench_book", lambda _con: {"id": "bench"})
    monkeypatch.setattr(sweep, "rank", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        sweep.runner, "run_book",
        lambda book_con, _config_id, **kwargs: observed.append(
            _coherent_grid_cell(book_con, live_path, kwargs)),
    )
    live = duckdb.connect(str(live_path), read_only=True)
    try:
        sweep.run_sweep(live, "grid", out_root=tmp_path / "sweeps")
        assert observed == [(id(live), observed[0][1], False)] * 3
    finally:
        live.close()


# ------------------------------------------------------------- NaN results -- #
def test_walkforward_result_with_flat_train_slice_is_strict_json():
    stats = runner.stats.equity_stats(
        [date(2016, 10, 7), date(2016, 10, 10), date(2016, 10, 14)],
        [39000.0, 39000.0, 39000.0], {}, 39000.0)
    assert stats["sharpe"] is None and stats["worst_month"] is None
    json.dumps(stats, allow_nan=False)
    # /meta accepts the undefined statistics as null.
    walkforward_artifact_folds._validate_performance_metrics(stats, 39000.0, 39000.0)


# ---------------------------------------------------------- stale cohorts -- #
CURRENT = {"fill_model": "v5", "runtime_contract": {"revision": 2, "sha256": "rc"},
           "source_sha256": "tree-now"}


def _wf_result(config_id, **identity):
    return {
        "config_id": config_id, "name": config_id, "strategy": "x",
        "protocol": {"anchor": "2026-10-16", "train_months": 24,
                     "validate_months": 12, "step_months": 12, "n_folds": 10},
        "universe_policy": "all", "initial_cash": 39000.0,
        "folds": [], "summary": {"n_folds_ok": 1},
        **identity,
    }


def _write(path, payload):
    path.write_text(json.dumps(payload))


def test_load_results_never_falls_back_to_a_larger_stale_cohort(tmp_path):
    stale = {"fill_model": "v4", "source_sha256": "tree-old"}
    for config_id in ("ew_benchmark", "low_vol", "high_52wk", "template_top5"):
        _write(tmp_path / f"{config_id}.json", _wf_result(config_id, **stale))
    _write(tmp_path / "spy_benchmark.json", _wf_result("spy_benchmark", **CURRENT))
    _write(tmp_path / "dual_momentum.json",
           _wf_result("dual_momentum", **{**CURRENT, "source_sha256": "tree-old"}))
    _write(tmp_path / "sector_momentum.json",
           _wf_result("sector_momentum", **{**CURRENT, "runtime_contract": None}))

    loaded = report.load_results(tmp_path, CURRENT)
    assert [r["config_id"] for r in loaded] == ["spy_benchmark"]


def test_load_results_shows_nothing_when_no_result_is_current(tmp_path):
    _write(tmp_path / "ew_benchmark.json",
           _wf_result("ew_benchmark", fill_model="v4", source_sha256="tree-old"))
    assert report.load_results(tmp_path, CURRENT) == []


def test_load_results_rejects_non_finite_json_like_meta(tmp_path):
    (tmp_path / "spy_benchmark.json").write_text(
        json.dumps(_wf_result("spy_benchmark", **CURRENT), allow_nan=True)
        .replace('"n_folds_ok": 1', '"n_folds_ok": 1, "x": NaN'))
    _write(tmp_path / "ew_benchmark.json", _wf_result("ew_benchmark", **CURRENT))
    assert [r["config_id"] for r in report.load_results(tmp_path, CURRENT)] == [
        "ew_benchmark"]


def test_readme_names_books_not_yet_revalidated(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "current_identity", lambda: dict(CURRENT))
    monkeypatch.setattr(report, "_eligible_ids",
                        lambda active_only=False: {"spy_benchmark", "low_vol"})
    results = tmp_path / "results"
    results.mkdir()
    _write(results / "low_vol.json",
           _wf_result("low_vol", fill_model="v4", source_sha256="tree-old"))
    report.write_reports(results, tmp_path)
    readme = (tmp_path / "README.md").read_text()
    assert "_0 book(s) re-validated" in readme
    assert "**Not yet re-validated: 2 of 2 scheduled book(s).**" in readme
    assert "`low_vol`, `spy_benchmark`" in readme
    assert "fill model `v5`, runtime contract revision 2, source `tree-now`" in readme


def test_capital_grid_keeps_one_live_reader_so_every_cell_shares_a_snapshot(
        monkeypatch, tmp_path):
    from farm import capital_sensitivity
    live_path = tmp_path / "live.duckdb"
    _snapshot_store(live_path)
    observed = []

    def fake_replay(cell_con, _config_id, _window, **kwargs):
        observed.append(_coherent_grid_cell(cell_con, live_path, kwargs))
        return {}

    monkeypatch.setattr(capital_sensitivity.replay, "run_replay", fake_replay)
    monkeypatch.setattr(capital_sensitivity, "_cell_summary", lambda _result: {})
    monkeypatch.setattr(capital_sensitivity, "_aggregate", lambda *_args: {})
    monkeypatch.setattr(capital_sensitivity, "_write_aggregate", lambda *_args: None)
    live = duckdb.connect(str(live_path), read_only=True)
    try:
        capital_sensitivity.run_grid(live, "probe", "5y", capitals=(10_000.0, 39_000.0),
                                     profiles=("baseline_v1",), out_dir=tmp_path / "out",
                                     scratch_root=tmp_path / "scratch")
        assert observed == [(id(live), observed[0][1], False)] * 2
    finally:
        live.close()
