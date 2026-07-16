#!/usr/bin/env python
"""Machinery shakedown — NOT a backtest for evidence, a plumbing test.

Inits the portfolios as of `--start N` trading sessions ago, then loops the
league day-step forward through every trading session to the latest bar, so the
whole pipeline (orders → t+1-open fills → MTM → equity curve → report) is
exercised end to end. Prints per-portfolio final equity and lifetime fill/reject
counts. Run it ONLY against a throwaway copy of the DB.

`--ensure-screens` first runs the M1 screener for any session in the window that
has no screen_results yet (strategies read passes_template / rs_rank), writing to
a throwaway data-dir so the real screens are untouched.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from lib import db  # noqa: E402
import screen as m1_screen  # noqa: E402

from . import league  # noqa: E402
from .schema import init_sim_schema  # noqa: E402


def window_days(con, start_n: int) -> list[date]:
    days = [r[0] for r in con.execute(
        "SELECT DISTINCT date FROM prices ORDER BY date DESC LIMIT ?", [start_n]
    ).fetchall()]
    return sorted(days)


def ensure_screens(db_path: str, days: list[date], screen_data_dir: Path) -> None:
    con = db.connect(db_path)
    have = {r[0] for r in con.execute(
        "SELECT DISTINCT run_date FROM screen_results").fetchall()}
    con.close()
    todo = [d for d in days if d not in have]
    print(f"[shakedown] ensuring screens: {len(todo)} of {len(days)} sessions missing")
    for d in todo:
        m1_screen.run(db_path, screen_data_dir, d.isoformat(), rerun=False)


def run(db_path: str, data_dir: Path, start_n: int, do_screens: bool) -> int:
    con = db.connect(db_path)
    db.init_schema(con)
    init_sim_schema(con)
    days = window_days(con, start_n)
    if not days:
        print("[shakedown] no trading days")
        return 1
    start, end = days[0], days[-1]
    print(f"[shakedown] window {start} → {end} ({len(days)} sessions)")
    con.close()

    if do_screens:
        ensure_screens(db_path, days, data_dir / "throwaway_screens")

    con = db.connect(db_path)
    db.init_schema(con)
    init_sim_schema(con)
    n = league.init_portfolios(con, start)
    print(f"[shakedown] created {n} portfolios as of {start}")

    for d in days:
        league.step(con, d, data_dir, rerun=False, verbose=True)

    print("\n[shakedown] FINAL per-portfolio state")
    print(f"{'portfolio':<32} {'equity':>12} {'fills':>7} {'rej':>5} {'open':>5}")
    for pf_id, name in con.execute(
        "SELECT id, name FROM portfolios ORDER BY id"
    ).fetchall():
        eq = con.execute(
            "SELECT equity FROM sim_equity WHERE portfolio_id = ? "
            "ORDER BY date DESC LIMIT 1", [pf_id]).fetchone()
        eq = eq[0] if eq else float("nan")
        nf = con.execute("SELECT COUNT(*) FROM sim_fills WHERE portfolio_id = ?",
                         [pf_id]).fetchone()[0]
        nr = con.execute("SELECT COUNT(*) FROM sim_orders WHERE portfolio_id = ? "
                         "AND status = 'rejected'", [pf_id]).fetchone()[0]
        no = con.execute("SELECT COUNT(*) FROM sim_positions WHERE portfolio_id = ? "
                         "AND qty > 0", [pf_id]).fetchone()[0]
        print(f"{name:<32} {eq:>12,.0f} {nf:>7} {nr:>5} {no:>5}")
    con.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="M2 machinery shakedown.")
    ap.add_argument("--db", default=str(db.DEFAULT_DB), help="DuckDB path (use a COPY)")
    ap.add_argument("--data-dir", default=str(league.DEFAULT_DATA_DIR))
    ap.add_argument("--start", type=int, default=15, help="trading sessions back")
    ap.add_argument("--ensure-screens", action="store_true",
                    help="run M1 screener for sessions missing screen_results")
    args = ap.parse_args()
    return run(args.db, Path(args.data_dir), args.start, args.ensure_screens)


if __name__ == "__main__":
    raise SystemExit(main())
