"""Scoring waits for legitimate writers within its registered UTC window."""
from __future__ import annotations

from contextlib import ExitStack
from datetime import timedelta
from types import SimpleNamespace

import duckdb
import pytest

from engine.lib import db, resources
from server import p15_scoring_runner as runner
from tests.test_lock_deadlines import held_lock
from tests.test_p15_scoring import P15_NOW, _news_response, _p15_database, _scoring_result


@pytest.mark.parametrize("phase,remaining_s", [
    ("initial", 120), ("response", 120), ("finalization", 120), ("books", 120),
    ("sample_start", 65), ("finalization", 65),
])
def test_scoring_waits_past_sixty_seconds_and_retains_responses(
    tmp_path, monkeypatch, phase, remaining_s,
):
    database = tmp_path / "market.duckdb"
    _p15_database(database)
    monkeypatch.setattr(runner, "LOCK_PATH", tmp_path / "scoring.lock")
    monkeypatch.setattr(runner, "NIGHTLY_LOCK", tmp_path / "nightly.lock")
    started = P15_NOW.replace(hour=12, minute=0) - timedelta(seconds=remaining_s)
    elapsed, holder, pending, completed_samples = 0.0, None, phase == "initial", 0
    generated, sleeps = [], []
    connect = db.connect
    create_run = runner.store.create_run
    complete_sample, complete_run = runner.store.complete_sample, runner.store.complete_run

    with ExitStack() as holders:
        def sleep(seconds):
            nonlocal elapsed
            sleeps.append(seconds)
            elapsed += seconds
            if elapsed >= 65 and holder is not None and holder.poll() is None:
                holder.terminate()
                holder.wait()

        def connect_after_writer(*args, **kwargs):
            nonlocal holder, pending
            if pending:
                pending = False
                holder = holders.enter_context(held_lock(database, "writer"))
            return connect(*args, **kwargs)

        def generate(payload):
            nonlocal pending
            generated.append(payload["sample_index"])
            if phase == "response" and payload["sample_index"] == 0:
                pending = True
            return _scoring_result(payload)

        def retain_sample(*args, **kwargs):
            nonlocal completed_samples, pending
            result = complete_sample(*args, **kwargs)
            completed_samples += 1
            if phase == "finalization" and completed_samples == 3:
                pending = True
            return result

        def retain_context(*args, **kwargs):
            nonlocal pending
            result = create_run(*args, **kwargs)
            pending = phase == "sample_start"
            return result

        def retain_run(*args, **kwargs):
            nonlocal pending
            result = complete_run(*args, **kwargs)
            pending = phase == "books"
            return result

        fake_time = SimpleNamespace(monotonic=lambda: 100.0 + elapsed, sleep=sleep)
        monkeypatch.setattr(db, "time", fake_time)
        monkeypatch.setattr(runner, "monotonic_time", fake_time)
        monkeypatch.setattr(db.settings, "lock_wait_s", lambda: 60.0)
        monkeypatch.setattr(db, "connect", connect_after_writer)
        monkeypatch.setattr(runner.store, "create_run", retain_context)
        monkeypatch.setattr(runner.store, "complete_sample", retain_sample)
        monkeypatch.setattr(runner.store, "complete_run", retain_run)
        result = runner.run(
            database=database, now=started, generate=generate,
            fetch_news=_news_response, clock=lambda: started + timedelta(seconds=elapsed),
        )

    assert elapsed == 65.0 and sum(sleeps) == 65.0
    assert generated == ([] if phase == "sample_start" else [0, 1, 2])
    if remaining_s == 65:
        assert result["status"] == "failed" and result["reason"] == "deadline_exceeded"
    else:
        assert result["status"] == "completed" and result["unavailable_count"] == 0
    con = connect(database, read_only=True, wait_s=0)
    try:
        assert con.execute(
            "SELECT status, response_payload IS NOT NULL FROM p15_scoring_samples "
            "ORDER BY sample_index"
        ).fetchall() == [("completed", True)] * len(generated)
        assert con.execute("SELECT COUNT(*) FROM agent_evaluation_traces").fetchone() == (
            0 if remaining_s == 65 else 1,
        )
    finally:
        con.close()


def test_scoring_store_wait_expires_at_noon_without_model_calls(tmp_path, monkeypatch):
    database = tmp_path / "market.duckdb"
    _p15_database(database)
    elapsed, calls = 0.0, []
    started = P15_NOW.replace(hour=11, minute=59, second=50)

    def sleep(seconds):
        nonlocal elapsed
        elapsed += seconds

    fake_time = SimpleNamespace(monotonic=lambda: 100.0 + elapsed, sleep=sleep)
    monkeypatch.setattr(db, "time", fake_time)
    monkeypatch.setattr(runner, "monotonic_time", fake_time)
    monkeypatch.setattr(db.settings, "lock_wait_s", lambda: 3600.0)
    with held_lock(database, "writer"):
        with pytest.raises(duckdb.IOException) as caught:
            runner._run(
                database=database, now=started, generate=lambda payload: calls.append(payload),
                fetch_news=_news_response,
                clock=lambda: started + timedelta(seconds=elapsed),
            )
        assert db.is_lock_error(caught.value)
        assert elapsed == 10.0 and calls == []


def test_scoring_advisory_locks_share_the_noon_budget(tmp_path, monkeypatch):
    scoring, nightly = tmp_path / "scoring.lock", tmp_path / "nightly.lock"
    monkeypatch.setattr(runner, "LOCK_PATH", scoring)
    monkeypatch.setattr(runner, "NIGHTLY_LOCK", nightly)
    elapsed, calls = 0.0, []
    started = P15_NOW.replace(hour=11, minute=59, second=59)

    def sleep(seconds):
        nonlocal elapsed
        elapsed += seconds
        if elapsed >= 0.4 and scoring_holder.poll() is None:
            scoring_holder.terminate()
            scoring_holder.wait()

    fake_time = SimpleNamespace(monotonic=lambda: 100.0 + elapsed, sleep=sleep)
    monkeypatch.setattr(resources, "time", fake_time)
    monkeypatch.setattr(runner, "monotonic_time", fake_time)
    monkeypatch.setattr(runner, "_run_with_books", lambda **kwargs: calls.append(kwargs))
    with held_lock(scoring, "advisory") as scoring_holder, held_lock(nightly, "advisory"):
        with pytest.raises(resources.AdvisoryLockTimeout, match="nightly.lock"):
            runner.run(database=tmp_path / "unused.duckdb", now=started, clock=lambda: started)
        assert elapsed == pytest.approx(1.0) and calls == []


class _Borrowed:
    def __init__(self, con):
        self._con = con

    def __getattr__(self, name):
        return getattr(self._con, name)

    def close(self):
        pass


def test_p15_window_waits_until_the_league_has_stepped_the_session(con, monkeypatch):
    from datetime import date

    from sim import p15_books

    con.execute("INSERT INTO portfolios (id, name, strategy, created, active, cash) "
                "VALUES ('league_book', 'league_book', 'x', DATE '2024-06-03', TRUE, 1)")
    con.execute("INSERT INTO sim_equity (portfolio_id, date, equity, cash) "
                "VALUES ('league_book', DATE '2024-06-03', 1, 1)")
    windows = []
    monkeypatch.setattr(runner, "_run", lambda **kwargs: {"status": "completed",
                                                          "market_date": "2024-06-04"})
    monkeypatch.setattr(runner, "_connect", lambda *args, **kwargs: _Borrowed(con))
    monkeypatch.setattr(p15_books, "run_window",
                        lambda con, day, observed_at: windows.append(day)
                        or {"status": "skipped"})
    result = runner._run_with_books(lock_deadline=0.0)
    assert windows == []
    assert result["books"] == {"status": "waiting_for_league", "league_through": "2024-06-03"}

    con.execute("INSERT INTO sim_equity (portfolio_id, date, equity, cash) "
                "VALUES ('league_book', DATE '2024-06-04', 1, 1)")
    result = runner._run_with_books(lock_deadline=0.0)
    assert windows == [date(2024, 6, 4)] and result["books"] == {"status": "skipped"}


def test_waiting_for_the_league_exits_tempfail(monkeypatch):
    monkeypatch.setattr(runner, "run", lambda **kwargs: {
        "status": "completed", "market_date": "2024-06-04",
        "books": {"status": "waiting_for_league", "league_through": "2024-06-03"}})
    assert runner.main(["--run"]) == 75
    monkeypatch.setattr(runner, "run", lambda **kwargs: {"status": "completed"})
    assert runner.main(["--run"]) == 0

