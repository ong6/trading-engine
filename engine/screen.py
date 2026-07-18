#!/usr/bin/env python
"""M1 screener — rank the liquid universe and apply Minervini's trend template.

Reads EOD bars from DuckDB (never fabricates one), computes a relative-strength
rank and the 8 trend-template checks for every eligible name as of a screen
date, then writes:
  - screen_results rows into the DB (append-only per run_date),
  - data/screens/<date>.md  (human report: passing + near-miss tables),
  - data/screens/<date>.csv (every screen_results column for the run),
  - data/screens/latest.md  (copy of the newest report),
  - data/eod/<TICKER>.csv   (last 250 bars for watchlist ∪ passing),
  - data/_meta.json         (regime + run counts, read-modify-write).

Eligibility (per active & liquid name, using bars up to and including the
screen date): the latest bar is within 3 trading days of the screen session AND
there are >= 252 daily bars (needed for the 252-day return, the 200-day SMA and
the 52-week range). Names that fail are reported honestly as stale vs short.

Append-only discipline: if screen_results already holds rows for the screen
date the run ABORTS. `--rerun` deletes that date's rows first, then rewrites —
this is a same-day correction only, never a way to rewrite history.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import db  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = REPO_ROOT / "data"
# Watchlist lives in the owner's personal-data-store, outside this repo.
WATCHLIST_PATH = Path(
    "/data00/home/jun.ong/personal-data-store/trading/watchlist.md"
)

MIN_BARS = 252          # 52-week window / 200d SMA / 252d return
WINDOW_BARS = 400       # bars pulled per name (all lookbacks fit in this)
STALE_TRADING_DAYS = 3  # latest bar must be within this many sessions
TABLE_CAP = 100         # max rows per md table

# Short labels for the 8 trend-template checks, listed on near-miss failures.
CHECK_LABELS = [
    "px>150/200d",   # 1 close above SMA150 and SMA200
    "150d>200d",     # 2 SMA150 above SMA200
    "200d-rising",   # 3 SMA200 today above SMA200 21 sessions ago
    "50>150>200d",   # 4 SMA50 > SMA150 > SMA200
    "px>50d",        # 5 close above SMA50
    "30%>low",       # 6 close >= 1.30 x 52-week low
    "25%<high",      # 7 close >= 0.75 x 52-week high (within 25% of high)
    "RS<70",         # 8 rs_rank >= 70
]


# --------------------------------------------------------------------------- #
# per-ticker computations
# --------------------------------------------------------------------------- #
def _compute_ticker(ticker: str, g: pd.DataFrame) -> dict:
    """Compute one name's metrics from its ascending-by-date OHLCV frame.

    Checks 1-7 are computed here; check 8 (RS>=70) is applied later once the
    cross-sectional rs_rank is known. `close` is the latest bar's close.
    """
    closes = g["close"].to_numpy(dtype=float)
    highs = g["high"].to_numpy(dtype=float)
    lows = g["low"].to_numpy(dtype=float)
    vols = g["volume"].to_numpy(dtype=float)
    n = len(closes)
    last = closes[-1]

    def ret(k: int) -> float:
        # close / close k bars ago - 1 (pandas .shift(k) semantics). Needs a bar
        # k positions back; k == n (exactly 252 bars for ret252) yields NaN.
        return last / closes[n - 1 - k] - 1 if k < n else math.nan

    r63, r126, r189, r252 = ret(63), ret(126), ret(189), ret(252)
    rs_raw = 2 * r63 + r126 + r189 + r252

    sma50 = closes[-50:].mean()
    sma150 = closes[-150:].mean()
    sma200 = closes[-200:].mean()
    sma200_21ago = closes[-221:-21].mean()  # 200-window ending 21 sessions back
    low52 = lows[-252:].min()
    high52 = highs[-252:].max()

    # base_tight: the last-20-close range (as a fraction of price) has contracted
    # to under half the prior-20-close range — i.e. the base is tightening.
    #   recent = (max-min of closes[-20:]) / close
    #   prior  = (max-min of closes[-40:-20]) / close
    #   base_tight := recent < 0.5 * prior     (the /close cancels, kept for clarity)
    recent_range = (closes[-20:].max() - closes[-20:].min()) / last
    prior_range = (closes[-40:-20].max() - closes[-40:-20].min()) / last
    base_tight = bool(recent_range < 0.5 * prior_range)

    vol_dryup = bool(vols[-10:].mean() < vols[-50:].mean())

    return {
        "ticker": ticker,
        "close": float(last),
        "rs_raw": float(rs_raw),
        "dist_50d": float(last / sma50 - 1),
        "dist_200d": float(last / sma200 - 1),
        "off_52w_low": float(last / low52 - 1),
        "off_52w_high": float(last / high52 - 1),
        "base_tight": base_tight,
        "vol_dryup": vol_dryup,
        # checks 1-7 (booleans)
        "c1": bool(last > sma150 and last > sma200),
        "c2": bool(sma150 > sma200),
        "c3": bool(sma200 > sma200_21ago),
        "c4": bool(sma50 > sma150 > sma200),
        "c5": bool(last > sma50),
        "c6": bool(last >= 1.30 * low52),
        "c7": bool(last >= 0.75 * high52),
    }


# --------------------------------------------------------------------------- #
# eligibility / data pulls
# --------------------------------------------------------------------------- #
def resolve_screen_date(con, requested: str | None) -> date:
    if requested:
        return date.fromisoformat(requested)
    row = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    if row is None:
        raise SystemExit("[screen] prices table is empty — nothing to screen")
    return row


def stale_cutoff(con, screen_date: date) -> date:
    """The trading day STALE_TRADING_DAYS sessions before the most recent
    session on/before the screen date. A name is stale if its latest bar is
    older than this. Trading days are taken from the dates present in prices, so
    the definition is self-contained (no external calendar needed)."""
    days = [
        r[0]
        for r in con.execute(
            "SELECT DISTINCT date FROM prices WHERE date <= ? ORDER BY date",
            [screen_date],
        ).fetchall()
    ]
    if not days:
        return screen_date
    anchor = len(days) - 1
    return days[max(0, anchor - STALE_TRADING_DAYS)]


def classify_universe(con, screen_date: date, cutoff: date):
    """Split active & liquid names into eligible / stale / short.
    Returns (eligible_tickers, n_stale, n_short)."""
    rows = con.execute(
        """
        SELECT u.ticker, p.md AS max_date, COALESCE(p.nbars, 0) AS nbars
        FROM universe u
        LEFT JOIN (
            SELECT ticker, MAX(date) AS md, COUNT(*) AS nbars
            FROM prices WHERE date <= ? GROUP BY ticker
        ) p ON u.ticker = p.ticker
        WHERE u.active = TRUE AND u.liquid = TRUE
        """,
        [screen_date],
    ).fetch_df()

    cutoff_ts = pd.Timestamp(cutoff)
    eligible, n_stale, n_short = [], 0, 0
    for tk, md, nbars in zip(rows["ticker"], rows["max_date"], rows["nbars"]):
        if pd.isna(md) or pd.Timestamp(md) < cutoff_ts:
            n_stale += 1
        elif int(nbars) < MIN_BARS:
            n_short += 1
        else:
            eligible.append(tk)
    return eligible, n_stale, n_short


def pull_bars(con, screen_date: date, eligible: list[str]) -> pd.DataFrame:
    """Last WINDOW_BARS bars per eligible name in one query (ascending)."""
    con.register("_elig", pd.DataFrame({"ticker": eligible}))
    try:
        bars = con.execute(
            """
            SELECT ticker, date, open, high, low, close, volume
            FROM (
                SELECT p.ticker, p.date, p.open, p.high, p.low, p.close, p.volume,
                       ROW_NUMBER() OVER (PARTITION BY p.ticker ORDER BY p.date DESC) rn
                FROM prices p JOIN _elig e ON p.ticker = e.ticker
                WHERE p.date <= ?
            ) WHERE rn <= ?
            ORDER BY ticker, date
            """,
            [screen_date, WINDOW_BARS],
        ).fetch_df()
    finally:
        con.unregister("_elig")
    return bars


def compute_regime(con, screen_date: date) -> str:
    """SPY close vs its SMA200 → 'risk-on' / 'risk-off'. 'unknown' if SPY is
    absent or has < 200 bars (never guessed)."""
    spy = con.execute(
        "SELECT close FROM prices WHERE ticker = 'SPY' AND date <= ? "
        "ORDER BY date DESC LIMIT 200",
        [screen_date],
    ).fetch_df()
    if len(spy) < 200:
        return "unknown"
    closes = spy["close"].to_numpy(dtype=float)
    return "risk-on" if closes[0] > closes.mean() else "risk-off"


# --------------------------------------------------------------------------- #
# formatting
# --------------------------------------------------------------------------- #
def fmt_pct(v: float) -> str:
    """Signed 0dp percent with a unicode minus, e.g. +71% / −8%."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "·"
    n = int(round(v * 100))
    sign = "+" if n >= 0 else "−"
    return f"{sign}{abs(n)}%"


def render_md(screen_date, eligible_n, passing, near, regime, new_n, truncated) -> str:
    lines = [
        f"# Screen — {screen_date.isoformat()}  "
        f"(universe: {eligible_n} · passing: {len(passing)} · "
        f"new today: {new_n} · regime: {regime})",
        "",
        "## ✅ Passing (template 8/8, RS ≥ 70) — RS-ranked",
        "| Ticker | Close | RS | 50d | 200d | off low | off high | base | vol | new |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in passing[:TABLE_CAP]:
        lines.append(
            f"| {r['ticker']} | {r['close']:.2f} | {int(r['rs_rank'])} | "
            f"{fmt_pct(r['dist_50d'])} | {fmt_pct(r['dist_200d'])} | "
            f"{fmt_pct(r['off_52w_low'])} | {fmt_pct(r['off_52w_high'])} | "
            f"{'tight' if r['base_tight'] else '·'} | "
            f"{'dry' if r['vol_dryup'] else '·'} | "
            f"{'★' if r['new_today'] else '·'} |"
        )
    if not passing:
        lines.append("| _none_ | | | | | | | | | |")
    if truncated.get("passing"):
        lines.append(f"\n_… truncated to {TABLE_CAP} of {len(passing)} passing rows._")

    lines += [
        "",
        "## 👀 Near-miss (6–7/8) — one/two checks from passing",
        "| Ticker | Score | Failing checks | RS |",
        "|---|---|---|---|",
    ]
    for r in near[:TABLE_CAP]:
        lines.append(
            f"| {r['ticker']} | {int(r['template_score'])}/8 | "
            f"{r['failing']} | {int(r['rs_rank'])} |"
        )
    if not near:
        lines.append("| _none_ | | | |")
    if truncated.get("near"):
        lines.append(f"\n_… truncated to {TABLE_CAP} of {len(near)} near-miss rows._")

    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# watchlist
# --------------------------------------------------------------------------- #
_TICKER_RE = re.compile(r"^[A-Z][A-Z.\-]{0,4}$")


def parse_watchlist(path: Path) -> list[str]:
    """Tickers from any markdown table row whose first cell is 1–5 uppercase
    letters/dots/hyphens (starting with a letter, so '---' separators and the
    '_—_' placeholder are skipped)."""
    if not path.exists():
        return []
    out: list[str] = []
    for line in path.read_text().splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        first = s.strip("|").split("|")[0].strip()
        if _TICKER_RE.match(first) and first not in out:
            out.append(first)
    return out


# --------------------------------------------------------------------------- #
# outputs
# --------------------------------------------------------------------------- #
def write_eod(con, screen_date, tickers, eod_dir: Path) -> list[str]:
    """Write last 250 bars per ticker. Returns tickers skipped (not in DB)."""
    eod_dir.mkdir(parents=True, exist_ok=True)
    missing = []
    for tk in tickers:
        df = con.execute(
            "SELECT date, open, high, low, close, volume FROM prices "
            "WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT 250",
            [tk, screen_date],
        ).fetch_df()
        if df.empty:
            missing.append(tk)
            continue
        df = df.sort_values("date")
        df.to_csv(eod_dir / f"{tk}.csv", index=False)
    return missing


def update_meta(meta_path: Path, **updates) -> None:
    """Read-modify-write _meta.json, preserving existing keys."""
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except json.JSONDecodeError:
            meta = {}
    meta.update(updates)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, indent=2))


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def run(db_path: str, data_dir: Path, requested_date: str | None, rerun: bool,
        skip_if_done: bool = False) -> int:
    con = db.connect(db_path)
    db.init_schema(con)

    screen_date = resolve_screen_date(con, requested_date)
    print(f"[screen] screen date = {screen_date.isoformat()}")

    # Append-only guard (fail fast before any heavy compute).
    existing = con.execute(
        "SELECT COUNT(*) FROM screen_results WHERE run_date = ?", [screen_date]
    ).fetchone()[0]
    if existing:
        if not rerun:
            if skip_if_done:
                # Benign no-op for the unattended nightly: on a weekend/holiday run
                # collect no-ops and MAX(date) doesn't advance, so the latest date is
                # already screened. Exit 0 (not 1) so the nightly proceeds to the
                # league step; a genuine failure below still returns 1.
                print(
                    f"[screen] {screen_date} already screened ({existing} rows); "
                    f"--skip-if-done → no-op, exit 0"
                )
                con.close()
                return 0
            print(
                f"[screen] ABORT: {existing} rows already exist for {screen_date} "
                f"— screen_results is append-only. Pass --rerun to overwrite this "
                f"date (same-day correction only)."
            )
            con.close()
            return 1
        con.execute("DELETE FROM screen_results WHERE run_date = ?", [screen_date])
        print(f"[screen] --rerun: deleted {existing} existing rows for {screen_date}")

    cutoff = stale_cutoff(con, screen_date)
    eligible, n_stale, n_short = classify_universe(con, screen_date, cutoff)
    print(
        f"[screen] active&liquid → screened={len(eligible)} "
        f"skipped_stale={n_stale} skipped_short={n_short}"
    )
    if not eligible:
        print("[screen] no eligible names — nothing to screen")
        con.close()
        return 1

    bars = pull_bars(con, screen_date, eligible)
    records = [
        _compute_ticker(tk, g) for tk, g in bars.groupby("ticker", sort=False)
    ]
    res = pd.DataFrame.from_records(records)

    # RS rank: cross-sectional percentile of rs_raw scaled to 1..99 (integer).
    pct = res["rs_raw"].rank(method="average", pct=True)
    res["rs_rank"] = np.clip(np.round(pct * 99), 1, 99).fillna(1).astype(int)

    # Check 8 + template score / pass flag.
    res["c8"] = res["rs_rank"] >= 70
    cols = ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"]
    res["template_score"] = res[cols].sum(axis=1).astype(int)
    res["passes_template"] = res["template_score"] == 8

    # new_today: passes today but not in the passing set of the most recent
    # prior run_date. First run → all False.
    prior_run = con.execute(
        "SELECT MAX(run_date) FROM screen_results WHERE run_date < ?", [screen_date]
    ).fetchone()[0]
    first_run = prior_run is None
    prior_pass: set[str] = set()
    if not first_run:
        prior_pass = {
            r[0]
            for r in con.execute(
                "SELECT ticker FROM screen_results "
                "WHERE run_date = ? AND passes_template = TRUE",
                [prior_run],
            ).fetchall()
        }
    res["new_today"] = res["passes_template"] & ~res["ticker"].isin(prior_pass)
    if first_run:
        res["new_today"] = False

    regime = compute_regime(con, screen_date)

    # Persist screen_results (append-only; rerun already cleared the date).
    res["run_date"] = screen_date
    out_cols = [
        "run_date", "ticker", "close", "rs_rank", "template_score",
        "passes_template", "dist_50d", "dist_200d", "off_52w_low",
        "off_52w_high", "base_tight", "vol_dryup", "new_today",
    ]
    con.register("_res", res[out_cols])
    con.execute(f"INSERT INTO screen_results SELECT {', '.join(out_cols)} FROM _res")
    con.unregister("_res")

    passing_n = int(res["passes_template"].sum())
    new_n = int(res["new_today"].sum())
    print(
        f"[screen] passing={passing_n} new_today={new_n} regime={regime}"
        + (" (first run)" if first_run else "")
    )

    # ----- build md tables -----
    passing = (
        res[res["passes_template"]]
        .sort_values(["rs_rank", "ticker"], ascending=[False, True])
        .to_dict("records")
    )
    near_df = res[res["template_score"].isin([6, 7])].copy()

    def failing(row) -> str:
        return ", ".join(
            CHECK_LABELS[i] for i in range(8) if not row[cols[i]]
        )

    near_df["failing"] = near_df.apply(failing, axis=1)
    near = (
        near_df.sort_values(
            ["template_score", "rs_rank", "ticker"], ascending=[False, False, True]
        ).to_dict("records")
    )
    truncated = {"passing": len(passing) > TABLE_CAP, "near": len(near) > TABLE_CAP}

    md = render_md(
        screen_date, len(eligible), passing, near, regime, new_n, truncated
    )

    screens_dir = data_dir / "screens"
    screens_dir.mkdir(parents=True, exist_ok=True)
    md_path = screens_dir / f"{screen_date.isoformat()}.md"
    md_path.write_text(md)
    shutil.copyfile(md_path, screens_dir / "latest.md")

    # CSV: every screen_results column for this run.
    csv_df = con.execute(
        "SELECT * FROM screen_results WHERE run_date = ? "
        "ORDER BY passes_template DESC, rs_rank DESC",
        [screen_date],
    ).fetch_df()
    csv_df.to_csv(screens_dir / f"{screen_date.isoformat()}.csv", index=False)

    # ----- eod files: watchlist ∪ top-100-by-RS passing -----
    watchlist = parse_watchlist(WATCHLIST_PATH)
    top_pass = [r["ticker"] for r in passing[:TABLE_CAP]]
    eod_set: list[str] = []
    for tk in watchlist + top_pass:
        if tk not in eod_set:
            eod_set.append(tk)
    missing = write_eod(con, screen_date, eod_set, data_dir / "eod")
    if missing:
        print(f"[screen] eod: skipped {len(missing)} watchlist names not in DB: "
              f"{', '.join(missing)}")

    # ----- _meta.json -----
    update_meta(
        data_dir / "_meta.json",
        regime=regime,
        last_screen=datetime.now(timezone.utc).isoformat(),
        passing_count=passing_n,
        new_today_count=new_n,
        screened=len(eligible),
        skipped_stale=n_stale,
        skipped_short=n_short,
    )

    print(f"[screen] wrote {md_path} (+ latest.md, csv, {len(eod_set) - len(missing)} eod files)")
    con.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="M1 trend-template screener.")
    ap.add_argument("--db", default=str(db.DEFAULT_DB), help="DuckDB path")
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="output dir")
    ap.add_argument("--date", default=None, help="screen date YYYY-MM-DD (default: latest bar)")
    ap.add_argument("--skip-if-done", action="store_true",
                    help="exit 0 (not 1) if the date is already screened — for the "
                         "unattended nightly, where a weekend/holiday run re-sees the "
                         "same MAX(date). Real failures still return 1.")
    ap.add_argument("--rerun", action="store_true",
                    help="overwrite an existing run_date (same-day correction only)")
    args = ap.parse_args()
    return run(args.db, Path(args.data_dir), args.date, args.rerun,
               skip_if_done=args.skip_if_done)


if __name__ == "__main__":
    raise SystemExit(main())
