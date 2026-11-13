"""Signal collection keeps external waits outside DuckDB writer leases."""
from __future__ import annotations

from datetime import date

import pytest

from engine import signals
from engine.lib import db


def test_connection_narrowed_external_source_releases_db(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    con = db.connect(db_path)
    db.init_schema(con)
    db.init_queue_schema(con)
    con.close()

    observed: list[int] = []

    def fetch_while_reading(con_arg, mode):
        assert con_arg is None
        assert mode == "incremental"
        reader = db.connect(db_path, read_only=True, wait_s=0)
        try:
            observed.append(
                reader.execute("SELECT COUNT(*) FROM macro_signals").fetchone()[0]
            )
        finally:
            reader.close()
        return [("test_series", date(2026, 9, 8), 1.25)]

    monkeypatch.setattr(signals, "SOURCES", {"external": fetch_while_reading})
    monkeypatch.setattr(signals, "DB_READ_SOURCES", frozenset())
    monkeypatch.setattr(signals.rsc, "dir_size_gb", lambda _path, **_kwargs: 0.0)

    result = signals.run_connection_narrowed(
        {"mode": "incremental"},
        db_path=db_path,
        meta_path=tmp_path / "meta.json",
    )

    assert observed == [0]
    assert result["rows_inserted"] == 1
    check = db.connect(db_path, read_only=True)
    try:
        assert check.execute(
            "SELECT series, obs_date, value FROM macro_signals"
        ).fetchall() == [("test_series", date(2026, 9, 8), 1.25)]
    finally:
        check.close()


def test_connection_narrowed_db_source_gets_read_only_lease(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    observed: list[int] = []

    def fetch_from_db(con, mode):
        assert mode == "incremental"
        observed.append(con.execute("SELECT COUNT(*) FROM prices").fetchone()[0])
        return [("breadth_test", date(2026, 9, 8), 50.0)]

    monkeypatch.setattr(signals, "SOURCES", {"breadth": fetch_from_db})
    monkeypatch.setattr(signals, "DB_READ_SOURCES", frozenset({"breadth"}))
    monkeypatch.setattr(signals.rsc, "dir_size_gb", lambda _path, **_kwargs: 0.0)

    result = signals.run_connection_narrowed(
        {"only": "breadth"},
        db_path=db_path,
        meta_path=tmp_path / "meta.json",
    )

    assert observed == [0]
    assert result["rows_inserted"] == 1


def test_unread_macro_collection_is_enabled_and_consumed_series_have_purposes():
    assert signals.UNREAD_MACRO_COLLECTION_ENABLED is True
    assert "cot" in signals.SOURCES
    assert all(signals._series_enabled(series) for series in signals.UNREAD_MACRO_SERIES)
    assert signals.COLLECTED_MACRO_SERIES == frozenset(signals.SERIES_PURPOSES)
    assert signals.COLLECTED_MACRO_SERIES.isdisjoint(signals.UNREAD_MACRO_SERIES)


@pytest.mark.parametrize("enabled", [True, False])
def test_shared_response_fields_follow_collection_flag(monkeypatch, enabled):
    monkeypatch.setattr(signals, "UNREAD_MACRO_COLLECTION_ENABLED", enabled)
    calls = []

    class Response:
        text = "date,dix,gex\n2026-10-01,0.45,9000000\n"

        @staticmethod
        def json():
            return {"ratios": [
                {"name": "TOTAL PUT/CALL RATIO", "value": 1.2},
                {"name": "EQUITY PUT/CALL RATIO", "value": 0.8},
            ]}

    def get(url, **_kwargs):
        calls.append(url)
        response = Response()
        if url.endswith(("equitypc.csv", "totalpc.csv")):
            response.text = "DATE,CALLS,PUTS,TOTAL,P/C RATIO\n10/01/2026,1,1,2,0.8\n"
        return response

    monkeypatch.setattr(signals, "_get", get)
    assert {row[0] for row in signals.src_squeezemetrics(None, "incremental")} == (
        {"dix", "gex"} if enabled else {"dix"})
    expected = {"pc_equity", "pc_total"} if enabled else {"pc_equity"}
    assert {row[0] for row in signals._pc_era1()} == expected
    assert {row[0] for row in signals._pc_era2_day(date(2026, 10, 1))} == expected
    assert any(url.endswith("totalpc.csv") for url in calls) is enabled


def test_breadth_unregisters_temporary_universe_when_calculation_fails(con, monkeypatch):
    con.execute(
        "CREATE TABLE universe_snapshot "
        "(snapshot_date DATE, ticker VARCHAR, liquid BOOLEAN)"
    )
    con.execute(
        "INSERT INTO universe_snapshot VALUES (DATE '2026-09-11', 'SPY', TRUE)"
    )
    con.execute(
        "INSERT INTO prices "
        "(ticker, date, open, high, low, close, volume) "
        "VALUES ('SPY', DATE '2026-09-11', 100, 101, 99, 100, 1000000)"
    )
    monkeypatch.setattr(
        signals,
        "_breadth_chunk",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("injected breadth failure")),
    )

    with pytest.raises(RuntimeError, match="injected breadth failure"):
        signals.src_breadth(con, "incremental")

    assert "_sig_universe" not in {
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }


@pytest.mark.parametrize("enabled", [True, False])
def test_aaii_and_finra_shared_fields_follow_collection_flag(monkeypatch, enabled):
    from types import SimpleNamespace

    import openpyxl
    import xlrd

    monkeypatch.setattr(signals, "UNREAD_MACRO_COLLECTION_ENABLED", enabled)
    monkeypatch.setattr(signals, "_get", lambda *_args: SimpleNamespace(content=b"fixture"))
    monkeypatch.setattr(signals, "_expect_spreadsheet", lambda body, *_args: body)
    sheet = SimpleNamespace(nrows=1, row_values=lambda _i: [46000.0, 0.35, 0.3, 0.35])
    book = SimpleNamespace(datemode=0, sheet_names=lambda: ["SENTIMENT"],
                           sheet_by_name=lambda _name: sheet)
    monkeypatch.setattr(xlrd, "open_workbook", lambda **_kw: book)
    aaii = {row[0] for row in signals.src_aaii(None, "incremental")}
    assert aaii == ({"aaii_bull", "aaii_bear"} if enabled else {"aaii_bear"})
    sheet = SimpleNamespace(iter_rows=lambda **_kw: iter([("2026-10", 100.0, 30.0, 20.0)]))

    class Workbook:
        sheetnames = ["Sheet1"]

        def __getitem__(self, _name):
            return sheet

        def close(self):
            pass

    monkeypatch.setattr(openpyxl, "load_workbook", lambda *_args, **_kw: Workbook())
    finra = {row[0] for row in signals.src_finra_margin(None, "incremental")}
    assert finra == ({"margin_debt", "free_credit"} if enabled else {"margin_debt"})


def test_enabled_cot_source_collects_retained_context_series(monkeypatch):
    from types import SimpleNamespace

    calls = []

    def get(url):
        calls.append(url)
        return SimpleNamespace(json=lambda: [{"report_date_as_yyyy_mm_dd": "2026-11-10",
            "lev_money_positions_long": "100", "lev_money_positions_short": "40"}])

    monkeypatch.setattr(signals, "_get", get)
    assert signals.SOURCES["cot"](None, "incremental") == [
        ("cot_es_lev_net", date(2026, 11, 10), 60.0)]
    assert len(calls) == 1 and calls[0].endswith("&$limit=10")
