from datetime import date

import pytest

from farm.study.data import Bar, MarketData, PriceSource
from farm.study.universe import SURVIVOR_WARNING, ListingInterval, Universe


def _source(bars, survivor_status="point_in_time"):
    return PriceSource.declared(
        source="fixture", bars=bars, point_in_time=True, survivor_status=survivor_status)


def _bar(ticker, day, close, volume=1_000):
    return Bar(ticker, day, close, close, close, close, volume)


def test_listing_intervals_and_trailing_liquidity_are_point_in_time():
    days = [date(2024, 1, day) for day in range(2, 7)]
    bars = [_bar(ticker, day, 10 if ticker == "AAA" else 2, 1_000_000)
            for day in days for ticker in ("AAA", "BBB")]
    source = _source(bars)
    universe = Universe(source, (
        ListingInterval("AAA", days[0]), ListingInterval("BBB", days[0], days[3])))
    view = MarketData(source).view(days[-1], "pre_open", days[-1])
    assert universe.eligible(view, days[-1], min_mdv60=5_000_000, min_price=3) == ["AAA"]
    assert universe.mdv60(view, "AAA", days[-1]) == pytest.approx(10_000_000)
    assert universe.survivor_warning is None


def test_current_listings_only_source_is_always_labelled():
    source = _source([_bar("AAA", date(2024, 1, 2), 10)], "current_listings_only")
    assert Universe(source).survivor_warning == SURVIVOR_WARNING
    assert Universe(source, (ListingInterval("AAA", date(2024, 1, 2)),)).survivor_warning == (
        SURVIVOR_WARNING)


def test_delisting_uses_last_close_including_zero_then_configured_fallback():
    start, end = date(2024, 1, 2), date(2024, 1, 4)
    priced = _source([_bar("ZERO", start, 5), _bar("ZERO", end, 0)])
    outcome = Universe(priced, (ListingInterval("ZERO", start, end),)).delisting_exit(
        "ZERO", held_on=start, entry_price=5)
    assert outcome.exit_price == 0 and not outcome.used_fallback

    missing = _source([_bar("MISS", date(2024, 1, 1), 10)])
    fallback = Universe(
        missing, (ListingInterval("MISS", start, end),), delisting_return=-0.4
    ).delisting_exit("MISS", held_on=start, entry_price=10)
    assert fallback.exit_price == pytest.approx(6)
    assert fallback.used_fallback and fallback.applied_return == -0.4
