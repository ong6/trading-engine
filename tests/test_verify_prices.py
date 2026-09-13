"""Price verification releases its store snapshot before network work."""
from __future__ import annotations

from datetime import date

from engine import verify_prices
from engine.lib import db


def test_held_tickers_include_only_active_portfolios(con):
    con.execute(
        "INSERT INTO portfolios (id, name, active, cash) VALUES "
        "('active', 'active', TRUE, 1000), ('retired', 'retired', FALSE, 1000)"
    )
    con.execute(
        "INSERT INTO sim_positions VALUES "
        "('active', 'LIVE', 2, 10), "
        "('active', 'ZERO', 0, 10), "
        "('retired', 'ARCHIVE', 3, 10), "
        "('retired', 'LIVE', 4, 10)"
    )

    assert verify_prices._held_tickers(con) == ["LIVE"]


def test_connection_narrowed_releases_reader_before_fetch(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    con = db.connect(db_path)
    db.init_schema(con)
    con.execute(
        "INSERT INTO universe (ticker, yf_ticker, etf, active, liquid) "
        "VALUES ('AAA', 'AAA', FALSE, TRUE, TRUE)"
    )
    con.execute(
        "INSERT INTO prices "
        "(ticker, date, open, high, low, close, volume, source, fetched_at) "
        "VALUES ('AAA', '2026-09-08', 10, 11, 9, 10.5, 1000, 'yfinance', now())"
    )
    con.close()

    writer_opened: list[bool] = []

    def fetch_while_writing(ticker, *, assetclass, start, end, session):
        assert (ticker, assetclass, end) == ("AAA", "stocks", date(2026, 9, 8))
        assert start < end
        assert session is not None
        writer = db.connect(db_path, wait_s=0)
        try:
            writer.execute(
                "INSERT INTO universe (ticker, yf_ticker, etf, active, liquid) "
                "VALUES ('BBB', 'BBB', FALSE, TRUE, TRUE)"
            )
            writer_opened.append(True)
        finally:
            writer.close()
        return {
            "symbol": "AAA",
            "bars": {
                date(2026, 9, 8): {
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.5,
                    "volume": 1000,
                }
            },
            "parse_errors": [],
            "rows": 1,
        }

    monkeypatch.setattr(verify_prices, "fetch_nasdaq_history", fetch_while_writing)
    monkeypatch.setattr(verify_prices, "PER_NAME_SLEEP", 0)

    result = verify_prices.run_connection_narrowed(
        {"tickers": "AAA", "sessions": 1},
        db_path=db_path,
        meta_path=tmp_path / "meta.json",
    )

    assert writer_opened == [True]
    assert result["names_checked"] == 1
    assert result["names_agreeing"] == 1
    check = db.connect(db_path, read_only=True)
    try:
        assert check.execute("SELECT COUNT(*) FROM universe").fetchone() == (2,)
    finally:
        check.close()
