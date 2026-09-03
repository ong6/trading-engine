"""Inference statistics on per-trade RETURN series — Sharpe, Deflated Sharpe, t-stat, bootstrap CI.

(Was farm/stats.py until 2026-09-03; equity-curve stats live in farm.stats.equity.)

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
from dataclasses import asdict, dataclass
from statistics import NormalDist

import numpy as np

from farm.stats.equity import max_drawdown

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


def deflated_sharpe(returns: np.ndarray, n_trials: int,
                    var_sr: float | None = None) -> tuple[float, float, float]:
    """Return (DSR, SR_per_trade, SR0_benchmark). returns = per-trade returns.

    `var_sr` is V in the SR0 formula: the VARIANCE OF THE TRIAL SHARPES. Bailey
    & Lopez de Prado want the observed dispersion of SR across the N variants
    actually tried; the module docstring's fallback (the sampling variance of
    the SR estimator under the null) exists only because the historical-backtest
    caller does not have the other trials to hand. A PARAMETER SWEEP DOES — every
    cell of the grid is a trial and its fold returns are on disk — so the sweep
    passes the real cross-trial variance here rather than the fallback, and the
    report says which of the two it used. Leaving `var_sr=None` reproduces the
    previous behaviour exactly, so `compute()` and the backtest farm are
    untouched by this seam.
    """
    n = len(returns)
    if n < 3:
        return float("nan"), float("nan"), float("nan")
    m, m2, skew, kurt = _moments(returns)
    std = float(returns.std(ddof=1))
    if std <= 0:
        return float("nan"), 0.0, 0.0
    sr = m / std
    denom_sq = max(1e-12, 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr ** 2)
    if var_sr is None:
        var_sr = denom_sq / (n - 1)      # SR-estimator sampling variance (fallback V)
    sr0 = expected_max_sharpe(var_sr, n_trials)
    dsr = probabilistic_sharpe(sr, sr0, n, skew, kurt)
    return dsr, sr, sr0


def max_drawdown_from_returns(net_returns: np.ndarray) -> float:
    """Most negative peak-to-trough on the compounded equity curve (<= 0).

    Thin wrapper: compounds the per-trade returns into an equity curve and
    delegates to the one drawdown definition in `farm.stats.equity`.
    """
    if len(net_returns) == 0:
        return 0.0
    return max_drawdown(np.cumprod(1.0 + np.asarray(net_returns, dtype=float)))


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
    mdd = max_drawdown_from_returns(net)

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


# --------------------------------------------------------------------------- #
# Bootstrap confidence intervals — the error bar every sweep row was missing
# --------------------------------------------------------------------------- #
# WHY THIS EXISTS. Until 2026-08-20 every sweep and walk-forward number in this
# store was a point estimate quoted without an error bar, and a table of point
# estimates reads as a ranking whether or not the ordering means anything. Four
# grids, 30 genuine trials, 10 folds each, and the best median excess anywhere
# was +0.02% — a number that cannot possibly be distinguished from zero at n=10
# but which the report presented in bold at the top of a sorted table. The
# ranking was not wrong; the report was silent about how much of it was noise.
#
# WHY THE BOOTSTRAP AND NOT A t-TEST. Fold excess returns are neither normal nor
# symmetric (the momentum family's whole excess lives in one 2018-2021 window,
# which is exactly why this house ranks by MEDIAN), and there is no sampling
# distribution for a median that a closed form gives us at n=10. Resampling
# makes no distributional assumption and gives the interval for whatever
# statistic the report actually ranks on. It does NOT manufacture precision: at
# n=10 the interval it returns is very wide, and that width IS the finding.
#
# WHY FOLDS ARE THE RESAMPLING UNIT. The fold is the unit of evidence in this
# protocol: each fold is an independent replay from the reference notional
# (D-WF2) over a validate window that no other fold's validate window touches
# (D-WF1: step == validate length ⇒ disjoint validate windows). So resampling
# folds with replacement is resampling the out-of-sample measurements.
#
#   CAVEAT, and it is a real one: the folds are NOT fully independent. TRAIN is
#   24 months and the step is 12, so adjacent folds share twelve months of train
#   window, and every fold is drawn from one market history rather than from ten
#   parallel universes. An i.i.d. bootstrap over overlapping-train folds
#   therefore UNDERSTATES the true uncertainty. The interval below is a floor on
#   the error bar, not a full accounting of it — which only strengthens an
#   INDISTINGUISHABLE verdict and weakens a distinguishable one. Every report
#   that prints these intervals prints this caveat too.
#
# WHY A FIXED SEED. A report that changes its own numbers when re-rendered from
# unchanged inputs is not a record. The seed is a constant here and is printed
# in every report that quotes an interval, so any row can be reproduced exactly.
# Seeding a fresh generator per call also means two candidates with the same
# fold count get the SAME resample index draws, so their intervals are paired
# and comparable rather than independently jittered.
BOOTSTRAP_SEED = 20260820          # printed in every report; do not drift it
BOOTSTRAP_DRAWS = 10_000           # enough to pin a 5th/95th percentile at n=10
BOOTSTRAP_CONF = 0.90              # 90%, two-sided ⇒ 5th and 95th percentiles
# Below three observations a percentile bootstrap is resampling a point, not a
# distribution. Such a row gets NO interval and says so — never a zero-filled or
# invented one (house rule: missing input means the row is absent or labelled).
MIN_BOOTSTRAP_N = 3


def bootstrap_ci(sample, *, stat: str = "median", conf: float = BOOTSTRAP_CONF,
                 n_boot: int = BOOTSTRAP_DRAWS,
                 seed: int = BOOTSTRAP_SEED) -> dict | None:
    """Percentile bootstrap interval for the median (or mean) of `sample`.

    `sample` is the per-fold statistic — fold excess vs the benchmark, one entry
    per fold that produced a real, comparable measurement. Folds with a status
    other than "ok" (notably the "inert" status added 2026-08-20 for a book that
    placed zero fills) must be filtered out BEFORE calling: an inert fold is not
    evidence and must not be resampled as if it were.

    Returns None when there is too little sample to interval honestly, so a
    caller can print an explicit "no interval" rather than a fabricated one.
    """
    xs = [float(v) for v in sample
          if v is not None and isinstance(v, (int, float)) and v == v]
    n = len(xs)
    if n < MIN_BOOTSTRAP_N:
        return None
    if stat not in ("median", "mean"):
        raise ValueError(f"bootstrap_ci: unsupported statistic {stat!r}")

    a = np.asarray(xs, dtype=float)
    rng = np.random.default_rng(seed)
    # (n_boot, n) matrix of resample INDICES, so the draw pattern depends only
    # on (seed, n_boot, n) — that is what makes two same-length candidates'
    # intervals paired rather than independently noisy.
    idx = rng.integers(0, n, size=(n_boot, n))
    fn = np.median if stat == "median" else np.mean
    boot = fn(a[idx], axis=1)

    alpha = 1.0 - conf
    lo, hi = (float(x) for x in np.quantile(boot, [alpha / 2.0, 1.0 - alpha / 2.0]))
    point = float(fn(a))
    return {
        "stat": stat,
        "n": n,
        "point": point,
        "lo": lo,
        "hi": hi,
        "conf": conf,
        "n_boot": n_boot,
        "seed": seed,
        # The pre-registered decision this whole module exists to support: an
        # interval straddling zero means the sign of the point estimate is not
        # established by this evidence, wherever the row sits in the ranking.
        "contains_zero": bool(lo <= 0.0 <= hi),
    }


def ci_verdict(ci: dict | None) -> str:
    """Mechanical, pre-registered label for one interval. No discretion."""
    if ci is None:
        return "NO-CI"
    if ci["contains_zero"]:
        return "INDISTINGUISHABLE"
    return "distinguishable +" if ci["lo"] > 0 else "distinguishable −"
