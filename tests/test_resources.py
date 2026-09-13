import json
import multiprocessing
import stat
from contextlib import contextmanager
from datetime import date

import pandas as pd
import pytest

from engine import backfill_dividends
from engine.lib import db
from engine.lib import resources as rsc
from farm import experiment
from farm.backtest import replay


def test_read_meta_missing_or_corrupt_is_empty(tmp_path):
    assert rsc.read_meta(tmp_path / "nope.json") == {}
    bad = tmp_path / "_meta.json"
    bad.write_text("{not json")
    assert rsc.read_meta(bad) == {}


def test_merge_meta_preserves_siblings(tmp_path):
    p = tmp_path / "_meta.json"
    p.write_text(json.dumps({"collect": {"rows": 1}, "intraday": {"ok": True}}))
    rsc.merge_meta(p, {"intraday": {"ok": False}})
    got = json.loads(p.read_text())
    assert got == {"collect": {"rows": 1}, "intraday": {"ok": False}}


@pytest.mark.parametrize("payload", ["{not json", "[]"])
def test_merge_meta_refuses_to_erase_invalid_existing_snapshot(tmp_path, payload):
    path = tmp_path / "_meta.json"
    path.write_text(payload)

    with pytest.raises(ValueError, match="refusing to replace"):
        rsc.merge_meta(path, {"intraday": {"ok": True}})

    assert path.read_text() == payload


def _merge_after_barrier(path, key, barrier):
    barrier.wait()
    rsc.merge_meta(path, {key: {"ok": True}})


def test_merge_meta_serializes_parallel_publishers(tmp_path):
    path = tmp_path / "_meta.json"
    path.write_text(json.dumps({"collect": {"rows": 1}}))
    # Pytest may have background threads (including coverage/plugins), so
    # forking its live process can inherit inconsistent thread state.  Spawn
    # clean interpreters while still exercising the real cross-process lock.
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(5)
    processes = [
        context.Process(target=_merge_after_barrier, args=(path, f"miner_{i}", barrier))
        for i in range(4)
    ]

    for process in processes:
        process.start()
    barrier.wait()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    assert json.loads(path.read_text()) == {
        "collect": {"rows": 1},
        **{f"miner_{i}": {"ok": True} for i in range(4)},
    }
    assert (tmp_path / "_meta.json.lock").exists()


def test_merge_meta_lock_covers_read_and_atomic_replace(tmp_path, monkeypatch):
    path = tmp_path / "_meta.json"
    events = []

    @contextmanager
    def recording_lock(lock_path):
        events.append(("lock-enter", lock_path))
        yield
        events.append(("lock-exit", lock_path))

    def recording_read(read_path):
        events.append(("read", read_path))
        return {"screened": 1}

    def recording_write(write_path, text):
        events.append(("write", write_path, json.loads(text)))

    monkeypatch.setattr(rsc, "advisory_file_lock", recording_lock)
    monkeypatch.setattr(rsc, "_read_meta_for_update", recording_read)
    monkeypatch.setattr(rsc, "write_text_atomic", recording_write)

    rsc.merge_meta(path, {"intraday": {"ok": True}})

    assert events == [
        ("lock-enter", tmp_path / "_meta.json.lock"),
        ("read", path),
        ("write", path, {"screened": 1, "intraday": {"ok": True}}),
        ("lock-exit", tmp_path / "_meta.json.lock"),
    ]


def test_write_text_atomic_leaves_no_temp_files(tmp_path):
    p = tmp_path / "sub" / "_meta.json"
    rsc.write_text_atomic(p, "hello")
    assert p.read_text() == "hello"
    assert [f.name for f in p.parent.iterdir()] == ["_meta.json"]
    assert stat.S_IMODE(p.stat().st_mode) == 0o644


def test_write_text_atomic_preserves_existing_mode(tmp_path):
    path = tmp_path / "private.json"
    path.write_text("old")
    path.chmod(0o600)

    rsc.write_text_atomic(path, "new")

    assert path.read_text() == "new"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_write_text_atomic_preserves_target_and_cleans_temp_on_replace_failure(
    tmp_path, monkeypatch
):
    path = tmp_path / "report.json"
    path.write_text("old")
    monkeypatch.setattr(
        rsc.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("replace failed")),
    )

    with pytest.raises(OSError, match="replace failed"):
        rsc.write_text_atomic(path, "new")

    assert path.read_text() == "old"
    assert [item.name for item in tmp_path.iterdir()] == ["report.json"]


def test_advisory_file_lock_takes_and_releases_exclusive_lock(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        rsc.fcntl,
        "flock",
        lambda fd, operation: calls.append((fd, operation)),
    )

    lock_path = tmp_path / "nested" / "report.lock"
    with rsc.advisory_file_lock(lock_path):
        assert lock_path.exists()

    assert [operation for _fd, operation in calls] == [
        rsc.fcntl.LOCK_EX,
        rsc.fcntl.LOCK_UN,
    ]


def test_advisory_file_lock_releases_after_body_failure(tmp_path, monkeypatch):
    operations = []
    monkeypatch.setattr(
        rsc.fcntl,
        "flock",
        lambda _fd, operation: operations.append(operation),
    )

    with pytest.raises(RuntimeError, match="report failed"):
        with rsc.advisory_file_lock(tmp_path / "report.lock"):
            raise RuntimeError("report failed")

    assert operations == [rsc.fcntl.LOCK_EX, rsc.fcntl.LOCK_UN]


def test_disk_warning_set_above_soft_cap(tmp_path):
    p = tmp_path / "_meta.json"
    p.write_text(json.dumps({"collect": 1}))
    rsc.update_disk_warning(p, 61.5, soft_gb=60.0)
    got = json.loads(p.read_text())
    assert got["collect"] == 1
    w = got["disk_warning"]
    assert w["store_gb"] == 61.5 and w["soft_cap_gb"] == 60.0
    assert "over the 60 GiB soft cap" in w["message"]


def test_disk_warning_cleared_at_or_below_cap(tmp_path):
    p = tmp_path / "_meta.json"
    rsc.update_disk_warning(p, 70.0, soft_gb=60.0)
    assert json.loads(p.read_text())["disk_warning"] is not None
    rsc.update_disk_warning(p, 60.0, soft_gb=60.0)          # boundary: not over
    assert json.loads(p.read_text())["disk_warning"] is None


def test_dir_size_gb(tmp_path):
    assert rsc.dir_size_gb(tmp_path / "missing") == 0.0
    (tmp_path / "a.bin").write_bytes(b"x" * (1024 ** 2))
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "b.bin").write_bytes(b"y" * (1024 ** 2))
    assert rsc.dir_size_gb(tmp_path) * 1024 == 2.0


def test_readings_never_block_on_unknown(monkeypatch):
    monkeypatch.setattr(rsc.os, "getloadavg", lambda: (_ for _ in ()).throw(OSError()))
    assert rsc.load_5min() == 0.0
    assert rsc.root_free_gb("/definitely/not/a/path") == float("inf")


def test_registered_frame_is_removed_after_body_failure(con):
    frame = pd.DataFrame({"value": [1]})

    with pytest.raises(RuntimeError, match="injected body failure"):
        with db.registered_frame(con, "_probe_frame", frame):
            assert con.execute("SELECT value FROM _probe_frame").fetchall() == [(1,)]
            raise RuntimeError("injected body failure")

    with pytest.raises(Exception, match="_probe_frame"):
        con.execute("SELECT * FROM _probe_frame")


def test_transaction_rolls_back_interruption_and_keeps_connection_reusable(con):
    con.execute("CREATE TABLE transaction_probe (value INTEGER)")

    with pytest.raises(KeyboardInterrupt, match="injected interruption"):
        with db.transaction(con):
            con.execute("INSERT INTO transaction_probe VALUES (1)")
            raise KeyboardInterrupt("injected interruption")

    assert con.execute("SELECT * FROM transaction_probe").fetchall() == []
    with db.transaction(con):
        con.execute("INSERT INTO transaction_probe VALUES (2)")
    assert con.execute("SELECT * FROM transaction_probe").fetchall() == [(2,)]


def test_transaction_preserves_original_error_when_rollback_fails():
    class RollbackFailingConnection:
        def execute(self, statement):
            if statement == "ROLLBACK":
                raise RuntimeError("injected rollback failure")

    with pytest.raises(KeyboardInterrupt, match="injected interruption") as caught:
        with db.transaction(RollbackFailingConnection()):
            raise KeyboardInterrupt("injected interruption")

    assert caught.value.__notes__ == [
        "transaction rollback also failed: RuntimeError('injected rollback failure')"
    ]


def test_transaction_can_deliberately_roll_back_successful_dry_run(con):
    con.execute("CREATE TABLE dry_run_probe (value INTEGER)")

    with db.transaction(con, commit=False):
        con.execute("INSERT INTO dry_run_probe VALUES (1)")

    assert con.execute("SELECT * FROM dry_run_probe").fetchall() == []


class _FailingInsertConnection:
    """Delegate registration while injecting a failure in the consuming SQL."""

    def __init__(self, con):
        self.con = con

    def register(self, name, frame):
        return self.con.register(name, frame)

    def unregister(self, name):
        return self.con.unregister(name)

    def execute(self, sql, params=None):
        if sql.lstrip().startswith("INSERT INTO"):
            raise RuntimeError("injected insert failure")
        return self.con.execute(sql, params)


def test_experiment_append_unregisters_frame_when_insert_fails(con):
    failing = _FailingInsertConnection(con)

    with pytest.raises(RuntimeError, match="injected insert failure"):
        experiment.append_results(failing, [{"experiment_id": "probe"}])

    with pytest.raises(Exception, match="_exp_rows"):
        con.execute("SELECT * FROM _exp_rows")


def test_replay_screen_copy_unregisters_frame_when_insert_fails(con):
    class LiveConnection:
        def execute(self, _sql, _params):
            return type(
                "Result",
                (),
                {"fetch_df": lambda _self: pd.DataFrame({"ticker": ["SPY"]})},
            )()

    failing = _FailingInsertConnection(con)
    with pytest.raises(RuntimeError, match="injected insert failure"):
        replay._copy_live_screens(
            LiveConnection(), failing, date(2026, 9, 1), date(2026, 9, 2)
        )

    with pytest.raises(Exception, match="_live_sr"):
        con.execute("SELECT * FROM _live_sr")


def test_dividend_backfill_closes_connection_on_initial_query_failure(monkeypatch):
    class Connection:
        closed = False

        def execute(self, _sql):
            raise RuntimeError("injected query failure")

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr("sys.argv", ["backfill_dividends.py"])
    monkeypatch.setattr(
        backfill_dividends.db,
        "connect",
        lambda *_args, **_kwargs: connection,
    )

    with pytest.raises(RuntimeError, match="injected query failure"):
        backfill_dividends.main()
    assert connection.closed is True
