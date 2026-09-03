"""Strategy interface + shared signal/sizing helpers.

A strategy turns close-of-`as_of_date` information into a list of Orders. The
contract: `generate_orders(con, pf, as_of_date)` may read price/screen data ONLY
with date <= as_of_date. Orders are *intents*; fills.py decides if/when/at what
price they execute (always at a later bar's open).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

import duckdb
import numpy as np

from engine.lib import settings
from engine.lib.log import get_logger

log = get_logger("gate")

MIN_ORDER_USD = 50.0  # skip dust rebalancing below this notional

# Where the agentic books keep their per-book state (charter / lessons /
# changes / daily gate files). Overridable so a shakedown on a store COPY can
# point at a scratch tree without touching the live one. The layer was retired
# 2026-08-18 and lives in archive/agentic-2026-08/; while the directory is
# absent, apply_agent_gate() is a silent no-op (fail-open, pure algo).
AGENTS_DIR = settings.AGENTS_DIR
# Hard floor on how far an agent may downscale an algo entry. A "downscale" that
# rounds a position to nothing is a veto wearing a disguise, and the two are
# accounted for separately.
MIN_GATE_SCALE = 0.25


@dataclass
class Order:
    portfolio_id: str
    ticker: str
    side: str          # 'buy' | 'sell'
    qty: float
    signal_date: date


@dataclass
class PortfolioView:
    """A portfolio's decision-time state, handed to a strategy."""
    id: str
    params: dict
    cash: float
    positions: dict          # {ticker: qty}
    equity: float            # MTM at as_of close


class Strategy:
    """Base strategy. Subclasses set `cadence` and implement generate_orders."""
    cadence = "daily"        # 'daily' | 'weekly' | 'monthly' | 'once'

    def generate_orders(
        self, con: duckdb.DuckDBPyConnection, pf: PortfolioView, as_of: date
    ) -> list[Order]:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# screen / regime reads (all with date <= as_of)
# --------------------------------------------------------------------------- #
def latest_screen_date(con, as_of: date) -> date | None:
    row = con.execute(
        "SELECT MAX(run_date) FROM screen_results WHERE run_date <= ?", [as_of]
    ).fetchone()
    return row[0] if row else None


def passing_ranked(con, screen_date: date) -> list[tuple[str, int]]:
    """(ticker, rs_rank) for passes_template names, best RS first."""
    return con.execute(
        "SELECT ticker, rs_rank FROM screen_results "
        "WHERE run_date = ? AND passes_template ORDER BY rs_rank DESC, ticker",
        [screen_date],
    ).fetchall()


def rank_position(con, screen_date: date) -> dict[str, int]:
    """{ticker: 1-based rank among passing names by RS} — for banding tests."""
    out = {}
    for i, (tk, _rs) in enumerate(passing_ranked(con, screen_date), start=1):
        out[tk] = i
    return out


def regime_risk_off(con, as_of: date) -> bool:
    """SPY close < its 200-session SMA at as_of → risk-off. Unknown (SPY absent
    / <200 bars) is treated as NOT risk-off (don't block on missing data)."""
    spy = con.execute(
        "SELECT close FROM prices WHERE ticker = 'SPY' AND date <= ? "
        "ORDER BY date DESC LIMIT 200",
        [as_of],
    ).fetchall()
    if len(spy) < 200:
        return False
    closes = np.array([r[0] for r in spy], dtype=float)
    return closes[0] < closes.mean()


def close_on(con, ticker: str, as_of: date) -> float | None:
    row = con.execute(
        "SELECT close FROM prices WHERE ticker = ? AND date <= ? "
        "ORDER BY date DESC LIMIT 1",
        [ticker, as_of],
    ).fetchone()
    return None if row is None or row[0] is None else float(row[0])


def recent_closes(con, ticker: str, as_of: date, n: int) -> np.ndarray:
    rows = con.execute(
        "SELECT close FROM prices WHERE ticker = ? AND date <= ? "
        "ORDER BY date DESC LIMIT ?",
        [ticker, as_of, n],
    ).fetchall()
    return np.array([r[0] for r in reversed(rows)], dtype=float)


def recent_ohlc(con, ticker: str, as_of: date, n: int):
    rows = con.execute(
        "SELECT date, high, close FROM prices WHERE ticker = ? AND date <= ? "
        "ORDER BY date DESC LIMIT ?",
        [ticker, as_of, n],
    ).fetchall()
    return list(reversed(rows))


def price_return(con, ticker: str, as_of: date, lookback: int) -> float | None:
    """close(as_of) / close(lookback sessions ago) - 1, or None if too short.

    PRICE only — no dividends. Correct for the conventional price-based signals
    (52-week-high ratio, realised vol, RS, ATR, breakouts). For anything that
    compares assets on the return an investor actually earns, use total_return:
    a price-only comparison against a distributing asset is badly wrong (BIL's
    price is ~flat by construction and essentially all its return is coupon).
    """
    rows = con.execute(
        "SELECT close FROM prices WHERE ticker = ? AND date <= ? "
        "ORDER BY date DESC LIMIT ?",
        [ticker, as_of, lookback + 1],
    ).fetchall()
    if len(rows) < lookback + 1:
        return None
    last = rows[0][0]
    past = rows[lookback][0]
    if past in (None, 0) or last is None:
        return None
    return last / past - 1


def dividends_between(con, ticker: str, start: date, end: date) -> float:
    """Σ cash dividends per share going ex in (start, end].

    Zero — never an error — when the store has no corporate_actions table (an old
    copy, or a fresh store before the first actions pull). A missing dividend
    history degrades a total return to a price return, which is the honest
    conservative direction, not a fabricated number.
    """
    try:
        row = con.execute(
            "SELECT COALESCE(SUM(value), 0) FROM corporate_actions "
            "WHERE ticker = ? AND kind = 'dividend' AND ex_date > ? AND ex_date <= ?",
            [ticker, start, end],
        ).fetchone()
    except Exception:  # noqa: BLE001 - table absent on an old store
        return 0.0
    return 0.0 if row is None or row[0] is None else float(row[0])


def total_return(con, ticker: str, as_of: date, lookback: int) -> float | None:
    """Total return over `lookback` sessions ending at as_of, or None if short.

        (P_end + Σ dividends ex in (start, as_of]) / P_start − 1

    v1 approximation: distributions are treated as accruing UNREINVESTED cash
    rather than buying more shares at the ex-date close. It slightly understates
    a true reinvested total return (by the compounding on interim distributions —
    for a ~4% yielder over 12 months, single-digit basis points), and it is the
    same convention the books themselves run on, since sim dividends land in cash
    and are only redeployed at the next rebalance. Exact enough for a momentum
    ranking and honest about what it is.

    Dividend share-basis note: yfinance back-adjusts historical dividends for
    later splits, which matches the split-restated price convention `prices`
    holds, so dps and P are on the same scale on both ends of the window.
    """
    rows = con.execute(
        "SELECT date, close FROM prices WHERE ticker = ? AND date <= ? "
        "ORDER BY date DESC LIMIT ?",
        [ticker, as_of, lookback + 1],
    ).fetchall()
    if len(rows) < lookback + 1:
        return None
    end_date, last = rows[0]
    start_date, past = rows[lookback]
    if past in (None, 0) or last is None:
        return None
    return (float(last) + dividends_between(con, ticker, start_date, end_date)) \
        / float(past) - 1


def total_return_between(con, ticker: str, start: date, end: date) -> float | None:
    """Total return between two DATES (not a session count) — for benchmarking a
    book against its own inception date. Uses the close on, or last known before,
    each endpoint; None if either side has no price at all."""
    a = con.execute("SELECT date, close FROM prices WHERE ticker = ? AND date <= ? "
                    "ORDER BY date DESC LIMIT 1", [ticker, start]).fetchone()
    b = con.execute("SELECT date, close FROM prices WHERE ticker = ? AND date <= ? "
                    "ORDER BY date DESC LIMIT 1", [ticker, end]).fetchone()
    if not a or not b or not a[1] or not b[1]:
        return None
    return (float(b[1]) + dividends_between(con, ticker, a[0], b[0])) \
        / float(a[1]) - 1


# --------------------------------------------------------------------------- #
# indicators
# --------------------------------------------------------------------------- #
def rsi_wilder(closes: np.ndarray, period: int = 2) -> float | None:
    """Standard Wilder RSI. Needs > period closes. Returns the latest value."""
    if closes is None or len(closes) <= period:
        return None
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gains[:period].mean()
    avg_loss = losses[:period].mean()
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def atr_wilder(con, ticker: str, as_of: date, period: int = 20) -> float | None:
    """Wilder-smoothed ATR at as_of. None if fewer than period+1 bars, or if any
    high/low/close in the window is NULL (never patch a missing bar)."""
    rows = con.execute(
        "SELECT high, low, close FROM prices WHERE ticker = ? AND date <= ? "
        "ORDER BY date DESC LIMIT ?",
        [ticker, as_of, period * 3 + 1],
    ).fetchall()
    if len(rows) < period + 1:
        return None
    bars = list(reversed(rows))
    if any(v is None for bar in bars for v in bar):
        return None
    trs = []
    for i in range(1, len(bars)):
        hi, lo, _ = bars[i]
        prev_close = bars[i - 1][2]
        trs.append(max(hi - lo, abs(hi - prev_close), abs(lo - prev_close)))
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return float(atr)


def highest_close_between(con, ticker: str, start_date: date, end_date: date):
    """Max close in (start_date, end_date] — the chandelier-exit reference peak."""
    row = con.execute(
        "SELECT MAX(close) FROM prices WHERE ticker = ? AND date > ? AND date <= ?",
        [ticker, start_date, end_date],
    ).fetchone()
    return None if row is None or row[0] is None else float(row[0])


def n_down_closes(closes: np.ndarray) -> int:
    """How many consecutive down closes end the series (close[i] < close[i-1])."""
    n = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] < closes[i - 1]:
            n += 1
        else:
            break
    return n


# --------------------------------------------------------------------------- #
# agent entry gate (books `news_gated_momo` and `earnings_context_pead`)
# --------------------------------------------------------------------------- #
def apply_agent_gate(pf: PortfolioView, as_of: date,
                     orders: list[Order]) -> list[Order]:
    """Let a daily agent session VETO or DOWNSCALE algo-proposed entries.

    Asymmetric by construction (agentic-strategies-design §The discipline, 4):
    the gate can only subtract. It never adds a name, never raises a size, and
    never touches a SELL — an agent that can only subtract cannot invent trades
    out of headlines, and can never trap a position the algo wants out of.

    **Twin safety.** A book without `agent_gate` in its params returns on the
    first line with the SAME list object it was handed. The frozen twins
    (`momo_stopped`, `pead_ear`) execute exactly one dict lookup more than they
    did before this function existed, and no other line of this module.

    **Fail-open, always.** No gate file for the date (agent session skipped,
    quota exhausted, box rebooted, weekend) → pure algo output. A malformed or
    unreadable file → pure algo output plus a WARN. The nightly must never
    depend on an agent session having run; the agent is an overlay, not a
    prerequisite.
    """
    if not pf.params.get("agent_gate"):
        return orders
    # Retired layer (archive/agentic-2026-08/): no agents tree → nothing to read.
    if AGENTS_DIR is None or not AGENTS_DIR.is_dir():
        return orders

    path = AGENTS_DIR / pf.id / f"gate-{as_of.isoformat()}.json"
    try:
        gate = json.loads(path.read_text())
    except FileNotFoundError:
        log.info(f"[gate] {pf.id} {as_of}: no gate file — fail-open, pure algo "
              f"({sum(1 for o in orders if o.side == 'buy')} buy order(s) unchanged)")
        return orders
    except Exception as exc:  # noqa: BLE001 — malformed JSON, bad permissions…
        log.warning(f"[gate] WARN {pf.id} {as_of}: unreadable gate file ({exc}) — "
              f"fail-open, pure algo")
        return orders

    # A gate file stamped with a different date is not this session's decision.
    if gate.get("date") not in (None, as_of.isoformat()):
        log.warning(f"[gate] WARN {pf.id} {as_of}: gate file is stamped "
              f"{gate.get('date')!r} — ignoring, fail-open")
        return orders

    decisions: dict[str, dict] = {}
    for d in gate.get("decisions") or []:
        tk = (d.get("ticker") or "").strip().upper()
        if tk and d.get("action") in ("veto", "downscale"):
            decisions[tk] = d
    if not decisions:
        log.info(f"[gate] {pf.id} {as_of}: gate file present, 0 vetoes/downscales")
        return orders

    out: list[Order] = []
    n_veto = n_scaled = 0
    for o in orders:
        d = decisions.get(o.ticker) if o.side == "buy" else None
        if d is None:
            out.append(o)
            continue
        if d["action"] == "veto":
            n_veto += 1
            log.info(f"[gate] {pf.id} {as_of}: VETO buy {o.ticker} — "
                  f"{str(d.get('reason', ''))[:120]}")
            continue
        try:
            scale = float(d.get("scale", 1.0))
        except (TypeError, ValueError):
            scale = 1.0
        scale = min(1.0, max(MIN_GATE_SCALE, scale))
        if scale >= 1.0:
            out.append(o)
            continue
        n_scaled += 1
        log.info(f"[gate] {pf.id} {as_of}: DOWNSCALE buy {o.ticker} ×{scale:.2f} — "
              f"{str(d.get('reason', ''))[:120]}")
        out.append(Order(o.portfolio_id, o.ticker, o.side, o.qty * scale,
                         o.signal_date))
    log.info(f"[gate] {pf.id} {as_of}: applied {n_veto} veto(es), "
          f"{n_scaled} downscale(s) over "
          f"{sum(1 for o in orders if o.side == 'buy')} buy order(s)")
    return out


# --------------------------------------------------------------------------- #
# sizing
# --------------------------------------------------------------------------- #
def rebalance_orders(
    con, pf: PortfolioView, as_of: date, target_weights: dict[str, float],
    *, allow_buys: bool = True,
) -> list[Order]:
    """Emit buy/sell orders moving `pf` toward target_weights (of equity).

    Held names absent from targets are sold in full. Dust deltas below
    MIN_ORDER_USD are skipped. If allow_buys is False (risk-off gate) only sell
    orders are emitted — entries are blocked, exits proceed.
    """
    orders: list[Order] = []
    names = set(target_weights) | set(pf.positions)
    for tk in sorted(names):
        price = close_on(con, tk, as_of)
        if price is None or price <= 0:
            continue
        target_qty = target_weights.get(tk, 0.0) * pf.equity / price
        cur_qty = pf.positions.get(tk, 0.0)
        delta = target_qty - cur_qty
        if abs(delta) * price < MIN_ORDER_USD:
            continue
        if delta > 0:
            if allow_buys:
                orders.append(Order(pf.id, tk, "buy", delta, as_of))
        else:
            orders.append(Order(pf.id, tk, "sell", -delta, as_of))
    return orders
