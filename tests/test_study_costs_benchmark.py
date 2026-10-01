from datetime import date

import numpy as np
import pytest

from farm.study.benchmark import Benchmark, compare, gross_returns
from farm.study.costs import PROFILES, CostSelection, calculate
from farm.study.data import Bar, MarketData, PriceSource
from farm.study.universe import ListingInterval, Universe


def test_ibkr_tiered_terms_are_exact_per_side():
    buy = calculate("ibkr_tiered_auction_v1", side="buy", notional=10_000, fill_price=100)
    assert buy.shares == 100
    assert buy.commission == pytest.approx(0.35)
    assert buy.pass_through == pytest.approx(0.20)
    assert buy.auction_allowance == pytest.approx(2.00)
    assert buy.total == pytest.approx(2.55)
    sell = calculate("ibkr_tiered_auction_v1", side="sell", notional=10_000, fill_price=100)
    assert sell.sec == pytest.approx(0.028)
    assert sell.taf == pytest.approx(0.0166)
    assert sell.total == pytest.approx(2.5946)


def test_ibkr_fixed_has_no_cap_or_pass_through_and_fractional_shares():
    buy = calculate("ibkr_fixed_v1", side="buy", notional=1_000, fill_price=300)
    assert buy.shares == pytest.approx(10 / 3)
    assert buy.commission == 1 and buy.pass_through == 0
    assert buy.total == pytest.approx(1.20)
    large = calculate("ibkr_fixed_v1", side="sell", notional=2_000_000, fill_price=1)
    assert large.commission == 10_000  # no one-percent cap
    assert large.taf == 332  # deliberately uncapped


def test_binance_tiers_taker_and_supplied_funding_are_exact():
    liquid = calculate(
        "binance_spot_base_v1", side="buy", notional=10_000, fill_price=100,
        mdv60=50_000_000)
    middle = calculate(
        "binance_spot_base_v1", side="sell", notional=10_000, fill_price=100,
        mdv60=5_000_000)
    assert (liquid.taker, liquid.slippage, liquid.total) == pytest.approx((10, 5, 15))
    assert (middle.taker, middle.slippage, middle.total) == pytest.approx((10, 15, 25))
    perp = calculate(
        "binance_perp_base_v1", side="buy", notional=10_000, fill_price=100,
        mdv60=50_000_000, funding_rate=0.0002)
    assert (perp.taker, perp.slippage, perp.funding, perp.total) == pytest.approx((5, 5, 2, 12))
    with pytest.raises(ValueError, match="MDV60"):
        calculate("binance_spot_base_v1", side="buy", notional=1_000,
                  fill_price=10, mdv60=4_999_999)


def test_profile_hashes_and_harsher_run_validation_are_stable():
    expected = {
        "ibkr_tiered_auction_v1": "be60ad69ae19cc9f1e2bcd5a1c91ee312c4a690260f1678e8def45991e72337e",
        "ibkr_fixed_v1": "27847c6ff385795ee127240a8aa3546d2142ecdfa92b2e8f5431edc92097d831",
        "binance_spot_base_v1": "3b4e6ec022fc2dac7aec95e31b061e55f0bfb44029acac752791c2922180455f",
        "binance_perp_base_v1": "ef1bf48aae29e9ff8881c7421d1499bd312a30d11c10b6061e3934fdb679b8af",
    }
    assert {name: profile.sha256 for name, profile in PROFILES.items()} == expected
    selection = CostSelection("binance_perp_base_v1", ("binance_spot_base_v1",))
    selection.require_harsher({"binance_perp_base_v1": 10, "binance_spot_base_v1": 15})
    with pytest.raises(ValueError, match="cost more"):
        selection.require_harsher({"binance_perp_base_v1": 10, "binance_spot_base_v1": 9})


def _market():
    warmup, d0, d1 = date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)
    bars = [
        Bar("AAA", warmup, 100, 100, 100, 100, 1_000_000),
        Bar("BBB", warmup, 50, 50, 50, 50, 1_000_000),
        Bar("AAA", d0, 100, 100, 100, 100, 1_000_000),
        Bar("BBB", d0, 50, 50, 50, 50, 1_000_000),
        Bar("AAA", d1, 110, 110, 110, 110, 1_000_000),
        Bar("BBB", d1, 45, 45, 45, 45, 1_000_000),
    ]
    source = PriceSource.declared(source="fixture", bars=bars)
    universe = Universe(
        source, (ListingInterval("AAA", warmup), ListingInterval("BBB", warmup)))
    return MarketData(source), universe, [d0, d1]


def test_benchmark_kinds_are_gross_and_equal_weighted():
    data, universe, sessions = _market()
    assert gross_returns(Benchmark("cash"), data, sessions).tolist() == [0]
    assert gross_returns(Benchmark("ticker", "AAA"), data, sessions) == pytest.approx([0.1])
    equal = gross_returns(Benchmark("equal_weight"), data, sessions, universe=universe)
    assert equal == pytest.approx([0])  # mean(+10%, -10%)


def test_strategy_pays_its_cost_but_gross_benchmark_does_not():
    gross = np.array([0.10])
    result = compare(np.array([0.09]), gross, Benchmark("ticker", "AAA"))
    assert result.excess_return == pytest.approx(-0.01)
    assert result.absolute_net_positive
    allocation = compare(
        np.array([0.09]), gross, Benchmark("ticker", "AAA", mode="allocation"),
        allocation_cost_returns=np.array([0.01]))
    assert allocation.excess_return == pytest.approx(0)
    with pytest.raises(ValueError, match="cannot pay"):
        compare(np.array([0.09]), gross, Benchmark("ticker", "AAA"),
                allocation_cost_returns=np.array([0.01]))
