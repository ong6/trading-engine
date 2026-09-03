#!/usr/bin/env python
"""M4 backtest farm — pre-registered experiment runner (spec §12.3).

An experiment is a FROZEN config file (farm/experiments/<id>.yaml). This runner:
  * loads a config and hashes it (immutability key),
  * backtests it on daily bars from the DuckDB store (prices read-only),
  * computes the full anti-overfitting stat pack (stats.py): per-trade returns,
    mean/std/t-stat, annualized gross & net, Sharpe AND Deflated Sharpe (haircut
    for variants tried), max drawdown, and subperiod / regime splits,
  * splits IN-SAMPLE vs a LOCKED HOLDOUT (the most recent N months) explicitly —
    the holdout is computed exactly once and reported separately,
  * appends every result (negative ones included) to the append-only
    `experiment_results` table AND writes data/reports/experiments/<id>.md.

Immutability: a result row stores the config hash. Re-running a CHANGED config
under the same id is REFUSED. Re-running the identical config is a no-op (the
holdout is never re-touched).

DB discipline (spec): prices are read READ-ONLY; the results append opens the DB
read-write only briefly, with retry on the single-writer lock. If the store stays
locked, results are written to farm/pending-results/<id>.json instead and the
report still gets written.

Entry points:
  CLI:   farm/experiment.py run    --id e1-spy-monday
         farm/experiment.py verify --id e1-spy-monday   (prints partitions/hand-checks)
  Queue: run_job(params, con, meta_path=None)  — dispatch-table callable for
         engine/queue_runner.py (see the report for the one-line registration).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from engine.lib import db as enginedb
from engine.lib.log import get_logger
from engine.lib.settings import DATA_DIR, DEFAULT_DB, REPO_ROOT  # noqa: F401
from farm import stats as fstats

log = get_logger("farm")

EXPERIMENTS_DIR = Path(__file__).resolve().parent / "experiments"
PENDING_DIR = Path(__file__).resolve().parent / "pending-results"
REPORTS_DIR = DATA_DIR / "reports" / "experiments"

WEEKDAY_MAP = {"monday": 0, "tuesday": 1, "wednesday": 2,
               "thursday": 3, "friday": 4}
LOCK_RETRIES = 6
LOCK_SLEEP_S = 5.0
REGIME_MIN_BARS = 200        # bars needed before a Monday to define the regime


# --------------------------------------------------------------------------- #
# config load + hash (immutability)
# --------------------------------------------------------------------------- #
def load_config(path: Path) -> dict:
    cfg = yaml.safe_load(path.read_text())
    if not isinstance(cfg, dict) or "id" not in cfg:
        raise SystemExit(f"[farm] {path} is not a valid experiment config")
    return cfg


def config_hash(cfg: dict) -> str:
    """SHA-256 over the canonicalized PARSED config (the YAML mapping, not the
    file text). Any change to a config VALUE alters the hash and is refused under
    the same id once a result exists. Comments and formatting are not part of the
    parsed mapping, so editing them leaves the hash unchanged."""
    canonical = json.dumps(cfg, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def resolve_config(cfg_id: str | None, cfg_path: str | None) -> tuple[dict, Path]:
    if cfg_path:
        p = Path(cfg_path)
    elif cfg_id:
        p = EXPERIMENTS_DIR / f"{cfg_id}.yaml"
        if not p.exists():
            p = EXPERIMENTS_DIR / f"{cfg_id}.json"
    else:
        raise SystemExit("[farm] need --id or --config")
    if not p.exists():
        raise SystemExit(f"[farm] config not found: {p}")
    return load_config(p), p


# --------------------------------------------------------------------------- #
# holdout data-window pin (locks the "computed once" holdout window)
# --------------------------------------------------------------------------- #
# The holdout is the most-recent-N-months slice of the data. If the cutoff were
# re-derived from the LIVE max bar on every regeneration, a growing store would
# silently advance the holdout window while the report still claims "computed
# once". So at first registration we PIN the data as-of (the max_date used) and
# reuse it forever after: subsequent runs cap the trade set to the pinned as-of
# and derive the cutoff from it, so both partitions are byte-for-byte reproducible
# regardless of how much the store has grown. Simplest correct mechanism: a
# sidecar next to the frozen YAML, created once and never overwritten.
def _pin_path(cfg_id: str) -> Path:
    return EXPERIMENTS_DIR / f"{cfg_id}.lock.json"


def _read_pin(cfg_id: str) -> date | None:
    """Return the pinned data as-of date, or None if no pin exists yet."""
    p = _pin_path(cfg_id)
    if not p.exists():
        return None
    try:
        s = json.loads(p.read_text()).get("data_as_of")
        return date.fromisoformat(s) if s else None
    except Exception:  # noqa: BLE001 - a corrupt pin must not break the run
        return None


def _write_pin(cfg_id: str, data_as_of: date) -> None:
    """Create the pin ONCE. Never overwrites an existing pin (the window is
    frozen at first registration, same as the config)."""
    p = _pin_path(cfg_id)
    if p.exists():
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"data_as_of": str(data_as_of)}, indent=2) + "\n")


def _recover_pin_from_db(con, cfg_id: str) -> date | None:
    """Back-fill the pin for an experiment registered BEFORE this pinning logic
    existed: read the data as-of from the earliest stored 'full' result row's
    meta_json (that row was written against the original data window). Read-only,
    tolerant of a missing table/column. Returns the recovered date or None."""
    try:
        row = con.execute(
            "SELECT meta_json FROM experiment_results "
            "WHERE experiment_id = ? AND partition = 'full' "
            "ORDER BY run_at ASC LIMIT 1",
            [cfg_id],
        ).fetchone()
    except Exception:  # noqa: BLE001 - table may not exist yet
        return None
    if not row or not row[0]:
        return None
    try:
        meta = json.loads(row[0])
        s = meta.get("data_as_of") or meta.get("max_date")
        return date.fromisoformat(s) if s else None
    except Exception:  # noqa: BLE001
        return None


def _resolve_pin(cfg_id: str, con=None) -> date | None:
    """Pinned as-of if one exists: sidecar first, else recover from DB (and
    back-fill the sidecar so it is stable thereafter). None on a first run."""
    pinned = _read_pin(cfg_id)
    if pinned is not None or con is None:
        return pinned
    recovered = _recover_pin_from_db(con, cfg_id)
    if recovered is not None:
        _write_pin(cfg_id, recovered)
    return recovered


# --------------------------------------------------------------------------- #
# backtest — build the per-trade return series from daily bars
# --------------------------------------------------------------------------- #
def _pull_instrument(con, ticker: str) -> pd.DataFrame:
    df = con.execute(
        "SELECT date, open, high, low, close, volume FROM prices "
        "WHERE ticker = ? ORDER BY date",
        [ticker],
    ).fetch_df()
    if df.empty:
        raise SystemExit(f"[farm] no bars in store for {ticker}")
    df["date"] = pd.to_datetime(df["date"])
    return df


def _regime_series(bars: pd.DataFrame) -> pd.Series:
    """Regime known BEFORE each bar's open: prior-day close vs its 200d SMA.
    Value on row i uses bars strictly before i (shift(1)) — no look-ahead.
    'risk-on' / 'risk-off' / 'unknown' (fewer than 200 prior bars)."""
    close = bars["close"].astype(float)
    sma200 = close.rolling(200).mean()
    prior_close = close.shift(1)
    prior_sma = sma200.shift(1)
    reg = pd.Series("unknown", index=bars.index)
    known = prior_sma.notna()
    reg[known & (prior_close > prior_sma)] = "risk-on"
    reg[known & (prior_close <= prior_sma)] = "risk-off"
    return reg


def build_trades(cfg: dict, con) -> pd.DataFrame:
    """One row per taken trade: date, open, close, gross, net, regime.

    Entry rule 'weekday_open' + exit 'same_day_close': same-bar open->close on
    the target weekday. Cost applied multiplicatively (buy up, sell down) at
    half the round-trip on each side.
    """
    ticker = cfg["instrument"]
    entry = cfg.get("entry", {})
    if entry.get("rule") != "weekday_open":
        raise SystemExit(f"[farm] unsupported entry rule {entry.get('rule')!r}")
    if cfg.get("exit", {}).get("rule") != "same_day_close":
        raise SystemExit(f"[farm] unsupported exit rule {cfg.get('exit', {}).get('rule')!r}")
    wd = WEEKDAY_MAP.get(str(entry.get("weekday", "")).lower())
    if wd is None:
        raise SystemExit(f"[farm] bad weekday {entry.get('weekday')!r}")

    bars = _pull_instrument(con, ticker)
    bars["regime"] = _regime_series(bars)

    sel = bars[bars["date"].dt.weekday == wd].copy()
    # a tradeable bar needs a real open and close
    sel = sel[sel["open"].notna() & sel["close"].notna() & (sel["open"] > 0)]

    rt_bps = float(cfg.get("cost", {}).get("roundtrip_bps", 0.0))
    h = (rt_bps / 2.0) / 1e4                     # per-side fraction
    gross = sel["close"].to_numpy(float) / sel["open"].to_numpy(float) - 1.0
    net = (sel["close"].to_numpy(float) * (1 - h)) / (sel["open"].to_numpy(float) * (1 + h)) - 1.0

    return pd.DataFrame({
        "date": sel["date"].dt.date.to_numpy(),
        "open": sel["open"].to_numpy(float),
        "close": sel["close"].to_numpy(float),
        "gross": gross,
        "net": net,
        "regime": sel["regime"].to_numpy(),
    })


# --------------------------------------------------------------------------- #
# partitioning + stats
# --------------------------------------------------------------------------- #
def _years_span(dates) -> float:
    if len(dates) < 2:
        return float("nan")
    d0, d1 = min(dates), max(dates)
    return max(1e-9, (d1 - d0).days / 365.25)


def _stats_for(sub: pd.DataFrame, variants: int | None) -> fstats.SeriesStats:
    return fstats.compute(
        sub["gross"].to_numpy(float), sub["net"].to_numpy(float),
        _years_span(list(sub["date"])), variants,
    )


def holdout_cutoff(max_date: date, months: int) -> date:
    """First day of the locked holdout window: max_date minus `months` months.
    Trades on/after this date are holdout; before it are in-sample."""
    y, m = max_date.year, max_date.month - months
    while m <= 0:
        m += 12
        y -= 1
    # clamp day to a valid day of the target month
    day = min(max_date.day, [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28,
                             31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return date(y, m, day)


def evaluate(cfg: dict, con, pinned_as_of: date | None = None) -> dict:
    """Run the full experiment (read-only). Returns a structured result dict.

    pinned_as_of: if set (an experiment already registered), the analysis window
    is LOCKED to it — trades after the pinned as-of are dropped and the holdout
    cutoff is derived from the pin, so the holdout is reproducible even as the
    live store grows. If None (first registration), the live max bar is used and
    becomes the pin the caller persists."""
    trades = build_trades(cfg, con)
    variants = cfg.get("variants_tried")
    months = int(cfg.get("holdout", {}).get("months", 12))

    live_max = max(trades["date"])
    if pinned_as_of is not None:
        # Lock the window: exclude anything after the pinned as-of so both the
        # in-sample and holdout partitions match the first registration exactly.
        trades = trades[trades["date"] <= pinned_as_of].reset_index(drop=True)
        data_as_of = pinned_as_of
    else:
        data_as_of = live_max

    max_d = data_as_of
    min_d = min(trades["date"])
    cutoff = holdout_cutoff(max_d, months)

    in_sample = trades[trades["date"] < cutoff].reset_index(drop=True)
    holdout = trades[trades["date"] >= cutoff].reset_index(drop=True)

    partitions: dict[str, fstats.SeriesStats] = {
        "full": _stats_for(trades, variants),
        "in_sample": _stats_for(in_sample, variants),
        "holdout": _stats_for(holdout, variants),
    }

    # 5-year blocks over the IN-SAMPLE data only (holdout stays sacred/separate).
    blocks: dict[str, fstats.SeriesStats] = {}
    if len(in_sample):
        y0 = min(in_sample["date"]).year
        y0 = y0 - (y0 % 5)
        for start in range(y0, max(in_sample["date"]).year + 1, 5):
            end = start + 5
            blk = in_sample[[start <= d.year < end for d in in_sample["date"]]]
            if len(blk):
                blocks[f"{start}-{end - 1}"] = _stats_for(blk, variants)

    # regime split over in-sample (regime known before each Monday open).
    regimes: dict[str, fstats.SeriesStats] = {}
    for r in ("risk-on", "risk-off"):
        sub = in_sample[in_sample["regime"] == r]
        if len(sub):
            regimes[r] = _stats_for(sub, variants)
    n_unknown_regime = int((in_sample["regime"] == "unknown").sum()) if len(in_sample) else 0

    # cost sensitivity: recompute NET at a conservative 20bp round-trip (sim §2 SPY tier)
    cons_h = (20.0 / 2.0) / 1e4
    cons_net_full = (trades["close"].to_numpy(float) * (1 - cons_h)) / \
                    (trades["open"].to_numpy(float) * (1 + cons_h)) - 1.0
    cons_net_is = cons_net_full[[d < cutoff for d in trades["date"]]]
    cons_stats_is = fstats.compute(
        in_sample["gross"].to_numpy(float), cons_net_is,
        _years_span(list(in_sample["date"])), variants) if len(in_sample) else None

    return {
        "trades": trades,
        "in_sample": in_sample,
        "holdout": holdout,
        "cutoff": cutoff,
        "min_date": min_d,
        "max_date": max_d,               # the as-of the window/cutoff was built on
        "data_as_of": data_as_of,        # pinned (or live) window edge
        "live_max_date": live_max,       # newest bar actually in the store
        "pinned": pinned_as_of is not None,
        "partitions": partitions,
        "blocks": blocks,
        "regimes": regimes,
        "n_unknown_regime": n_unknown_regime,
        "cons_stats_is": cons_stats_is,
        "variants": variants,
        "months": months,
    }


def verdict(cfg: dict, res: dict) -> str:
    """In-sample verdict vs the registered expectation (never uses holdout)."""
    is_s = res["partitions"]["in_sample"]
    exp = float(cfg.get("expected_effect", {}).get("gross_annual", 0.0))
    gross = is_s.gross_cagr
    t = is_s.t_stat
    dsr = is_s.deflated_sharpe
    parts = []
    if is_s.mean > 0 and t is not None and not np.isnan(t) and t >= 0.5:
        parts.append("in-sample edge is positive and non-trivial (t >= 0.5)")
    else:
        parts.append("in-sample edge is weak or absent (mean <= 0 or t < 0.5)")
    if not np.isnan(gross):
        ratio = gross / exp if exp else float("nan")
        parts.append(f"gross CAGR {gross*100:.2f}%/yr vs registered {exp*100:.0f}%/yr "
                     f"({ratio:.2f}x)")
    if dsr is not None and not np.isnan(dsr):
        parts.append(f"deflated Sharpe (N={res['variants']} trials) = {dsr:.3f}")
    return "; ".join(parts)


# --------------------------------------------------------------------------- #
# persistence — experiment_results table (+ pending-results fallback)
# --------------------------------------------------------------------------- #
def ensure_results_table(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS experiment_results (
            experiment_id      VARCHAR,
            config_hash        VARCHAR,
            run_at             TIMESTAMP,
            partition          VARCHAR,
            n_trades           INTEGER,
            mean_ret           DOUBLE,
            std_ret            DOUBLE,
            t_stat             DOUBLE,
            gross_cagr         DOUBLE,
            net_cagr           DOUBLE,
            ann_mean_net       DOUBLE,
            sharpe_annual      DOUBLE,
            deflated_sharpe    DOUBLE,
            sr0_benchmark      DOUBLE,
            max_drawdown       DOUBLE,
            skew               DOUBLE,
            kurtosis           DOUBLE,
            cost_roundtrip_bps DOUBLE,
            variants_tried     INTEGER,
            hypothesis         VARCHAR,
            verdict            VARCHAR,
            meta_json          VARCHAR,
            PRIMARY KEY (experiment_id, config_hash, partition, run_at)
        )
        """
    )


def check_immutable(con, cfg_id: str, chash: str) -> str | None:
    """Returns None if OK to run. Returns 'exists' if this exact config already
    has results (idempotent skip). Raises SystemExit if a DIFFERENT config
    already has results under this id (immutability violation)."""
    rows = con.execute(
        "SELECT DISTINCT config_hash FROM experiment_results WHERE experiment_id = ?",
        [cfg_id],
    ).fetchall()
    hashes = {r[0] for r in rows}
    if not hashes:
        return None
    if hashes == {chash}:
        return "exists"
    raise SystemExit(
        f"[farm] IMMUTABILITY VIOLATION: experiment '{cfg_id}' already has results "
        f"under config hash(es) {sorted(h[:12] for h in hashes)}, but the current "
        f"config hashes to {chash[:12]}. A pre-registered config is frozen once a "
        f"result exists. Register a NEW id instead. Refusing to run."
    )


def _rows_from_res(cfg: dict, chash: str, run_at, res: dict) -> list[dict]:
    rt_bps = float(cfg.get("cost", {}).get("roundtrip_bps", 0.0))
    variants = res["variants"]
    hypo = " ".join(str(cfg.get("hypothesis", "")).split())[:900]
    vdict = verdict(cfg, res)
    out = []

    def row(part: str, s: fstats.SeriesStats, extra: dict | None = None):
        out.append({
            "experiment_id": cfg["id"], "config_hash": chash, "run_at": run_at,
            "partition": part, "n_trades": s.n, "mean_ret": s.mean, "std_ret": s.std,
            "t_stat": s.t_stat, "gross_cagr": s.gross_cagr, "net_cagr": s.net_cagr,
            "ann_mean_net": s.ann_mean_net, "sharpe_annual": s.sharpe_annual,
            "deflated_sharpe": s.deflated_sharpe, "sr0_benchmark": s.sr0_benchmark,
            "max_drawdown": s.max_drawdown, "skew": s.skew, "kurtosis": s.kurtosis,
            "cost_roundtrip_bps": rt_bps, "variants_tried": variants,
            "hypothesis": hypo, "verdict": vdict,
            "meta_json": json.dumps(extra or {}, default=str),
        })

    row("full", res["partitions"]["full"],
        {"cutoff": str(res["cutoff"]), "min_date": str(res["min_date"]),
         "max_date": str(res["max_date"]), "data_as_of": str(res["data_as_of"])})
    row("in_sample", res["partitions"]["in_sample"],
        {"cutoff": str(res["cutoff"])})
    row("holdout", res["partitions"]["holdout"],
        {"cutoff": str(res["cutoff"]), "computed_once": True})
    for label, s in res["blocks"].items():
        row(f"block:{label}", s)
    for label, s in res["regimes"].items():
        row(f"regime:{label}", s)
    return out


def append_results(con, rows: list[dict]) -> None:
    df = pd.DataFrame(rows)
    cols = list(df.columns)
    con.register("_exp_rows", df)
    # NAME the target columns. A bare `INSERT INTO t SELECT ...` is positional and
    # requires the row width to equal the table width — which silently breaks the
    # moment the table gains a column. It has: the forward phase
    # (farm/experiment_runner.py) added trade_date/gross_ret/net_ret, which a
    # backtest row leaves NULL. Naming the columns makes this append independent
    # of the table's shape.
    quoted = ", ".join(f'"{c}"' for c in cols)
    con.execute(
        f"INSERT INTO experiment_results ({quoted}) SELECT {quoted} FROM _exp_rows"
    )
    con.unregister("_exp_rows")


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
def _fmt(v, pct=False, dp=2):
    if v is None or (isinstance(v, float) and (np.isnan(v))):
        return "—"
    if pct:
        return f"{v*100:+.{dp}f}%"
    return f"{v:.{dp}f}"


def _stat_row(name, s: fstats.SeriesStats):
    return (f"| {name} | {s.n} | {_fmt(s.mean*100,dp=4)}% | {_fmt(s.t_stat)} | "
            f"{_fmt(s.gross_cagr,pct=True)} | {_fmt(s.net_cagr,pct=True)} | "
            f"{_fmt(s.sharpe_annual)} | {_fmt(s.deflated_sharpe,dp=3)} | "
            f"{_fmt(s.max_drawdown,pct=True)} |")


def render_report(cfg: dict, chash: str, res: dict, run_at, storage_note: str) -> str:
    p = res["partitions"]
    is_s, ho, full = p["in_sample"], p["holdout"], p["full"]
    exp = cfg.get("expected_effect", {})
    L = []
    L.append(f"# Experiment {cfg['id']} — SPY Monday intraday")
    L.append("")
    L.append(f"*Pre-registered {cfg.get('registered','?')} · report generated "
             f"{run_at:%Y-%m-%d %H:%M UTC} · config hash `{chash[:16]}`*")
    L.append("")
    L.append("> **Pre-registered, frozen config.** This report was produced by "
             "`farm/experiment.py` from `farm/experiments/e1-spy-monday.yaml`. The "
             "config is immutable once this result exists (hash stored in every "
             "`experiment_results` row); a changed config is refused under this id.")
    L.append("")
    L.append("## Hypothesis")
    L.append("> " + " ".join(str(cfg.get("hypothesis", "")).split()))
    L.append("")
    L.append(f"- **Instrument:** {cfg['instrument']} (single) · "
             f"**entry:** {cfg['entry']['rule']} / {cfg['entry']['weekday']} · "
             f"**exit:** {cfg['exit']['rule']} (same-bar open→close)")
    L.append(f"- **Registered expectation:** {exp.get('direction','?')}, "
             f"~{exp.get('gross_annual',0)*100:.0f}%/yr GROSS (decayed prior — not fitted). "
             f"Source: {' '.join(str(exp.get('source','')).split())}")
    L.append(f"- **Cost (registered):** {cfg['cost']['roundtrip_bps']}bp round-trip "
             f"(~{cfg['cost']['roundtrip_bps']*is_s.trades_per_year/100:.2f}%/yr at "
             f"{is_s.trades_per_year:.1f} trades/yr).")
    L.append(f"- **Kill criterion (forward):** "
             f"{' '.join(str(cfg.get('kill_criterion','')).split())}")
    L.append(f"- **Variants tried (multiple-testing N):** {res['variants']} — "
             "used for the Deflated-Sharpe haircut (see Methods).")
    L.append("")

    # data span / partition accounting
    L.append("## Data & partition accounting")
    L.append(f"- SPY daily bars used: **{res['min_date']} → {res['max_date']}** "
             f"(real data, read-only).")
    if res.get("pinned") and res.get("live_max_date") \
            and res["live_max_date"] != res["data_as_of"]:
        L.append(f"- **Data window PINNED at first registration: as-of "
                 f"{res['data_as_of']}.** The live store now extends to "
                 f"{res['live_max_date']}, but the holdout is locked to the "
                 f"original window (computed once): bars after {res['data_as_of']} "
                 f"are excluded so the holdout never silently advances.")
    L.append(f"- **Holdout = most recent {res['months']} months of Mondays**, locked at "
             f"cutoff **{res['cutoff']}** (trades on/after are holdout).")
    L.append(f"- In-sample Mondays: **{is_s.n}** · Holdout Mondays: **{ho.n}** · "
             f"Total: **{full.n}** — {is_s.n} + {ho.n} = {is_s.n + ho.n} "
             f"({'✓ sums, no overlap' if is_s.n + ho.n == full.n else '✗ MISMATCH'}).")
    L.append("")

    # headline table
    L.append("## Results — in-sample vs LOCKED HOLDOUT (holdout computed once)")
    L.append("")
    L.append("| Partition | n | mean/trade | t-stat | gross CAGR | net CAGR | "
             "ann. Sharpe | deflated Sharpe | max DD |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    L.append(_stat_row("In-sample", is_s))
    L.append(_stat_row("**Holdout (once)**", ho))
    L.append(_stat_row("Full (reference)", full))
    L.append("")
    L.append(f"- **Registered gross expectation:** {exp.get('gross_annual',0)*100:.0f}%/yr. "
             f"**In-sample gross:** {_fmt(is_s.gross_cagr,pct=True)}/yr "
             f"({is_s.gross_cagr/exp.get('gross_annual',1):.2f}× the registered prior). "
             f"**In-sample net:** {_fmt(is_s.net_cagr,pct=True)}/yr.")
    L.append(f"- **In-sample t-stat** on the per-trade net mean: **{_fmt(is_s.t_stat)}** "
             f"(mean/trade {_fmt(is_s.mean*100,dp=4)}%, sd {_fmt(is_s.std*100,dp=3)}%).")
    L.append(f"- **Deflated Sharpe (in-sample, N={res['variants']} trials):** "
             f"**{_fmt(is_s.deflated_sharpe,dp=3)}** "
             f"(benchmark SR0={_fmt(is_s.sr0_benchmark,dp=4)} per-trade; "
             f"annualized Sharpe {_fmt(is_s.sharpe_annual)}).")
    L.append("")

    # verdict
    L.append("## Verdict (in-sample only — holdout never feeds the decision)")
    L.append("")
    L.append("> " + verdict(cfg, res))
    L.append("")

    # cost sensitivity
    cs = res["cons_stats_is"]
    L.append("## Cost sensitivity (in-sample)")
    L.append(f"- Registered 3bp r/t → net CAGR **{_fmt(is_s.net_cagr,pct=True)}/yr**.")
    if cs is not None:
        L.append(f"- Conservative 20bp r/t (sim fill model, exec-design §2 SPY tier) → "
                 f"net CAGR **{_fmt(cs.net_cagr,pct=True)}/yr**, "
                 f"mean/trade {_fmt(cs.mean*100,dp=4)}%, t {_fmt(cs.t_stat)}.")
    L.append("")

    # subperiods
    L.append("## Subperiod stability (in-sample, 5-year blocks)")
    L.append("")
    L.append("| Block | n | mean/trade | t-stat | gross CAGR | net CAGR | ann. Sharpe |")
    L.append("|---|--:|--:|--:|--:|--:|--:|")
    for label, s in res["blocks"].items():
        L.append(f"| {label} | {s.n} | {_fmt(s.mean*100,dp=4)}% | {_fmt(s.t_stat)} | "
                 f"{_fmt(s.gross_cagr,pct=True)} | {_fmt(s.net_cagr,pct=True)} | "
                 f"{_fmt(s.sharpe_annual)} |")
    L.append("")
    L.append("_The decay hypothesis predicts the earliest blocks carry the effect and "
             "later blocks fade — read the trend, not any single block._")
    L.append("")

    # regime
    L.append("## Regime split (in-sample)")
    L.append("")
    L.append("_Regime = SPY prior-day close vs its 200-day SMA, known BEFORE the Monday "
             "open (no look-ahead). The store's `screen_results.regime` only covers "
             "2026-07-15→17 (3 days), so it is unusable historically; regime is computed "
             "from SPY price history instead — stated honestly._")
    L.append("")
    L.append("| Regime | n | mean/trade | t-stat | gross CAGR | net CAGR | ann. Sharpe |")
    L.append("|---|--:|--:|--:|--:|--:|--:|")
    for label, s in res["regimes"].items():
        L.append(f"| {label} | {s.n} | {_fmt(s.mean*100,dp=4)}% | {_fmt(s.t_stat)} | "
                 f"{_fmt(s.gross_cagr,pct=True)} | {_fmt(s.net_cagr,pct=True)} | "
                 f"{_fmt(s.sharpe_annual)} |")
    if res["n_unknown_regime"]:
        L.append(f"\n_({res['n_unknown_regime']} early in-sample Mondays had < 200 prior "
                 "bars to define a regime and are excluded from this split only.)_")
    L.append("")

    # methods
    L.append("## Methods & honesty notes")
    L.append("- **No look-ahead:** the entry is the Monday open and the exit is the same "
             "bar's close — the open is known before the close. No signal or filter uses "
             "any data at/after the Monday open. Regime uses only the prior day.")
    L.append("- **Costs** applied multiplicatively: buy at open·(1+h), sell at close·(1−h), "
             "h = round-trip_bps/2/1e4.")
    L.append("- **CAGR** is geometric on the compounded per-trade equity curve over the "
             "partition's calendar span; the strategy is flat except on Mondays.")
    L.append("- **Annualized Sharpe** = (mean/sd per trade)·√(trades/yr), rf=0.")
    L.append("- **Deflated Sharpe Ratio** (Bailey & López de Prado 2014) = PSR(SR0), where "
             "PSR(SR*) = Φ[(SR−SR*)·√(n−1) / √(1−γ₃·SR + ((γ₄−1)/4)·SR²)] with γ₃ skew, "
             "γ₄ non-excess kurtosis, and the deflation benchmark "
             "SR0 = √V·[(1−γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(Ne))], γ=0.5772 (Euler-Mascheroni), "
             "N = variants tried. **V (variance of trial Sharpes) is unknown**, so we use "
             "the SR-estimator sampling variance V = (1−γ₃·SR+((γ₄−1)/4)·SR²)/(n−1) as a "
             "documented, conservative fallback. DSR is a probability the true SR>0 after "
             "the multiple-testing/non-normality haircut.")
    L.append(f"- **Skew/kurtosis (in-sample per-trade):** skew {_fmt(is_s.skew,dp=3)}, "
             f"kurtosis {_fmt(is_s.kurtosis,dp=2)} (Gaussian = 3).")
    L.append("- **Negative results are reported as prominently as positive ones** — the "
             "farm exists to kill bad ideas cheaply.")
    L.append(f"- **Storage:** {storage_note}")
    L.append("")
    L.append("## Forward (out-of-sample) plan")
    L.append(f"- The kill criterion runs FORWARD from league go-live: "
             f"{' '.join(str(cfg.get('kill_criterion','')).split())}")
    L.append("- The holdout above was touched exactly once, at this publication, and is "
             "not the forward test — the forward test is new Mondays after go-live.")
    L.append(f"- **The forward record is live and published separately: "
             f"[`{cfg['id']}-forward.md`](./{cfg['id']}-forward.md)** — one row per "
             f"out-of-sample Monday from 2026-07-20, written nightly by "
             f"`farm/experiment_runner.py`, accumulating toward the 40-Monday kill "
             f"evaluation.")
    L.append("")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
# Both are thin wrappers over the one connection factory (engine.lib.db.connect);
# the names stay because run_standalone reads as "RO compute, then brief RW append".
def _connect_ro(db_path):
    return enginedb.connect(db_path, read_only=True)


def _connect_rw_retry(db_path):
    return enginedb.connect(db_path, wait_s=LOCK_RETRIES * LOCK_SLEEP_S)


def _write_report(cfg, chash, res, run_at, storage_note):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{cfg['id']}.md"
    path.write_text(render_report(cfg, chash, res, run_at, storage_note))
    return path


def run_standalone(cfg_id, cfg_path, db_path) -> int:
    """CLI path: RO price read + compute, then brief RW append with retry, then
    report. Falls back to pending-results/<id>.json if the store stays locked."""
    cfg, path = resolve_config(cfg_id, cfg_path)
    chash = config_hash(cfg)
    log.info(f"[farm] {cfg['id']} config hash {chash[:16]} (from {path})")

    # 1) compute read-only (pin the data window so the holdout is reproducible)
    ro = _connect_ro(db_path)
    try:
        pinned = _resolve_pin(cfg["id"], ro)
        res = evaluate(cfg, ro, pinned_as_of=pinned)
    finally:
        ro.close()
    run_at = datetime.now(timezone.utc)
    rows = _rows_from_res(cfg, chash, run_at, res)

    # 2) brief RW: immutability check + append
    storage_note = ""
    try:
        rw = _connect_rw_retry(db_path)
    except Exception as exc:  # noqa: BLE001
        pend = PENDING_DIR / f"{cfg['id']}.json"
        PENDING_DIR.mkdir(parents=True, exist_ok=True)
        pend.write_text(json.dumps(rows, indent=2, default=str))
        storage_note = (f"store stayed LOCKED ({exc}); results written to {pend} "
                        f"(append to experiment_results later).")
        log.info(f"[farm] {storage_note}")
        _write_report(cfg, chash, res, run_at, storage_note)
        return 0

    try:
        ensure_results_table(rw)
        state = check_immutable(rw, cfg["id"], chash)  # may SystemExit
        if state == "exists":
            storage_note = ("identical config already has results — append skipped "
                            "(holdout not re-touched); report refreshed.")
            log.info(f"[farm] {storage_note}")
        else:
            append_results(rw, rows)
            _write_pin(cfg["id"], res["data_as_of"])   # pin at first registration
            storage_note = (f"{len(rows)} rows appended to experiment_results "
                            f"(append-only) at {run_at:%Y-%m-%d %H:%M UTC}.")
            log.info(f"[farm] {storage_note}")
    finally:
        rw.close()

    p = _write_report(cfg, chash, res, run_at, storage_note)
    log.info(f"[farm] report → {p}")
    _print_summary(cfg, res)
    return 0


def run_job(params: dict, con, meta_path=None) -> None:
    """Queue dispatch entry point (engine/queue_runner.py contract:
    fn(params, con, meta_path=...)). `con` is the runner's read-write connection
    on the real store, so we use it for both the price read and the append."""
    cfg_id = params.get("id")
    cfg_path = params.get("config")
    if not cfg_id and not cfg_path:
        raise ValueError("experiment job needs params {'id': ...} or {'config': ...}")
    cfg, path = resolve_config(cfg_id, cfg_path)
    chash = config_hash(cfg)
    ensure_results_table(con)
    # Pin the data window (sidecar, or recover+back-fill from an existing result
    # row) so a grown store cannot silently advance a "computed once" holdout.
    pinned = _resolve_pin(cfg["id"], con)
    res = evaluate(cfg, con, pinned_as_of=pinned)  # price read on the shared con
    run_at = datetime.now(timezone.utc)
    rows = _rows_from_res(cfg, chash, run_at, res)
    state = check_immutable(con, cfg["id"], chash)  # raises on violation
    if state == "exists":
        note = "identical config already has results — append skipped (holdout intact)."
    else:
        append_results(con, rows)
        _write_pin(cfg["id"], res["data_as_of"])   # pin at first registration
        note = f"{len(rows)} rows appended to experiment_results."
    _write_report(cfg, chash, res, run_at, note)
    log.info(f"[farm] job {cfg['id']}: {note}")


def _print_summary(cfg, res):
    is_s, ho = res["partitions"]["in_sample"], res["partitions"]["holdout"]
    print("\n=== E1 headline ===")
    print(f"  in-sample: n={is_s.n} gross CAGR={is_s.gross_cagr*100:.2f}%/yr "
          f"net CAGR={is_s.net_cagr*100:.2f}%/yr t={is_s.t_stat:.2f} "
          f"annSharpe={is_s.sharpe_annual:.2f} DSR={is_s.deflated_sharpe:.3f}")
    print(f"  HOLDOUT  : n={ho.n} gross CAGR={ho.gross_cagr*100:.2f}%/yr "
          f"net CAGR={ho.net_cagr*100:.2f}%/yr t={ho.t_stat:.2f} "
          f"mean/trade={ho.mean*100:.4f}%")
    print(f"  cutoff={res['cutoff']}  span={res['min_date']}→{res['max_date']}")


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="M4 backtest-farm experiment runner.")
    ap.add_argument("cmd", choices=["run", "verify"], help="run = compute+persist+report")
    ap.add_argument("--id", default=None, help="experiment id (config in farm/experiments/)")
    ap.add_argument("--config", default=None, help="explicit config path")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="DuckDB path")
    args = ap.parse_args()

    if args.cmd == "verify":
        cfg, path = resolve_config(args.id, args.config)
        ro = _connect_ro(args.db)
        try:
            res = evaluate(cfg, ro)
        finally:
            ro.close()
        _print_summary(cfg, res)
        print("\npartitions:", {k: v.n for k, v in res["partitions"].items()})
        print("blocks:", {k: v.n for k, v in res["blocks"].items()})
        print("regimes:", {k: v.n for k, v in res["regimes"].items()},
              "unknown:", res["n_unknown_regime"])
        return 0

    return run_standalone(args.id, args.config, args.db)


if __name__ == "__main__":
    raise SystemExit(main())
