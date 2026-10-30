"""Absolute lock deadlines use only temporary artifacts and separate holders."""
from __future__ import annotations

import subprocess
import sys
import time
from contextlib import contextmanager

import duckdb
import pytest

from engine.lib import db, resources, settings


@contextmanager
def held_lock(path, kind, *, release_after=None):
    script = """
import fcntl, sys, time
import duckdb
path, kind = sys.argv[1:]
if kind == 'advisory':
    handle = open(path, 'a')
    fcntl.flock(handle, fcntl.LOCK_EX)
else:
    handle = duckdb.connect(path)
print('locked', flush=True)
delay = sys.stdin.readline().strip()
if delay:
    time.sleep(float(delay))
else:
    sys.stdin.read()
handle.close()
"""
    holder = subprocess.Popen(
        [sys.executable, "-c", script, str(path), kind],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        holder.stdin.write("\n" if release_after is None else f"{release_after}\n")
        holder.stdin.flush()
        yield holder
    finally:
        if holder.poll() is None:
            holder.terminate()
        holder.communicate(timeout=5)


@pytest.mark.parametrize("kind", ["advisory", "writer"])
def test_held_lock_cannot_wait_past_deadline(tmp_path, monkeypatch, kind):
    path = tmp_path / ("test.lock" if kind == "advisory" else "test.duckdb")
    monkeypatch.setenv(settings.LOCK_WAIT_ENV, "3600")
    with held_lock(path, kind) as holder:
        started = time.monotonic()
        deadline = started + 0.2
        if kind == "advisory":
            with pytest.raises(TimeoutError, match="deadline"):
                with resources.advisory_file_lock(path, deadline=deadline):
                    pytest.fail("entered held lock")
        else:
            with pytest.raises(duckdb.IOException) as caught:
                db.connect(path, wait_s=60, deadline=deadline)
            assert db.is_lock_error(caught.value)
        elapsed = time.monotonic() - started
        assert 0.18 <= elapsed < 0.7
        assert holder.poll() is None


@pytest.mark.parametrize("kind", ["advisory", "writer"])
def test_lock_released_just_before_deadline_succeeds(tmp_path, monkeypatch, kind):
    path = tmp_path / ("test.lock" if kind == "advisory" else "test.duckdb")
    monkeypatch.setattr(db, "_LOCK_RETRY_S", 0.02)
    with held_lock(path, kind, release_after=0.65):
        started = time.monotonic()
        deadline = started + 0.8
        if kind == "advisory":
            with resources.advisory_file_lock(path, deadline=deadline):
                assert time.monotonic() < deadline
        else:
            con = db.connect(path, deadline=deadline)
            assert time.monotonic() < deadline
            assert con.execute("SELECT 1").fetchone() == (1,)
            con.close()
        assert time.monotonic() - started >= 0.6


@pytest.mark.parametrize("wait_s,env_s,expected_attempts", [
    (None, 15, 3), (0, 60, 1), (6, 15, 3), (20, 15, 4),
])
def test_connections_without_deadline_keep_existing_waits(
    tmp_path, monkeypatch, wait_s, env_s, expected_attempts,
):
    attempts, sleeps = [], []
    error = duckdb.IOException("conflicting lock is held")

    def locked(*args, **kwargs):
        attempts.append((args, kwargs))
        raise error

    monkeypatch.setenv(settings.LOCK_WAIT_ENV, str(env_s))
    monkeypatch.setattr(db.duckdb, "connect", locked)
    monkeypatch.setattr(db.time, "sleep", sleeps.append)
    with pytest.raises(duckdb.IOException) as caught:
        db.connect(tmp_path / "test.duckdb", wait_s=wait_s)
    assert caught.value is error
    assert len(attempts) == expected_attempts
    assert sleeps == [db._LOCK_RETRY_S] * (expected_attempts - 1)


def test_deadline_caps_retries_including_connection_attempt_time(tmp_path, monkeypatch):
    clock, sleeps, attempts = [100.0], [], []
    error = duckdb.IOException("conflicting lock is held")

    def locked(*args, **kwargs):
        attempts.append(clock[0])
        clock[0] += 0.1
        raise error

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setenv(settings.LOCK_WAIT_ENV, "3600")
    monkeypatch.setattr(db.duckdb, "connect", locked)
    monkeypatch.setattr(db.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(db.time, "sleep", sleep)
    with pytest.raises(duckdb.IOException) as caught:
        db.connect(tmp_path / "test.duckdb", wait_s=60, deadline=100.25)
    assert caught.value is error
    assert sleeps == pytest.approx([0.15])
    assert len(attempts) == 2  # final immediate probe at expiry, no further sleep


def test_expired_deadline_allows_only_an_immediate_store_probe(tmp_path, monkeypatch):
    path = tmp_path / "test.duckdb"
    con = db.connect(path, deadline=time.monotonic() - 1)
    con.close()
    with held_lock(path, "writer"):
        with pytest.raises(duckdb.IOException):
            db.connect(path, deadline=time.monotonic() - 1)


def test_advisory_deadline_releases_lock_after_body_failure(tmp_path):
    path = tmp_path / "test.lock"
    with pytest.raises(RuntimeError, match="body failed"):
        with resources.advisory_file_lock(path, deadline=time.monotonic() + 1):
            raise RuntimeError("body failed")
    with resources.advisory_file_lock(path, deadline=time.monotonic() + 1):
        pass
