"""engine/repair_integrity.py: repairs of already-stored integrity defects, proven
against the source's current history, dry-run by default and idempotent."""
from __future__ import annotations

import json
from datetime import date, datetime, time

import pytest
from conftest import SESSIONS, insert_bars

from engine import repair_integrity
from engine.lib import db
from sim.schema import init_sim_schema

EX_IDX = 20
EX = SESSIONS[EX_IDX]


def _store(path):
    con = db.connect(path)
    db.init_schema(con)
    db.init_actions_schema(con)
    init_sim_schema(con)
    con.execute("ALTER TABLE prices ADD COLUMN IF NOT EXISTS first_fetched_at TIMESTAMP")
    return con


def _stamp_after_ex(con, ticker):
    stamp = datetime.combine(EX, time(22, 30))
    con.execute("UPDATE prices SET fetched_at = ?, first_fetched_at = ? WHERE ticker = ?",
                [stamp, stamp, ticker])


def _closes(path, ticker):
    con = db.connect(path, read_only=True)
    try:
        return [c for (c,) in con.execute(
            "SELECT close FROM prices WHERE ticker = ? ORDER BY date", [ticker]).fetchall()]
    finally:
        con.close()


def _run(path, closes_by_ticker, **kwargs):
    def source(_yf, ticker, start):
        return {d: c for d, c in zip(SESSIONS, closes_by_ticker[ticker], strict=True)
                if start is None or d >= start}
    return repair_integrity.run(path, steps=("double", "splits"), since=SESSIONS[0],
                                source=source, **kwargs)


def test_skipped_split_is_restated_only_with_source_evidence(tmp_path):
    """ETHA 1:3: every pre-break bar sits at stored/source = 1/3 and every later one
    at 1, but rule 3 read the 5d re-fetch's restamps and skipped the split."""
    path = tmp_path / "market.duckdb"
    con = _store(path)
    brk = EX_IDX - 3
    for ticker in ("AAA", "BBB"):
        con.execute("INSERT INTO universe (ticker, yf_ticker, active, liquid) "
                    "VALUES (?, ?, TRUE, TRUE)", [ticker, ticker])
        insert_bars(con, ticker, SESSIONS, close=[20.0 if k < brk else 60.0
                                                   for k in range(len(SESSIONS))])
        _stamp_after_ex(con, ticker)
        con.execute("INSERT INTO split_adjustments VALUES (?, ?, ?, "
                    "'skipped_already_adjusted', 0.33, ?, 0, now())",
                    [ticker, EX, 1 / 3, SESSIONS[brk]])
    con.close()
    source = {"AAA": [60.0] * len(SESSIONS),
              # BBB's source disagrees on one old bar: not proven, nothing restated.
              "BBB": [60.0] * 5 + [61.5] + [60.0] * (len(SESSIONS) - 6)}

    dry = _run(path, source, apply=False)
    assert [(i["ticker"], i["evidence"]["proven"]) for i in dry["splits"]] == [
        ("AAA", True), ("BBB", False)]
    assert _closes(path, "AAA")[0] == 20.0                      # dry-run wrote nothing
    # The dry-run says what --apply will do: the reconciler's own verdict is only the
    # input, and rows_changed stays 0 until --apply (the 2026-10-21 live dry-run read
    # as if nothing would be restated).
    assert [(i["reconciler_verdict"], i["action"], i["rows_planned"], i["rows_changed"])
            for i in dry["splits"]] == [("skipped_already_adjusted", "restate", brk, 0),
                                         ("skipped_already_adjusted", "none", 0, 0)]
    assert dry["summary"]["splits"] == {"candidates": 2, "proven": 1, "source_unavailable": [],
                                        "rows_planned": brk, "rows_changed": 0}

    applied = _run(path, source, apply=True)
    assert [i["rows_changed"] for i in applied["splits"]] == [brk, 0]
    assert applied["summary"]["splits"]["rows_changed"] == brk
    assert _closes(path, "AAA") == pytest.approx([60.0] * len(SESSIONS))
    assert _closes(path, "BBB")[0] == 20.0
    con = db.connect(path, read_only=True)
    try:
        assert con.execute("SELECT ticker, outcome FROM split_adjustments ORDER BY ticker"
                           ).fetchall() == [("AAA", "applied"), ("BBB", "skipped_already_adjusted")]
        assert con.execute("SELECT COUNT(*) FROM price_observation_rejects WHERE ticker = 'AAA' "
                           "AND reason = 'split_restatement_predecessor'").fetchone() == (brk,)
        assert con.execute("SELECT actor FROM audit_log WHERE action = "
                           "'split_restated_with_source_evidence'").fetchall() == [
            ("repair_integrity",)]
    finally:
        con.close()
    again = _run(path, source, apply=True)                     # idempotent
    assert [i["ticker"] for i in again["splits"]] == ["BBB"]
    assert again["splits"][0]["rows_changed"] == 0


def test_sanity_skip_break_is_found_from_the_source_and_an_empty_answer_is_retried(
        tmp_path, monkeypatch):
    """QBTX 1:4 (skipped_sanity: a real move on the break day) has no reconciler
    break, so the source locates it. On 2026-10-22 the source answered nothing for
    QBTX and SMU and the dry-run read that as "no break"; it is retried once, and
    an answer that stays empty is reported as unavailable, never as evidence."""
    path = tmp_path / "market.duckdb"
    con = _store(path)
    con.execute("INSERT INTO universe (ticker, yf_ticker, active, liquid) "
                "VALUES ('QQQX', 'QQQX', TRUE, TRUE)")
    brk = EX_IDX - 3
    source = [100.0] * brk + [117.0] * (len(SESSIONS) - brk)   # +17% on the break day
    stored = [c / 4 if k < brk else c for k, c in enumerate(source)]
    insert_bars(con, "QQQX", SESSIONS, close=stored)
    _stamp_after_ex(con, "QQQX")
    con.execute("INSERT INTO split_adjustments VALUES ('QQQX', ?, 0.25, 'skipped_sanity', "
                "4.68, NULL, 0, now())", [EX])
    con.close()

    monkeypatch.setattr(repair_integrity.time, "sleep", lambda _s: None)
    answers = iter([{}, {}])
    down = repair_integrity.run(path, apply=False, steps=("splits",), since=SESSIONS[0],
                                source=lambda *_a: next(answers))
    assert down["splits"][0]["evidence"]["source_unavailable"] is True
    assert down["summary"]["splits"]["source_unavailable"] == ["QQQX"]
    answers = iter([{}, dict(zip(SESSIONS, source, strict=True))])
    report = repair_integrity.run(path, apply=True, steps=("splits",), since=SESSIONS[0],
                                  source=lambda *_a: next(answers))

    (item,) = report["splits"]
    assert item["reconciler_verdict"] == "skipped_sanity"
    assert (item["action"], item["evidence"]["break_date"], item["rows_changed"]) == (
        "restate", SESSIONS[brk].isoformat(), brk)
    assert _closes(path, "QQQX")[:brk] == pytest.approx([100.0] * brk)


def test_bar_divided_twice_is_multiplied_back_when_the_source_agrees(tmp_path):
    """WLFC 3:1: 07-15 was stored already restated and the July restatement divided
    it again (23.00 between 72.33 and 65.33; the source's current bar is 68.99)."""
    path = tmp_path / "market.duckdb"
    con = _store(path)
    con.execute("INSERT INTO universe (ticker, yf_ticker, active, liquid) "
                "VALUES ('WLFC', 'WLFC', TRUE, TRUE)")
    brk, island = EX_IDX - 1, EX_IDX - 4
    closes = [100.0 / 3 if k == island else 100.0 for k in range(len(SESSIONS))]
    insert_bars(con, "WLFC", SESSIONS, close=closes, volume=[3_000 if k == island else 1_000
                                                             for k in range(len(SESSIONS))])
    con.execute("INSERT INTO split_adjustments VALUES ('WLFC', ?, 3.0, 'applied', 3.0, ?, "
                "100, now())", [EX, SESSIONS[brk]])
    con.close()
    source = {"WLFC": [100.0] * len(SESSIONS)}

    dry = _run(path, source, apply=False)
    assert (dry["double"][0]["action"], dry["double"][0]["rows_planned"],
            dry["double"][0]["rows_changed"]) == ("restore", 1, 0)
    report = _run(path, source, apply=True)

    (item,) = report["double"]
    assert item["dates"] == [SESSIONS[island].isoformat()] and item["rows_changed"] == 1
    assert _closes(path, "WLFC") == pytest.approx([100.0] * len(SESSIONS))
    con = db.connect(path, read_only=True)
    try:
        assert con.execute("SELECT volume FROM prices WHERE date = ?",
                           [SESSIONS[island]]).fetchone() == (1_000,)
        (payload,) = con.execute("SELECT payload FROM audit_log WHERE action = "
                                 "'split_double_restatement_reverted'").fetchone()
        assert json.loads(payload)["dates"] == [SESSIONS[island].isoformat()]
    finally:
        con.close()
    assert _run(path, source, apply=True)["double"] == []      # idempotent


def test_glitch_bar_divided_by_a_restatement_outside_its_window_is_restored(tmp_path):
    """RUSHA 3:2: the source served 08-05 and 08-10 already restated three weeks
    before the ex-date; a restatement of every pre-break bar divides them again."""
    path = tmp_path / "market.duckdb"
    con = _store(path)
    con.execute("INSERT INTO universe (ticker, yf_ticker, active, liquid) "
                "VALUES ('RUSH', 'RUSH', TRUE, TRUE)")
    glitch = [2, 5]                                   # far outside the 15-session window
    closes = [100.0 / 1.5 if k in glitch else 100.0 for k in range(len(SESSIONS))]
    insert_bars(con, "RUSH", SESSIONS, close=closes)
    con.execute("INSERT INTO split_adjustments VALUES ('RUSH', ?, 1.5, 'applied', 1.5, ?, "
                "100, now())", [EX, SESSIONS[EX_IDX - 3]])
    con.close()

    report = _run(path, {"RUSH": [100.0] * len(SESSIONS)}, apply=True)

    assert report["double"][0]["evidence"]["dates"] == [SESSIONS[k] for k in glitch]
    assert _closes(path, "RUSH") == pytest.approx([100.0] * len(SESSIONS))


def test_dry_run_reports_a_failed_actions_fetch_instead_of_no_split(tmp_path):
    """2026-10-21: the dry-run's actions fetch for IESC and RUSHA failed and the
    report simply listed no split for them, under-reporting what --apply restates."""
    import pandas as pd

    path = tmp_path / "market.duckdb"
    con = _store(path)
    for ticker in ("AAA", "BBB"):
        con.execute("INSERT INTO universe (ticker, yf_ticker, active, liquid) "
                    "VALUES (?, ?, TRUE, TRUE)", [ticker, ticker])
    con.close()
    report = repair_integrity.run(
        path, apply=False, steps=("unrecorded",), since=SESSIONS[0],
        fetch_actions=lambda yft: None if yft == "AAA" else pd.DataFrame(),
        breaks=lambda _con: [{"ticker": t, "date": "2024-07-01", "ratio": 2.0}
                             for t in ("AAA", "BBB")])
    assert report["unrecorded"]["fetch"] == {"AAA": "failed", "BBB": "empty"}
    assert report["summary"]["unrecorded"] == {"names": 2, "fetch_failed": ["AAA"]}


def test_dry_run_is_the_default_and_never_writes(tmp_path, monkeypatch):
    import sys

    path = tmp_path / "market.duckdb"
    _store(path).close()
    calls = []
    monkeypatch.setattr(repair_integrity, "run",
                        lambda db_path, **kw: calls.append(kw["apply"]) or {})
    monkeypatch.setattr(sys, "argv", ["repair_integrity", "--db", str(path)])
    assert repair_integrity.main() == 0
    assert calls == [False]
    assert repair_integrity.DEFAULT_SINCE == date(2026, 7, 16)
