"""macro_composite — weekly SPY allocation from four pre-registered signal blocks.

A DRAWDOWN REDUCER, NOT AN ALPHA MACHINE. The research
(`../personal-data-store/research/market-regime-signals.md`) found no single
signal that times tops, but a repeatable *sequence* into a cyclical top —
breadth divergence, then credit widening off its lows, then a re-steepening
curve with claims rising off trough — and a better-evidenced bottom pattern
(washout breadth, then a Zweig thrust). This book scores that sequence and
converts it into an SPY weight in {0, 25, 50, 75, 100}%. It is expected to LAG in
strong bull years; it is judged on max drawdown and full-cycle Sharpe.

THRESHOLDS ARE FROZEN — every number below was written into the research note on
2026-07-31, *before* any of it was tested against this store's data, and every
one of them comes from the published literature rather than a fit. They are
pre-registered in the same sense the league's other configs are: if they are ever
changed, this book's forward record starts over. Do not tune them against
observed performance.

POINT-IN-TIME CONTRACT. Every read of `macro_signals` gates on BOTH
`obs_date <= as_of` (the data is about a date we have reached) and
`fetch_as_of <= as_of` (we had actually stored it by then). The second gate is
what makes a backfill honest: rows collected today are invisible to any earlier
as-of, so a historical replay cannot see a number that did not exist yet. The
consequence is deliberate and worth stating plainly — replaying this book over a
window *before* the collector's first run yields all-zero votes and a flat 50%
allocation. That is the gate working, not a bug.

MISSING DATA IS NEVER GUESSED. A series the point-in-time gate cannot supply
makes its block vote 0 and prints one WARN line. The failure mode of a dead
source is therefore "drift toward neutral, loudly", never "hold a stale view
silently".

The only series the book deliberately ignores is `cot_es_lev_net`: the collector
stores it for context, and the research is clear that COT positioning is a weak,
heavily over-fitted timing signal (Sanders-Irwin-Merrin 2009, Kyriacou 2013).
"""
from __future__ import annotations

from datetime import date

import numpy as np

from .base import (
    PortfolioView, Strategy, close_on, rebalance_orders, total_return,
)

# --- FROZEN THRESHOLDS (pre-registered 2026-07-31) -------------------------- #
BREADTH_BULL = 55.0          # % of the liquid universe above its own 200d SMA
BREADTH_BEAR = 35.0
BREADTH_WASHOUT = 15.0
ZWEIG_LOW = 0.40             # 10-session adv/(adv+dec) trough...
ZWEIG_HIGH = 0.615           # ...and the thrust level it must reach
ZWEIG_SPAN = 10              # sessions allowed between trough and thrust
ZWEIG_LOOKBACK = 20          # a thrust still counts this many sessions later

CREDIT_WINDOW = 126          # sessions of HY OAS
CREDIT_WIDEN_BP = 0.75       # +75bp off the window low (hy_oas is in PERCENT)
CREDIT_MIN_OBS = 63          # below this the OAS window is too short to trust
CREDIT_PROXY_LOOKBACK = 63   # HYG vs LQD total-return fallback

VOL_BACKWARDATION = 1.00     # vix/vix3m above this = stress
VOL_CONTANGO = 0.95          # below this = calm

CLAIMS_SMOOTH = 4            # weeks in the claims mean
CLAIMS_TROUGH_WEEKS = 52     # trailing window for the trough of that mean
CLAIMS_TIGHT = 1.05          # c <= 1.05 x trough -> labour market still tight
CLAIMS_LOOSE = 1.20          # c >= 1.20 x trough -> recession clock running
CURVE_CROSS_WINDOW = 63      # sessions since the un-inversion
CURVE_INVERTED_MIN = 63      # consecutive inverted sessions required before it

FEAR_ADD = 0.25              # exposure added back at capitulation extremes
FEAR_AAII_PCTL = 90          # aaii_bear percentile over...
FEAR_AAII_WINDOW = 156       # ...three years of weekly obs
FEAR_PC_MEAN_OBS = 10        # put/call smoothing
FEAR_PC_WINDOW = 252         # its own mean+2sd reference window
FEAR_PC_SIGMA = 2.0
FEAR_DIX_MIN = 0.47          # dark-pool buying at a level that marks washouts

SLOW_CAP = 0.50              # leverage/short-interest ceiling on the target
MARGIN_YOY_HOT = 0.25        # +25% YoY margin debt inside the trailing year...
MARGIN_LOOKBACK_M = 12       # ...and a roll to negative YoY now
SI_WINDOW = 72               # ~3y of semi-monthly settlement dates
SI_SIGMA = 1.5

HYSTERESIS = 0.20            # don't trade for less than a 20pp weight change

# Composite score -> SPY target weight. Scores outside the table clamp.
TIERS = {2: 1.00, 1: 0.75, 0: 0.50, -1: 0.25, -2: 0.00}


def _tier(score: int) -> float:
    return TIERS[max(-2, min(2, score))]


# --------------------------------------------------------------------------- #
# point-in-time reads — BOTH gates, always
# --------------------------------------------------------------------------- #
def latest(con, series: str, as_of: date) -> float | None:
    """The most recent value of `series` we both have data for AND had stored by
    `as_of`. None when the gate leaves nothing — never a stale guess."""
    try:
        row = con.execute(
            "SELECT value FROM macro_signals WHERE series = ? "
            "AND obs_date <= ? AND fetch_as_of <= ? "
            "ORDER BY obs_date DESC LIMIT 1",
            [series, as_of, as_of],
        ).fetchone()
    except Exception:  # noqa: BLE001 - macro_signals absent on an old store copy
        return None
    return None if row is None or row[0] is None else float(row[0])


def series_window(con, series: str, as_of: date, n: int) -> list[float]:
    """The last `n` values of `series` visible at `as_of`, OLDEST first."""
    try:
        rows = con.execute(
            "SELECT value FROM macro_signals WHERE series = ? "
            "AND obs_date <= ? AND fetch_as_of <= ? "
            "ORDER BY obs_date DESC LIMIT ?",
            [series, as_of, as_of, n],
        ).fetchall()
    except Exception:  # noqa: BLE001 - macro_signals absent on an old store copy
        return []
    return [float(r[0]) for r in reversed(rows) if r[0] is not None]


# --------------------------------------------------------------------------- #
# the four blocks
# --------------------------------------------------------------------------- #
def _block_breadth(con, as_of: date, warn) -> tuple[int, dict]:
    """Internal breadth. Bull above 55% of names over their 200d SMA, bear below
    35%. Two overrides sit on top, in this order: a Zweig breadth thrust inside
    the last 20 sessions forces +1 (about twenty since 1945, every one of them
    positive 6 and 12 months later), and a sub-15% washout forces −1 while
    flagging `washout` — the condition the fear overlay exists to catch."""
    pct = latest(con, "breadth_pct_200", as_of)
    info: dict = {"breadth_pct_200": pct, "zweig_thrust": False, "washout": False}
    if pct is None:
        warn("breadth_pct_200 unavailable at this as_of — breadth block votes 0")
        return 0, info

    vote = 1 if pct >= BREADTH_BULL else (-1 if pct <= BREADTH_BEAR else 0)

    z = series_window(con, "zweig_ratio", as_of, ZWEIG_LOOKBACK + ZWEIG_SPAN)
    if len(z) >= 2:
        recent_from = max(1, len(z) - ZWEIG_LOOKBACK)
        for j in range(recent_from, len(z)):
            if z[j] <= ZWEIG_HIGH:
                continue
            lo = max(0, j - ZWEIG_SPAN)
            if any(v < ZWEIG_LOW for v in z[lo:j]):
                info["zweig_thrust"] = True
                vote = 1
                break
    else:
        warn("zweig_ratio history too short at this as_of — no thrust check")

    if pct <= BREADTH_WASHOUT:
        info["washout"] = True
        vote = -1
    info["vote"] = vote
    return vote, info


def _block_credit(con, as_of: date, warn) -> tuple[int, dict]:
    """Credit. High-yield OAS 75bp off its own 126-session low is the confirming
    widening the research puts second in the topping sequence; at or below the
    window median credit is not the problem. FRED hard-caps BAMLH0A0HYM2 to a
    trailing window, so when the OAS history is too short the block falls back to
    the internal HYG-vs-LQD 63-session total-return spread — same question,
    coarser instrument, computed from prices we own."""
    w = series_window(con, "hy_oas", as_of, CREDIT_WINDOW)
    info: dict = {"hy_oas_obs": len(w)}
    if len(w) >= CREDIT_MIN_OBS:
        cur, lo, med = w[-1], min(w), float(np.median(w))
        info.update({"hy_oas": cur, "hy_oas_min": lo, "hy_oas_median": med,
                     "source": "hy_oas"})
        vote = -1 if cur >= lo + CREDIT_WIDEN_BP else (1 if cur <= med else 0)
        info["vote"] = vote
        return vote, info

    hyg = total_return(con, "HYG", as_of, CREDIT_PROXY_LOOKBACK)
    lqd = total_return(con, "LQD", as_of, CREDIT_PROXY_LOOKBACK)
    info["source"] = "hyg_lqd"
    if hyg is None or lqd is None:
        warn("hy_oas window too short AND HYG/LQD history missing — "
             "credit block votes 0")
        info["vote"] = 0
        return 0, info
    info.update({"hyg_63d": hyg, "lqd_63d": lqd})
    vote = 1 if hyg - lqd >= 0 else -1
    info["vote"] = vote
    return vote, info


def _block_vol(con, as_of: date, warn) -> tuple[int, dict]:
    """VIX term structure. Spot below the 3-month curve (contango) is the calm
    state; backwardation is the market paying up for immediate protection
    (Johnson JFQA 2017 — the slope carries the information, not the level)."""
    v1 = latest(con, "vix", as_of)
    v3 = latest(con, "vix3m", as_of)
    info: dict = {"vix": v1, "vix3m": v3}
    if v1 is None or v3 is None or v3 <= 0:
        warn("vix/vix3m unavailable at this as_of — vol block votes 0")
        info["vote"] = 0
        return 0, info
    ratio = v1 / v3
    info["vix_ratio"] = ratio
    vote = 1 if ratio < VOL_CONTANGO else (-1 if ratio > VOL_BACKWARDATION else 0)
    info["vote"] = vote
    return vote, info


def _block_macro(con, as_of: date, warn) -> tuple[int, dict]:
    """Macro. Initial claims smoothed over 4 weeks against their own 52-week
    trough is the recession clock (a ~20% rise off trough is the historical
    marker). NFCI above 0 — financial conditions tighter than average — caps the
    block at neutral rather than letting a still-tight labour market vote risk-on
    into a tightening. And the curve override: an inversion is famously useless
    as a timing signal (Fama-French 2019), but the RE-STEEPENING out of a long
    inversion has been the late marker, so it forces the block negative."""
    info: dict = {}
    weekly = series_window(con, "icsa", as_of,
                           CLAIMS_TROUGH_WEEKS + CLAIMS_SMOOTH + 4)
    need = CLAIMS_TROUGH_WEEKS + CLAIMS_SMOOTH - 1
    if len(weekly) < need:
        warn(f"icsa history too short ({len(weekly)} < {need} weekly obs) — "
             f"macro block votes 0")
        vote = 0
    else:
        means = [float(np.mean(weekly[i - CLAIMS_SMOOTH + 1:i + 1]))
                 for i in range(CLAIMS_SMOOTH - 1, len(weekly))]
        c = means[-1]
        trough = min(means[-CLAIMS_TROUGH_WEEKS:])
        info.update({"claims_4wk": c, "claims_trough_52w": trough,
                     "claims_ratio": c / trough if trough else None})
        vote = 1 if c <= CLAIMS_TIGHT * trough else (
            -1 if c >= CLAIMS_LOOSE * trough else 0)

    nfci = latest(con, "nfci", as_of)
    info["nfci"] = nfci
    if nfci is None:
        warn("nfci unavailable at this as_of — no financial-conditions cap")
    elif nfci > 0:
        vote = min(vote, 0)
        info["nfci_capped"] = True

    curve = series_window(con, "t10y2y", as_of,
                          CURVE_CROSS_WINDOW + CURVE_INVERTED_MIN + 5)
    info["resteepened"] = False
    if len(curve) >= CURVE_INVERTED_MIN + 2:
        first_recent = max(1, len(curve) - CURVE_CROSS_WINDOW)
        for k in range(len(curve) - 1, first_recent - 1, -1):
            if curve[k] >= 0 > curve[k - 1] and k - 1 - CURVE_INVERTED_MIN >= 0:
                prior = curve[k - 1 - CURVE_INVERTED_MIN:k]
                if all(v < 0 for v in prior):
                    info["resteepened"] = True
                    vote = -1
                    break
    else:
        warn("t10y2y history too short at this as_of — no re-steepening check")

    info["vote"] = vote
    return vote, info


# --------------------------------------------------------------------------- #
# overlays
# --------------------------------------------------------------------------- #
def _fear_extremes(con, as_of: date) -> tuple[bool, dict]:
    """Capitulation check — ONLY consulted when the composite is already negative.

    Sentiment adds value at fear extremes and nowhere else (the greed side is
    momentum, not a sell), so this can only ever ADD exposure, and only into a
    tape the four blocks have already marked risk-off. Any one of three readings
    is enough: retail bears in the top decile of three years, smoothed equity
    put/call two standard deviations hot, or dark-pool buying (DIX) at a level
    that has historically marked washout lows.
    """
    info: dict = {}
    fired = False

    bear = series_window(con, "aaii_bear", as_of, FEAR_AAII_WINDOW)
    if len(bear) >= 52:
        thresh = float(np.percentile(bear, FEAR_AAII_PCTL))
        info.update({"aaii_bear": bear[-1], "aaii_bear_p90": thresh})
        if bear[-1] >= thresh:
            info["aaii_fired"] = True
            fired = True

    pc = series_window(con, "pc_equity", as_of, FEAR_PC_WINDOW)
    if len(pc) >= FEAR_PC_MEAN_OBS + 20:
        smoothed = float(np.mean(pc[-FEAR_PC_MEAN_OBS:]))
        thresh = float(np.mean(pc)) + FEAR_PC_SIGMA * float(np.std(pc))
        info.update({"pc_equity_10obs": smoothed, "pc_equity_thresh": thresh})
        if smoothed >= thresh:
            info["pc_fired"] = True
            fired = True

    dix = latest(con, "dix", as_of)
    info["dix"] = dix
    if dix is not None and dix >= FEAR_DIX_MIN:
        info["dix_fired"] = True
        fired = True

    return fired, info


def _slow_conditioners(con, as_of: date) -> tuple[bool, dict]:
    """Leverage + short interest: they say how bad a break will be, not when it
    comes, so they cap the maximum allocation instead of triggering a trade.

    Margin debt rolling to a negative year-on-year change AFTER a >25% YoY
    build-up inside the trailing year is the deleveraging pattern that turns a
    correction into a drawdown. Market-wide days-to-cover 1.5 standard deviations
    above its three-year mean is the crowded-short condition."""
    info: dict = {}
    capped = False

    m = series_window(con, "margin_debt", as_of, MARGIN_LOOKBACK_M + 13)
    if len(m) >= 13:
        yoy = [m[i] / m[i - 12] - 1 for i in range(12, len(m)) if m[i - 12]]
        if yoy:
            info.update({"margin_yoy": yoy[-1],
                         "margin_yoy_max_12m": max(yoy[-MARGIN_LOOKBACK_M:])})
            if yoy[-1] < 0 and max(yoy[-MARGIN_LOOKBACK_M:]) > MARGIN_YOY_HOT:
                info["margin_capped"] = True
                capped = True

    si = series_window(con, "short_interest_dtc", as_of, SI_WINDOW)
    if len(si) >= 12:
        thresh = float(np.mean(si)) + SI_SIGMA * float(np.std(si))
        info.update({"short_interest_dtc": si[-1], "si_thresh": thresh})
        if si[-1] >= thresh:
            info["si_capped"] = True
            capped = True

    return capped, info


# --------------------------------------------------------------------------- #
class MacroComposite(Strategy):
    cadence = "weekly"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        warned: list[str] = []

        def warn(msg: str) -> None:
            warned.append(msg)
            print(f"[macro_composite] WARN {as_of}: {msg}")

        vb, ib = _block_breadth(con, as_of, warn)
        vc, ic = _block_credit(con, as_of, warn)
        vv, iv = _block_vol(con, as_of, warn)
        vm, im = _block_macro(con, as_of, warn)
        score = vb + vc + vv + vm
        target = _tier(score)

        fear, ifear = (False, {})
        if score <= -1:
            fear, ifear = _fear_extremes(con, as_of)
            if fear:
                target = min(1.0, target + FEAR_ADD)

        capped, icap = _slow_conditioners(con, as_of)
        if capped:
            target = min(target, SLOW_CAP)

        px = close_on(con, "SPY", as_of)
        held = pf.positions.get("SPY", 0.0)
        current = (held * px / pf.equity) if (px and pf.equity) else 0.0
        move = abs(target - current)

        print(f"[macro_composite] {as_of} votes breadth={vb} credit={vc} "
              f"vol={vv} macro={vm} → score {score:+d} → tier "
              f"{_tier(score):.2f}"
              f"{' +fear' if fear else ''}{' capped@0.50' if capped else ''}"
              f" → target {target:.2f} (current {current:.2f}, Δ {move:.2f})"
              f"{' · washout' if ib.get('washout') else ''}"
              f"{' · zweig-thrust' if ib.get('zweig_thrust') else ''}"
              f"{' · resteepened' if im.get('resteepened') else ''}"
              f"{' · credit=' + str(ic.get('source'))}"
              f"{f' · {len(warned)} missing series' if warned else ''}")

        if move < HYSTERESIS:
            print(f"[macro_composite] {as_of} hysteresis: |Δ| {move:.2f} < "
                  f"{HYSTERESIS:.2f} — no trade")
            return []
        print(f"[macro_composite] {as_of} ALLOCATION CHANGE "
              f"{current:.2f} → {target:.2f}")
        return rebalance_orders(con, pf, as_of, {"SPY": target})
