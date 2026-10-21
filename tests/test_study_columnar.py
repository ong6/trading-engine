from datetime import date, timedelta

import duckdb
import numpy as np
import pytest

from farm.study.data import Bar, DataDeclaration, PriceSource
from farm.study_columnar import panel_digest, price_source_from_columns, price_source_from_duckdb

DECLARATION = DataDeclaration("columnar-test", "a" * 64, True, "unknown",
                              daily_bar_lag=timedelta(minutes=5))


def _rows():
    rng = np.random.default_rng(7)
    rows = []
    for day in range(40):
        session = date(2024, 1, 1) + timedelta(days=day)
        for ticker in ("MSFT", "AAPL", "Z", "BRK.B"):
            if rng.random() < 0.2:
                continue
            values = [float(v) for v in rng.uniform(1, 100, 4)]
            volume = int(rng.integers(0, 10**12))
            if rng.random() < 0.1:
                values[1] = None
            if rng.random() < 0.1:
                volume = None
            rows.append((ticker, session, *values, volume))
    rng.shuffle(rows)
    return rows


def _store(tmp_path, rows):
    path = tmp_path / "prices.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE prices (ticker VARCHAR NOT NULL, date DATE NOT NULL, open DOUBLE, "
                "high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT, source VARCHAR)")
    con.executemany("INSERT INTO prices VALUES (?, ?, ?, ?, ?, ?, ?, 'x')", rows)
    con.close()
    return path


def test_columns_build_the_same_panel_as_bar_objects():
    rows = _rows()
    legacy = PriceSource(DECLARATION, (Bar(*row) for row in rows))
    columns = {name: [row[index] for row in rows]
               for index, name in enumerate(("open", "high", "low", "close", "volume"), 2)}
    fast = price_source_from_columns(DECLARATION, [row[0] for row in rows],
                                     [row[1] for row in rows], columns)
    assert panel_digest(fast) == panel_digest(legacy)
    assert list(fast.bars) == list(legacy.bars)
    assert fast.history("AAPL", ("close", "high"), before=date(2024, 2, 1),
                        through=date(2024, 2, 1), limit=10) == legacy.history(
        "AAPL", ("close", "high"), before=date(2024, 2, 1), through=date(2024, 2, 1), limit=10)


@pytest.mark.parametrize("window", [
    {}, {"start": date(2024, 1, 10), "end": date(2024, 1, 30)},
    {"tickers": ["Z", "AAPL"]}, {"tickers": ["NONE"]},
])
def test_duckdb_builder_matches_from_duckdb(tmp_path, window):
    path = _store(tmp_path, _rows())
    legacy = PriceSource.from_duckdb(path, DECLARATION, **window)
    fast = price_source_from_duckdb(path, DECLARATION, **window)
    assert panel_digest(fast) == panel_digest(legacy)
    for ticker in legacy.tickers:
        assert fast.mdv60(ticker, date(2024, 2, 9)) == legacy.mdv60(ticker, date(2024, 2, 9))
        assert fast.get(ticker, date(2024, 1, 20)) == legacy.get(ticker, date(2024, 1, 20))


def test_columnar_builder_keeps_the_panel_errors():
    day = date(2024, 1, 2)
    with pytest.raises(ValueError, match="duplicate ticker/session bar"):
        price_source_from_columns(DECLARATION, ["A", "A"], [day, day], {"close": [1.0, 2.0]})
    with pytest.raises(ValueError, match="bar ticker is required"):
        price_source_from_columns(DECLARATION, ["A", ""], [day, day], {"close": [1.0, 2.0]})
    with pytest.raises(ValueError, match="sessions must be dates"):
        price_source_from_columns(DECLARATION, ["A"], [object()], {"close": [1.0]})
