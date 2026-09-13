"""engine/queue_runner.py — nightly enqueue policy, per-job timeout, supersede.

Every DB is in-memory (or a tmp_path file where a subprocess must reopen it).
store/ is never opened.
"""
from __future__ import annotations

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
        ("intraday", 100), ("signals", 105), ("earnings", 110), ("fundamentals", 120)]


@pytest.mark.parametrize("wd", [1, 2, 3, 4, 6, 7])
def test_nightly_plan_weekday_override_non_friday(wd):
    assert [k for k, _, _ in qr.nightly_plan(weekday=wd)] == ["intraday", "signals", "earnings"]


def test_nightly_plan_weekday_override_beats_date():
    plan = qr.nightly_plan(date(2026, 8, 31), weekday=5)   # Monday date, forced Friday
    assert plan[-1][0] == "fundamentals"


def test_nightly_plan_rejects_bad_weekday():
    with pytest.raises(ValueError):
        qr.nightly_plan(weekday=0)


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
    assert [r[0] for r in _rows(qcon, "kind")] == ["intraday", "signals", "earnings"]


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
    db.init_schema(c)
    db.init_queue_schema(c)
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
    return "sleepy"


def test_parallel_child_is_killed_at_timeout(tmp_path, sleepy_kind, monkeypatch):
    dbp = tmp_path / "q.duckdb"
    con = db.connect(dbp)
    qr.ensure_schema(con)
    qr.cmd_enqueue(con, sleepy_kind, "{}", 100, None)           # kind default 1 s
    qr.cmd_enqueue(con, sleepy_kind, '{"n": 2}', 100, None, 2)  # explicit 2 s
    batch = [(1, sleepy_kind, None), (2, sleepy_kind, 2)]
    t0 = time.monotonic()
    results, con = qr._run_parallel_batch(batch, str(dbp), tmp_path / "meta.json", con)
    elapsed = time.monotonic() - t0
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
    results, con = qr._run_parallel_batch(
        [(1, sleepy_kind, 60)], str(dbp), tmp_path / "meta.json", con)
    assert results == {1: 0}
    assert con.execute("SELECT state FROM jobs WHERE id = 1").fetchone() == ("done",)
    con.close()


def test_wait_batch_records_nonzero_exit_as_rc():
    import subprocess
    pr = subprocess.Popen([sys.executable, "-c", "raise SystemExit(7)"])
    res = qr._wait_batch([(9, "k", pr, time.monotonic() + 60)], poll_s=0.05)
    assert res == {9: 7}


def test_drain_never_mixes_parallel_kinds_or_priority_tiers(qcon, monkeypatch, tmp_path):
    for kind, priority, params in (
        ("walkforward", 170, '{"config_id":"a"}'),
        ("walkforward", 170, '{"config_id":"b"}'),
        ("walkforward", 176, '{"config_id":"c"}'),
        ("sweep", 900, '{"grid":"x"}'),
        ("sweep", 900, '{"grid":"y"}'),
    ):
        qr.cmd_enqueue(qcon, kind, params, priority, None)
    batches = []

    def record(batch, db_path, meta_path, con):
        batches.append([(jid, kind) for jid, kind, _timeout in batch])
        return {}, con

    monkeypatch.setattr(qr, "_run_parallel_batch", record)
    monkeypatch.setattr(qr.rsc, "load_5min", lambda: 0.0)
    monkeypatch.setattr(qr.rsc, "free_ram_gb", lambda: 100.0)
    assert qr._drain(qcon, tmp_path / "meta.json", jobs=8) == 0
    assert batches == [
        [(1, "walkforward"), (2, "walkforward")],
        [(3, "walkforward")],
        [(4, "sweep"), (5, "sweep")],
    ]


def test_targeted_drain_runs_only_exact_authorized_params(qcon, monkeypatch, tmp_path):
    qr.cmd_enqueue(qcon, "sweep", '{"grid":"old"}', 900, None)
    qr.cmd_enqueue(qcon, "sweep", '{"grid":"open"}', 900, None)
    qr.cmd_enqueue(qcon, "walkforward", '{"config_id":"book"}', 170, None)
    batches = []

    def record(batch, db_path, meta_path, con):
        batches.append([jid for jid, _kind, _timeout in batch])
        for jid, _kind, _timeout in batch:
            qr._set_state(con, jid, "done")
        return {}, con

    monkeypatch.setattr(qr, "_run_parallel_batch", record)
    monkeypatch.setattr(qr.rsc, "load_5min", lambda: 0.0)
    monkeypatch.setattr(qr.rsc, "free_ram_gb", lambda: 100.0)
    assert qr._drain(
        qcon,
        tmp_path / "meta.json",
        jobs=8,
        run_kind="sweep",
        run_params=['{"grid": "open"}'],
    ) == 0
    assert batches == [[2]]
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
