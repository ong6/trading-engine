"""Failure visibility, bounded retries, session settings and generation lifetimes."""

import asyncio
import gc
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event, Lock
from types import SimpleNamespace

import duckdb
import pytest

from server import db, main
from tests.test_api_latency import _get
from tests.test_ops_digest import _collect, _fetch
from tools import ops_digest

NOW = datetime(2026, 11, 20, 13, tzinfo=timezone.utc)


@pytest.fixture
def generations(monkeypatch, tmp_path):
    class Clock(datetime):
        value = NOW

        @classmethod
        def now(cls, _tz=None):
            return cls.value

    reader = db._GenerationReader()
    monkeypatch.setattr(db, "_generation_reader", reader)
    monkeypatch.setattr(db, "datetime", Clock)
    monkeypatch.setattr(db, "DEFAULT_DB", tmp_path / "primary.duckdb")
    monkeypatch.setenv("TRADING_ENGINE_DUCKDB_THREADS", "1")
    monkeypatch.setenv("TRADING_ENGINE_DUCKDB_MEMORY", "1GB")
    target = {"id": "generation1", "fail": False}
    pins, attempts = [], []
    roots = []
    directory = tmp_path / "snapshots"
    directory.mkdir()
    for number in (1, 2, 3):
        (directory / f"generation{number}.duckdb").write_bytes(b"fixture identity")
        (directory / f"generation{number}.json").write_text("{}")
    monkeypatch.setattr(reader, "_published_id", lambda: target["id"])
    monkeypatch.setattr(db, "verified_snapshot_file", lambda _path: True)
    monkeypatch.setattr(db, "source_storage_identity", lambda _path: {"source": 1})

    def pin(_path):
        attempts.append((target["id"], Clock.value))
        if target["fail"]:
            raise db.GenerationError("fixture generation hash mismatch")
        result = SimpleNamespace(
            info=SimpleNamespace(
                path=directory / (target["id"] + ".duckdb"),
                generation_id=target["id"], as_of=NOW,
                source_storage_identity={"source": 1}, sha256="a" * 64,
            ),
            closed=False,
        )
        result.close = lambda: setattr(result, "closed", True)
        pins.append(result)
        return result

    def connect(path, **_kwargs):
        root = duckdb.connect(":memory:", config={"threads": 1})
        root.execute("SET TimeZone='UTC'")
        root.execute("SET memory_limit='1GB'")
        number = int(path.stem[-1])
        root.execute("CREATE TABLE payload AS SELECT ? AS version, i FROM range(16) t(i)", [number])
        roots.append(root)
        return root

    monkeypatch.setattr(db, "pin_latest_generation", pin)
    monkeypatch.setattr(db.engine_db, "connect", connect)
    assert main._warm_generation()
    state = SimpleNamespace(reader=reader, clock=Clock, target=target, pins=pins,
                            attempts=attempts, roots=roots, directory=directory)
    yield state
    reader.close()


def _generation_state():
    with db.response_data_source() as state, db.read_con():
        return state["generation"]


def test_failed_verification_is_visible_and_warns(generations, caplog):
    g = generations
    g.target.update(id="generation2", fail=True)
    with caplog.at_level(logging.WARNING):
        assert main._warm_generation() is False
    assert any(record.levelno >= logging.WARNING for record in caplog.records)
    state = _generation_state()
    assert state["generation_id"] == "generation1"
    assert state["status"] == "verification_failed"
    assert state["last_refresh_error"] == "GenerationError"
    assert state["refresh_error_first_at"] == NOW.isoformat()
    assert state["refresh_error_last_at"] == NOW.isoformat()
    assert state["pending_since"] == NOW.isoformat()
    g.clock.value += timedelta(minutes=1)
    assert main._warm_generation() is False
    state = _generation_state()
    assert state["refresh_error_first_at"] == NOW.isoformat()
    assert state["refresh_error_last_at"] == g.clock.value.isoformat()
    assert state["pending_seconds"] == 60
    response, body = asyncio.run(_get("/ready"))
    assert response["status"] == 503 and body["ok"] is False
    assert body["reason"] == "verification_failed"
    # Data availability and verification health are separate: the old data is still served.
    with db.read_con() as con:
        assert con.execute("SELECT DISTINCT version FROM payload").fetchone() == (1,)


def test_bad_publication_is_not_reverified_every_poll(generations):
    g = generations
    g.target.update(id="generation2", fail=True)
    assert main._warm_generation() is False
    for _ in range(59):
        g.clock.value += timedelta(seconds=1)
        assert main._warm_generation() is False
    assert len(g.attempts) == 2  # first good generation and one failed candidate
    g.clock.value += timedelta(seconds=1)
    assert main._warm_generation() is False
    assert len(g.attempts) == 3
    retry = datetime.fromisoformat(db.readiness()["refresh_retry_at"])
    assert retry - g.clock.value == timedelta(seconds=120)
    for seconds in (120, 240, 480, 600):
        g.clock.value += timedelta(seconds=seconds)
        assert main._warm_generation() is False
    retry = datetime.fromisoformat(db.readiness()["refresh_retry_at"])
    assert retry - g.clock.value == timedelta(minutes=10)


def test_backoff_also_skips_failed_selected_generation_verification(generations, monkeypatch):
    checks = []

    def invalid(path):
        checks.append(path)
        return None

    monkeypatch.setattr(db, "verified_snapshot_file", invalid)
    generations.target["fail"] = True
    assert main._warm_generation() is False
    for _ in range(5):
        generations.clock.value += timedelta(seconds=1)
        assert main._warm_generation() is False
    assert len(checks) == 1


def test_changed_publication_identity_retries_without_waiting(generations):
    g = generations
    g.target.update(id="generation2", fail=True)
    assert main._warm_generation() is False
    g.target["fail"] = False
    (g.directory / "generation2.json").write_text('{"repaired":true}')
    assert main._warm_generation()
    assert db.readiness()["ok"] is True
    assert _generation_state()["status"] == "current"
    g.target.update(id="generation3", fail=True)
    assert main._warm_generation() is False
    assert g.attempts[-1][0] == "generation3"


def test_recovered_selected_generation_clears_active_refresh_failure(generations, monkeypatch):
    monkeypatch.setattr(db, "verified_snapshot_file", lambda _path: None)
    generations.target["fail"] = True
    assert main._warm_generation() is False
    assert db.readiness()["status"] == "verification_failed"
    monkeypatch.setattr(db, "verified_snapshot_file", lambda _path: True)
    generations.target["fail"] = False
    (generations.directory / "generation1.json").write_text('{"repaired":true}')
    assert main._warm_generation()
    assert db.readiness()["ok"] is True
    assert db.readiness()["status"] == "current"


def test_pending_timeout_and_worker_heartbeat_degrade_readiness(generations):
    g = generations
    g.target["id"] = "generation2"
    state = _generation_state()  # the request observes publication without verifying it
    assert state["status"] == "pending"
    assert db.readiness()["ok"] is True
    g.clock.value += timedelta(minutes=15, seconds=1)
    g.reader.heartbeat()
    ready = db.readiness()
    assert ready["ok"] is False and ready["reason"] == "pending_timeout"
    assert ready["status"] == "pending"
    assert ready["pending_seconds"] == 901


def test_dead_worker_does_not_leave_readiness_green(generations):
    g = generations
    g.clock.value += timedelta(minutes=5, seconds=1)
    state = db.readiness()
    assert state["ok"] is False and state["reason"] == "worker_stalled"
    assert state["heartbeat_at"] == NOW.isoformat()
    assert state["heartbeat_age_seconds"] == 301
    assert _generation_state()["status"] == "stale"


def test_existing_evidence_stale_budget_degrades_readiness(generations, monkeypatch):
    g = generations
    monkeypatch.setattr(db, "source_storage_identity", lambda _path: {"source": 2})
    g.clock.value += timedelta(minutes=210, seconds=1)
    assert main._warm_generation()
    state = db.readiness()
    assert state["ok"] is False and state["reason"] == "generation_stale"
    assert state["status"] == "stale"


def test_unchanged_primary_keeps_the_existing_quiet_market_exception(generations):
    generations.clock.value += timedelta(days=2)
    assert main._warm_generation()
    assert db.readiness()["ok"] is True
    assert _generation_state()["status"] == "current"


def test_request_cursor_reapplies_utc_and_resource_settings(generations, monkeypatch):
    import time

    monkeypatch.setenv("TZ", "Asia/Singapore")
    time.tzset()
    try:
        with db.read_con() as con:
            assert con.execute("SELECT current_setting('TimeZone')").fetchone() == ("UTC",)
            assert con.execute("SELECT current_setting('threads')").fetchone() == (1,)
            expected = generations.roots[0].execute("SELECT current_setting('memory_limit')").fetchone()
            assert con.execute("SELECT current_setting('memory_limit')").fetchone() == expected
            stamp = con.execute("SELECT TIMESTAMP '2026-11-20 13:00:00'::TIMESTAMPTZ").fetchone()[0]
            assert stamp.utcoffset() == timedelta(0) and stamp.hour == 13
    finally:
        monkeypatch.undo()
        time.tzset()


def test_leaked_request_releases_retired_generation_pin(generations):
    g = generations
    leaked = db.read_con()
    old_pin = g.pins[0]
    g.target["id"] = "generation2"
    assert main._warm_generation()
    assert not old_pin.closed
    del leaked
    gc.collect()
    assert old_pin.closed


def test_closed_request_finalizer_does_not_release_twice(generations):
    g = generations
    releases = []
    original = g.pins[0].close

    def close():
        releases.append(True)
        original()

    g.pins[0].close = close
    request = db.read_con()
    request.close()
    request.close()
    g.target["id"] = "generation2"
    assert main._warm_generation()
    del request
    gc.collect()
    assert releases == [True]


def test_sql_errors_do_not_count_as_store_io_failures(generations):
    with db.read_con() as con, pytest.raises(duckdb.BinderException):
        con.execute("SELECT absent_column FROM payload")
    assert db.readiness()["recent_read_errors"] == 0
    assert db.readiness()["ok"] is True


def test_late_io_errors_on_a_retired_reader_do_not_degrade_new_generation(generations):
    class FailingQuery:
        def execute(self, _sql):
            raise duckdb.IOException("old generation read failed")

    request = db.read_con()
    request._connection = FailingQuery()  # the finalizer still owns the real cursor
    generations.target["id"] = "generation2"
    assert main._warm_generation()
    try:
        for _ in range(3):
            with pytest.raises(duckdb.IOException):
                request.execute("SELECT 1")
        state = db.readiness()
        assert state["generation_id"] == "generation2" and state["ok"] is True
        assert state["recent_read_errors"] == 0
    finally:
        request.close()


@pytest.mark.parametrize("operation", ["execute", "fetchone"])
def test_real_query_io_errors_degrade_only_the_served_generation(generations, monkeypatch, operation):
    g = generations

    class FaultyCursor:
        def execute(self, statement):
            if statement.startswith("SET ") or operation == "fetchone":
                return self
            raise duckdb.IOException("fixture read I/O failure")

        def fetchone(self):
            raise OSError("fixture deferred read I/O failure")

        def close(self):
            pass

    original_root = g.reader._current.connection
    g.reader._current.connection = SimpleNamespace(cursor=FaultyCursor, close=lambda: None)
    try:
        for index in range(3):
            with db.read_con() as con, pytest.raises((duckdb.IOException, OSError)):
                con.execute("SELECT 1").fetchone()
            ready = db.readiness()
            assert ready["recent_read_errors"] == index + 1
            assert ready["ok"] is (index < 2)
        assert ready["reason"] == "read_errors"
        g.clock.value += timedelta(minutes=5, seconds=1)
        g.reader.heartbeat()
        assert db.readiness()["recent_read_errors"] == 0
        assert db.readiness()["ok"] is True
    finally:
        g.reader._current.connection = original_root


def test_continuous_readers_see_one_complete_utc_generation(generations, monkeypatch):
    import time

    monkeypatch.setenv("TZ", "Asia/Singapore")
    time.tzset()
    barrier, stop = Barrier(5), Event()
    first_seen, second_seen = Event(), Event()
    observed, lock = set(), Lock()

    def read_continuously():
        barrier.wait(timeout=5)
        while not stop.is_set():
            with db.read_con() as con:
                identity = con.generation_info.generation_id
                rows = con.execute("SELECT * FROM payload ORDER BY i").fetchall()
                zone = con.execute("SELECT current_setting('TimeZone')").fetchone()[0]
                assert zone == "UTC"
                assert rows == [(int(identity[-1]), i) for i in range(16)]
                with lock:
                    observed.add(identity)
                (first_seen if identity == "generation1" else second_seen).set()

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            readers = [pool.submit(read_continuously) for _ in range(4)]
            try:
                barrier.wait(timeout=5)
                assert first_seen.wait(3)
                generations.target["id"] = "generation2"
                assert main._warm_generation()
                assert second_seen.wait(3)
            finally:
                stop.set()
                for reader in readers:
                    reader.result(timeout=5)
        assert observed == {"generation1", "generation2"}
    finally:
        monkeypatch.undo()
        time.tzset()


@pytest.mark.parametrize("status,reason,expected,severity", [
    ("pending", "pending_timeout", "WARN", 1),
    ("verification_failed", "verification_failed", "FAIL", 3),
    ("stale", "generation_stale", "FAIL", 3),
    ("stale", "worker_stalled", "FAIL", 3),
    ("stale", "read_errors", "FAIL", 3),
])
def test_digest_classifies_readiness_status_not_just_http(tmp_path, monkeypatch, status, reason,
                                                        expected, severity):
    def fetch(url, timeout):
        if url.endswith("/ready"):
            # Semantic failure must be noticed even if an intermediary returns HTTP 200.
            return 200, 1, json.dumps({"ok": False, "status": status, "reason": reason}).encode()
        return _fetch(url, timeout)

    monkeypatch.setattr(ops_digest, "latest_snapshot", lambda *_a, **_k: None)
    monkeypatch.setattr("tests.test_ops_digest._fetch", fetch)
    [hour] = _collect(tmp_path, {})
    assert hour["status"] == expected
    probes, _sections = ops_digest.probe(fetch)
    findings = ops_digest.findings({"signals": {}, "runs": [], "failed_runs": 0, "probes": probes})
    ready = next(item for item in findings if item["source"] == "probe:/ready")
    assert ready["severity"] == severity
