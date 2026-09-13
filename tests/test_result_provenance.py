"""Research artifacts identify their exact config and runtime source tree."""
import hashlib
import json
from datetime import date

import pytest

from engine.lib import provenance
from farm.backtest import replay
from farm.walkforward import runner


def _write_runtime_tree(root):
    (root / "engine").mkdir()
    (root / "farm").mkdir()
    (root / "sim").mkdir()
    (root / "engine" / "a.py").write_text("print('a')\n")
    (root / "farm" / "run.sh").write_text("#!/bin/sh\n")
    (root / "sim" / "ignored.txt").write_text("not executable source\n")
    (root / "pyproject.toml").write_text("[project]\n")


def test_runtime_source_hash_is_deterministic_and_sensitive(tmp_path):
    _write_runtime_tree(tmp_path)
    first, count = provenance.runtime_source_hash(tmp_path)
    second, second_count = provenance.runtime_source_hash(tmp_path)
    assert (first, count) == (second, second_count)
    assert count == 3

    (tmp_path / "sim" / "ignored.txt").write_text("changed but excluded\n")
    assert provenance.runtime_source_hash(tmp_path) == (first, count)
    (tmp_path / "engine" / "a.py").write_text("print('changed')\n")
    assert provenance.runtime_source_hash(tmp_path)[0] != first


def test_provenance_is_canonical_shared_and_marks_dirty(monkeypatch, tmp_path):
    _write_runtime_tree(tmp_path)

    def fake_git(*args, repo_root):
        return "abc123" if args == ("rev-parse", "HEAD") else " M engine/a.py"

    monkeypatch.setattr(provenance, "_git", fake_git)
    monkeypatch.setattr(replay, "research_provenance",
                        lambda cfg: provenance.research_provenance(cfg, tmp_path))
    monkeypatch.setattr(runner, "research_provenance",
                        lambda cfg: provenance.research_provenance(cfg, tmp_path))
    a = {"b": 2, "a": 1}
    b = {"a": 1, "b": 2}
    expected = hashlib.sha256(
        json.dumps(a, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    backtest = replay._provenance(a)
    walkforward = runner._provenance(b)
    assert backtest["config_sha256"] == expected
    assert walkforward["config_sha256"] == expected
    assert backtest["git_sha"] == "abc123"
    assert backtest["git_dirty"] is True
    assert backtest["source_sha256"] == walkforward["source_sha256"]
    assert backtest["source_file_count"] == 3


class _Result:
    def __init__(self, one=None, rows=None):
        self.one = one
        self.rows = rows or []

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.rows


class _ScratchCon:
    def __init__(self, portfolio_count=1):
        self.portfolio_count = portfolio_count
        self.closed = False

    def execute(self, sql, params=None):
        if "COUNT(*) FROM portfolios" in sql:
            return _Result((self.portfolio_count,))
        if "FROM sim_equity" in sql and "GROUP BY" not in sql:
            return _Result(rows=[
                (date(2026, 1, 1), 100.0),
                (date(2026, 1, 2), 101.0),
                (date(2026, 1, 3), 102.0),
            ])
        if "FROM sim_execution_attempts" in sql:
            return _Result((0, 0.0))
        if "LEFT JOIN sim_fill_costs" in sql:
            return _Result((0.0, 0.0, 0.0, 0.0, 0.0))
        if "FROM sim_fills" in sql:
            return _Result((2,))
        if "FROM sim_orders" in sql:
            return _Result((0,))
        if "FROM sim_dividends" in sql:
            return _Result((0, 0.0))
        if "FROM corporate_actions" in sql:
            return _Result((0,))
        if "FROM sim_equity" in sql and "GROUP BY" in sql:
            return _Result(rows=[("2026-01", 102.0)])
        return self

    def close(self):
        self.closed = True


class _LiveCon:
    def execute(self, sql, params=None):
        if "MIN(date)" in sql:
            return _Result((date(2024, 1, 2),))
        if "MAX(date)" in sql:
            return _Result((date(2026, 1, 3),))
        raise AssertionError(sql)


def test_walkforward_result_keeps_provenance_captured_before_work(monkeypatch, tmp_path):
    start = {"source_sha256": "start", "config_sha256": "config-start",
             "config": {"id": "probe"}}
    monkeypatch.setattr(runner, "_provenance", lambda cfg: dict(start))
    monkeypatch.setattr(runner, "data_snapshot", lambda con: {"sha256": "data-start"})
    monkeypatch.setattr(runner, "data_floor", lambda *_: date(2000, 1, 1))
    monkeypatch.setattr(runner.hist_screen, "sessions_between",
                        lambda *_: [date(2024, 1, 2), date(2025, 1, 2), date(2026, 1, 2)])

    def begin_work(*args, **kwargs):
        monkeypatch.setattr(runner, "_provenance", lambda cfg: {
            "source_sha256": "late", "config_sha256": "config-late"})
        return tmp_path / "scratch.duckdb"

    monkeypatch.setattr(runner, "build_scratch", begin_work)
    monkeypatch.setattr(runner.db, "connect", lambda *_args, **_kwargs: _ScratchCon())
    monkeypatch.setattr(runner, "run_fold", lambda *args, **kwargs: {"status": "inert"})
    monkeypatch.setattr(runner, "summarize", lambda folds: {"n_folds_ok": 0})
    book = {"id": "probe", "name": "probe", "strategy": "spy_benchmark",
            "config": {"id": "probe", "cadence": "monthly"},
            "config_json": '{"id":"probe"}', "created": "2026-01-01",
            "initial_cash": 123_456.0,
            "execution_profile": "cost_2x_v1", "excluded": None}
    result = runner.run_book(
        _LiveCon(), "probe", anchor=date(2026, 1, 3), n_folds=1, book=book,
        scratch_root=tmp_path, results_dir=tmp_path, write_result=False,
        verbose=False, threads=None, mem_mb=None)
    assert result["source_sha256"] == "start"
    assert result["config_sha256"] == "config-start"
    assert result["initial_cash"] == 123_456.0
    assert result["execution_profile"]["id"] == "cost_2x_v1"
    assert result["comparison"]["control_id"] == "ew_benchmark"
    assert result["comparison"]["protocol"] == "wf-controls-2026-09-07-v1"


def test_walkforward_closes_scratch_connection_before_failure_cleanup(monkeypatch, tmp_path):
    scratch = tmp_path / f"wf__probe__p{runner.os.getpid()}"
    scratch_con = _ScratchCon()
    monkeypatch.setattr(runner, "_provenance", lambda _cfg: {})
    monkeypatch.setattr(runner, "data_snapshot", lambda _con: {})
    monkeypatch.setattr(runner, "data_floor", lambda *_: date(2000, 1, 1))
    monkeypatch.setattr(
        runner.hist_screen,
        "sessions_between",
        lambda *_: [date(2024, 1, 2), date(2025, 1, 2), date(2026, 1, 2)],
    )

    def build_scratch(*_args, **_kwargs):
        scratch.mkdir()
        return scratch / "replay.duckdb"

    monkeypatch.setattr(runner, "build_scratch", build_scratch)
    monkeypatch.setattr(runner.db, "connect", lambda *_args, **_kwargs: scratch_con)
    monkeypatch.setattr(
        runner,
        "run_fold",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("injected fold failure")
        ),
    )
    book = {
        "id": "probe",
        "name": "probe",
        "strategy": "spy_benchmark",
        "config": {"id": "probe", "cadence": "monthly"},
        "config_json": '{"id":"probe"}',
        "created": "2026-01-01",
        "initial_cash": 39_000.0,
        "execution_profile": "baseline_v1",
        "excluded": None,
    }

    with pytest.raises(RuntimeError, match="injected fold failure"):
        runner.run_book(
            _LiveCon(), "probe", anchor=date(2026, 1, 3), n_folds=1,
            book=book, scratch_root=tmp_path, results_dir=tmp_path,
            write_result=False, verbose=False, threads=None, mem_mb=None,
        )

    assert scratch_con.closed is True
    assert not scratch.exists()


def test_backtest_result_keeps_provenance_captured_before_work(monkeypatch, tmp_path):
    cfg = {"id": "probe", "name": "probe", "strategy": "spy_benchmark",
           "cadence": "monthly", "active": True}
    monkeypatch.setattr(replay, "config_by_id", lambda *_: cfg)
    monkeypatch.setattr(replay, "registered_config", lambda *_: cfg)
    monkeypatch.setattr(replay, "registered_assumptions",
                        lambda *_: (39_000.0, "baseline_v1"))
    monkeypatch.setattr(replay, "_provenance", lambda config: {
        "source_sha256": "start", "config_sha256": "config-start",
        "config": dict(config)})
    monkeypatch.setattr(replay, "data_snapshot", lambda con: {"sha256": "data-start"})
    monkeypatch.setattr(replay, "resolve_window",
                        lambda *_args, **_kwargs: (date(2026, 1, 1), date(2026, 1, 3), False))
    monkeypatch.setattr(replay.hist_screen, "sessions_between",
                        lambda *_: [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)])

    def begin_work(*args, **kwargs):
        monkeypatch.setattr(replay, "_provenance", lambda config: {
            "source_sha256": "late", "config_sha256": "config-late"})
        return tmp_path / "scratch.duckdb"

    monkeypatch.setattr(replay, "build_scratch", begin_work)
    monkeypatch.setattr(replay.db, "connect", lambda *_args, **_kwargs: _ScratchCon())
    monkeypatch.setattr(replay.league, "step", lambda *args, **kwargs: None)
    monkeypatch.setattr(replay.stats, "bil_daily_returns", lambda *_: [])
    monkeypatch.setattr(replay.stats, "equity_stats", lambda *_: {"cagr": 0.01})
    result = replay.run_replay(
        object(), "probe", "6mo", scratch_root=tmp_path, results_dir=tmp_path,
        write_result=False, verbose=False, threads=None, mem_mb=None)
    assert result["source_sha256"] == "start"
    assert result["config_sha256"] == "config-start"


def test_backtest_closes_scratch_connection_before_failure_cleanup(monkeypatch, tmp_path):
    cfg = {"id": "probe", "name": "probe", "strategy": "spy_benchmark",
           "cadence": "monthly", "active": True}
    scratch = tmp_path / "probe__6mo"
    scratch_con = _ScratchCon(portfolio_count=2)
    monkeypatch.setattr(replay, "config_by_id", lambda *_: cfg)
    monkeypatch.setattr(replay, "registered_config", lambda *_: cfg)
    monkeypatch.setattr(replay, "registered_assumptions",
                        lambda *_: (39_000.0, "baseline_v1"))
    monkeypatch.setattr(replay, "_provenance", lambda _config: {})
    monkeypatch.setattr(replay, "data_snapshot", lambda _con: {})
    monkeypatch.setattr(
        replay,
        "resolve_window",
        lambda *_args, **_kwargs: (date(2026, 1, 1), date(2026, 1, 3), False),
    )
    monkeypatch.setattr(replay.hist_screen, "sessions_between", lambda *_: [])

    def build_scratch(*_args, **_kwargs):
        scratch.mkdir()
        return scratch / "replay.duckdb"

    monkeypatch.setattr(replay, "build_scratch", build_scratch)
    monkeypatch.setattr(replay.db, "connect", lambda *_args, **_kwargs: scratch_con)

    with pytest.raises(RuntimeError, match="exactly one portfolio; found 2"):
        replay.run_replay(
            object(), "probe", "6mo", scratch_root=tmp_path,
            results_dir=tmp_path, write_result=False, verbose=False,
            threads=None, mem_mb=None,
        )

    assert scratch_con.closed is True
    assert not scratch.exists()


def test_build_scratch_closes_connection_when_initialization_fails(monkeypatch, tmp_path):
    class LiveConnection:
        def execute(self, _sql, _params=None):
            return self

    scratch_con = _ScratchCon()
    monkeypatch.setattr(replay.hist_screen, "session_n_back", lambda *_: date(2025, 1, 1))
    monkeypatch.setattr(replay.db, "connect", lambda *_args, **_kwargs: scratch_con)
    monkeypatch.setattr(
        replay.db,
        "init_schema",
        lambda _con: (_ for _ in ()).throw(RuntimeError("injected init failure")),
    )

    with pytest.raises(RuntimeError, match="injected init failure"):
        replay.build_scratch(
            LiveConnection(), tmp_path / "scratch", date(2026, 1, 1),
            date(2026, 1, 3), verbose=False,
        )
    assert scratch_con.closed is True


def test_m1_screen_probe_closes_connection_when_query_fails(monkeypatch, tmp_path):
    class FailingConnection:
        closed = False

        def execute(self, _sql):
            raise RuntimeError("injected screen query failure")

        def close(self):
            self.closed = True

    connection = FailingConnection()
    monkeypatch.setattr(replay.db, "connect", lambda *_args, **_kwargs: connection)

    with pytest.raises(RuntimeError, match="injected screen query failure"):
        replay._run_m1_screens(tmp_path / "scratch.duckdb", [], tmp_path)
    assert connection.closed is True
