"""engine/queue_runner.py — nightly enqueue policy, per-job timeout, supersede.

Every DB is in-memory (or a tmp_path file where a subprocess must reopen it).
store/ is never opened.
"""
from __future__ import annotations

import builtins
import subprocess
import sys
import time
from datetime import date

import duckdb
import pytest

from engine import queue_runner as qr
from engine.lib import db


@pytest.fixture
def qcon():
    """In-memory store with the base + queue schema, as the runner's main() does."""
    c = duckdb.connect()
    qr.ensure_schema(c)
    yield c
    c.close()


def _rows(con, cols="id, kind, state, priority, params, timeout_s"):
    return con.execute(f"SELECT {cols} FROM jobs ORDER BY id").fetchall()


def test_main_closes_connection_on_schema_failure(monkeypatch):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr("sys.argv", ["queue_runner.py", "--status"])
    monkeypatch.setattr(qr.db, "connect", lambda *_args, **_kwargs: connection)
    monkeypatch.setattr(
        qr,
        "ensure_schema",
        lambda _con: (_ for _ in ()).throw(RuntimeError("injected schema failure")),
    )

    with pytest.raises(RuntimeError, match="injected schema failure"):
        qr.main()
    assert connection.closed is True


# --------------------------------------------------------------------------- #
# nightly plan
# --------------------------------------------------------------------------- #
def test_nightly_plan_monday_has_three_mining_jobs():
    plan = qr.nightly_plan(date(2026, 8, 31))  # a Monday
    assert [(k, p) for k, p, _ in plan] == [
        ("intraday", 100), ("signals", 105), ("earnings", 110)]
    assert dict((k, params) for k, _, params in plan)["signals"] == '{"mode": "incremental"}'


def test_nightly_plan_friday_adds_fundamentals_last():
    plan = qr.nightly_plan(date(2026, 9, 4))  # a Friday
    assert [(k, p) for k, p, _ in plan] == [
        ("intraday", 100), ("signals", 105), ("earnings", 110),
        ("fundamentals", 120)]


@pytest.mark.parametrize("wd", [1, 2, 3, 4, 6, 7])
def test_nightly_plan_weekday_override_non_friday(wd):
    assert [k for k, _, _ in qr.nightly_plan(weekday=wd)] == [
        "intraday", "signals", "earnings"]


def test_nightly_plan_weekday_override_beats_date():
    plan = qr.nightly_plan(date(2026, 8, 31), weekday=5)   # Monday date, forced Friday
    assert plan[-1][0] == "fundamentals"


def test_nightly_plan_rejects_bad_weekday():
    with pytest.raises(ValueError):
        qr.nightly_plan(weekday=0)


def test_paused_nightly_plan_does_not_import_tradingview_collector(monkeypatch):
    monkeypatch.setattr(qr, "_tradingview_history_collection_enabled", lambda: False)
    original_import = builtins.__import__

    def refuse_collector(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "engine" and "tradingview_history_archive" in fromlist:
            raise ImportError("injected stopped collector import failure")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", refuse_collector)
    assert [kind for kind, _priority, _params in qr.nightly_plan(weekday=2)] == [
        "intraday", "signals", "earnings",
    ]


def test_nightly_plan_priorities_precede_every_research_kind():
    # sweeps 900, walk-forward 170-176, backtests 140-165: mining must sort first
    assert max(p for _, p, _ in qr.nightly_plan(weekday=5)) < 140


def test_enqueue_nightly_writes_rows_and_is_idempotent(qcon, capsys):
    assert qr.cmd_enqueue_nightly(qcon, weekday=5) == 0
    rows = _rows(qcon, "kind, state, priority, params")
    assert rows == [
        ("intraday", "pending", 100, "{}"),
        ("signals", "pending", 105, '{"mode": "incremental"}'),
        ("earnings", "pending", 110, "{}"),
        ("fundamentals", "pending", 120, "{}"),
    ]
    # a second nightly (same weekday) dedups every one — the guard-tripped case
    assert qr.cmd_enqueue_nightly(qcon, weekday=5) == 0
    assert len(_rows(qcon)) == 4
    assert "skipping duplicate enqueue" in capsys.readouterr().out


def test_enqueue_nightly_monday_skips_fundamentals(qcon):
    qr.cmd_enqueue_nightly(qcon, date(2026, 8, 31))
    assert [r[0] for r in _rows(qcon, "kind")] == [
        "intraday", "signals", "earnings"]


def test_enqueue_nightly_params_match_the_old_bash_text(qcon):
    """Dedup compares the stored params TEXT; the bash driver wrote exactly
    '{"mode": "incremental"}' for signals, so a pending row from before the
    policy moved into Python must still dedup against the new enqueue."""
    qr.cmd_enqueue(qcon, "signals", '{"mode": "incremental"}', 105, None)
    qr.cmd_enqueue_nightly(qcon, weekday=2)
    assert qcon.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'signals'").fetchone()[0] == 1


def test_enqueue_nightly_dry_run_writes_nothing(qcon, capsys):
    assert qr.cmd_enqueue_nightly(qcon, weekday=5, dry_run=True) == 0
    assert _rows(qcon) == []
    out = capsys.readouterr().out
    assert out.count("DRY RUN would enqueue") == 4
    assert "fundamentals priority=120" in out


def test_one_shot_enqueue_skips_equivalent_completed_job(qcon, capsys):
    qr.cmd_enqueue(qcon, "sweep", '{"grid":"new_hypothesis"}', 900, None)
    qcon.execute("UPDATE jobs SET state = 'done' WHERE id = 1")

    assert qr.cmd_enqueue(
        qcon, "sweep", '{"grid": "new_hypothesis"}', 900, None, once=True
    ) == 0

    assert _rows(qcon, "id, state") == [(1, "done")]
    assert "already done" in capsys.readouterr().out


def test_one_shot_completed_job_supersedes_equivalent_pending_duplicate(qcon):
    qr.cmd_enqueue(qcon, "sweep", '{"grid":"x","charter_version":"v1"}', 900, None)
    qcon.execute("UPDATE jobs SET state = 'done' WHERE id = 1")
    qr.cmd_enqueue(qcon, "sweep", '{"grid":"x","charter_version":"v1"}', 900, None)
    assert _rows(qcon, "id, state") == [(1, "done"), (2, "pending")]

    qr.cmd_enqueue(
        qcon,
        "sweep",
        '{"charter_version":"v1","grid":"x"}',
        900,
        None,
        once=True,
    )
    assert _rows(qcon, "id, state") == [(1, "done"), (2, "superseded")]


def test_normal_enqueue_may_repeat_completed_job(qcon):
    qr.cmd_enqueue(qcon, "sweep", '{"grid":"manual_reproduction"}', 900, None)
    qcon.execute("UPDATE jobs SET state = 'done' WHERE id = 1")
    qr.cmd_enqueue(qcon, "sweep", '{"grid": "manual_reproduction"}', 900, None)
    assert _rows(qcon, "id, state") == [(1, "done"), (2, "pending")]


def test_param_identity_preserves_json_types_and_rejects_nonfinite(qcon):
    qr.cmd_enqueue(qcon, "sweep", '{"limit":true}', 900, None)
    qr.cmd_enqueue(qcon, "sweep", '{"limit":1}', 900, None)
    assert _rows(qcon, "id, state") == [(1, "pending"), (2, "pending")]
    assert qr.cmd_enqueue(qcon, "sweep", '{"limit":NaN}', 900, None) == 1


# --------------------------------------------------------------------------- #
# schema / timeout column
# --------------------------------------------------------------------------- #
def test_ensure_schema_adds_timeout_column_idempotently():
    c = duckdb.connect()
    # A pre-2026-09-03 jobs table; fresh stores now create the column themselves.
    c.execute(
        "CREATE TABLE jobs (id INTEGER PRIMARY KEY, kind VARCHAR, params VARCHAR, "
        "state VARCHAR DEFAULT 'queued', progress VARCHAR, created_at TIMESTAMP, "
        "updated_at TIMESTAMP, priority INTEGER DEFAULT 100, mem_mb INTEGER DEFAULT 0, "
        "last_error VARCHAR)"
    )
    cols = {r[0] for r in c.execute("DESCRIBE jobs").fetchall()}
    assert "timeout_s" not in cols
    qr.ensure_schema(c)
    qr.ensure_schema(c)  # second call must be a no-op, like the live migration
    cols = {r[0] for r in c.execute("DESCRIBE jobs").fetchall()}
    assert "timeout_s" in cols


def test_enqueue_timeout_defaults_to_null_and_kind_default(qcon):
    qr.cmd_enqueue(qcon, "sweep", "{}", 900, None)
    qr.cmd_enqueue(qcon, "sweep", '{"grid": "x"}', 900, None, 123)
    assert _rows(qcon, "kind, timeout_s") == [("sweep", None), ("sweep", 123)]
    assert qr.default_timeout_s("sweep") == 14 * 3600
    assert qr.default_timeout_s("intraday") == qr.TIMEOUT_DEFAULT_S
    assert qr.default_timeout_s("no-such-kind") == qr.TIMEOUT_DEFAULT_S


def test_every_kind_default_timeout_is_generous():
    for kind in qr.JOB_TYPES:
        assert qr.default_timeout_s(kind) >= 4 * 3600, kind


@pytest.mark.parametrize(
    "kind", ["actions", "earnings", "fundamentals", "intraday", "signals"]
)
def test_long_http_miners_release_writer_but_remain_sequential(kind):
    spec = qr.JOB_TYPES[kind]
    assert spec["releases_writer"] is True
    assert not spec.get("parallel_safe", False)
    assert callable(spec["detached_loader"]())


def test_connection_narrowed_earnings_child_completes_and_reacquires(tmp_path):
    dbp = tmp_path / "q.duckdb"
    con = db.connect(dbp)
    qr.ensure_schema(con)
    # An empty initialized universe makes this a real subprocess/lifecycle test
    # without making any external HTTP request.
    qr.cmd_enqueue(con, "earnings", "{}", 110, None)
    result, con = qr._run_releasing_job(
        (1, "earnings", 60), str(dbp), tmp_path / "meta.json", con
    )
    assert result == 0
    assert con.execute(
        "SELECT state, progress, last_error FROM jobs WHERE id = 1"
    ).fetchone() == ("done", "complete", None)
    assert con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = 'earnings_fetch_log'"
    ).fetchone() == (1,)
    con.close()


def test_connection_narrowed_fundamentals_child_completes_and_reacquires(tmp_path):
    dbp = tmp_path / "q.duckdb"
    con = db.connect(dbp)
    qr.ensure_schema(con)
    qr.cmd_enqueue(con, "fundamentals", "{}", 120, None)
    result, con = qr._run_releasing_job(
        (1, "fundamentals", 60), str(dbp), tmp_path / "meta.json", con
    )
    assert result == 0
    assert con.execute(
        "SELECT state, progress, last_error FROM jobs WHERE id = 1"
    ).fetchone() == ("done", "complete", None)
    assert con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = 'fundamentals_fetch_log'"
    ).fetchone() == (1,)
    con.close()


def test_connection_narrowed_actions_child_completes_and_reacquires(tmp_path):
    dbp = tmp_path / "q.duckdb"
    con = db.connect(dbp)
    qr.ensure_schema(con)
    qr.cmd_enqueue(con, "actions", '{"mode":"backfill"}', 130, None)
    result, con = qr._run_releasing_job(
        (1, "actions", 60), str(dbp), tmp_path / "meta.json", con
    )
    assert result == 0
    assert con.execute(
        "SELECT state, progress, last_error FROM jobs WHERE id = 1"
    ).fetchone() == ("done", "complete", None)
    assert con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = 'actions_fetch_log'"
    ).fetchone() == (1,)
    con.close()


def test_connection_narrowed_intraday_child_completes_and_reacquires(tmp_path):
    dbp = tmp_path / "q.duckdb"
    con = db.connect(dbp)
    qr.ensure_schema(con)
    # limit=0 exercises the real subprocess path without an external HTTP call.
    qr.cmd_enqueue(con, "intraday", '{"limit":0}', 100, None)
    result, con = qr._run_releasing_job(
        (1, "intraday", 60), str(dbp), tmp_path / "meta.json", con
    )
    assert result == 0
    assert con.execute(
        "SELECT state, progress, last_error FROM jobs WHERE id = 1"
    ).fetchone() == ("done", "complete", None)
    assert con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = 'intraday_prices'"
    ).fetchone() == (1,)
    con.close()


def test_connection_narrowed_signals_child_completes_and_reacquires(tmp_path):
    dbp = tmp_path / "q.duckdb"
    con = db.connect(dbp)
    qr.ensure_schema(con)
    # Breadth alone avoids HTTP; an empty fixture is a reported source warning,
    # not a queue failure, under signals' established warn-and-continue contract.
    qr.cmd_enqueue(con, "signals", '{"only":"breadth"}', 105, None)
    result, con = qr._run_releasing_job(
        (1, "signals", 60), str(dbp), tmp_path / "meta.json", con
    )
    assert result == 0
    assert con.execute(
        "SELECT state, progress, last_error FROM jobs WHERE id = 1"
    ).fetchone() == ("done", "complete", None)
    assert con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = 'macro_signals'"
    ).fetchone() == (1,)
    con.close()


def test_connection_narrowed_child_reports_lock_exhaustion(tmp_path, monkeypatch):
    """Exercise the real child entry while another process owns DuckDB."""
    dbp = tmp_path / "q.duckdb"
    con = db.connect(dbp)
    qr.ensure_schema(con)
    qr.cmd_enqueue(con, "tradingview_history", "{}", 130, None)
    monkeypatch.setenv("TRADING_ENGINE_LOCK_WAIT_S", "0")

    result = subprocess.run(
        qr._child_cmd(1, str(dbp), tmp_path / "meta.json"),
        cwd=qr.REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Could not set lock on file" in result.stderr
    assert "Conflicting lock is held" in result.stderr
    con.close()


# --------------------------------------------------------------------------- #
# per-job timeout enforced on the parallel children
# --------------------------------------------------------------------------- #
@pytest.fixture
def sleepy_kind(monkeypatch):
    """A fake parallel_safe kind whose child is a python that sleeps; the parent
    kills it at timeout_s. `_child_cmd` is swapped so the child needs neither
    the store nor the dispatch table."""
    monkeypatch.setitem(qr.JOB_TYPES, "sleepy", {
        "loader": lambda: None, "archive": False, "mem_mb": 10,
        "parallel_safe": True, "timeout_s": 1})
    monkeypatch.setattr(
        qr, "_child_cmd",
        lambda jid, db_path, meta_path: [sys.executable, "-c", "import time; time.sleep(30)"])
    monkeypatch.setattr(qr, "BATCH_STAGGER_S", 0.0)
    monkeypatch.setattr(qr, "KILL_GRACE_S", 2.0)
    monkeypatch.setattr(qr.rsc, "load_5min", lambda: 0.0)
    monkeypatch.setattr(qr.rsc, "free_ram_gb", lambda: 100.0)
    return "sleepy"


def test_parallel_child_is_killed_at_timeout(tmp_path, sleepy_kind, monkeypatch):
    dbp = tmp_path / "q.duckdb"
    con = db.connect(dbp)
    qr.ensure_schema(con)
    qr.cmd_enqueue(con, sleepy_kind, "{}", 100, None)           # kind default 1 s
    qr.cmd_enqueue(con, sleepy_kind, '{"n": 2}', 100, None, 2)  # explicit 2 s
    pool = [
        (1, sleepy_kind, "{}", 10, None, 100),
        (2, sleepy_kind, '{"n": 2}', 10, 2, 100),
    ]
    t0 = time.monotonic()
    results, con, stopped = qr._run_parallel_pool(
        pool, str(dbp), tmp_path / "meta.json", con, width=2,
        drain_deadline=t0 + 60,
    )
    elapsed = time.monotonic() - t0
    assert stopped is None
    assert results == {1: "timeout", 2: "timeout"}
    assert elapsed < 15, "a 30 s sleeper must not run to completion"
    rows = con.execute(
        "SELECT id, state, progress, last_error FROM jobs ORDER BY id").fetchall()
    assert rows[0] == (1, "failed", "timeout", "timeout: killed after 1s")
    assert rows[1] == (2, "failed", "timeout", "timeout: killed after 2s")
    con.close()


def test_parallel_child_finishing_in_time_is_done(tmp_path, sleepy_kind, monkeypatch):
    monkeypatch.setattr(
        qr, "_child_cmd", lambda jid, db_path, meta_path: [sys.executable, "-c", "pass"])
    dbp = tmp_path / "q.duckdb"
    con = db.connect(dbp)
    qr.ensure_schema(con)
    qr.cmd_enqueue(con, sleepy_kind, "{}", 100, None, 60)
    results, con, stopped = qr._run_parallel_pool(
        [(1, sleepy_kind, "{}", 10, 60, 100)],
        str(dbp), tmp_path / "meta.json", con, width=2,
        drain_deadline=time.monotonic() + 60,
    )
    assert stopped is None
    assert results == {1: 0}
    assert con.execute("SELECT state FROM jobs WHERE id = 1").fetchone() == ("done",)
    con.close()


def test_wait_batch_records_nonzero_exit_as_rc():
    import subprocess
    pr = subprocess.Popen([sys.executable, "-c", "raise SystemExit(7)"])
    res = qr._wait_batch([(9, "k", pr, time.monotonic() + 60)], poll_s=0.05)
    assert res == {9: 7}


def _fake_pool_processes(monkeypatch, durations):
    import subprocess

    class Clock:
        now = 0.0

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    clock = Clock()
    starts = []

    class Process:
        def __init__(self, jid):
            self.jid = jid
            self.finished_at = clock.now + durations[jid]
            self.returncode = None
            starts.append((jid, clock.now))

        def poll(self):
            if self.returncode is None and clock.now >= self.finished_at:
                self.returncode = 0
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

        def wait(self, timeout=None):
            if self.returncode is None:
                clock.now = self.finished_at
                self.returncode = 0
            return self.returncode

    monkeypatch.setattr(qr, "_child_cmd", lambda jid, *_args: [str(jid)])
    monkeypatch.setattr(
        subprocess, "Popen", lambda command, **_kwargs: Process(int(command[0]))
    )
    monkeypatch.setattr(qr, "BATCH_STAGGER_S", 0.0)
    monkeypatch.setattr(qr, "BATCH_POLL_S", 0.1)
    monkeypatch.setattr(qr.rsc, "load_5min", lambda: 0.0)
    monkeypatch.setattr(qr.rsc, "free_ram_gb", lambda: 100.0)
    return clock, starts


def test_rolling_pool_refills_freed_slots_and_records_in_job_order(
    tmp_path, monkeypatch
):
    clock, starts = _fake_pool_processes(
        monkeypatch, {1: 10.0, 2: 1.0, 3: 1.0, 4: 1.0}
    )
    dbp = tmp_path / "q.duckdb"
    con = db.connect(dbp)
    qr.ensure_schema(con)
    for jid, priority in enumerate((170, 170, 172, 176), start=1):
        qr.cmd_enqueue(
            con, "walkforward", f'{{"config_id":"book-{jid}"}}', priority, 10
        )

    state_order = []
    set_state = qr._set_state

    def record_state(connection, jid, state, **kwargs):
        state_order.append((jid, state))
        set_state(connection, jid, state, **kwargs)

    monkeypatch.setattr(qr, "_set_state", record_state)
    pool = con.execute(
        "SELECT id, kind, params, mem_mb, timeout_s, priority FROM jobs "
        "ORDER BY priority, created_at"
    ).fetchall()
    results, con, stopped = qr._run_parallel_pool(
        pool, str(dbp), tmp_path / "meta.json", con, width=2,
        drain_deadline=100.0, _clock=clock.monotonic, _sleep=clock.sleep,
    )

    assert stopped is None
    assert [jid for jid, _started in starts] == [1, 2, 3, 4]
    assert starts[2][1] < 10.0  # job 3 starts while slow job 1 still occupies slot 1
    assert starts[3][1] < 10.0
    assert list(results) == [1, 2, 3, 4]
    assert state_order[-4:] == [(1, "done"), (2, "done"),
                               (3, "done"), (4, "done")]
    assert _rows(con, "id, state") == [
        (1, "done"), (2, "done"), (3, "done"), (4, "done")
    ]
    con.close()


def test_rolling_pool_stops_launching_at_drain_budget(tmp_path, monkeypatch):
    clock, starts = _fake_pool_processes(
        monkeypatch, {1: 1.0, 2: 1.0, 3: 1.0}
    )
    dbp = tmp_path / "q.duckdb"
    con = db.connect(dbp)
    qr.ensure_schema(con)
    for jid, priority in enumerate((170, 172, 174), start=1):
        qr.cmd_enqueue(
            con, "walkforward", f'{{"config_id":"book-{jid}"}}', priority, 10
        )
    pool = con.execute(
        "SELECT id, kind, params, mem_mb, timeout_s, priority FROM jobs "
        "ORDER BY priority, created_at"
    ).fetchall()

    results, con, stopped = qr._run_parallel_pool(
        pool, str(dbp), tmp_path / "meta.json", con, width=1,
        drain_deadline=1.5, _clock=clock.monotonic, _sleep=clock.sleep,
    )

    assert stopped == "budget"
    assert [jid for jid, _started in starts] == [1, 2]
    assert results == {1: 0, 2: 0}
    assert _rows(con, "id, state") == [
        (1, "done"), (2, "done"), (3, "pending")
    ]
    con.close()


def test_drain_rolling_pool_keeps_sorted_priority_order_until_writer_barrier(
    qcon, monkeypatch, tmp_path
):
    for kind, priority, params in (
        ("walkforward", 170, '{"config_id":"a"}'),
        ("walkforward", 170, '{"config_id":"b"}'),
        ("walkforward", 176, '{"config_id":"c"}'),
        ("sweep", 900, '{"grid":"x"}'),
        ("sweep", 900, '{"grid":"y"}'),
    ):
        qr.cmd_enqueue(qcon, kind, params, priority, None)
    pools = []

    def record(pool, db_path, meta_path, con, *, width, drain_deadline):
        pools.append([(row[0], row[1], row[5]) for row in pool])
        return {}, con, None

    monkeypatch.setattr(qr, "_run_parallel_pool", record)
    monkeypatch.setattr(qr.rsc, "load_5min", lambda: 0.0)
    monkeypatch.setattr(qr.rsc, "free_ram_gb", lambda: 100.0)
    assert qr._drain(qcon, tmp_path / "meta.json", jobs=8) == 0
    assert pools == [[
        (1, "walkforward", 170),
        (2, "walkforward", 170),
        (3, "walkforward", 176),
        (4, "sweep", 900),
        (5, "sweep", 900),
    ]]


def test_targeted_drain_runs_only_exact_authorized_params(qcon, monkeypatch, tmp_path):
    qr.cmd_enqueue(qcon, "sweep", '{"grid":"old"}', 900, None)
    qr.cmd_enqueue(qcon, "sweep", '{"grid":"open"}', 900, None)
    qr.cmd_enqueue(qcon, "walkforward", '{"config_id":"book"}', 170, None)
    pools = []

    def record(pool, db_path, meta_path, con, *, width, drain_deadline):
        pools.append([row[0] for row in pool])
        for jid, _kind, _params, _mem_mb, _timeout, _priority in pool:
            qr._set_state(con, jid, "done")
        return {}, con, None

    monkeypatch.setattr(qr, "_run_parallel_pool", record)
    monkeypatch.setattr(qr.rsc, "load_5min", lambda: 0.0)
    monkeypatch.setattr(qr.rsc, "free_ram_gb", lambda: 100.0)
    assert qr._drain(
        qcon,
        tmp_path / "meta.json",
        jobs=8,
        run_kind="sweep",
        run_params=['{"grid": "open"}'],
    ) == 0
    assert pools == [[2]]
    assert _rows(qcon, "id, state") == [
        (1, "pending"), (2, "done"), (3, "pending")
    ]


def test_targeted_drain_reclaims_but_does_not_run_unrelated_stale_job(qcon, capsys, tmp_path):
    qr.cmd_enqueue(qcon, "sweep", '{"grid":"old"}', 900, None)
    qcon.execute("UPDATE jobs SET state = 'running' WHERE id = 1")
    assert qr._drain(
        qcon,
        tmp_path / "meta.json",
        run_kind="sweep",
        run_params=['{"grid":"open"}'],
    ) == 0
    assert _rows(qcon, "id, state") == [(1, "pending")]
    assert "reclaimed stale running job 1" in capsys.readouterr().out


def test_global_drain_fails_closed_on_legacy_unversioned_sweep(
    qcon, monkeypatch, tmp_path
):
    qr.cmd_enqueue(qcon, "sweep", '{"grid":"concentration"}', 900, None)
    monkeypatch.setattr(qr.rsc, "load_5min", lambda: 0.0)
    monkeypatch.setattr(qr.rsc, "free_ram_gb", lambda: 100.0)
    monkeypatch.setattr(qr, "_DRAIN_LOCK_FD", 1)
    assert qr._drain(qcon, tmp_path / "meta.json", jobs=1) == 0
    state, error = qcon.execute(
        "SELECT state, last_error FROM jobs WHERE id = 1"
    ).fetchone()
    assert state == "failed"
    assert "require a charter_version" in error


# --------------------------------------------------------------------------- #
# supersede
# --------------------------------------------------------------------------- #
def test_supersede_marks_older_pending_of_same_kind_with_other_params(qcon):
    assert qr.JOB_TYPES["intraday"].get("supersedes") is True
    qr.cmd_enqueue(qcon, "intraday", '{"limit": 5}', 100, None)
    qr.cmd_enqueue(qcon, "intraday", '{"limit": 9}', 100, None)
    qr.cmd_enqueue(qcon, "intraday", "{}", 100, None)
    rows = _rows(qcon, "id, params, state, last_error")
    assert rows[0][2] == rows[1][2] == "superseded"
    assert "superseded by a newer enqueue" in rows[0][3]
    assert rows[2] == (3, "{}", "pending", None)
    # a superseded row is not pending, so the drain never picks it up
    pend = qcon.execute("SELECT id FROM jobs WHERE state = 'pending'").fetchall()
    assert pend == [(3,)]


def test_supersede_leaves_identical_params_deduped_not_superseded(qcon, capsys):
    qr.cmd_enqueue(qcon, "intraday", "{}", 100, None)
    qr.cmd_enqueue(qcon, "intraday", "{}", 100, None)
    assert _rows(qcon, "id, state") == [(1, "pending")]
    assert "skipping duplicate enqueue" in capsys.readouterr().out


def test_supersede_ignores_running_done_failed_rows(qcon):
    qr.cmd_enqueue(qcon, "intraday", '{"limit": 1}', 100, None)
    qr.cmd_enqueue(qcon, "intraday", '{"limit": 2}', 100, None)
    qr.cmd_enqueue(qcon, "intraday", '{"limit": 3}', 100, None)
    qcon.execute("UPDATE jobs SET state = 'running' WHERE id = 1")
    qcon.execute("UPDATE jobs SET state = 'done' WHERE id = 2")
    qcon.execute("UPDATE jobs SET state = 'pending' WHERE id = 3")
    qr.cmd_enqueue(qcon, "intraday", "{}", 100, None)
    assert [r[1] for r in _rows(qcon, "id, state")] == [
        "running", "done", "superseded", "pending"]


def test_supersede_covers_legacy_queued_state(qcon):
    qcon.execute(
        "INSERT INTO jobs (id, kind, params, state) VALUES (1, 'intraday', '{\"old\": 1}', 'queued')")
    qr.cmd_enqueue(qcon, "intraday", "{}", 100, None)
    assert _rows(qcon, "id, state") == [(1, "superseded"), (2, "pending")]


def test_non_superseding_kind_keeps_older_variants(qcon):
    assert not qr.JOB_TYPES["sweep"].get("supersedes")
    qr.cmd_enqueue(qcon, "sweep", '{"grid": "a"}', 900, None)
    qr.cmd_enqueue(qcon, "sweep", '{"grid": "b"}', 900, None)
    assert [r[1] for r in _rows(qcon, "id, state")] == ["pending", "pending"]


def test_supersede_dry_run_writes_nothing(qcon, capsys):
    qr.cmd_enqueue(qcon, "intraday", '{"limit": 5}', 100, None)
    qr.cmd_enqueue(qcon, "intraday", "{}", 100, None, dry_run=True)
    assert _rows(qcon, "id, state") == [(1, "pending")]
    assert "would supersede job 1" in capsys.readouterr().out


def test_status_lists_superseded_rows(qcon, capsys):
    qr.cmd_enqueue(qcon, "intraday", '{"limit": 5}', 100, None)
    qr.cmd_enqueue(qcon, "intraday", "{}", 100, None)
    capsys.readouterr()
    assert qr.cmd_status(qcon) == 0
    out = capsys.readouterr().out
    assert "superseded" in out and "pending" in out


# --------------------------------------------------------------------------- #
# drain scheduling (2026-10-20): research isolation, non-latching guard,
# partial reporting, walk-forward ceiling, snapshot reads
# --------------------------------------------------------------------------- #
@pytest.fixture
def sequential_kind(monkeypatch):
    """A fake store-writing kind that runs in-process and records each run."""
    ran = []
    monkeypatch.setitem(qr.JOB_TYPES, "seqfake", {
        "loader": lambda: (lambda params, con, meta_path=None: ran.append(params)),
        "archive": False, "mem_mb": 10})
    monkeypatch.setattr(qr.rsc, "load_5min", lambda: 0.0)
    monkeypatch.setattr(qr.rsc, "free_ram_gb", lambda: 100.0)
    monkeypatch.setattr(qr.rsc, "dir_size_gb", lambda _path, **_kwargs: 0.0)
    monkeypatch.setattr(qr.rsc, "root_free_gb", lambda _path: 100.0)
    monkeypatch.setattr(qr.rsc, "update_disk_warning", lambda *_args, **_kwargs: None)
    return ran


def test_nightly_drain_leaves_research_rows_pending(
    qcon, sequential_kind, monkeypatch, tmp_path, capsys
):
    """Sunday leftovers must not reach Monday's 22:30 drain (2026-10-19)."""
    qr.cmd_enqueue(qcon, "seqfake", '{"n":1}', 100, None)
    qr.cmd_enqueue(qcon, "walkforward", '{"config_id":"a"}', 170, None)
    qr.cmd_enqueue(qcon, "sweep", '{"grid":"x"}', 900, None)
    qr.cmd_enqueue(qcon, "capital_sensitivity", "{}", 900, None)
    pools = []
    monkeypatch.setattr(qr, "_run_parallel_pool",
                        lambda pool, *_a, **_k: pools.append(pool))
    assert qr._drain(qcon, tmp_path / "meta.json", jobs=8,
                     skip_parallel_safe=True) == 0
    assert pools == []
    assert sequential_kind == [{"n": 1}]
    assert _rows(qcon, "kind, state") == [
        ("seqfake", "done"), ("walkforward", "pending"),
        ("sweep", "pending"), ("capital_sensitivity", "pending")]
    assert "leaving 3 parallel-safe research job(s)" in capsys.readouterr().out


def test_kinds_filter_keeps_other_research_out_of_the_walkforward_drain(
    qcon, monkeypatch, tmp_path
):
    qr.cmd_enqueue(qcon, "walkforward", '{"config_id":"a"}', 170, None)
    qr.cmd_enqueue(qcon, "backtest", '{"config_id":"a"}', 140, None)
    qr.cmd_enqueue(qcon, "sweep", '{"grid":"x"}', 900, None)
    pools = []

    def record(pool, db_path, meta_path, con, *, width, drain_deadline):
        pools.append([row[1] for row in pool])
        return {}, con, None

    monkeypatch.setattr(qr, "_run_parallel_pool", record)
    monkeypatch.setattr(qr.rsc, "load_5min", lambda: 0.0)
    monkeypatch.setattr(qr.rsc, "free_ram_gb", lambda: 100.0)
    assert qr._drain(qcon, tmp_path / "meta.json", jobs=8,
                     kinds={"walkforward"}) == 0
    assert pools == [["walkforward"]]


def test_main_rejects_unknown_kinds_and_flags_without_run(monkeypatch):
    for argv in (["--run", "--kinds", "walkforward,nope"],
                 ["--status", "--skip-parallel-safe"],
                 ["--status", "--report-partial"]):
        monkeypatch.setattr("sys.argv", ["queue_runner.py", *argv])
        with pytest.raises(SystemExit) as exc:
            qr.main()
        assert exc.value.code == 2


def test_rolling_pool_resource_guard_waits_for_its_own_load_to_clear(
    tmp_path, monkeypatch
):
    """2026-10-19: the guard tripped on the pool's own load and latched,
    leaving 10 jobs deferred while the pool sat idle for hours."""
    clock, starts = _fake_pool_processes(monkeypatch, {1: 2.0, 2: 1.0, 3: 1.0})
    # load is high while job 1 runs and for a second after it exits
    monkeypatch.setattr(qr.rsc, "load_5min",
                        lambda: 30.0 if 0.5 <= clock.now < 3.0 else 0.0)
    dbp = tmp_path / "q.duckdb"
    con = db.connect(dbp)
    qr.ensure_schema(con)
    for jid in (1, 2, 3):
        qr.cmd_enqueue(con, "walkforward", f'{{"config_id":"b{jid}"}}', 170, 10)
    pool = con.execute(
        "SELECT id, kind, params, mem_mb, timeout_s, priority FROM jobs ORDER BY id"
    ).fetchall()
    results, con, stopped = qr._run_parallel_pool(
        pool, str(dbp), tmp_path / "meta.json", con, width=2,
        drain_deadline=1000.0, _clock=clock.monotonic, _sleep=clock.sleep,
    )
    assert stopped is None
    assert results == {1: 0, 2: 0, 3: 0}
    assert [jid for jid, _ in starts] == [1, 2, 3]
    assert starts[2][1] >= 3.0
    con.close()


def test_rolling_pool_defers_after_idle_settle_not_at_first_trip(
    tmp_path, monkeypatch
):
    clock, starts = _fake_pool_processes(monkeypatch, {1: 1.0, 2: 1.0})
    monkeypatch.setattr(qr.rsc, "load_5min",
                        lambda: 30.0 if clock.now >= 0.5 else 0.0)
    monkeypatch.setattr(qr, "RESOURCE_SETTLE_S", 5.0)
    dbp = tmp_path / "q.duckdb"
    con = db.connect(dbp)
    qr.ensure_schema(con)
    for jid in (1, 2):
        qr.cmd_enqueue(con, "walkforward", f'{{"config_id":"b{jid}"}}', 170, 10)
    pool = con.execute(
        "SELECT id, kind, params, mem_mb, timeout_s, priority FROM jobs ORDER BY id"
    ).fetchall()
    results, con, stopped = qr._run_parallel_pool(
        pool, str(dbp), tmp_path / "meta.json", con, width=1,
        drain_deadline=1000.0, _clock=clock.monotonic, _sleep=clock.sleep,
    )
    assert stopped == "resources"
    assert results == {1: 0}
    assert 6.0 <= clock.now < 7.0  # job 1 ends at 1.0, then a 5 s idle settle
    assert _rows(con, "id, state") == [(1, "done"), (2, "pending")]
    con.close()


def test_rolling_pool_sleeps_between_polls_after_the_last_launch(
    tmp_path, monkeypatch
):
    """With a launch stagger, a pool whose free slots cannot be used must still
    sleep a full poll; it used to spin without sleeping until workers exited."""
    clock, _starts = _fake_pool_processes(monkeypatch, {1: 50.0})
    monkeypatch.setattr(qr, "BATCH_STAGGER_S", 4.0)
    calls = {"n": 0}

    def counted_clock():
        calls["n"] += 1
        if calls["n"] > 10_000:
            raise AssertionError("pool loop spun without sleeping")
        return clock.monotonic()

    dbp = tmp_path / "q.duckdb"
    con = db.connect(dbp)
    qr.ensure_schema(con)
    qr.cmd_enqueue(con, "walkforward", '{"config_id":"b1"}', 170, 10)
    pool = con.execute(
        "SELECT id, kind, params, mem_mb, timeout_s, priority FROM jobs"
    ).fetchall()
    results, con, stopped = qr._run_parallel_pool(
        pool, str(dbp), tmp_path / "meta.json", con, width=2,
        drain_deadline=1000.0, _clock=counted_clock, _sleep=clock.sleep,
    )
    assert stopped is None and results == {1: 0}
    con.close()


def test_drain_reports_partial_when_selected_jobs_are_left_undone(
    qcon, sequential_kind, monkeypatch, tmp_path, capsys
):
    """2026-10-19: 4 done, 4 timed out, 10 deferred, and the driver said 'ok'."""
    qr.cmd_enqueue(qcon, "walkforward", '{"config_id":"a"}', 170, None)
    qr.cmd_enqueue(qcon, "walkforward", '{"config_id":"b"}', 170, None)
    qr.cmd_enqueue(qcon, "walkforward", '{"config_id":"c"}', 170, None)

    def pool_run(pool, db_path, meta_path, con, *, width, drain_deadline):
        qr._set_state(con, 1, "done", progress="complete")
        qr._set_state(con, 2, "failed", progress="timeout", last_error="timeout")
        return {1: 0, 2: "timeout"}, con, "resources"

    monkeypatch.setattr(qr, "_run_parallel_pool", pool_run)
    assert qr._drain(qcon, tmp_path / "meta.json", jobs=8,
                     report_partial=True) == 0
    out = capsys.readouterr().out
    assert ("\nPARTIAL: queue drain left selected work undone (1 done, 1 timed out, "
            "0 failed, 1 left pending of 3 selected)\n") in out


def test_drain_reports_partial_when_global_guard_starts_nothing(
    qcon, sequential_kind, monkeypatch, tmp_path, capsys
):
    """2026-10-18 20:35: load 34.3 > 28, exit 0 after 0.65 s, status 'ok'."""
    qr.cmd_enqueue(qcon, "walkforward", '{"config_id":"a"}', 170, None)
    monkeypatch.setattr(qr.rsc, "load_5min", lambda: 34.3)
    assert qr._drain(qcon, tmp_path / "meta.json", jobs=8, report_partial=True) == 0
    assert "PARTIAL: queue drain left selected work undone" in capsys.readouterr().out


def test_drain_complete_or_unflagged_prints_no_partial_marker(
    qcon, sequential_kind, tmp_path, capsys
):
    qr.cmd_enqueue(qcon, "seqfake", "{}", 100, None)
    assert qr._drain(qcon, tmp_path / "meta.json", report_partial=True) == 0
    out = capsys.readouterr().out
    assert "drain outcome: 1 done" in out and "PARTIAL:" not in out
    qr.cmd_enqueue(qcon, "seqfake", '{"bad": 1}', 100, None, 0)
    qr.JOB_TYPES["seqfake"]["loader"] = lambda: (lambda *_a, **_k: 1 / 0)
    assert qr._drain(qcon, tmp_path / "meta.json") == 0
    assert "PARTIAL:" not in capsys.readouterr().out


def test_report_partial_drain_declined_by_drain_lock_is_partial(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["queue_runner.py", "--run", "--report-partial"])
    monkeypatch.setattr(qr, "acquire_drain_lock", lambda: False)
    assert qr.main() == 0
    assert "PARTIAL: queue drain did not start" in capsys.readouterr().out


def test_walkforward_has_an_explicit_ceiling_above_the_4h_default():
    assert qr.default_timeout_s("walkforward") == 7 * 3600


def test_supersede_stale_pending_drops_last_weeks_leftovers_only(qcon):
    qr.cmd_enqueue(qcon, "walkforward", '{"config_id":"old"}', 170, None)
    qr.cmd_enqueue(qcon, "walkforward", '{"config_id":"done"}', 170, None)
    qr.cmd_enqueue(qcon, "walkforward", '{"config_id":"fresh"}', 170, None)
    qr.cmd_enqueue(qcon, "sweep", '{"grid":"old"}', 900, None)
    qcon.execute("UPDATE jobs SET created_at = created_at - INTERVAL 7 DAY "
                 "WHERE id IN (1, 2, 4)")
    qcon.execute("UPDATE jobs SET state = 'done' WHERE id = 2")
    assert qr.supersede_stale_pending(qcon, "walkforward", 24 * 3600, "newer grid",
                                      dry_run=True) == [1]
    assert _rows(qcon, "id, state")[0] == (1, "pending")
    assert qr.supersede_stale_pending(qcon, "walkforward", 24 * 3600,
                                      "newer grid") == [1]
    assert _rows(qcon, "id, state") == [
        (1, "superseded"), (2, "done"), (3, "pending"), (4, "pending")]


def test_walkforward_grid_enqueue_supersedes_previous_week(qcon, monkeypatch):
    from farm.walkforward import grid

    qr.cmd_enqueue(qcon, "walkforward", '{"config_id": "gone"}', 170, None)
    qr.cmd_enqueue(qcon, "walkforward", '{"config_id": "spy"}', 170, None)
    qcon.execute("UPDATE jobs SET created_at = created_at - INTERVAL 7 DAY")
    monkeypatch.setattr(grid, "plan", lambda _con, _overrides=None: [
        ("spy", 170, '{"config_id": "spy"}')])
    assert grid.enqueue(qcon) == 0
    assert _rows(qcon, "id, state, params") == [
        (1, "superseded", '{"config_id": "gone"}'),
        (2, "superseded", '{"config_id": "spy"}'),
        (3, "pending", '{"config_id": "spy"}')]


def _publish_fake_snapshot(live_path, *, as_of):
    import json as _json
    import os as _os

    directory = live_path.parent / "snapshots"
    directory.mkdir()
    name = "market-20261018T060000000000Z.duckdb"
    snap = directory / name
    c = duckdb.connect(str(snap))
    c.execute("CREATE TABLE marker AS SELECT 'snapshot' AS source")
    c.close()
    (directory / name).with_suffix(".json").write_text(_json.dumps({
        "schema_version": 1, "snapshot": name, "as_of": as_of,
        "sha256": "0" * 64, "row_counts": {"marker": 1}}))
    _os.symlink(name, directory / "market-latest.duckdb")
    return snap


@pytest.fixture
def research_kind(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(qr.rsc, "apply_niceness", lambda: None)
    monkeypatch.setitem(qr.JOB_TYPES, "researchfake", {
        "loader": lambda: (lambda params, con, meta_path=None: seen.append(
            con.execute("SELECT source FROM marker").fetchone()[0])),
        "archive": False, "mem_mb": 10, "parallel_safe": True})
    live = tmp_path / "store" / "market.duckdb"
    live.parent.mkdir()
    con = db.connect(live)
    qr.ensure_schema(con)
    con.execute("CREATE TABLE marker AS SELECT 'live' AS source")
    qr.cmd_enqueue(con, "researchfake", "{}", 170, None)
    con.close()
    return live, seen


def test_parallel_child_reads_the_published_snapshot(research_kind, tmp_path):
    """Live read-only handles blocked the 13:05 pre-open and weekend writers."""
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    live, seen = research_kind
    _publish_fake_snapshot(live, as_of=_dt.now(_tz.utc).isoformat())
    assert qr.cmd_run_one(1, str(live), tmp_path / "meta.json") == 0
    assert seen == ["snapshot"]


def test_parallel_child_falls_back_to_live_without_a_fresh_snapshot(
    research_kind, tmp_path, capsys
):
    live, seen = research_kind
    assert qr.cmd_run_one(1, str(live), tmp_path / "meta.json") == 0
    _publish_fake_snapshot(live, as_of="2026-01-01T00:00:00+00:00")
    assert qr.cmd_run_one(1, str(live), tmp_path / "meta.json") == 0
    assert seen == ["live", "live"]
    out = capsys.readouterr().out
    assert "no valid published snapshot" in out and "h old" in out
