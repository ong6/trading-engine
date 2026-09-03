#!/usr/bin/env python
"""Trade autopsy — the paper league's own fill log, turned into per-trade evidence.

STRICTLY READ-ONLY. This module opens the store with `read_only=True` and issues
nothing but SELECTs. It is the evidence source for the weekly agent tuner session,
which asks three questions the equity curve cannot answer:

  * were our stops too tight?      -> mae_pct on WINNERS (how much heat a winner took)
  * did we exit winners early?     -> gave_back = mfe_pct - gross_ret
  * did losers run?                -> mae_pct / mfe_pct on LOSERS (did they ever show green?)

Method. Per (book, ticker) the fill log is FIFO-matched: buys open lots, sells consume
them oldest-first, and a lot that is fully consumed becomes one CLOSED round trip. Lots
still holding shares are emitted as OPEN positions with the same excursion fields marked
to the latest stored session. Excursions come from the daily bars over the holding window
(MAE from the LOW, MFE from the HIGH) — never from the fills.

Honesty rules, all load-bearing:
  * No price is ever invented. If any bar the window needs is missing or NULL, the
    dependent field is None and the record carries `incomplete: true`.
  * `hold_sessions` counts SESSIONS (distinct trading dates in `prices`), never calendar
    days and never price ROWS — a prior bug in this repo counted rows across all tickers,
    which multiplied every holding period by the size of the universe.
  * Exit reasons are NOT guessed. `time_stop_hit` / `stop_frac_breach` are set only when
    the book's own frozen config carries the corresponding parameter; an unknown reason
    reads as None, which is a different fact from False.
  * A statistic over an empty set is None, never 0.0 dressed up as a measurement.

Usage:
    .venv/bin/python -m farm.autopsy                              # markdown to stdout
    .venv/bin/python -m farm.autopsy --book mr_overlay --book pead_ear
    .venv/bin/python -m farm.autopsy --since 2026-07-01 --json out.json --md out.md
    python -m farm.autopsy --help
"""
from __future__ import annotations

import argparse
import json
import statistics
from bisect import bisect_left, bisect_right
from collections import deque
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from engine.lib import db
from engine.lib.settings import REPO_ROOT  # noqa: F401

DB_PATH = db.DEFAULT_DB

# Bounded wait for the single-writer lock (nightly / farm / queue runner hold it).
# ~6 tries x 5s = 30s, then a clear error — the CALLER decides whether to degrade.
LOCK_TRIES = 6
LOCK_RETRY_S = 5.0

# MAE bands reported as "share of losers that went at least this far against us".
MAE_THRESHOLDS = (-0.05, -0.10, -0.15, -0.20)
# A winner that handed back more than this much of its best unrealized gain.
GAVE_BACK_PP = 0.05
# Float share counts: a lot is closed when its remainder is below this.
QTY_EPS = 1e-9


# --------------------------------------------------------------------------- #
# connection — read-only, bounded retry
# --------------------------------------------------------------------------- #
def connect_readonly(path: str | Path = DB_PATH,
                     tries: int = LOCK_TRIES,
                     retry_s: float = LOCK_RETRY_S) -> duckdb.DuckDBPyConnection:
    """A READ-ONLY DuckDB handle, retrying while another process holds the writer lock.

    DuckDB is single-writer on disk, so an overlapping nightly/farm run makes a
    transient open failure normal rather than exceptional. After the bounded window
    the error is raised with the elapsed budget spelled out — this module never
    silently returns an empty autopsy, because "no trades" and "could not look" are
    completely different answers for the tuner reading the report.
    """
    # Thin wrapper over the one connection factory (engine.lib.db.connect).
    try:
        return db.connect(path, read_only=True, wait_s=max(1, tries) * retry_s)
    except Exception as exc:  # duckdb.IOException et al.
        raise RuntimeError(
            f"[autopsy] could not open {path} read-only after {tries} attempt(s) "
            f"(~{tries * retry_s:.0f}s): {exc}"
        ) from exc


# --------------------------------------------------------------------------- #
# small stats helpers — empty set means None, never 0.0
# --------------------------------------------------------------------------- #
def _mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else None


def _median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _share(xs, pred):
    """Share of a population satisfying `pred`. None if the population is empty."""
    xs = [x for x in xs if x is not None]
    return (sum(1 for x in xs if pred(x)) / len(xs)) if xs else None


# --------------------------------------------------------------------------- #
# price access
# --------------------------------------------------------------------------- #
class _Prices:
    """Per-ticker bar cache plus the market's session calendar.

    `sessions` is the sorted set of DISTINCT dates in `prices` — the trading
    calendar. Holding periods are measured against it, so a hold is a count of
    SESSIONS, independent of how many tickers happen to have a row on a date.
    """

    def __init__(self, con: duckdb.DuckDBPyConnection):
        self.con = con
        self.sessions: list[date] = [
            r[0] for r in con.execute(
                "SELECT DISTINCT date FROM prices ORDER BY date").fetchall()
        ]
        self._bars: dict[str, list[tuple]] = {}

    @property
    def latest_session(self) -> date | None:
        return self.sessions[-1] if self.sessions else None

    def sessions_after(self, start: date, end: date) -> int:
        """Sessions with date > start AND date <= end — the holding period."""
        return bisect_right(self.sessions, end) - bisect_right(self.sessions, start)

    def sessions_inclusive(self, start: date, end: date) -> int:
        """Sessions with start <= date <= end — the excursion window."""
        return bisect_right(self.sessions, end) - bisect_left(self.sessions, start)

    def bars(self, ticker: str) -> list[tuple]:
        """[(date, low, high, close)] for a ticker, ascending. Cached."""
        got = self._bars.get(ticker)
        if got is None:
            got = self.con.execute(
                "SELECT date, low, high, close FROM prices WHERE ticker = ? "
                "ORDER BY date", [ticker]).fetchall()
            self._bars[ticker] = got
        return got

    def window(self, ticker: str, start: date, end: date) -> list[tuple]:
        rows = self.bars(ticker)
        dates = [r[0] for r in rows]
        return rows[bisect_left(dates, start):bisect_right(dates, end)]


def _excursions(prices: _Prices, ticker: str, start: date, end: date,
                entry_px: float):
    """(mae_pct, mfe_pct, incomplete) over [start, end] inclusive.

    MAE uses the LOW (worst adverse excursion), MFE uses the HIGH (best unrealized
    gain). If the ticker is missing any session in the window, or any low/high in it
    is NULL, both come back None and incomplete is True — a partial window would
    understate both excursions, and understating them is exactly the error that makes
    a stop look wide enough when it was not.
    """
    want = prices.sessions_inclusive(start, end)
    bars = prices.window(ticker, start, end)
    if not entry_px or want <= 0 or len(bars) != want:
        return None, None, True
    lows = [b[1] for b in bars]
    highs = [b[2] for b in bars]
    if any(v is None for v in lows) or any(v is None for v in highs):
        return None, None, True
    return min(lows) / entry_px - 1.0, max(highs) / entry_px - 1.0, False


# --------------------------------------------------------------------------- #
# book config — the only source of stop / hold parameters
# --------------------------------------------------------------------------- #
def book_params(con: duckdb.DuckDBPyConnection, book: str) -> dict:
    """The `params` block of the book's frozen `portfolios.config` JSON, or {}.

    Nothing here is inferred from behaviour: if the book never declared a stop, the
    autopsy reports None for stop labels rather than inventing a threshold.
    """
    row = con.execute("SELECT config FROM portfolios WHERE id = ?", [book]).fetchone()
    if not row or not row[0]:
        return {}
    try:
        cfg = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(cfg, dict):
        return {}
    params = cfg.get("params")
    return params if isinstance(params, dict) else {}


def _hold_limit(params: dict):
    """The book's declared max holding period in sessions, or None if it has none."""
    for key in ("time_stop", "max_hold"):
        v = params.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def _stop_frac(params: dict):
    v = params.get("stop_frac")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return None


# --------------------------------------------------------------------------- #
# FIFO round-trip construction
# --------------------------------------------------------------------------- #
def _fifo_lots(con: duckdb.DuckDBPyConnection, book: str):
    """(closed_lots, open_lots, unmatched_sell_qty) for one book.

    Buys open lots; sells consume them oldest-first, in (fill_date, order_id) order.
    A lot whose remainder falls to zero is a CLOSED round trip carrying the list of
    sell fills that consumed it; whatever is left holding shares is OPEN. An
    over-sell (more sold than any lot on record can supply) is not silently absorbed
    — it is counted and surfaced, because it would mean the fill log disagrees with
    the position ledger.
    """
    rows = con.execute(
        "SELECT ticker, side, qty, fill_px, fill_date, order_id FROM sim_fills "
        "WHERE portfolio_id = ? ORDER BY fill_date, order_id", [book]).fetchall()

    lots_by_ticker: dict[str, deque] = {}
    closed: list[dict] = []
    unmatched = 0.0

    for ticker, side, qty, fill_px, fill_date, order_id in rows:
        qty = float(qty or 0.0)
        if qty <= 0:
            continue
        lots = lots_by_ticker.setdefault(ticker, deque())
        if side == "buy":
            lots.append({"ticker": ticker, "qty": qty, "remaining": qty,
                         "entry_px": float(fill_px), "entry_date": fill_date,
                         "order_id": order_id, "sells": []})
            continue
        # sell — consume open lots FIFO
        left = qty
        while left > QTY_EPS and lots:
            lot = lots[0]
            take = min(lot["remaining"], left)
            lot["remaining"] -= take
            left -= take
            lot["sells"].append((take, float(fill_px), fill_date))
            if lot["remaining"] <= QTY_EPS:
                closed.append(lots.popleft())
        if left > QTY_EPS:
            unmatched += left

    open_lots = [lot for lots in lots_by_ticker.values() for lot in lots]
    open_lots.sort(key=lambda l: (l["entry_date"], l["order_id"]))
    return closed, open_lots, unmatched


def _closed_record(lot: dict, book: str, prices: _Prices,
                   hold_limit, stop_frac) -> dict:
    entry_px = lot["entry_px"]
    entry_date, exit_date = lot["entry_date"], lot["sells"][-1][2]
    # exit_px is the qty-weighted average of the sell fills that consumed THIS lot,
    # so a lot closed across several days is priced by what it actually realized.
    filled = sum(q for q, _px, _d in lot["sells"])
    exit_px = (sum(q * px for q, px, _d in lot["sells"]) / filled) if filled else None
    gross_ret = (exit_px / entry_px - 1.0) if (exit_px and entry_px) else None
    hold = prices.sessions_after(entry_date, exit_date)
    mae, mfe, incomplete = _excursions(prices, lot["ticker"], entry_date, exit_date,
                                       entry_px)
    gave_back = (mfe - gross_ret) if (mfe is not None and gross_ret is not None) else None
    return {
        "book": book,
        "ticker": lot["ticker"],
        "status": "closed",
        "entry_date": entry_date.isoformat(),
        "exit_date": exit_date.isoformat(),
        "qty": lot["qty"],
        "entry_px": entry_px,
        "exit_px": exit_px,
        "hold_sessions": hold,
        "gross_ret": gross_ret,
        "mae_pct": mae,
        "mfe_pct": mfe,
        "gave_back": gave_back,
        "exit_at_loss": (gross_ret < 0) if gross_ret is not None else None,
        # Only ever a fact about a DECLARED rule; never a guessed exit reason.
        "time_stop_hit": (hold >= hold_limit) if hold_limit is not None else None,
        "stop_frac_breach": ((mae <= stop_frac - 1.0)
                             if (stop_frac is not None and mae is not None) else None),
        "incomplete": incomplete,
    }


def _open_record(lot: dict, book: str, prices: _Prices,
                 hold_limit, stop_frac) -> dict:
    entry_px = lot["entry_px"]
    entry_date = lot["entry_date"]
    asof = prices.latest_session
    if asof is None or asof < entry_date:
        asof = entry_date
    hold = prices.sessions_after(entry_date, asof)
    mae, mfe, incomplete = _excursions(prices, lot["ticker"], entry_date, asof, entry_px)
    # Unrealized mark: the latest stored close for this ticker inside the window, and
    # only if that final session's bar actually exists. Nothing is carried forward.
    bars = prices.window(lot["ticker"], entry_date, asof)
    last_px = None
    if bars and bars[-1][0] == asof and bars[-1][3] is not None:
        last_px = float(bars[-1][3])
    gross_ret = (last_px / entry_px - 1.0) if (last_px and entry_px) else None
    if gross_ret is None:
        incomplete = True
    gave_back = (mfe - gross_ret) if (mfe is not None and gross_ret is not None) else None
    return {
        "book": book,
        "ticker": lot["ticker"],
        "status": "open",
        "entry_date": entry_date.isoformat(),
        "exit_date": None,
        "as_of": asof.isoformat(),
        "qty": lot["remaining"],
        "entry_px": entry_px,
        "exit_px": None,
        "last_px": last_px,
        "hold_sessions": hold,
        "gross_ret": gross_ret,          # unrealized, marked to `as_of`
        "mae_pct": mae,
        "mfe_pct": mfe,
        "gave_back": gave_back,
        "exit_at_loss": None,            # nothing exited — not False, unknown
        "time_stop_hit": (hold >= hold_limit) if hold_limit is not None else None,
        "stop_frac_breach": ((mae <= stop_frac - 1.0)
                             if (stop_frac is not None and mae is not None) else None),
        "incomplete": incomplete,
    }


# --------------------------------------------------------------------------- #
# aggregates
# --------------------------------------------------------------------------- #
def summarize(trades: list[dict], open_trades: list[dict],
              unmatched_sell_qty: float = 0.0) -> dict:
    rets = [t["gross_ret"] for t in trades if t["gross_ret"] is not None]
    winners = [t for t in trades if t["gross_ret"] is not None and t["gross_ret"] > 0]
    losers = [t for t in trades if t["gross_ret"] is not None and t["gross_ret"] < 0]
    holds = [t["hold_sessions"] for t in trades if t["hold_sessions"] is not None]

    loser_maes = [t["mae_pct"] for t in losers if t["mae_pct"] is not None]
    winner_gb = [t["gave_back"] for t in winners if t["gave_back"] is not None]

    ts_known = [t["time_stop_hit"] for t in trades if t["time_stop_hit"] is not None]
    sf_known = [t["stop_frac_breach"] for t in trades
                if t["stop_frac_breach"] is not None]

    mean_ret = _mean(rets)
    return {
        "n_closed": len(trades),
        "n_open": len(open_trades),
        "win_rate": _share(rets, lambda r: r > 0),
        "mean_ret": mean_ret,
        "median_ret": _median(rets),
        "mean_win": _mean([t["gross_ret"] for t in winners]),
        "mean_loss": _mean([t["gross_ret"] for t in losers]),
        # Expectancy per trade IS the mean return here: every trade is one lot and
        # the league sizes them by rule, so there is no separate probability x payoff
        # to reconstruct. Named separately because the tuner asks for it by name.
        "expectancy": mean_ret,
        "mean_hold_sessions": _mean(holds),
        "median_hold_sessions": _median(holds),
        "mean_mae_winners": _mean([t["mae_pct"] for t in winners]),
        "mean_mae_losers": _mean([t["mae_pct"] for t in losers]),
        # Did losers ever show a profit? A large value here says the exit, not the
        # entry, is what lost the money.
        "mean_mfe_losers": _mean([t["mfe_pct"] for t in losers]),
        "mean_gave_back_winners": _mean(winner_gb),
        "share_losers_mae_beyond": {
            f"{th:.2f}": _share(loser_maes, lambda m, th=th: m <= th)
            for th in MAE_THRESHOLDS
        },
        "share_winners_gave_back_over_5pp": _share(winner_gb,
                                                   lambda g: g > GAVE_BACK_PP),
        # Rates are over the trades where the label is KNOWN (i.e. the book declared
        # the parameter). None means the book has no such rule to hit.
        "time_stop_hit_rate": _share(ts_known, lambda v: v),
        "stop_frac_breach_rate": _share(sf_known, lambda v: v),
        "n_incomplete": sum(1 for t in trades + open_trades if t["incomplete"]),
        "unmatched_sell_qty": unmatched_sell_qty or 0.0,
    }


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def autopsy(con: duckdb.DuckDBPyConnection,
            books: list[str] | None = None,
            since: date | None = None) -> dict:
    """Per-book round trips, open lots and aggregates. Read-only; never writes.

    `books` filters to the given portfolio ids (a requested book with no fills is
    still emitted, empty, so the caller sees it was asked about rather than guessing).
    `since` filters CLOSED trades by exit_date — the matching itself always runs over
    the full fill history, or a lot opened before the cutoff would be orphaned. Open
    positions are current state and are never filtered by `since`.
    """
    have = [r[0] for r in con.execute(
        "SELECT DISTINCT portfolio_id FROM sim_fills ORDER BY portfolio_id").fetchall()]
    wanted = list(books) if books else have
    prices = _Prices(con)
    since_iso = since.isoformat() if since else None

    out: dict[str, dict] = {}
    for book in wanted:
        params = book_params(con, book)
        hold_limit, stop_frac = _hold_limit(params), _stop_frac(params)
        closed_lots, open_lots, unmatched = _fifo_lots(con, book)

        trades = [_closed_record(l, book, prices, hold_limit, stop_frac)
                  for l in closed_lots]
        trades.sort(key=lambda t: (t["exit_date"], t["entry_date"], t["ticker"]))
        if since_iso:
            trades = [t for t in trades if t["exit_date"] >= since_iso]
        opens = [_open_record(l, book, prices, hold_limit, stop_frac)
                 for l in open_lots]

        out[book] = {
            "trades": trades,
            "open": opens,
            "summary": summarize(trades, opens, unmatched),
        }

    return {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "since": since_iso,
        "books": out,
    }


# --------------------------------------------------------------------------- #
# rendering — this text goes into an LLM prompt, so it stays dense
# --------------------------------------------------------------------------- #
def _p(v) -> str:
    """A signed percentage to 2dp; '·' when the number does not exist."""
    if v is None or (isinstance(v, float) and v != v):
        return "·"
    return f"{v * 100:+.2f}%"


def _r(v) -> str:
    """An unsigned rate (a share of trades) to 2dp; '·' when unmeasured."""
    if v is None or (isinstance(v, float) and v != v):
        return "·"
    return f"{v * 100:.2f}%"


def _n(v, nd: int = 1) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "·"
    return f"{v:.{nd}f}"


def _flags(t: dict) -> str:
    f = ""
    if t.get("exit_at_loss"):
        f += "L"
    if t.get("time_stop_hit"):
        f += "T"
    if t.get("stop_frac_breach"):
        f += "S"
    if t.get("incomplete"):
        f += "?"
    return f or "·"


def render_markdown(result: dict, max_trades: int = 25) -> str:
    books = result.get("books", {})
    lines = [
        f"# Trade autopsy — {result.get('generated_utc')}"
        + (f" · closed trades since {result['since']}" if result.get("since") else ""),
        "",
        "FIFO round trips from `sim_fills`. `hold` = SESSIONS held. MAE = worst low vs "
        "entry, MFE = best high vs entry, `gave back` = MFE − realized. Flags: "
        "L loss · T book's time-stop/max-hold reached · S MAE beyond the book's "
        "stop_frac · ? a bar was missing so excursions are unmeasured. `·` = no "
        "measurement exists (never zero).",
        "",
        "| Book | closed | open | win | mean | median | mean win | mean loss | "
        "hold mean | hold med | incompl |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for b in sorted(books):
        s = books[b]["summary"]
        lines.append(
            f"| {b} | {s['n_closed']} | {s['n_open']} | {_r(s['win_rate'])} "
            f"| {_p(s['mean_ret'])} | {_p(s['median_ret'])} | {_p(s['mean_win'])} "
            f"| {_p(s['mean_loss'])} | {_n(s['mean_hold_sessions'])} "
            f"| {_n(s['median_hold_sessions'])} | {s['n_incomplete']} |")

    lines += [
        "",
        "| Book | MAE winners | MAE losers | MFE losers | gave back win | "
        "losers ≤−5% | ≤−10% | ≤−15% | ≤−20% | win gave >5pp | time-stop | "
        "stop breach |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for b in sorted(books):
        s = books[b]["summary"]
        m = s["share_losers_mae_beyond"]
        lines.append(
            f"| {b} | {_p(s['mean_mae_winners'])} | {_p(s['mean_mae_losers'])} "
            f"| {_p(s['mean_mfe_losers'])} | {_p(s['mean_gave_back_winners'])} "
            f"| {_r(m.get('-0.05'))} | {_r(m.get('-0.10'))} | {_r(m.get('-0.15'))} "
            f"| {_r(m.get('-0.20'))} | {_r(s['share_winners_gave_back_over_5pp'])} "
            f"| {_r(s['time_stop_hit_rate'])} | {_r(s['stop_frac_breach_rate'])} |")

    for b in sorted(books):
        bk = books[b]
        trades, opens, s = bk["trades"], bk["open"], bk["summary"]
        lines += ["", f"## {b} — {s['n_closed']} closed, {s['n_open']} open", ""]
        if trades:
            shown = trades[-max_trades:]
            if len(trades) > len(shown):
                lines.append(f"_latest {len(shown)} of {len(trades)} closed trades_")
                lines.append("")
            lines += ["| ticker | in | out | hold | ret | MAE | MFE | gave back | flags |",
                      "|---|---|---|---|---|---|---|---|---|"]
            for t in reversed(shown):
                lines.append(
                    f"| {t['ticker']} | {t['entry_date']} | {t['exit_date']} "
                    f"| {t['hold_sessions']} | {_p(t['gross_ret'])} "
                    f"| {_p(t['mae_pct'])} | {_p(t['mfe_pct'])} "
                    f"| {_p(t['gave_back'])} | {_flags(t)} |")
        else:
            lines.append("_no closed round trips_")
        if opens:
            lines += ["", "| open | in | hold | unreal | MAE | MFE | flags |",
                      "|---|---|---|---|---|---|---|"]
            for t in opens[-max_trades:][::-1]:
                lines.append(
                    f"| {t['ticker']} | {t['entry_date']} | {t['hold_sessions']} "
                    f"| {_p(t['gross_ret'])} | {_p(t['mae_pct'])} | {_p(t['mfe_pct'])} "
                    f"| {_flags(t)} |")
        if s.get("unmatched_sell_qty"):
            lines += ["", f"⚠ {s['unmatched_sell_qty']:.4f} shares sold with no open "
                          "lot to match — the fill log and the position ledger disagree."]
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--book", action="append", dest="books",
                    help="portfolio id; repeatable. Default: every book with fills.")
    ap.add_argument("--since", help="only closed trades exiting on/after YYYY-MM-DD")
    ap.add_argument("--json", dest="json_out", help="write the full result as JSON")
    ap.add_argument("--md", dest="md_out", help="write the markdown report")
    ap.add_argument("--max-trades", type=int, default=25,
                    help="per-book closed trades shown in the markdown (default 25)")
    a = ap.parse_args(argv)

    since = date.fromisoformat(a.since) if a.since else None
    con = connect_readonly(a.db)
    try:
        result = autopsy(con, books=a.books, since=since)
    finally:
        con.close()

    md = render_markdown(result, max_trades=a.max_trades)
    if a.json_out:
        p = Path(a.json_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(result, indent=2, default=str) + "\n")
        print(f"[autopsy] wrote {p}")
    if a.md_out:
        p = Path(a.md_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(md)
        print(f"[autopsy] wrote {p}")
    if not a.json_out and not a.md_out:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
