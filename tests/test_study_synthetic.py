import pytest

from farm.study.synthetic import (
    GAP_FADE_TRUE_RETURN,
    POWER_SEEDS,
    SIZE_SEEDS,
    cross_sectional_momentum_weights,
    generate_market,
    run_proving_ground,
)


def test_synthetic_market_contains_declared_price_features():
    market = generate_market(7, session_count=80)
    assert set(market.volume_tiers.values()) == {"low", "mid", "high"}
    zero = [bar for bar in market.data.primary.bars
            if bar.ticker == market.zero_delisting_ticker and bar.close == 0]
    assert len(zero) == 1
    gap_bars = [bar for bar in market.data.primary.bars if bar.ticker == market.gap_fade_ticker]
    assert any(bar.open < market.data.primary.get("GAP", gap_bars[index - 1].session).close
               for index, bar in enumerate(gap_bars[1:], 1))
    weights = cross_sectional_momentum_weights(
        market.data.primary, market.data.primary.sessions[-1])
    assert sorted(weights.values()) == [-0.5, 0.5]
    primary = market.data.primary.get("SPY", market.data.primary.sessions[1])
    secondary = market.data.secondary.get("SPY", market.data.primary.sessions[1])
    assert secondary.open / primary.open - 1 == pytest.approx(0.01)


def test_registered_proving_ground_power_size_and_canaries():
    result = run_proving_ground()
    assert result["power"]["seeds"] == len(POWER_SEEDS) == 50
    assert result["power"]["detections"] >= 45
    assert result["power"]["rate"] >= 0.90
    assert result["power"]["truth"] == GAP_FADE_TRUE_RETURN
    assert result["power"]["within_two_se"]
    assert result["size"]["seeds"] == len(SIZE_SEEDS) == 200
    assert result["size"]["inside_band"]
    assert all(canary["passes"] for canary in result["canaries"].values())
    assert result["canaries"]["survivor"]["inflation"] == pytest.approx(0.5)
    cost = result["canaries"]["cost"]
    assert abs(cost["mean_net"] + cost["expected_cost"]) <= cost["se"]
    benchmark = result["canaries"]["benchmark"]
    assert benchmark["excess"] == pytest.approx(benchmark["expected"])
    secondary = result["canaries"]["secondary"]
    assert secondary["open_ratio_mean"] == pytest.approx(secondary["expected"])
    assert secondary["uncovered_trades"] == 1
