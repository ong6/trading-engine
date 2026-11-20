"""Liveness must not queue behind database work or the shared request workers."""

import asyncio
import json
from threading import Event

import anyio.to_thread

from server import main
from tests.test_server_routes import _request_messages


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
                assert not meta.done()
            finally:
                release.set()
                _response, result = await meta
            assert result == {"meta": {"sentinel": "unchanged"}, "generation": None}

        finally:
            limiter.total_tokens = previous

    asyncio.run(requests())


def test_startup_warms_the_generation_before_meta_requests(monkeypatch):
    opened = []
    closed = []

    class Connection:
        def close(self):
            closed.append(True)

    def read():
        opened.append(True)
        return Connection()

    monkeypatch.setattr(main, "read_con", read)

    async def startup():
        async with main.app.router.lifespan_context(main.app):
            assert opened
            assert closed == opened

    asyncio.run(startup())


def test_generation_warmer_retries_failure_and_warms_each_publication(monkeypatch):
    first, second, third = (1,), (2,), (3,)
    markers = iter([first, second, second, second, third])
    observed = []
    outcomes = iter([False, True, True])

    class Stop:
        def wait(self, _interval):
            marker = next(markers, None)
            monkeypatch.setattr(main, "_generation_marker", lambda: marker)
            return marker is None

    def warm():
        observed.append(main._generation_marker())
        return next(outcomes)

    monkeypatch.setattr(main, "_warm_generation", warm)
    main._warm_generations(Stop(), first)
    assert observed == [second, second, third]


def test_unreadable_generation_does_not_prevent_startup_or_liveness(monkeypatch):
    def unreadable():
        raise OSError("cannot read the generation")

    monkeypatch.setattr(main, "read_con", unreadable)
    monkeypatch.setattr(main, "_generation_marker", lambda: None)

    async def startup():
        async with main.app.router.lifespan_context(main.app):
            response, body = await _get("/health")
            assert response["status"] == 200
            assert body == {"ok": True, "status": "ok"}

    asyncio.run(startup())
