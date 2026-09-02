"""farm/stats.py and farm/backtest/stats.py against hand-computed values."""
import math
from datetime import date

import numpy as np
import pytest

from farm import stats as fs
from farm.backtest import stats as bs


# ------------------------------------------------------- farm/stats.py ----- #
def test_max_drawdown_hand_series():
    # equity: 1.10, 0.88, 0.968, 1.0164 ; peak 1.10 ; trough 0.88 -> -20%
    assert fs.max_drawdown(np.array([0.10, -0.20, 0.10, 0.05])) == pytest.approx(-0.20)


def test_max_drawdown_monotone_and_empty():
    assert fs.max_drawdown(np.array([0.01, 0.02, 0.03])) == 0.0
    assert fs.max_drawdown(np.array([])) == 0.0


def test_compute_hand_series():
    # net = [.10, -.05, .02, .03]: mean .025; deviations .075,-.075,-.005,.005
    # sum sq = .01130 ; /3 -> .0037667 ; std = .0613732 ; SR = .4073441
    net = np.array([0.10, -0.05, 0.02, 0.03])
    s = fs.compute(net, net, years=2.0, variants_tried=None)
    assert s.n == 4
    assert s.mean == pytest.approx(0.025)
    assert s.std == pytest.approx(0.0613732, rel=1e-6)
    assert s.sharpe_per_trade == pytest.approx(0.4073441, rel=1e-6)
    assert s.trades_per_year == 2.0
    assert s.sharpe_annual == pytest.approx(0.4073441 * math.sqrt(2.0), rel=1e-6)
    assert s.t_stat == pytest.approx(0.025 / (0.0613732 / 2.0), rel=1e-6)
    # prod(1+r) = 1.1*.95*1.02*1.03 = 1.097877 ; CAGR over 2y = sqrt(.) - 1
    assert s.net_cagr == pytest.approx(1.097877 ** 0.5 - 1, rel=1e-6)
    assert s.ann_mean_net == pytest.approx(0.05)
    assert s.max_drawdown == pytest.approx(-0.05)
    assert s.deflated_sharpe is None and s.sr0_benchmark is None


def test_compute_degenerate_inputs():
    s = fs.compute(np.array([]), np.array([]), years=1.0, variants_tried=None)
    assert s.n == 0 and math.isnan(s.mean) and s.max_drawdown == 0.0
    one = np.array([0.1])
    s1 = fs.compute(one, one, years=1.0, variants_tried=None)
    assert math.isnan(s1.std) and math.isnan(s1.sharpe_per_trade)


def test_probabilistic_sharpe_at_benchmark_is_half():
    assert fs.probabilistic_sharpe(0.2, 0.2, 50, 0.0, 3.0) == pytest.approx(0.5)
    assert fs.probabilistic_sharpe(0.5, 0.0, 50, 0.0, 3.0) > 0.99
    assert fs.probabilistic_sharpe(-0.5, 0.0, 50, 0.0, 3.0) < 0.01


def test_expected_max_sharpe_grows_with_trials():
    assert fs.expected_max_sharpe(1.0, 1) == 0.0
    assert fs.expected_max_sharpe(0.0, 10) == 0.0
    a, b = fs.expected_max_sharpe(1.0, 10), fs.expected_max_sharpe(1.0, 100)
    assert 0 < a < b
    # closed form: (1-g)*z(0.9) + g*z(1-1/(10e))
    from statistics import NormalDist
    z = NormalDist().inv_cdf
    g = 0.5772156649015329
    assert a == pytest.approx((1 - g) * z(0.9) + g * z(1 - 1 / (10 * math.e)))


def test_deflated_sharpe_edges():
    assert all(math.isnan(v) for v in fs.deflated_sharpe(np.array([0.1, 0.2]), 5))
    dsr, sr, sr0 = fs.deflated_sharpe(np.array([0.1, 0.1, 0.1, 0.1]), 5)
    assert math.isnan(dsr) and sr == 0.0 and sr0 == 0.0


def test_deflated_sharpe_more_trials_deflate_more():
    rng = np.random.default_rng(0)
    r = rng.normal(0.01, 0.02, 60)
    d1, sr, s0_1 = fs.deflated_sharpe(r, 1)
    d50, _, s0_50 = fs.deflated_sharpe(r, 50)
    assert s0_1 == 0.0 and s0_50 > 0
    assert d50 < d1


def test_bootstrap_ci_known_series():
    ci = fs.bootstrap_ci([1, 2, 3, 4, 5])
    assert ci["n"] == 5 and ci["point"] == 3.0
    assert ci["lo"] == 1.0 and ci["hi"] == 5.0     # deterministic under the fixed seed
    assert ci["contains_zero"] is False
    assert fs.ci_verdict(ci) == "distinguishable +"


def test_bootstrap_ci_straddles_zero():
    ci = fs.bootstrap_ci([-1, 0.5, -0.2, 0.3, 0.1])
    assert ci["point"] == pytest.approx(0.1)
    assert ci["lo"] <= 0.0 <= ci["hi"] and ci["contains_zero"]
    assert fs.ci_verdict(ci) == "INDISTINGUISHABLE"
    neg = fs.bootstrap_ci([-3, -2, -1, -4, -5])
    assert fs.ci_verdict(neg) == "distinguishable −"


def test_bootstrap_ci_constant_sample_is_a_point():
    ci = fs.bootstrap_ci([0.02] * 6, stat="mean")
    assert ci["lo"] == ci["hi"] == ci["point"] == pytest.approx(0.02)


def test_bootstrap_ci_refuses_small_or_dirty_samples():
    assert fs.bootstrap_ci([1, 2]) is None
    assert fs.bootstrap_ci([1, None, float("nan"), 2]) is None   # only 2 real values
    assert fs.ci_verdict(None) == "NO-CI"
    with pytest.raises(ValueError):
        fs.bootstrap_ci([1, 2, 3], stat="max")


def test_bootstrap_ci_is_reproducible():
    a = fs.bootstrap_ci([0.3, -0.1, 0.2, 0.05, 0.4, -0.2])
    b = fs.bootstrap_ci([0.3, -0.1, 0.2, 0.05, 0.4, -0.2])
    assert a == b and a["seed"] == fs.BOOTSTRAP_SEED


# -------------------------------------------------- farm/backtest/stats ---- #
def test_backtest_max_drawdown_on_equity():
    eq = np.array([100.0, 120.0, 90.0, 110.0, 80.0])
    assert bs.max_drawdown(eq) == pytest.approx(-1 / 3)        # 80/120 - 1
    assert bs.max_drawdown(np.array([])) == 0.0


def test_backtest_sharpe_hand_series():
    # r = [.1, -.1, .1]: mean 1/30 ; std(ddof=1) = sqrt(.026667/2) = .11547
    r = np.array([0.1, -0.1, 0.1])
    assert bs._sharpe(r) == pytest.approx((1 / 30) / 0.1154700538 * math.sqrt(252), rel=1e-6)
    assert math.isnan(bs._sharpe(np.array([0.1])))
    assert math.isnan(bs._sharpe(np.array([0.1, 0.1])))        # zero vol


def test_worst_month():
    dates = [date(2024, 1, 2), date(2024, 1, 31), date(2024, 2, 15), date(2024, 2, 29),
             date(2024, 3, 28)]
    eq = np.array([100, 110, 105, 99, 108.9])
    # month-ends: Jan 110, Feb 99, Mar 108.9 -> Feb -10%, Mar +10%
    assert bs.worst_month(dates, eq) == pytest.approx(-0.10)
    assert math.isnan(bs.worst_month(dates[:2], eq[:2]))


def test_equity_stats_hand_series():
    dates = [date(2023, 1, 1), date(2023, 7, 2), date(2024, 1, 1)]   # 365 days
    eq = [100.0, 110.0, 121.0]
    out = bs.equity_stats(dates, eq)
    assert out["n_sessions"] == 3
    assert out["total_return"] == pytest.approx(0.21)
    assert out["years"] == pytest.approx(365 / 365.25)
    assert out["cagr"] == pytest.approx(1.21 ** (365.25 / 365) - 1)
    assert out["max_dd"] == 0.0
    assert out["vol_ann"] == pytest.approx(0.0)                      # both r = 10%
    assert out["sharpe_ex_bil"] is None and out["bil_coverage"] == 0.0


def test_equity_stats_too_short_returns_nones():
    out = bs.equity_stats([date(2024, 1, 2)], [100.0])
    assert out["total_return"] is None and out["sharpe"] is None and out["max_dd"] is None


def test_equity_stats_ex_bil_needs_half_coverage():
    dates = [date(2024, 1, d) for d in range(2, 8)]
    eq = [100, 101, 103, 102, 104, 105]
    bil_full = {d: 0.0002 for d in dates[1:]}
    out = bs.equity_stats(dates, eq, bil_full)
    assert out["bil_coverage"] == 1.0 and out["sharpe_ex_bil"] is not None
    assert out["sharpe_ex_bil"] < out["sharpe"]
    bil_thin = {dates[1]: 0.0002}
    thin = bs.equity_stats(dates, eq, bil_thin)
    assert thin["bil_coverage"] == pytest.approx(0.2) and thin["sharpe_ex_bil"] is None
