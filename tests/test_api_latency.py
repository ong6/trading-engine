"""Liveness must not queue behind database work or the shared request workers."""

import asyncio
import fcntl
import json
import time
from threading import Event, Thread, current_thread

import anyio.to_thread
import pytest

from server import db as server_db
from server import main
from tests.test_server_routes import _request_messages, _snapshot_cohort, _snapshot_source
from tools import publish_snapshot


@pytest.fixture(autouse=True)
def isolated_generation_reader(monkeypatch):
    if not hasattr(server_db, "_GenerationReader"):
        yield None
        return
    reader = server_db._GenerationReader()
    monkeypatch.setattr(server_db, "_generation_reader", reader)
    yield reader
    reader.close()


async def _get(path):
    messages = await _request_messages(path)
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = json.loads(b"".join(m.get("body", b"") for m in messages
                              if m["type"] == "http.response.body"))
    return start, body


def test_health_does_not_open_or_wait_for_the_store(monkeypatch):
    def locked():
        raise main.DBBusyError("store unavailable")

    monkeypatch.setattr(main, "read_con", locked)

    async def request():
        response, body = await _get("/health")
        assert response["status"] == 200
        assert body == {"ok": True, "status": "ok"}
        assert b"x-data-source" not in dict(response["headers"])

    asyncio.run(request())


def test_health_answers_while_meta_occupies_all_request_workers(monkeypatch):
    release = Event()

    class Connection:
        def close(self):
            pass

    monkeypatch.setattr(main, "read_con", Connection)

    async def requests():
        entered = asyncio.Event()
        loop = asyncio.get_running_loop()

        def project(*_args, **_kwargs):
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise TimeoutError("test did not release the metadata projection")
            return {"meta": {"sentinel": "unchanged"}}

        monkeypatch.setattr(main.meta_projection, "project", project)
        limiter = anyio.to_thread.current_default_thread_limiter()
        previous = limiter.total_tokens
        limiter.total_tokens = 1
        try:
            meta = asyncio.create_task(_get("/meta"))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                response, _body = await asyncio.wait_for(_get("/health"), 0.5)
                assert response["status"] == 200
                response, _body = await asyncio.wait_for(_get("/ready"), 0.5)
                assert response["status"] == 503
                assert not meta.done()
            finally:
                release.set()
                _response, result = await meta
            assert result == {"meta": {"sentinel": "unchanged"}, "generation": None}

        finally:
            limiter.total_tokens = previous

    asyncio.run(requests())


def test_startup_and_probes_do_not_wait_for_first_verification(monkeypatch):
    entered, release = Event(), Event()

    def verify():
        entered.set()
        if not release.wait(5):
            raise TimeoutError("test did not release initial verification")
        return False

    monkeypatch.setattr(server_db, "refresh_generation", verify)

    async def startup():
        started = time.perf_counter()
        async with main.app.router.lifespan_context(main.app):
            assert time.perf_counter() - started < 0.5
            await asyncio.wait_for(asyncio.to_thread(entered.wait, 2), 3)
            for path, expected in (("/health", 200), ("/ready", 503), ("/meta", 503)):
                response, _body = await asyncio.wait_for(_get(path), 0.5)
                assert response["status"] == expected
            release.set()

    try:
        asyncio.run(startup())
    finally:
        release.set()


def test_cold_read_is_not_ready_without_verifying_inline(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("request must not verify a generation")

    monkeypatch.setattr(server_db, "pin_latest_generation", forbidden)

    async def requests():
        for path in ("/meta", "/league", "/ready"):
            response, body = await asyncio.wait_for(_get(path), 0.5)
            assert response["status"] == 503
            assert "not ready" in json.dumps(body)

    asyncio.run(requests())


def test_reads_serve_previous_generation_during_verification(monkeypatch, tmp_path):
    from engine.lib import snapshots

    root = tmp_path / "repo"
    source = root / "store" / "market.duckdb"
    source.parent.mkdir(parents=True)
    _snapshot_source(source)
    _snapshot_cohort(root)
    publish_snapshot.publish_snapshot(root, source)
    monkeypatch.setattr(server_db, "DEFAULT_DB", source)
    assert main._warm_generation()
    first = server_db.read_con()
    first_id = first.generation_info.generation_id
    with server_db.engine_db.connect(source, wait_s=0) as writer:
        writer.execute("UPDATE prices SET close=2 WHERE ticker='SPY'")
    publish_snapshot.publish_snapshot(root, source)
    second_id = snapshots.structural_snapshot_info(
        (source.parent / "snapshots" / "market-latest.duckdb").resolve()
    ).generation_id
    for key in list(snapshots._verified_generations):
        if key[0].stem == second_id:
            snapshots._verified_generations.pop(key)
    entered, release = Event(), Event()
    original = snapshots._hash_file

    def verify(path):
        if current_thread().name != "test-generation-worker":
            raise AssertionError("read request ran verification inline")
        entered.set()
        if not release.wait(5):
            raise TimeoutError("test did not release verification")
        return original(path)

    monkeypatch.setattr(snapshots, "_hash_file", verify)
    monkeypatch.setattr(main.meta_projection, "project", lambda con, **kw: {
        "meta": {"close": con.execute("SELECT close FROM prices WHERE ticker='SPY'").fetchone()[0]},
    })
    monkeypatch.setattr(main.league_read_models, "league", lambda con: {
        "close": con.execute("SELECT close FROM prices WHERE ticker='SPY'").fetchone()[0],
    })
    worker = Thread(target=main._warm_generation, name="test-generation-worker")
    worker.start()
    try:
        assert entered.wait(2)

        async def requests():
            started = time.perf_counter()
            response, body = await asyncio.wait_for(_get("/meta"), 0.5)
            assert time.perf_counter() - started < 0.5
            assert response["status"] == 200
            assert body["meta"]["close"] == 1
            assert body["generation"]["generation_id"] == first_id
            assert body["generation"]["pending_verification"] is True
            assert body["generation"]["pending_generation_id"] == second_id
            headers = dict(response["headers"])
            assert headers[b"x-generation-id"].decode() == first_id
            response, body = await asyncio.wait_for(_get("/league"), 0.5)
            assert response["status"] == 200 and body["close"] == 1
            response, body = await asyncio.wait_for(_get("/ready"), 0.5)
            assert response["status"] == 200 and body["ok"] is True
            assert body["generation_id"] == first_id

        asyncio.run(requests())
    finally:
        release.set()
        worker.join(5)
    try:
        assert not worker.is_alive()
        # A request's own cursor and lifetime pin survive the atomic switch.
        assert first.execute("SELECT close FROM prices WHERE ticker='SPY'").fetchone()[0] == 1
        response, body = asyncio.run(_get("/meta"))
        assert response["status"] == 200 and body["meta"]["close"] == 2
        assert body["generation"]["generation_id"] == second_id
        assert body["generation"]["pending_verification"] is False
        old_lock = source.parent / "snapshots" / "pins" / (first_id + ".lock")
        with old_lock.open("a+b") as handle:
            with pytest.raises(BlockingIOError):
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            first.close()
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        first.close()


def test_corrupt_publication_keeps_previous_ready_and_readable(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    source = root / "store" / "market.duckdb"
    source.parent.mkdir(parents=True)
    _snapshot_source(source)
    _snapshot_cohort(root)
    publish_snapshot.publish_snapshot(root, source)
    monkeypatch.setattr(server_db, "DEFAULT_DB", source)
    assert main._warm_generation()
    first_id = server_db.readiness()["generation_id"]
    with server_db.engine_db.connect(source, wait_s=0) as writer:
        writer.execute("UPDATE prices SET close=2 WHERE ticker='SPY'")
    publish_snapshot.publish_snapshot(root, source)
    newest = (source.parent / "snapshots" / "market-latest.duckdb").resolve()
    newest.chmod(0o600)
    with newest.open("r+b") as damaged:
        damaged.write(b"damaged")
    assert main._warm_generation() is False
    state = server_db.readiness()
    assert state["ok"] is True and state["generation_id"] == first_id
    assert state["pending_verification"] is True
    with server_db.read_con() as con:
        assert con.execute("SELECT close FROM prices WHERE ticker='SPY'").fetchone() == (1,)


def test_readiness_fails_when_selected_generation_becomes_unreadable(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    source = root / "store" / "market.duckdb"
    source.parent.mkdir(parents=True)
    _snapshot_source(source)
    _snapshot_cohort(root)
    publish_snapshot.publish_snapshot(root, source)
    monkeypatch.setattr(server_db, "DEFAULT_DB", source)
    assert main._warm_generation()
    newest = (source.parent / "snapshots" / "market-latest.duckdb").resolve()
    newest.rename(newest.with_suffix(".removed"))
    assert main._warm_generation() is False
    assert server_db.readiness()["ok"] is False

    async def requests():
        for path in ("/meta", "/ready"):
            response, body = await asyncio.wait_for(_get(path), 0.5)
            assert response["status"] == 503
            assert "not ready" in json.dumps(body)
        response, body = await _get("/health")
        assert response["status"] == 200 and body["ok"] is True

    asyncio.run(requests())
