"""Shared walk-forward scratch and interruption cleanup."""
from __future__ import annotations

import json
import multiprocessing
import os
import signal
from datetime import date
from pathlib import Path

from engine import queue_runner as qr
from engine.lib import db
from farm.walkforward import runner


def test_orphan_sweep_never_removes_locked_or_open_directory(tmp_path):
    stale = tmp_path / "wf__stale"
    locked = tmp_path / "wf__locked"
    opened = tmp_path / "wf__opened"
    for directory in (stale, locked, opened):
        directory.mkdir()
        (directory / "replay.duckdb").write_bytes(b"scratch")

    with (opened / "replay.duckdb").open("rb") as open_db:
        with runner._hold_scratch_directory(locked):
            stats = qr._sweep_walkforward_orphans(tmp_path)
            assert open_db.read(1) == b"s"
            assert stats["removed"] == 1
            assert stats["held"] == 2
            assert not stale.exists()
            assert locked.exists()
            assert opened.exists()

    stats = qr._sweep_walkforward_orphans(tmp_path)
    assert stats["removed"] == 2
    assert not locked.exists()
    assert not opened.exists()


class _Result:
    def __init__(self, one=None):
        self.one = one

    def fetchone(self):
        return self.one


class _LiveConnection:
    def execute(self, sql, _params=None):
        if "MIN(date)" in sql:
            return _Result((date(2023, 1, 3),))
        if "MAX(date)" in sql:
            return _Result((date(2026, 1, 2),))
        raise AssertionError(sql)


def _book(config_id="probe"):
    return {
        "id": config_id,
        "name": config_id,
        "strategy": "spy_benchmark",
        "config": {"id": config_id, "cadence": "monthly"},
        "config_json": json.dumps({"id": config_id, "cadence": "monthly"}),
        "created": "2026-01-01",
        "initial_cash": 39_000.0,
        "execution_profile": "baseline_v1",
        "comparison": {"control_id": "fixture", "protocol": "fixture-v1"},
        "excluded": None,
    }


def test_sigterm_runs_walkforward_finally_cleanup(monkeypatch, tmp_path):
    context = multiprocessing.get_context("fork")
    building = context.Event()
    monkeypatch.delenv(runner.SHARED_RUN_ENV, raising=False)
    monkeypatch.setattr(runner, "_provenance", lambda _cfg: {})
    monkeypatch.setattr(runner, "data_snapshot", lambda _con: {})
    monkeypatch.setattr(runner, "data_floor", lambda *_args: date(2000, 1, 1))
    monkeypatch.setattr(
        runner.hist_screen,
        "sessions_between",
        lambda *_args: [date(2023, 1, 3), date(2025, 1, 3), date(2026, 1, 2)],
    )

    def block_in_scratch(_live, scratch_dir, _start, _end, verbose=False):
        (scratch_dir / "replay.duckdb").touch()
        building.set()
        signal.pause()

    monkeypatch.setattr(runner, "build_scratch", block_in_scratch)

    def worker():
        try:
            runner.run_book(
                _LiveConnection(), "probe", anchor=date(2026, 1, 3), n_folds=1,
                book=_book(), scratch_root=tmp_path, results_dir=tmp_path,
                write_result=False, verbose=False, threads=None, mem_mb=None,
            )
        except SystemExit:
            pass

    process = context.Process(target=worker)
    process.start()
    assert building.wait(timeout=5)
    os.kill(process.pid, signal.SIGTERM)
    process.join(timeout=5)

    assert process.exitcode == 0
    assert list(tmp_path.glob("wf__probe__p*")) == []


def test_shared_overlay_fixture_grid_matches_private_results(
    con, monkeypatch, tmp_path
):
    db.init_schema(con)
    db.init_queue_schema(con)
    db.init_mining_schema(con)
    db.init_actions_schema(con)
    dates = [date(2023, 1, 3), date(2024, 1, 3),
             date(2025, 1, 3), date(2026, 1, 2)]
    con.executemany(
        "INSERT INTO prices (ticker,date,open,high,low,close,volume) "
        "VALUES ('SPY',?,?,?,?,?,1000000)",
        [(day, 100.0, 101.0, 99.0, 100.0 + index)
         for index, day in enumerate(dates)],
    )
    monkeypatch.setattr(runner, "_provenance", lambda cfg: {
        "config": dict(cfg), "config_sha256": cfg["id"],
        "source_sha256": "fixture", "source_file_count": 1,
        "git_sha": "fixture", "git_dirty": False,
    })
    monkeypatch.setattr(runner, "data_snapshot", lambda _con: {"sha256": "fixture"})
    monkeypatch.setattr(runner, "data_floor", lambda *_args: date(2000, 1, 1))
    monkeypatch.setattr(runner.hist_screen, "sessions_between", lambda *_args: dates)

    def fixture_fold(scratch_con, _book, fold, sessions, *_args, **_kwargs):
        count, total = scratch_con.execute(
            "SELECT COUNT(*), SUM(close) FROM prices"
        ).fetchone()
        scratch_con.execute(
            "INSERT INTO sim_equity VALUES (?, ?, ?, ?, ?)",
            [_book["id"], sessions[-1], float(total), 1.0, 0],
        )
        return {
            **fold.as_dict(), "status": "inert", "sessions": int(count),
            "reason": f"fixture price sum {total}",
        }

    monkeypatch.setattr(runner, "run_fold", fixture_fold)
    real_build = runner.build_scratch
    builds = []

    def counted_build(*args, **kwargs):
        builds.append(Path(args[1]))
        return real_build(*args, **kwargs)

    monkeypatch.setattr(runner, "build_scratch", counted_build)
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    old = []
    monkeypatch.delenv(runner.SHARED_RUN_ENV, raising=False)
    for config_id in ("fixture-a", "fixture-b"):
        old.append(runner.run_book(
            con, config_id, anchor=date(2026, 1, 3), n_folds=1,
            book=_book(config_id), scratch_root=old_root,
            write_result=False, verbose=False, threads=None, mem_mb=None,
        ))

    monkeypatch.setenv(runner.SHARED_RUN_ENV, "fixture-grid")
    new = []
    for config_id in ("fixture-a", "fixture-b"):
        new.append(runner.run_book(
            con, config_id, anchor=date(2026, 1, 3), n_folds=1,
            book=_book(config_id), scratch_root=new_root,
            write_result=False, verbose=False, threads=None, mem_mb=None,
        ))

    def stable(result):
        return {key: value for key, value in result.items()
                if key not in {"generated_utc", "runtime_s", "scratch_s", "screen_s"}}

    assert [stable(result) for result in new] == [stable(result) for result in old]
    assert len(builds) == 3  # two private copies, then one base shared by both workers
    assert len(list((new_root / "wf__shared__fixture-grid").glob("replay.duckdb"))) == 1
