#!/usr/bin/env python
"""The backtest farm's proof harness — run the evidence, don't assert it.

Three checks, each reproducible from a clean tree against the live store (which
is only ever COPIED, never opened for writing):

  --screen-equivalence
      Copies the store, recomputes the screen for three live screen dates with
      `hist_screen` (membership='live', all rows) and diffs every column against
      (a) the STORED live rows and (b) a FRESH `engine/screen.py --rerun` on the
      same copy. (b) is the real formula proof — it holds data constant. (a) is
      the interesting one anyway: its residual differences are pure data drift
      (names delisted out of `universe`, closes restated by the corporate-actions
      reconciler), which is survivorship caught in the act.

  --replay-fidelity
      Copies the store, truncates `prices` at the window end and wipes the sim
      tables, runs the EXISTING `sim/backtest_shakedown.py` over 2026-06-22 →
      2026-07-16 with `--ensure-screens`, then runs the new replay driver over
      the same span off the same screens (`--screen-source m1`) and compares
      sim_orders / sim_fills / sim_equity / sim_positions / sim_dividends row for
      row. Both paths drive the same league code, so anything short of equality
      is a bug in the new driver.

  --stats-sanity
      Replays `spy_benchmark` over 1y and recomputes equity, CAGR, vol, Sharpe,
      Sharpe-excess-vs-BIL and max drawdown from SPY's bars with an independent
      implementation that imports none of `farm/backtest`. Also asserts the
      BIL excess Sharpe is BELOW the raw Sharpe (a positive cash rate must cost
      the ratio something).

Everything lands under scratch/proofs/ and is removed on success.
"""
from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import duckdb  # noqa: E402
import numpy as np  # noqa: E402

from lib import db  # noqa: E402

if __package__:
    from . import hist_screen  # noqa: E402
    from .replay import run_replay  # noqa: E402
else:  # pragma: no cover
    from farm.backtest import hist_screen  # noqa: E402
    from farm.backtest.replay import run_replay  # noqa: E402

LIVE_DB = REPO_ROOT / "store" / "market.duckdb"
PROOF_DIR = REPO_ROOT / "scratch" / "proofs"
PY = str(REPO_ROOT / ".venv" / "bin" / "python")

EQUIV_DATES = [date(2026, 7, 15), date(2026, 7, 21), date(2026, 7, 28)]
FIDELITY_START = date(2026, 6, 22)
FIDELITY_END = date(2026, 7, 16)
FIDELITY_BOOKS = ["template_top10_banded", "mr_overlay"]


def _copy_store(name: str) -> Path:
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    dst = PROOF_DIR / name
    if dst.exists():
        dst.unlink()
    shutil.copyfile(LIVE_DB, dst)
    return dst


def _hdr(t: str) -> None:
    print(f"\n{'=' * 72}\n{t}\n{'=' * 72}", flush=True)


# --------------------------------------------------------------------------- #
def screen_equivalence() -> bool:
    _hdr("PROOF 1 — screen equivalence (hist_screen vs engine/screen.py)")
    path = _copy_store("equiv.duckdb")
    con = db.connect(path)
    db.init_schema(con)
    con.execute("CREATE OR REPLACE TABLE sr_stored AS SELECT * FROM screen_results")
    con.execute("DROP TABLE IF EXISTS hs")
    con.execute("CREATE TABLE hs AS SELECT * FROM screen_results LIMIT 0")
    hist_screen.screen_sessions(con, EQUIV_DATES, membership="live",
                                passing_only=False, table="hs")
    con.close()

    for d in EQUIV_DATES:
        subprocess.run([PY, "engine/screen.py", "--db", str(path), "--data-dir",
                        str(PROOF_DIR / "screens"), "--date", d.isoformat(),
                        "--rerun"], cwd=REPO_ROOT, check=True,
                       capture_output=True, text=True)

    con = duckdb.connect(str(path), read_only=True)
    ok = True
    cols = ["close", "rs_rank", "template_score", "passes_template", "dist_50d",
            "dist_200d", "off_52w_low", "off_52w_high", "base_tight", "vol_dryup"]
    print("\n-- (b) vs a FRESH engine/screen.py run on the same data (formula proof)")
    for d in EQUIV_DATES:
        n_a, n_b = (con.execute(f"SELECT COUNT(*) FROM {t} WHERE run_date = ?",
                                [d]).fetchone()[0] for t in ("screen_results", "hs"))
        only = con.execute(
            "SELECT (SELECT COUNT(*) FROM (SELECT ticker FROM screen_results "
            "WHERE run_date = ? EXCEPT SELECT ticker FROM hs WHERE run_date = ?)),"
            "       (SELECT COUNT(*) FROM (SELECT ticker FROM hs WHERE run_date = ? "
            "EXCEPT SELECT ticker FROM screen_results WHERE run_date = ?))",
            [d, d, d, d]).fetchone()
        pred = " OR ".join(
            f"s.{c} IS DISTINCT FROM h.{c}" if c in ("base_tight", "vol_dryup",
                                                     "passes_template")
            else (f"ABS(s.{c} - h.{c}) > 1e-12" if c not in ("rs_rank",
                                                             "template_score")
                  else f"s.{c} <> h.{c}")
            for c in cols)
        ndiff = con.execute(
            f"SELECT COUNT(*) FROM screen_results s JOIN hs h USING (run_date, "
            f"ticker) WHERE s.run_date = ? AND ({pred})", [d]).fetchone()[0]
        good = only == (0, 0) and ndiff == 0
        ok &= good
        print(f"  {d}: live={n_a} hist={n_b} only_live={only[0]} only_hist={only[1]} "
              f"column_diffs={ndiff}  {'PASS' if good else 'FAIL'}")

    print("\n-- (a) vs the rows STORED on the day (differences = data drift since)")
    for d in EQUIV_DATES:
        drift = con.execute(
            "SELECT (SELECT COUNT(*) FROM (SELECT ticker FROM sr_stored WHERE "
            "run_date = ? EXCEPT SELECT ticker FROM hs WHERE run_date = ?)),"
            "(SELECT COUNT(*) FROM sr_stored s JOIN hs h USING (run_date, ticker) "
            "WHERE s.run_date = ? AND s.rs_rank <> h.rs_rank),"
            "(SELECT COUNT(*) FROM sr_stored s JOIN hs h USING (run_date, ticker) "
            "WHERE s.run_date = ? AND ABS(s.close - h.close) > 1e-12)",
            [d, d, d, d]).fetchone()
        names = [r[0] for r in con.execute(
            "SELECT ticker FROM (SELECT ticker FROM sr_stored WHERE run_date = ? "
            "EXCEPT SELECT ticker FROM hs WHERE run_date = ?) ORDER BY ticker",
            [d, d]).fetchall()]
        print(f"  {d}: gone_from_universe={drift[0]} {names} "
              f"rs_rank_moved={drift[1]} close_restated={drift[2]}")
    con.close()
    print(f"\nPROOF 1: {'PASS' if ok else 'FAIL'}")
    return ok


# --------------------------------------------------------------------------- #
def replay_fidelity() -> bool:
    _hdr("PROOF 2 — replay fidelity (new driver vs sim/backtest_shakedown.py)")
    path = _copy_store("fidelity.duckdb")
    con = db.connect(path)
    con.execute("DELETE FROM prices WHERE date > ?", [FIDELITY_END])
    for t in ("sim_equity", "sim_fills", "sim_orders", "sim_positions",
              "sim_dividends", "portfolios"):
        con.execute(f"DELETE FROM {t}")
    con.execute("DELETE FROM screen_results WHERE run_date > ?", [FIDELITY_END])
    n_sessions = con.execute(
        "SELECT COUNT(DISTINCT date) FROM prices WHERE date >= ?",
        [FIDELITY_START]).fetchone()[0]
    con.close()
    print(f"window {FIDELITY_START} → {FIDELITY_END} ({n_sessions} sessions)")

    r = subprocess.run([PY, "-m", "sim.backtest_shakedown", "--db", str(path),
                        "--data-dir", str(PROOF_DIR / "shakedown"),
                        "--start", str(n_sessions), "--ensure-screens"],
                       cwd=REPO_ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:], r.stderr[-2000:])
        return False
    print("shakedown done")

    live = duckdb.connect(str(path), read_only=True)
    ok = True
    try:
        for cid in FIDELITY_BOOKS:
            run_replay(live, cid, "6mo", scratch_root=PROOF_DIR / "replay",
                       screen_source="m1", keep_scratch=True, write_result=False,
                       verbose=False, override=(FIDELITY_START, FIDELITY_END))
            b = duckdb.connect(
                str(PROOF_DIR / "replay" / f"{cid}__6mo" / "replay.duckdb"),
                read_only=True)
            queries = {
                "sim_orders": "SELECT ticker, side, qty, signal_date, status, "
                              "COALESCE(reject_reason, '') FROM sim_orders "
                              "WHERE portfolio_id = ? ORDER BY signal_date, "
                              "ticker, side, qty",
                "sim_fills": "SELECT ticker, side, qty, fill_date, open_px, "
                             "fill_px, slippage_bps, cost_bps FROM sim_fills "
                             "WHERE portfolio_id = ? ORDER BY fill_date, ticker, "
                             "side, qty",
                "sim_equity": "SELECT date, equity, cash, n_positions FROM "
                              "sim_equity WHERE portfolio_id = ? ORDER BY date",
                "sim_positions": "SELECT ticker, qty, avg_cost FROM sim_positions "
                                 "WHERE portfolio_id = ? ORDER BY ticker",
                "sim_dividends": "SELECT ticker, ex_date, qty, dps, amount FROM "
                                 "sim_dividends WHERE portfolio_id = ? "
                                 "ORDER BY ex_date, ticker",
            }
            for label, sql in queries.items():
                ra = live.execute(sql, [cid]).fetchall()
                rb = b.execute(sql, [cid]).fetchall()
                same = ra == rb
                ok &= same
                print(f"  {cid:<24} {label:<14} shakedown={len(ra):>4} "
                      f"replay={len(rb):>4} identical={same}")
            b.close()
    finally:
        live.close()
    print(f"\nPROOF 2: {'PASS' if ok else 'FAIL'}")
    return ok


# --------------------------------------------------------------------------- #
def stats_sanity() -> bool:
    _hdr("PROOF 3 — stats sanity (spy_benchmark 1y vs a hand computation)")
    live = duckdb.connect(str(LIVE_DB), read_only=True)
    try:
        res = run_replay(live, "spy_benchmark", "1y", scratch_root=PROOF_DIR,
                         write_result=False, verbose=False)
        start = date.fromisoformat(res["start_date"])
        end = date.fromisoformat(res["end_date"])
        rows = live.execute(
            "SELECT date, open, close FROM prices WHERE ticker = 'SPY' AND "
            "date >= ? AND date <= ? ORDER BY date", [start, end]).fetchall()
        spydiv = dict(live.execute(
            "SELECT ex_date, value FROM corporate_actions WHERE ticker = 'SPY' "
            "AND kind = 'dividend' AND ex_date >= ? AND ex_date <= ?",
            [start, end]).fetchall())
        brows = live.execute(
            "SELECT date, close FROM prices WHERE ticker = 'BIL' AND date >= ? "
            "AND date <= ? ORDER BY date", [start, end]).fetchall()
        bdiv = dict(live.execute(
            "SELECT ex_date, value FROM corporate_actions WHERE ticker = 'BIL' "
            "AND kind = 'dividend'").fetchall())
    finally:
        live.close()

    # --- independent recomputation (imports nothing from farm/backtest) ------ #
    CASH = 39_000.0
    qty = CASH / rows[0][2]                      # signal: cash / close(d0)
    fill_px = rows[1][1] * (1 + 10.0 / 1e4)      # t+1 open, 10 bp (SPY tier)
    if qty * fill_px > CASH:
        qty = float(math.floor(CASH / fill_px))  # apply_fill's cash clamp
    cash = CASH - qty * fill_px
    eq, dates = [CASH], [rows[0][0]]
    for d, _o, c in rows[1:]:
        cash += qty * float(spydiv.get(d, 0.0))
        eq.append(cash + qty * c)
        dates.append(d)
    eq = np.array(eq)
    r = eq[1:] / eq[:-1] - 1
    years = (dates[-1] - dates[0]).days / 365.25
    hand = {
        "equity_end": float(eq[-1]),
        "total_return": float(eq[-1] / eq[0] - 1),
        "cagr": float((eq[-1] / eq[0]) ** (1 / years) - 1),
        "vol_ann": float(r.std(ddof=1) * math.sqrt(252)),
        "sharpe": float(r.mean() / r.std(ddof=1) * math.sqrt(252)),
        "max_dd": float((eq / np.maximum.accumulate(eq) - 1).min()),
    }
    bd = {brows[i][0]: (brows[i][1] + float(bdiv.get(brows[i][0], 0.0)))
          / brows[i - 1][1] - 1 for i in range(1, len(brows))}
    ex = np.array([r[i] - bd[dates[i + 1]] for i in range(len(r))
                   if dates[i + 1] in bd])
    hand["sharpe_ex_bil"] = float(ex.mean() / ex.std(ddof=1) * math.sqrt(252))

    ok = True
    print(f"{'metric':<16} {'hand':>18} {'farm':>18} {'|delta|':>10}")
    for k, v in hand.items():
        got = res[k]
        delta = abs(v - got)
        good = delta < 1e-9 * max(1.0, abs(v))
        ok &= good
        print(f"{k:<16} {v:>18.10f} {got:>18.10f} {delta:>10.2e} "
              f"{'PASS' if good else 'FAIL'}")
    lower = res["sharpe_ex_bil"] < res["sharpe"]
    ok &= lower
    print(f"\nBIL excess lowers Sharpe: {res['sharpe']:.4f} → "
          f"{res['sharpe_ex_bil']:.4f}  {'PASS' if lower else 'FAIL'}")
    print(f"\nPROOF 3: {'PASS' if ok else 'FAIL'}")
    return ok


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Backtest-farm proof harness.")
    ap.add_argument("--screen-equivalence", action="store_true")
    ap.add_argument("--replay-fidelity", action="store_true")
    ap.add_argument("--stats-sanity", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep scratch/proofs/")
    args = ap.parse_args()
    if not any((args.screen_equivalence, args.replay_fidelity, args.stats_sanity,
                args.all)):
        ap.error("pick a proof (or --all)")

    ok = True
    if args.all or args.screen_equivalence:
        ok &= screen_equivalence()
    if args.all or args.replay_fidelity:
        ok &= replay_fidelity()
    if args.all or args.stats_sanity:
        ok &= stats_sanity()
    if not args.keep:
        shutil.rmtree(PROOF_DIR, ignore_errors=True)
    print(f"\n{'ALL PROOFS PASS' if ok else 'SOME PROOFS FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
