"""Retirement previews, transactional refusals, and retained nightly evidence."""

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from engine.lib.db import connect
from server import nightly_monitor
from sim import league
from sim.schema import init_sim_schema
from tests.nightly_test_helpers import nightly_fixture
from tools import retire_books as retire


@pytest.fixture
def retirement_store(tmp_path, monkeypatch):
    database = tmp_path / "paper.duckdb"
    con = connect(database)
    init_sim_schema(con)
    meta, driver = nightly_fixture(con, tmp_path)
    con.execute("INSERT INTO sim_positions VALUES ('paper','AAA',2,10)")
    con.execute("INSERT INTO sim_orders VALUES (1,'paper','AAA','buy',2,DATE '2026-09-03',"
                "'filled',NULL)")
    con.execute("INSERT INTO sim_fills VALUES (1,'paper','AAA','buy',2,DATE '2026-09-04',"
                "10,10,0,0)")
    con.close()
    alpha = tmp_path / "alpha"
    for directory in ("live", "registrations", "trials"):
        (alpha / directory).mkdir(parents=True)
    evidence = tmp_path / "evidence.md"
    evidence.write_text("Published evidence: duplicate paper book.\n")

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 5, 8, 22, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(retire, "datetime", Clock)
    return database, alpha, evidence, meta, driver


def _run(store, *books, apply=False):
    database, alpha, evidence, *_ = store
    return retire.retire_books([retire.Retirement(book, "duplicate", evidence) for book in books],
                               database=database, alpha_root=alpha, apply=apply)


def _state(database):
    con = connect(database, read_only=True)
    try:
        return {table: con.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall()
                for table in ("portfolios", "sim_orders", "sim_fills", "sim_positions",
                              "sim_equity", "audit_log")}
    finally:
        con.close()


def _add_book(database, book, active=True):
    con = connect(database)
    con.execute("INSERT INTO portfolios (id,name,config,active) VALUES (?,?,'{}',?)",
                [book, book, active])
    con.close()


def test_default_dry_run_opens_snapshot_read_only_and_changes_nothing(retirement_store, monkeypatch):
    database = retirement_store[0]
    before = _state(database)
    calls = []

    def observed_connect(path, **kwargs):
        calls.append((path, kwargs))
        return connect(path, **kwargs)

    monkeypatch.setattr(retire, "connect", observed_connect)
    monkeypatch.setattr(retire, "SNAPSHOT", database)
    _, alpha, evidence, *_ = retirement_store
    changes = retire.retire_books([retire.Retirement("paper", "duplicate", evidence)],
                                  alpha_root=alpha)
    assert calls == [(database, {"read_only": True})]
    assert changes[0]["active"] == {"from": True, "to": False}
    assert changes[0]["audit_row"]["payload"] == {
        "portfolio_id": "paper", "reason": "duplicate", "positions_kept": 1,
        "pending_cancelled": 0, "precedent": "2026-08-18", "evidence": evidence.as_posix(),
    }
    assert _state(database) == before


def test_apply_uses_normal_writer_and_keeps_every_other_row(retirement_store, monkeypatch):
    database = retirement_store[0]
    before = _state(database)
    calls = []

    def observed_connect(path, **kwargs):
        calls.append((path, kwargs))
        return connect(path, **kwargs)

    monkeypatch.setattr(retire, "connect", observed_connect)
    _run(retirement_store, "paper", apply=True)
    assert calls == [(database, {"read_only": False})]
    after = _state(database)
    assert after["portfolios"][0][5] is False
    assert len(after["audit_log"]) == 1
    ts, actor, action, payload = after["audit_log"][0]
    assert (ts, actor, action) == (datetime(2026, 9, 5, 8, 22), retire.ACTOR, "portfolio_retired")
    assert json.loads(payload)["portfolio_id"] == "paper"
    assert {k: v for k, v in before.items() if k not in {"portfolios", "audit_log"}} == {
        k: v for k, v in after.items() if k not in {"portfolios", "audit_log"}}
    assert after["portfolios"][0][:5] == before["portfolios"][0][:5]
    assert after["portfolios"][0][6:] == before["portfolios"][0][6:]


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize("book,active,error", [
    ("missing", None, "unknown book"), ("old", False, "already retired"),
    ("p15_rule_control", True, "protected book"), ("p15_ai_ranked", True, "protected book"),
    ("p15_hybrid_veto", True, "protected book"), ("pead_ear", True, "protected book"),
    ("news_gated_momo", True, "protected book"), ("p16_future_ai", True, "protected book"),
])
def test_refusals_leave_entire_batch_unchanged(retirement_store, book, active, error, apply):
    database = retirement_store[0]
    if active is not None:
        _add_book(database, book, active)
    before = _state(database)
    with pytest.raises(ValueError, match=error):
        _run(retirement_store, "paper", book, apply=apply)
    assert _state(database) == before


@pytest.mark.parametrize("directory,suffix", [
    ("live", ".json"), ("registrations", ".md"), ("registrations", ".json"),
    ("trials", ".csv"), ("live/nested", ".json"),
])
def test_alpha_references_are_protected(retirement_store, directory, suffix):
    database, alpha, *_ = retirement_store
    path = alpha / directory / ("reference" + suffix)
    path.parent.mkdir(exist_ok=True)
    path.write_text('book: "paper"')
    with pytest.raises(ValueError, match="protected book"):
        _run(retirement_store, "paper", apply=True)
    assert _state(database)["portfolios"][0][5] is True


def test_unrelated_identifier_does_not_protect_a_book(retirement_store):
    (retirement_store[1] / "live/reference.json").write_text('"paper_gated"')
    _run(retirement_store, "paper", apply=True)


@pytest.mark.parametrize("state", ["pending", "p15_pending", "queued", None])
def test_open_order_refusal(retirement_store, state):
    con = connect(retirement_store[0])
    con.execute("UPDATE sim_orders SET status=?", [state])
    con.close()
    before = _state(retirement_store[0])
    with pytest.raises(ValueError, match="open orders"):
        _run(retirement_store, "paper", apply=True)
    assert _state(retirement_store[0]) == before


def test_write_failure_rolls_back_both_books_and_audit_rows(retirement_store):
    database = retirement_store[0]
    _add_book(database, "other")
    con = connect(database)
    con.execute("DROP TABLE audit_log")
    con.execute("CREATE TABLE audit_log (ts TIMESTAMP, actor VARCHAR, action VARCHAR, "
                "payload VARCHAR CHECK (payload NOT LIKE '%other%'))")
    con.close()
    before = _state(database)
    with pytest.raises(Exception, match="CHECK constraint failed"):
        _run(retirement_store, "paper", "other", apply=True)
    assert _state(database) == before


def test_successful_batch_and_idempotent_rerun(retirement_store):
    database = retirement_store[0]
    _add_book(database, "other")
    _run(retirement_store, "paper", "other", apply=True)
    before = _state(database)
    assert len(before["audit_log"]) == 2
    assert all(row[5] is False for row in before["portfolios"])
    with pytest.raises(ValueError, match="already retired"):
        _run(retirement_store, "paper", "other", apply=True)
    assert _state(database) == before


def test_post_close_retirement_keeps_nightly_report_current(retirement_store, tmp_path):
    database, _, _, meta, driver = retirement_store
    con = connect(database)
    con.execute("INSERT INTO prices (ticker,date,open,high,low,close,volume) "
                "VALUES ('AAA',DATE '2026-09-01',10,11,9,10,100)")
    con.execute("INSERT INTO portfolios SELECT 'survivor','Survivor',strategy,config,created,"
                "active,cash,initial_cash,execution_profile FROM portfolios WHERE id='paper'")
    con.execute("INSERT INTO sim_equity SELECT 'survivor',date,equity,cash,n_positions "
                "FROM sim_equity WHERE portfolio_id='paper'")
    league.write_reports(con, date(2026, 9, 4), tmp_path)
    assert "| paper | AAA |" in (tmp_path / "reports/league.md").read_text()
    assert nightly_monitor.evidence_status(
        meta, driver, con, date(2026, 9, 4), data_dir=tmp_path)["status"] == "current"
    con.close()
    _run(retirement_store, "paper", apply=True)
    con = connect(database, read_only=True)
    try:
        result = nightly_monitor.evidence_status(
            meta, driver, con, date(2026, 9, 4), data_dir=tmp_path)
    finally:
        con.close()
    assert result["status"] == "current"


def test_before_close_refuses_instead_of_invalidating_report(retirement_store):
    con = connect(retirement_store[0])
    con.execute("UPDATE sim_equity SET date=DATE '2026-09-05'")
    con.close()
    with pytest.raises(ValueError, match="session has not closed"):
        _run(retirement_store, "paper", apply=True)


def test_missing_private_inputs_refuses(retirement_store):
    (retirement_store[1] / "registrations").rmdir()
    with pytest.raises(ValueError, match="cannot check protected books"):
        _run(retirement_store, "paper", apply=True)


def test_invalid_request_and_cli_batch_counts(retirement_store, capsys):
    database, alpha, evidence, *_ = retirement_store
    for requests in ([], [retire.Retirement("paper", " ", evidence)],
                     [retire.Retirement("paper", "duplicate", Path("missing.md"))]):
        with pytest.raises(ValueError):
            retire.retire_books(requests, database=database, alpha_root=alpha)
    with pytest.raises(ValueError, match="distinct"):
        _run(retirement_store, "paper", "paper")
    with pytest.raises(SystemExit):
        retire.main(["--book", "paper", "--book", "other", "--reason", "duplicate",
                     "--evidence", str(evidence)])
    assert "equally often" in capsys.readouterr().err


def test_cli_prints_preview_and_refusal(retirement_store, capsys):
    database, alpha, evidence, *_ = retirement_store
    args = ["--book", "paper", "--reason", "duplicate", "--evidence", str(evidence),
            "--db", str(database), "--alpha-root", str(alpha)]
    before = _state(database)
    assert retire.main(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry-run"
    assert output["changes"][0]["book"] == "paper"
    assert _state(database) == before
    assert retire.main(args + ["--apply"]) == 0
    capsys.readouterr()
    assert retire.main(args + ["--apply"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "refused: already retired" in captured.err
