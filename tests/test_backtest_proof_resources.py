"""Historical analysis drivers must release DuckDB handles on every exit."""

from datetime import date
from types import SimpleNamespace

import pytest

from farm import execution_drag
from farm.backtest import hist_screen, proofs
from sim import backtest_shakedown


class _Result:
    def __init__(self, *, one=None, rows=None):
        self._one = one
        self._rows = [] if rows is None else rows

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _Connection:
    def __init__(self, execute=None):
        self.closed = False
        self._execute = execute

    def execute(self, sql, params=None):
        if self._execute is not None:
            return self._execute(sql, params)
        return self

    def close(self):
        self.closed = True


def test_screen_equivalence_closes_preparation_connection_on_failure(
    monkeypatch, tmp_path
):
    connection = _Connection()
    monkeypatch.setattr(proofs, "_copy_store", lambda _name: tmp_path / "proof.duckdb")
    monkeypatch.setattr(proofs.db, "connect", lambda *_args, **_kwargs: connection)
    monkeypatch.setattr(
        proofs.db,
        "init_schema",
        lambda _con: (_ for _ in ()).throw(RuntimeError("injected init failure")),
    )

    with pytest.raises(RuntimeError, match="injected init failure"):
        proofs.screen_equivalence()
    assert connection.closed is True


def test_screen_equivalence_closes_read_connection_on_failure(monkeypatch, tmp_path):
    preparation = _Connection()
    readback = _Connection(
        lambda _sql, _params: (_ for _ in ()).throw(RuntimeError("injected read failure"))
    )
    connections = iter((preparation, readback))
    monkeypatch.setattr(proofs, "_copy_store", lambda _name: tmp_path / "proof.duckdb")
    monkeypatch.setattr(
        proofs.db, "connect", lambda *_args, **_kwargs: next(connections)
    )
    monkeypatch.setattr(proofs.db, "init_schema", lambda _con: None)
    monkeypatch.setattr(proofs.hist_screen, "screen_sessions", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(proofs.subprocess, "run", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="injected read failure"):
        proofs.screen_equivalence()
    assert preparation.closed is True
    assert readback.closed is True


def test_replay_fidelity_closes_preparation_connection_on_failure(monkeypatch, tmp_path):
    connection = _Connection(
        lambda _sql, _params: (_ for _ in ()).throw(RuntimeError("injected query failure"))
    )
    monkeypatch.setattr(proofs, "_copy_store", lambda _name: tmp_path / "proof.duckdb")
    monkeypatch.setattr(proofs.db, "connect", lambda *_args, **_kwargs: connection)

    with pytest.raises(RuntimeError, match="injected query failure"):
        proofs.replay_fidelity()
    assert connection.closed is True


def test_replay_fidelity_closes_comparison_connections_on_failure(monkeypatch, tmp_path):
    def preparation_execute(sql, _params):
        if "COUNT(DISTINCT date)" in sql:
            return _Result(one=(1,))
        return preparation

    preparation = _Connection(preparation_execute)
    live = _Connection(lambda _sql, _params: _Result(rows=[]))
    replay_result = _Connection(
        lambda _sql, _params: (_ for _ in ()).throw(RuntimeError("injected compare failure"))
    )
    connections = iter((preparation, live, replay_result))
    monkeypatch.setattr(proofs, "_copy_store", lambda _name: tmp_path / "proof.duckdb")
    monkeypatch.setattr(
        proofs.db, "connect", lambda *_args, **_kwargs: next(connections)
    )
    monkeypatch.setattr(
        proofs.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(proofs, "run_replay", lambda *_args, **_kwargs: {})

    with pytest.raises(RuntimeError, match="injected compare failure"):
        proofs.replay_fidelity()
    assert preparation.closed is True
    assert live.closed is True
    assert replay_result.closed is True


def test_ensure_screens_closes_connection_on_query_failure(monkeypatch, tmp_path):
    connection = _Connection(
        lambda _sql, _params: (_ for _ in ()).throw(RuntimeError("injected query failure"))
    )
    monkeypatch.setattr(backtest_shakedown.db, "connect", lambda *_args, **_kwargs: connection)

    with pytest.raises(RuntimeError, match="injected query failure"):
        backtest_shakedown.ensure_screens("unused", [], tmp_path)
    assert connection.closed is True


def test_shakedown_empty_window_closes_connection(monkeypatch, tmp_path):
    connection = _Connection()
    monkeypatch.setattr(backtest_shakedown.db, "connect", lambda *_args, **_kwargs: connection)
    monkeypatch.setattr(backtest_shakedown.db, "init_schema", lambda _con: None)
    monkeypatch.setattr(backtest_shakedown, "init_sim_schema", lambda _con: None)
    monkeypatch.setattr(backtest_shakedown, "window_days", lambda *_args: [])

    assert backtest_shakedown.run("unused", tmp_path, 15, False) == 1
    assert connection.closed is True


def test_shakedown_closes_execution_connection_when_step_fails(monkeypatch, tmp_path):
    probe = _Connection()
    execution = _Connection()
    connections = iter((probe, execution))
    monkeypatch.setattr(
        backtest_shakedown.db,
        "connect",
        lambda *_args, **_kwargs: next(connections),
    )
    monkeypatch.setattr(backtest_shakedown.db, "init_schema", lambda _con: None)
    monkeypatch.setattr(backtest_shakedown, "init_sim_schema", lambda _con: None)
    monkeypatch.setattr(
        backtest_shakedown,
        "window_days",
        lambda *_args: [date(2026, 9, 11)],
    )
    monkeypatch.setattr(backtest_shakedown.league, "init_portfolios", lambda *_args: 1)
    monkeypatch.setattr(
        backtest_shakedown.league,
        "step",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("injected step failure")
        ),
    )

    with pytest.raises(RuntimeError, match="injected step failure"):
        backtest_shakedown.run("unused", tmp_path, 15, False)
    assert probe.closed is True
    assert execution.closed is True


def test_hist_screen_main_closes_connection_on_failure(monkeypatch):
    connection = _Connection()
    monkeypatch.setattr(
        "sys.argv",
        [
            "hist_screen.py",
            "--db",
            "unused",
            "--start",
            "2026-09-01",
            "--end",
            "2026-09-02",
        ],
    )
    monkeypatch.setattr(hist_screen.db, "connect", lambda *_args, **_kwargs: connection)
    monkeypatch.setattr(
        hist_screen.db,
        "init_schema",
        lambda _con: (_ for _ in ()).throw(RuntimeError("injected init failure")),
    )

    with pytest.raises(RuntimeError, match="injected init failure"):
        hist_screen.main()
    assert connection.closed is True


def test_execution_drag_main_closes_connection_on_query_failure(monkeypatch):
    connection = _Connection(
        lambda _sql, _params: (_ for _ in ()).throw(RuntimeError("injected query failure"))
    )
    monkeypatch.setattr("sys.argv", ["execution_drag.py", "--no-write"])
    monkeypatch.setattr(
        execution_drag.db,
        "connect",
        lambda *_args, **_kwargs: connection,
    )

    with pytest.raises(RuntimeError, match="injected query failure"):
        execution_drag.main()
    assert connection.closed is True
