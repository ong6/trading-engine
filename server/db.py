"""Per-request DuckDB connection helpers for the local paper-trading API.

`read_con()` opens an independent cursor on the last verified readable generation. Only the
background worker verifies publications; requests never wait for it. `pending_verification`
identifies a publication not yet selected. `pending_publication` says whether the primary has changed since the
generation was captured; a generation that is both older than its dataset's budget and
possibly behind the primary is served and flagged stale.
An absent or unreadable verified generation refuses (503). `write_con()` alone opens the primary, waiting a
bounded time for a short lock (a publication's capture copy) instead of failing at once.

Thin wrappers only (refactor step 2, 2026-09-03): server/main.py and the tests
depend on these names.
"""
from __future__ import annotations

import os
import time
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Iterator
from weakref import finalize

import duckdb

from engine.lib import db as engine_db
from engine.lib import store_limits
from engine.lib.db import DBBusyError
from engine.lib.settings import DEFAULT_DB
from engine.lib.snapshots import (
    GenerationError,
    SnapshotPin,
    pin_latest_generation,
    source_storage_identity,
    verified_snapshot_file,
)

_DATA_SOURCE_STATE: ContextVar[dict | None] = ContextVar("api_data_source_state", default=None)
# Staleness budgets: a generation older than its dataset's budget is still served, but the
# response says it is stale. During US market hours a changed
# primary is republished at most once every three hours (publish-on-change),
# so evidence there lags its last write by at most 3 hours plus one publication (about 15
# minutes); 3.5 hours covers it. Responses still flag pending_publication.
GENERAL_GENERATION_MAX_AGE = timedelta(hours=24)
DATASET_GENERATION_MAX_AGE = {
    "board": GENERAL_GENERATION_MAX_AGE,
    "evidence": timedelta(minutes=210),
}
_DATASET_CLASS: ContextVar[str] = ContextVar("api_dataset_class", default="board")
# A publication holds a read-only capture handle while it copies the primary: 50-130 s for
# the 12.7 GB store under write traffic in the rehearsal. API writes wait that out.
API_WRITE_WAIT_S = float(os.environ.get("TRADING_ENGINE_API_WRITE_WAIT_S", "180"))
_WRITE_RETRY_S = 0.25
# Publication normally verifies in 10–75 s on the retained multi-GiB fixture. Fifteen
# minutes covers a slow capture/verification; five minutes without a worker heartbeat
# already indicates a stalled worker. A quiet, unchanged primary keeps the existing
# evidence-budget exception; otherwise the 210-minute evidence budget applies.
VERIFICATION_PENDING_LIMIT = timedelta(minutes=15)
WORKER_HEARTBEAT_LIMIT = timedelta(minutes=5)
READ_ERROR_WINDOW = timedelta(minutes=5)
READ_ERROR_LIMIT = 3
VERIFICATION_RETRY_SECONDS = 60
VERIFICATION_RETRY_MAX_SECONDS = 600


def db_path() -> Path:
    """Resolved DB path — env `TRADING_ENGINE_DB` or the default store path."""
    return DEFAULT_DB


def _connect(read_only: bool) -> duckdb.DuckDBPyConnection:
    try:
        return engine_db.connect(db_path(), read_only=read_only, wait_s=0)
    except Exception as exc:  # duckdb.IOException et al.
        different_configuration = (
            "same database file with a different configuration" in str(exc).lower()
        )
        if engine_db.is_lock_error(exc) or different_configuration:
            raise DBBusyError(str(exc)) from exc
        raise


def _close_cursor(connection, generation, release) -> None:
    try:
        connection.close()
    finally:
        release(generation)


def _request_cursor(connection):
    """DuckDB duplicates reset session settings, including the host's default timezone."""
    cursor = connection.cursor()
    try:
        threads, memory = store_limits.duckdb_limits(True)
        cursor.execute("SET TimeZone='UTC'")
        cursor.execute(f"SET threads={int(threads)}")
        cursor.execute(f"SET memory_limit='{memory}'")
        return cursor
    except BaseException:
        cursor.close()
        raise


class _PinnedConnection:
    """DuckDB connection proxy that holds its generation pin until close."""

    def __init__(self, connection: duckdb.DuckDBPyConnection, generation, release, read_error):
        self._connection = connection
        self._generation = generation
        self._read_error = read_error
        self._finalizer = finalize(self, _close_cursor, connection, generation, release)

    def __getattr__(self, name: str):
        value = getattr(self._connection, name)
        if not callable(value):
            return value

        def call(*args, **kwargs):
            try:
                result = value(*args, **kwargs)
            except (duckdb.IOException, OSError):
                self._read_error(self._generation)
                raise
            # Keep fluent execute(...).fetch*() calls inside the observed cursor.
            return self if result is self._connection else result

        return call

    @property
    def generation_info(self):
        """The pinned generation's manifest record (``SnapshotInfo``)."""
        return self._generation.pin.info

    def close(self) -> None:
        self._finalizer()

    def __enter__(self):
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def generation_state(pin: SnapshotPin, *, dataset: str | None = None) -> dict:
    """Describe a pinned generation: age, staleness against its budget, pending writes."""
    budget = DATASET_GENERATION_MAX_AGE[dataset or _DATASET_CLASS.get()]
    age = datetime.now(timezone.utc) - pin.info.as_of
    try:
        pending = pin.info.source_storage_identity != source_storage_identity(db_path())
    except OSError:
        pending = None
    return {
        "generation_id": pin.info.generation_id,
        "as_of": pin.info.as_of.isoformat(),
        "age_seconds": max(0, int(age.total_seconds())),
        "budget_seconds": int(budget.total_seconds()),
        # Past its budget AND possibly behind the primary: a generation captured from the
        # primary's current bytes is current however old it is (a quiet weekend).
        "stale": age > budget and pending is not False,
        "pending_publication": pending,
    }


class DBNotReadyError(DBBusyError):
    """No fully verified readable generation is available to this request."""


class _VerifiedGeneration:
    def __init__(self, database: Path, pin: SnapshotPin, connection):
        self.database = database
        self.pin = pin
        self.connection = connection
        self.users = 1  # selector ownership, plus one for each request or worker lease
        self.readable = True
        self.pending_publication: bool | None = None
        self.read_errors: deque[datetime] = deque()

    def close(self):
        try:
            self.connection.close()
        finally:
            self.pin.close()


class _GenerationReader:
    """Atomically select verified connections without holding locks during I/O."""

    def __init__(self):
        self._lock = Lock()
        self._refresh_lock = Lock()
        self._current: _VerifiedGeneration | None = None
        self._pending_id: str | None = None
        self._observed_id: str | None = None
        self._pending_since: datetime | None = None
        self._heartbeat_at: datetime | None = None
        self._last_refresh_error: str | None = None
        self._error_first_at: datetime | None = None
        self._error_last_at: datetime | None = None
        self._error_id: str | None = None
        self._error_active = False
        self._failed_key: tuple | None = None
        self._failure_count = 0
        self._retry_at: datetime | None = None

    def _published_id(self) -> str | None:
        try:
            target = Path(os.readlink(db_path().parent / "snapshots" / "market-latest.duckdb"))
        except OSError:
            return None
        return target.stem if not target.is_absolute() and len(target.parts) == 1 else None

    def _set_publication(self, published: str | None, now: datetime) -> None:
        current = self._current
        served = current.pin.info.generation_id if current else None
        pending = published if published != served else None
        if pending != self._pending_id:
            self._pending_since = now if pending else None
        self._observed_id = published
        self._pending_id = pending

    def _observe_publication(self) -> None:
        published = self._published_id()
        with self._lock:
            self._set_publication(published, datetime.now(timezone.utc))

    def _publication_key(self) -> tuple:
        """Cheap retry identity; backoff also covers repaired cold parts or transient I/O."""
        identity = [self._published_id()]
        directory = db_path().parent / "snapshots"
        for suffix in (".duckdb", ".json"):
            try:
                node = (directory / f"{identity[0]}{suffix}").stat(follow_symlinks=False)
                identity.append((node.st_dev, node.st_ino, node.st_size,
                                 node.st_mtime_ns, node.st_ctime_ns, node.st_mode))
            except OSError:
                identity.append(None)
        return tuple(identity)

    def heartbeat(self) -> None:
        with self._lock:
            self._heartbeat_at = datetime.now(timezone.utc)

    def _refresh_failed(self, key: tuple, exc: Exception) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            if key != self._failed_key:
                self._error_first_at = now
                self._failure_count = 0
            self._failure_count += 1
            self._failed_key = key
            self._last_refresh_error = type(exc).__name__  # never publish local paths/details
            self._error_last_at = now
            self._error_id = key[0]
            self._error_active = True
            delay = min(VERIFICATION_RETRY_SECONDS * 2 ** min(self._failure_count - 1, 4),
                        VERIFICATION_RETRY_MAX_SECONDS)
            self._retry_at = now + timedelta(seconds=delay)

    def _clear_refresh_failure(self) -> None:
        """Caller holds the lock; retain error timestamps as history after recovery."""
        self._error_active = False
        self._failed_key = None
        self._failure_count = 0
        self._retry_at = None

    def _retain(self, *, require_readable: bool = True) -> _VerifiedGeneration:
        with self._lock:
            current = self._current
            if (current is None or current.database != db_path()
                    or (require_readable and not current.readable)):
                raise DBNotReadyError("database not ready: no verified readable generation")
            current.users += 1
            return current

    def _release(self, generation: _VerifiedGeneration) -> None:
        with self._lock:
            generation.users -= 1
            close = generation.users == 0
        if close:
            generation.close()

    def _mark_readable(self, generation, readable: bool) -> None:
        with self._lock:
            generation.readable = readable

    def _read_error(self, generation) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            generation.read_errors.append(now)
            self._recent_errors(generation, now)

    def _recent_errors(self, generation, now: datetime) -> int:
        while generation.read_errors and generation.read_errors[0] <= now - READ_ERROR_WINDOW:
            generation.read_errors.popleft()
        return len(generation.read_errors)

    def read(self):
        self._observe_publication()  # a symlink read only; no manifest, hash or store lock
        generation = self._retain()
        try:
            connection = _request_cursor(generation.connection)
        except Exception as exc:
            self._mark_readable(generation, False)
            self._release(generation)
            raise DBNotReadyError("database not ready: verified generation is unreadable") from exc
        result = _PinnedConnection(connection, generation, self._release, self._read_error)
        try:
            state = _DATA_SOURCE_STATE.get()
            if state is not None:
                served = generation_state(generation.pin)
                with self._lock:
                    served.update(self._status(generation, datetime.now(timezone.utc),
                                               served["pending_publication"]))
                state.update(source="snapshot", snapshot_as_of=served["as_of"],
                             generation_id=served["generation_id"], generation=served)
            return result
        except BaseException:
            result.close()
            raise

    def _status(self, generation, now: datetime, primary_pending: bool | None) -> dict:
        """Caller holds the selector lock; diagnostics use memory only."""
        served_id = generation.pin.info.generation_id if generation else None
        pending = self._observed_id if self._observed_id != served_id else None
        pending_seconds = max(0, int((now - self._pending_since).total_seconds())) if (
            pending and self._pending_since) else 0
        heartbeat_age = max(0, int((now - self._heartbeat_at).total_seconds())) if (
            self._heartbeat_at) else None
        errors = self._recent_errors(generation, now) if generation else 0
        status, reason = ("pending" if pending else "current"), None
        if self._error_active and self._error_id == self._observed_id:
            status, reason = "verification_failed", "verification_failed"
        elif not generation or not generation.readable:
            status, reason = ("stale" if generation else "not ready"), "not_ready"
        elif (now - generation.pin.info.as_of > DATASET_GENERATION_MAX_AGE["evidence"]
              and primary_pending is not False):
            status, reason = "stale", "generation_stale"
        elif heartbeat_age is None or heartbeat_age > WORKER_HEARTBEAT_LIMIT.total_seconds():
            status, reason = "stale", "worker_stalled"
        elif errors >= READ_ERROR_LIMIT:
            status, reason = "stale", "read_errors"
        elif pending_seconds > VERIFICATION_PENDING_LIMIT.total_seconds():
            reason = "pending_timeout"
        return {
            "status": status, "reason": reason,
            "pending_verification": pending is not None, "pending_generation_id": pending,
            "pending_since": self._pending_since.isoformat() if self._pending_since else None,
            "pending_seconds": pending_seconds,
            "pending_limit_seconds": int(VERIFICATION_PENDING_LIMIT.total_seconds()),
            "readiness_budget_seconds": int(DATASET_GENERATION_MAX_AGE["evidence"].total_seconds()),
            "last_refresh_error": self._last_refresh_error,
            "refresh_error_first_at": self._error_first_at.isoformat() if self._error_first_at else None,
            "refresh_error_last_at": self._error_last_at.isoformat() if self._error_last_at else None,
            "refresh_error_generation_id": self._error_id,
            "refresh_retry_at": self._retry_at.isoformat() if self._retry_at else None,
            "heartbeat_at": self._heartbeat_at.isoformat() if self._heartbeat_at else None,
            "heartbeat_age_seconds": heartbeat_age,
            "heartbeat_limit_seconds": int(WORKER_HEARTBEAT_LIMIT.total_seconds()),
            "recent_read_errors": errors,
            "read_error_limit": READ_ERROR_LIMIT,
            "read_error_window_seconds": int(READ_ERROR_WINDOW.total_seconds()),
        }

    def readiness(self) -> dict:
        with self._lock:
            current = self._current
            if current is not None and current.database != db_path():
                current = None
            state = self._status(current, datetime.now(timezone.utc),
                                 current.pending_publication if current else None)
            info = current.pin.info if current else None
            return {"ok": state["reason"] is None, **state,
                    "generation_id": info.generation_id if info else None,
                    "as_of": info.as_of.isoformat() if info else None}

    def refresh(self) -> bool:
        """Worker-only verification, readability check and atomic generation switch."""
        with self._refresh_lock:
            self.heartbeat()
            key = self._publication_key()
            try:
                return self._refresh(key)
            except Exception as exc:
                self._refresh_failed(key, exc)
                raise
            finally:
                self.heartbeat()

    def _refresh(self, key: tuple) -> bool:
        self._observe_publication()
        with self._lock:
            deferred = key == self._failed_key and self._retry_at is not None and (
                datetime.now(timezone.utc) < self._retry_at
            )
        try:
            current = self._retain(require_readable=False)
        except DBNotReadyError:
            current = None
        if current is not None:
            invalid_selected = False
            try:
                if deferred and key[0] == current.pin.info.generation_id:
                    return False
                valid = verified_snapshot_file(current.pin.info.path) is not None
                invalid_selected = not valid and key[0] == current.pin.info.generation_id
                with _request_cursor(current.connection) as check:
                    valid = valid and check.execute("SELECT 1").fetchone() == (1,)
                self._mark_readable(current, valid)
                pending = generation_state(current.pin, dataset="evidence")["pending_publication"]
                with self._lock:
                    current.pending_publication = pending
                if valid and self._published_id() == current.pin.info.generation_id:
                    with self._lock:
                        self._clear_refresh_failure()
                    return True
            except Exception:
                self._mark_readable(current, False)
            finally:
                self._release(current)
            if invalid_selected:
                raise GenerationError("selected generation failed verification")
        if deferred:
            return False
        # Only this background path acquires a pin, hashes bytes or opens DuckDB.
        pin = pin_latest_generation(db_path())
        try:
            connection = engine_db.connect(pin.info.path, read_only=True, wait_s=0)
        except BaseException:
            pin.close()
            raise
        candidate = _VerifiedGeneration(db_path(), pin, connection)
        try:
            if connection.execute("SELECT 1").fetchone() != (1,):
                raise GenerationError("verified generation is unreadable")
            published = self._published_id()
            pending = generation_state(pin, dataset="evidence")["pending_publication"]
            with self._lock:
                previous = self._current
                self._current = candidate
                candidate.pending_publication = pending
                self._set_publication(published, datetime.now(timezone.utc))
                self._clear_refresh_failure()
        except BaseException:
            candidate.close()
            raise
        if previous is not None:
            self._release(previous)
        return True

    def close(self) -> None:
        with self._lock:
            current, self._current = self._current, None
            self._pending_id = None
            self._observed_id = None
        if current is not None:
            self._release(current)


_generation_reader = _GenerationReader()


def refresh_generation() -> bool:
    """Worker entrypoint; leave the previous generation selected on verification failure."""
    return _generation_reader.refresh()


def readiness() -> dict:
    """In-memory result of the background verification and readability checks."""
    return _generation_reader.readiness()


def close_generation_reader() -> None:
    """Release selector ownership; active request leases retain their own lifetimes."""
    _generation_reader.close()


def read_con() -> duckdb.DuckDBPyConnection:
    """Serve the last verified generation with an independent request cursor."""
    return _generation_reader.read()


def served_generation() -> dict | None:
    """The generation the current request read from, as recorded by `read_con()`."""
    state = _DATA_SOURCE_STATE.get()
    return None if state is None else state.get("generation")


def write_con() -> duckdb.DuckDBPyConnection:
    """Open the primary read-write, waiting up to API_WRITE_WAIT_S for a short lock."""
    deadline = time.monotonic() + API_WRITE_WAIT_S
    while True:
        try:
            return _connect(read_only=False)
        except DBBusyError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(_WRITE_RETRY_S)


@contextmanager
def response_data_source() -> Iterator[dict]:
    """Track the source selected by a request for response-header middleware."""
    state = {
        "source": "generation", "snapshot_as_of": None, "generation_id": None,
        "generation": None,
    }
    token = _DATA_SOURCE_STATE.set(state)
    try:
        yield state
    finally:
        _DATA_SOURCE_STATE.reset(token)


@contextmanager
def require_fresh_evidence_snapshot() -> Iterator[None]:
    """Judge the served generation against the evidence budget (it is never refused)."""
    dataset_token = _DATASET_CLASS.set("evidence")
    try:
        yield
    finally:
        _DATASET_CLASS.reset(dataset_token)
