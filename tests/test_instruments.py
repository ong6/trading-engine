"""Instrument master and OCC symbology."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from engine.instruments import Instrument, ensure, format_occ, normalise, parse_occ, resolve


def test_occ_example_parses_and_formats_exactly():
    instrument = parse_occ("AAPL  260117C00200000")
    assert instrument.instrument_id == "AAPL260117C00200000"
    assert instrument.underlying == "AAPL"
    assert instrument.expiry == date(2026, 1, 17)
    assert instrument.right == "C"
    assert instrument.strike == 200.0
    assert instrument.multiplier == 100.0
    assert format_occ(instrument) == "AAPL  260117C00200000"


def test_occ_round_trip_for_fifty_generated_contracts():
    base = date(2026, 1, 16)
    for index in range(50):
        instrument = Instrument(
            instrument_id="",
            kind="option",
            underlying=f"X{index % 10}",
            multiplier=100,
            expiry=base + timedelta(days=7 * index),
            strike=0.5 + index * 1.125,
            right="C" if index % 2 == 0 else "P",
        )
        symbol = format_occ(instrument)
        parsed = parse_occ(symbol)
        assert format_occ(parsed) == symbol
        assert normalise(symbol) == parsed.instrument_id


def test_master_ensure_and_resolve_preserve_first_seen(con):
    original = Instrument(
        "SPY", "etf", 1.0, source="seed", first_seen=date(2026, 1, 2),
        last_seen=date(2026, 1, 2),
    )
    ensure(con, original)
    ensure(con, Instrument(
        "SPY", "etf", 1.0, source="refresh", first_seen=date(2026, 2, 2),
        last_seen=date(2026, 2, 2),
    ))
    found = resolve("SPY", con=con)
    assert found.kind == "etf" and found.multiplier == 1
    assert found.first_seen == date(2026, 1, 2)
    assert found.last_seen == date(2026, 2, 2)
    assert found.source == "refresh"


@pytest.mark.parametrize("symbol", ["", "AAPL260117X00200000", "TOOLONG260117C00200000"])
def test_invalid_occ_symbol_is_refused(symbol):
    with pytest.raises(ValueError):
        parse_occ(symbol)
