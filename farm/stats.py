"""Statistics for the backtest farm — Sharpe, Deflated Sharpe, drawdown, t-stat.

Dependency-light on purpose: only numpy + the stdlib `statistics.NormalDist`
(scipy is not installed on the box). NormalDist gives us both the standard
normal CDF and its inverse (probit), which is all the Deflated Sharpe machinery
needs.

Formulas (all documented in the report generator too):

  Per-observation Sharpe (rf = 0):   SR = mean / std(ddof=1)
  Annualized Sharpe:                 SR_ann = SR * sqrt(obs_per_year)

  Probabilistic Sharpe Ratio (Bailey & Lopez de Prado 2012):
     PSR(SR*) = Phi[ (SR - SR*) * sqrt(n - 1)
                     / sqrt(1 - g3*SR + ((g4 - 1)/4)*SR^2) ]
     where SR, SR* are per-observation, g3 = skew, g4 = kurtosis (non-excess;
     Gaussian g4 = 3), n = number of observations, Phi = standard normal CDF.

  Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014, "The Deflated Sharpe
  Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-
  Normality"): DSR = PSR(SR0), where SR0 is the deflation benchmark — the
  Sharpe you would EXPECT to see as the maximum across N independent trials of
  a truly zero-skill strategy:

     SR0 = sqrt(V) * [ (1 - gamma) * Phi^{-1}(1 - 1/N)
                       + gamma * Phi^{-1}(1 - 1/(N*e)) ]

     gamma = Euler-Mascheroni ~= 0.5772, N = number of variants tried, and V is
     the variance of the trial Sharpe ratios. We do not have every trial's
     realized SR, so we use the sampling variance of the SR estimator under the
     null (Lo 2002 / Mertens), V = (1 - g3*SR + ((g4 - 1)/4)*SR^2) / (n - 1) —
     i.e. the same denominator that appears inside the PSR, per observation.
     This is a documented, conservative fallback; it is stated as an assumption
     in the report.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from statistics import NormalDist

import numpy as np

_N = NormalDist()  # standard normal
_EULER = 0.5772156649015329


@dataclass
class SeriesStats:
    n: int
    mean: float
    std: float
    t_stat: float
    skew: float
    kurtosis: float          # non-excess (Gaussian = 3.0)
    sharpe_per_trade: float
    sharpe_annual: float
    gross_cagr: float
    net_cagr: float
    ann_mean_gross: float
    ann_mean_net: float
    max_drawdown: float
    trades_per_year: float
    deflated_sharpe: float | None
    sr0_benchmark: float | None
    variants_tried: int | None

    def as_dict(self) -> dict:
        return asdict(self)


def _moments(x: np.ndarray):
    """Population central moments; skew and non-excess kurtosis."""
    m = float(x.mean())
    d = x - m
    m2 = float((d ** 2).mean())
    m3 = float((d ** 3).mean())
    m4 = float((d ** 4).mean())
    if m2 <= 0:
        return m, m2, 0.0, 3.0
    skew = m3 / m2 ** 1.5
    kurt = m4 / m2 ** 2
    return m, m2, skew, kurt


def probabilistic_sharpe(sr: float, sr_star: float, n: int,
                         skew: float, kurt: float) -> float:
    """PSR(sr_star): P(true SR > sr_star), per-observation SR inputs."""
    denom = math.sqrt(max(1e-12, 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr ** 2))
    z = (sr - sr_star) * math.sqrt(max(1, n - 1)) / denom
    return _N.cdf(z)


def expected_max_sharpe(var_sr: float, n_trials: int) -> float:
    """Expected maximum per-observation Sharpe across n_trials zero-skill trials
    (the DSR deflation benchmark SR0). n_trials >= 1; n_trials == 1 -> 0."""
    if n_trials <= 1 or var_sr <= 0:
        return 0.0
    a = _N.inv_cdf(1.0 - 1.0 / n_trials)
    b = _N.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(var_sr) * ((1.0 - _EULER) * a + _EULER * b)


def deflated_sharpe(returns: np.ndarray, n_trials: int) -> tuple[float, float, float]:
    """Return (DSR, SR_per_trade, SR0_benchmark). returns = per-trade returns."""
    n = len(returns)
    if n < 3:
        return float("nan"), float("nan"), float("nan")
    m, m2, skew, kurt = _moments(returns)
    std = float(returns.std(ddof=1))
    if std <= 0:
        return float("nan"), 0.0, 0.0
    sr = m / std
    denom_sq = max(1e-12, 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr ** 2)
    var_sr = denom_sq / (n - 1)          # SR-estimator sampling variance (fallback V)
    sr0 = expected_max_sharpe(var_sr, n_trials)
    dsr = probabilistic_sharpe(sr, sr0, n, skew, kurt)
    return dsr, sr, sr0


def max_drawdown(net_returns: np.ndarray) -> float:
    """Most negative peak-to-trough on the compounded equity curve (<= 0)."""
    if len(net_returns) == 0:
        return 0.0
    equity = np.cumprod(1.0 + net_returns)
    running_max = np.maximum.accumulate(equity)
    dd = equity / running_max - 1.0
    return float(dd.min())


def compute(gross: np.ndarray, net: np.ndarray, years: float,
            variants_tried: int | None) -> SeriesStats:
    """Full stat pack for a partition.

    gross / net: per-trade return arrays (same length, aligned).
    years: calendar span of the partition (first->last trade), for CAGR/annualization.
    variants_tried: N for the Deflated Sharpe haircut (None -> skip DSR).
    """
    n = len(net)
    mean = float(net.mean()) if n else float("nan")
    std = float(net.std(ddof=1)) if n > 1 else float("nan")
    t_stat = (mean / (std / math.sqrt(n))) if (n > 1 and std > 0) else float("nan")
    _, _, skew, kurt = _moments(net) if n >= 3 else (0, 0, float("nan"), float("nan"))

    trades_per_year = (n / years) if years > 0 else float("nan")
    sr_pt = (mean / std) if (n > 1 and std > 0) else float("nan")
    sr_ann = (sr_pt * math.sqrt(trades_per_year)
              if (not math.isnan(sr_pt) and not math.isnan(trades_per_year))
              else float("nan"))

    def cagr(r: np.ndarray) -> float:
        if n == 0 or years <= 0:
            return float("nan")
        equity = float(np.prod(1.0 + r))
        if equity <= 0:
            return -1.0
        return equity ** (1.0 / years) - 1.0

    gross_cagr = cagr(gross)
    net_cagr = cagr(net)
    ann_mean_gross = float(gross.mean()) * trades_per_year if n else float("nan")
    ann_mean_net = mean * trades_per_year if n else float("nan")
    mdd = max_drawdown(net)

    dsr = sr0 = None
    if variants_tried is not None and n >= 3:
        dsr, _, sr0 = deflated_sharpe(net, variants_tried)

    return SeriesStats(
        n=n, mean=mean, std=std, t_stat=t_stat, skew=skew, kurtosis=kurt,
        sharpe_per_trade=sr_pt, sharpe_annual=sr_ann,
        gross_cagr=gross_cagr, net_cagr=net_cagr,
        ann_mean_gross=ann_mean_gross, ann_mean_net=ann_mean_net,
        max_drawdown=mdd, trades_per_year=trades_per_year,
        deflated_sharpe=dsr, sr0_benchmark=sr0, variants_tried=variants_tried,
    )
