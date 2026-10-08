"""Tests for the P3 frozen-archive parser and census decision."""
from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path

import pytest

from engine import free_frozen_archive as frozen

# Fixed entry time: writestr(name, ...) stamps the current time, so two fixtures
# built across a 2-second tick hash differently.
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def _price_file(rows: list[tuple[str, float]]) -> bytes:
    lines = [",".join(frozen.EXPECTED_COLUMNS)]
    lines.extend(f"{day},{close},{close},{close},{close},100,0" for day, close in rows)
    return ("\n".join(lines) + "\n").encode()


def _archive(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in members.items():
            archive.writestr(zipfile.ZipInfo(f"Data/{name}", FIXED_ZIP_TIME), body)
            archive.writestr(name, body)
    digest = frozen._sha256(path)
    target = path.with_name(f"{digest}.zip")
    path.rename(target)
    return target


def test_parse_price_file_preserves_adjusted_values_and_rejects_bad_ohlc():
    body = _price_file([("2017-11-09", 12.5), ("2017-11-10", 13.0)])
    rows = frozen.parse_price_file(body, "Data/Stocks/abc.us.txt")
    assert rows == [
        {"date": date(2017, 11, 9), "o": 12.5, "h": 12.5, "l": 12.5,
         "c": 12.5, "v": 100.0, "open_interest": 0.0, "ohlc_consistent": True},
        {"date": date(2017, 11, 10), "o": 13.0, "h": 13.0, "l": 13.0,
         "c": 13.0, "v": 100.0, "open_interest": 0.0, "ohlc_consistent": True},
    ]

    bad = b"Date,Open,High,Low,Close,Volume,OpenInt\n2017-11-10,2,1,1,2,3,0\n"
    assert frozen.parse_price_file(bad, "Data/Stocks/abc.us.txt")[0]["ohlc_consistent"] is False


def test_census_counts_ended_names_and_flags_reuse(tmp_path: Path):
    archive = _archive(tmp_path / "fixture.zip", {
        "Stocks/old.us.txt": _price_file([
            ("2010-01-04", 1.0), ("2010-03-01", 20.0), ("2017-09-28", 20.0),
        ]),
        "Stocks/live.us.txt": _price_file([
            ("2017-11-09", 5.0), ("2017-11-10", 5.1),
        ]),
        "Stocks/empty.us.txt": b"",
        "ETFs/fund.us.txt": _price_file([
            ("2017-11-09", 10.0), ("2017-11-10", 10.0),
        ]),
    })

    result = frozen.census_archive(archive)

    assert result["canonical_files"] == 4
    assert result["duplicate_files"] == 4
    assert result["empty_files"] == 1
    assert result["ended_count"] == 1
    assert result["ended_share"] == pytest.approx(1 / 3)
    old = next(row for row in result["securities"] if row["ticker"] == "OLD")
    assert old["ended"] is True
    assert old["gap_events"] == 2
    assert old["price_jump_events"] == 1
    assert old["ticker_reuse_flag"] is True


def test_census_rejects_a_nonidentical_duplicate_tree(tmp_path: Path):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(zipfile.ZipInfo("Data/Stocks/abc.us.txt", FIXED_ZIP_TIME), _price_file([("2017-11-10", 1.0)]))
        archive.writestr(zipfile.ZipInfo("Stocks/abc.us.txt", FIXED_ZIP_TIME), _price_file([("2017-11-10", 2.0)]))

    with pytest.raises(frozen.FrozenArchiveError, match="duplicate tree differs"):
        frozen.census_archive(path)


def test_stratified_sample_is_deterministic_and_prefers_sec_rows():
    intervals = [
        {"ticker": ticker, "start_date": date(2010, 1, 4),
         "end_date": date(2012, 1, day), "exchange": "NYSE", "source_row": day}
        for day, ticker in enumerate(("AAA", "BBB", "CCC"), 3)
    ]
    corroborated = {("CCC", date(2010, 1, 4), date(2012, 1, 5))}

    first = frozen.stratified_sample(
        intervals, corroborated, start_year=2012, end_year=2012, per_year=2
    )
    second = frozen.stratified_sample(
        reversed(intervals), corroborated, start_year=2012, end_year=2012, per_year=2
    )

    assert first == second
    assert first[0]["ticker"] == "CCC"


@pytest.mark.parametrize(
    ("coverage", "expected"),
    [(0.299999, "skip"), (0.30, "ingest"), (1.0, "ingest")],
)
def test_recommendation_uses_the_frozen_30_percent_rule(coverage: float, expected: str):
    assert frozen.recommendation(coverage) == expected


def test_known_split_continuity_is_adjusted_like():
    rows = frozen.parse_price_file(
        _price_file([("2014-06-06", 86.494), ("2014-06-09", 87.879)]),
        "Data/Stocks/aapl.us.txt",
    )

    check = frozen._split_check("AAPL", rows)

    assert check is not None
    assert check["raw_expected_post_pre"] == pytest.approx(1 / 7)
    assert check["adjusted_like"] is True
