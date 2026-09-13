"""Nasdaq symbol-directory parsing and security-class boundaries."""

from datetime import date

import pytest

from engine import universe
from engine.lib import db

HEADER = (
    "Nasdaq Traded|Symbol|Security Name|Listing Exchange|Market Category|ETF|"
    "Round Lot Size|Test Issue|Financial Status|CQS Symbol|NASDAQ Symbol|NextShares"
)


def _directory(*rows: str) -> str:
    return "\n".join((HEADER, *rows, "File Creation Time: 0911202618:02|||||"))


def _row(symbol: str, name: str, *, etf: str = "N", test: str = "N", nextshares: str = "N"):
    return f"Y|{symbol}|{name}|Q|Q|{etf}|100|{test}|N||{symbol}|{nextshares}"


def test_parse_keeps_common_equity_and_etfs_but_rejects_non_common_classes():
    text = _directory(
        _row("PLAIN", "Plain Company Common Stock"),
        _row("ADR", "Issuer American Depositary Shares"),
        _row("UNITED", "United Example, Inc. Common Stock"),
        _row("TRUST", "Example Trust Units", etf="Y"),
        _row("PFBK", "Preferred Bank - Common Stock"),
        _row("SPACU", "Example Acquisition Corp. - Units"),
        _row("ACQ.U", "Example Acquisition Corp. - Unit"),
        _row("CORPU", "Example Utility Corporate Units"),
        _row("LP", "Example Partners L.P. Common Units"),
        _row("RIGHTR", "Example Acquisition Corp. - Rights"),
        _row("ODDWZ", "Example Corporation - Warrants"),
        _row("PREFP", "Example 7% Series A Preferred Stock"),
        _row("PREF$A", "Example Series A Preference Shares"),
        _row("TEST", "Test Common Stock", test="Y"),
        _row("NEXT", "NextShares Fund", nextshares="Y"),
    )

    parsed = universe.parse(text)

    assert parsed.attrs["total"] == 15
    assert parsed[["ticker", "yf_ticker", "etf"]].to_dict("records") == [
        {"ticker": "PLAIN", "yf_ticker": "PLAIN", "etf": False},
        {"ticker": "ADR", "yf_ticker": "ADR", "etf": False},
        {"ticker": "UNITED", "yf_ticker": "UNITED", "etf": False},
        {"ticker": "TRUST", "yf_ticker": "TRUST", "etf": True},
        {"ticker": "PFBK", "yf_ticker": "PFBK", "etf": False},
        {"ticker": "LP", "yf_ticker": "LP", "etf": False},
    ]


def test_parse_rejects_singular_and_plural_non_common_labels_case_insensitively():
    text = _directory(
        _row("U1U", "Acquisition Unit"),
        _row("U2.U", "Acquisition UNITS"),
        _row("R1", "Subscription Right"),
        _row("R2", "Subscription RIGHTS"),
        _row("W1", "Purchase Warrant"),
        _row("W2", "Purchase WARRANTS"),
        _row("P1", "Preferred Share"),
        _row("P2", "Preference Shares"),
        _row("P3", "Preferred Series B"),
        _row("P4", "Preference Units"),
    )

    assert universe.parse(text).empty


def test_sync_deactivates_without_deleting_and_preserves_existing_state(con):
    db.init_schema(con)
    con.execute(
        """
        INSERT INTO universe
            (ticker, yf_ticker, name, exchange, etf, member, added,
             active, liquid, backfill_done)
        VALUES
            ('KEEP', 'KEEP-OLD', 'Old name', 'N', FALSE, 'SP500',
             DATE '2026-01-02', FALSE, TRUE, TRUE),
            ('OLDW', 'OLDW', 'Old warrant', 'Q', FALSE, NULL,
             DATE '2026-01-03', TRUE, TRUE, TRUE)
        """
    )
    parsed = universe.parse(
        _directory(
            _row("KEEP", "Updated Common Stock"),
            _row("NEW", "New Common Stock"),
            _row("OLDW", "Old Corporation - Warrants"),
        )
    )

    assert universe.sync_universe(con, parsed) == (1, 1)
    assert con.execute(
        """
        SELECT ticker, yf_ticker, name, exchange, etf, member, added,
               active, liquid, backfill_done
        FROM universe ORDER BY ticker
        """
    ).fetchall() == [
        (
            "KEEP",
            "KEEP",
            "Updated Common Stock",
            "Q",
            False,
            "SP500",
            date(2026, 1, 2),
            True,
            True,
            True,
        ),
        (
            "NEW",
            "NEW",
            "New Common Stock",
            "Q",
            False,
            None,
            universe.datetime.now(universe.timezone.utc).date(),
            True,
            False,
            False,
        ),
        (
            "OLDW",
            "OLDW",
            "Old warrant",
            "Q",
            False,
            None,
            date(2026, 1, 3),
            False,
            True,
            True,
        ),
    ]

    assert universe.append_snapshot(con) is True
    assert universe.append_snapshot(con) is False
    assert con.execute(
        "SELECT ticker, active, liquid FROM universe_snapshot ORDER BY ticker"
    ).fetchall() == [
        ("KEEP", True, True),
        ("NEW", True, False),
        ("OLDW", False, True),
    ]


def test_reconcile_rolls_back_every_database_change_when_snapshot_fails(con, monkeypatch):
    db.init_schema(con)
    con.execute(
        """
        INSERT INTO universe
            (ticker, yf_ticker, name, exchange, etf, member, added,
             active, liquid, backfill_done)
        VALUES ('OLD', 'OLD', 'Old common stock', 'N', FALSE, NULL,
                DATE '2026-01-03', TRUE, TRUE, TRUE)
        """
    )
    parsed = universe.parse(_directory(_row("NEW", "New Common Stock")))
    monkeypatch.setattr(
        universe,
        "append_snapshot",
        lambda _con: (_ for _ in ()).throw(RuntimeError("snapshot failed")),
    )

    with pytest.raises(RuntimeError, match="snapshot failed"):
        universe.reconcile_universe(con, parsed)

    assert con.execute(
        "SELECT ticker, active, liquid, backfill_done FROM universe ORDER BY ticker"
    ).fetchall() == [("OLD", True, True, True)]


def test_sync_unregisters_temporary_relation_when_a_statement_fails(con):
    db.init_schema(con)
    parsed = universe.parse(
        _directory(
            _row("DUP", "Duplicate Common Stock"),
            _row("DUP", "Duplicate Common Stock"),
        )
    )

    with pytest.raises(Exception, match="duplicate key|PRIMARY KEY"):
        universe.sync_universe(con, parsed)

    assert "_incoming_univ" not in {
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }


def test_write_csv_publishes_current_universe_atomically(con, tmp_path, monkeypatch):
    db.init_schema(con)
    con.execute(
        """
        INSERT INTO universe (ticker, yf_ticker, name, exchange, etf, active, liquid)
        VALUES ('BRK.A', 'BRK-A', 'Berkshire Hathaway Common Stock', 'N', FALSE, TRUE, TRUE)
        """
    )
    monkeypatch.setattr(universe, "DATA_DIR", tmp_path)
    atomic_writes = []
    real_atomic_write = universe.resources.write_text_atomic

    def recording_atomic_write(path, text):
        atomic_writes.append((path, text))
        real_atomic_write(path, text)

    monkeypatch.setattr(universe.resources, "write_text_atomic", recording_atomic_write)

    path = universe.write_csv(con)

    assert path == tmp_path / "universe.csv"
    assert path.read_text() == (
        "ticker,yf_ticker,name,exchange,etf,active,liquid\n"
        "BRK.A,BRK-A,Berkshire Hathaway Common Stock,N,False,True,True\n"
    )
    assert atomic_writes == [(path, path.read_text())]
    assert list(tmp_path.glob("universe.csv.*.tmp")) == []


def test_cache_raw_publishes_atomically(tmp_path, monkeypatch):
    monkeypatch.setattr(universe, "STORE_DIR", tmp_path)
    calls = []
    real_atomic_write = universe.resources.write_text_atomic

    def recording_atomic_write(path, text):
        calls.append((path, text))
        real_atomic_write(path, text)

    monkeypatch.setattr(universe.resources, "write_text_atomic", recording_atomic_write)

    path = universe.cache_raw("complete directory\n")

    assert path.read_text() == "complete directory\n"
    assert calls == [(path, "complete directory\n")]
    assert list(tmp_path.glob("nasdaqtraded-*.txt.*.tmp")) == []
