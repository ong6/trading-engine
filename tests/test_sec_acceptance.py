"""EDGAR acceptance clocks against recorded SGML headers and filing index pages.

The fixture records 75 filings fetched on 2026-10-21: the filing index "Accepted"
field, the ``.hdr.sgml`` ``ACCEPTANCE-DATETIME`` (both Eastern wall time), the
live submissions-API label and the nightly ``submissions.zip`` label. Raw bodies
are identified by their SHA-256 and kept outside Git.
"""
from __future__ import annotations

import io
import json
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pytest

from engine import free_sec_bulk, sec_acceptance

FIXTURE = Path(__file__).parent / "fixtures" / "sec_acceptance_audit.json"
ROWS = json.loads(FIXTURE.read_text())["rows"]


def _truth(row: dict) -> datetime:
    return sec_acceptance.sgml_acceptance(row["sgml_acceptance"])


def _labels():
    for row in ROWS:
        for key in ("bulk_label", "live_label"):
            if row[key]:
                yield row, key, row[key]


def test_fixture_index_page_matches_sgml_header():
    assert len(ROWS) == 75
    for row in ROWS:
        compact = row["index_accepted"].replace("-", "").replace(" ", "").replace(":", "")
        assert compact == row["sgml_acceptance"], row["accession"]


def test_label_read_as_utc_is_early_for_recorded_bulk_rows():
    """The reported defect: reading the ``Z`` literally is up to five hours early."""
    early = [(row["accession"], key) for row, key, label in _labels()
             if datetime.fromisoformat(label.replace("Z", "+00:00")) < _truth(row)]
    assert len(early) == 21 and {key for _, key in early} == {"bulk_label"}
    sample = {row["accession"] for row in ROWS if row["sample"] == "item_202"}
    assert sum(accession in sample for accession, _ in early) == 12


def test_conservative_label_clock_is_never_early_and_at_most_ten_hours_late():
    for row, key, label in _labels():
        truth = _truth(row)
        conservative = sec_acceptance.label_available_at(label)
        offset = -truth.astimezone(sec_acceptance.ET).utcoffset()
        assert truth <= conservative <= truth + 2 * offset, (row["accession"], key)
        received = truth + timedelta(minutes=5)
        assert truth <= sec_acceptance.label_available_at(label, received_at=received) <= received


def test_sgml_header_is_preferred_over_label():
    row = next(row for row in ROWS if row["accession"] == "0001193125-19-102874")
    chosen = sec_acceptance.available_at(sgml=row["sgml_acceptance"], label=row["live_label"])
    assert chosen == datetime(2019, 4, 10, 20, 41, 26, tzinfo=timezone.utc)
    assert sec_acceptance.available_at(label="") is None


def _bulk_archives(tmp_path: Path) -> tuple[Path, Path]:
    by_cik = defaultdict(list)
    for row in ROWS:
        by_cik[row["cik"]].append(row)
    submissions, facts = io.BytesIO(), io.BytesIO()
    with zipfile.ZipFile(submissions, "w") as sub_zip, zipfile.ZipFile(facts, "w") as fact_zip:
        for cik, rows in by_cik.items():
            name = f"CIK{cik:010d}.json"
            sub_zip.writestr(name, json.dumps({"cik": str(cik), "filings": {"recent": {
                "accessionNumber": [row["accession"] for row in rows],
                "filingDate": [row["filed"] for row in rows],
                "acceptanceDateTime": [row["bulk_label"] for row in rows],
                "form": [row["form"] for row in rows],
                "items": [row["items"] for row in rows],
            }, "files": []}}))
            fact_zip.writestr(name, json.dumps({"cik": cik, "facts": {"us-gaap": {"Revenues": {
                "units": {"USD": [{"end": "2004-12-31", "val": index, "accn": row["accession"],
                                   "form": row["form"], "filed": row["filed"]}
                                  for index, row in enumerate(rows)]}}}}}))
    (tmp_path / "submissions.zip").write_bytes(submissions.getvalue())
    (tmp_path / "companyfacts.zip").write_bytes(facts.getvalue())
    return tmp_path / "submissions.zip", tmp_path / "companyfacts.zip"


@pytest.mark.parametrize("session_zone", ["UTC", "Asia/Singapore"])
def test_bulk_store_availability_is_never_before_sgml_acceptance(tmp_path, session_zone):
    submissions, facts = _bulk_archives(tmp_path)
    con = duckdb.connect()
    try:
        con.execute(f"SET TimeZone='{session_zone}'")
        free_sec_bulk.load_submissions_zip(con, submissions)
        free_sec_bulk.load_companyfacts_zip(con, facts)
        available = dict(con.execute(
            "SELECT accn,available_at FROM sec_facts_available").fetchall())
        assert len(available) == 75
        for row in ROWS:
            assert available[row["accession"]] >= _truth(row), row["accession"]
            assert available[row["accession"]] == sec_acceptance.label_available_at(
                row["bulk_label"])
        events = dict(con.execute(
            "SELECT accession,available_at FROM sec_earnings_events_with_ticker").fetchall())
    finally:
        con.close()
    sample = [row for row in ROWS if row["sample"] == "item_202"]
    assert len(events) == len(sample) == 30
    for row in sample:
        assert events[row["accession"]] == available[row["accession"]]


@pytest.mark.parametrize("wall", [
    "2024-11-03 01:30:00", "2024-03-10 02:30:00", "2024-03-10 03:00:00",
    "2024-11-03 00:59:59", "2024-07-01 12:00:00", "2025-01-15 23:59:59",
])
def test_store_and_python_rules_agree_at_daylight_saving_changes(wall):
    label = wall.replace(" ", "T") + ".000Z"
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE t (x TIMESTAMPTZ)")
        con.execute("INSERT INTO t VALUES (?)", [free_sec_bulk._acceptance(label)])
        stored = con.execute(
            f"SELECT {free_sec_bulk._label_available_sql('x')} FROM t").fetchone()[0]
    finally:
        con.close()
    assert stored == sec_acceptance.label_available_at(label)
