#!/usr/bin/env python
"""Minimal reproduction: apply_fill's INTEGER cash clamp strands cash in a
fractional-share simulator. DIAGNOSIS ONLY — changes nothing, writes nothing.

Runs entirely on an in-memory DuckDB. It never opens store/market.duckdb.

    .venv/bin/python docs/repro_fill_integer_clamp.py

Two cases, both taken from real lines in logs/run-2026-08-19.log:

  A. cash-clamp — the order is partly affordable. floor() rounds the affordable
     share count DOWN to a whole number and the remainder stays in cash forever.
  B. insufficient_cash — one share costs more than the whole cash balance, so
     floor() gives 0 and the ENTIRE order is rejected, even though the strategy
     asked for a fraction of a share that the book could easily afford.
     Real line: momo_stop n=5 wanted 0.7027 DRIP @ $47,988.54 holding $29,569.57
     of cash (76% of the book). Nothing was bought.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from sim.portfolio import apply_fill, get_cash
from sim.schema import init_sim_schema


def fresh(cash: float) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    init_sim_schema(con)
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, cash)"
        " VALUES ('repro', 'repro', 'x', '{}', DATE '2020-01-01', TRUE, ?)", [cash])
    return con


def case(label: str, cash: float, ticker: str, qty: float, px: float) -> None:
    con = fresh(cash)
    applied = apply_fill(con, {"portfolio_id": "repro", "ticker": ticker,
                               "side": "buy", "qty": qty, "fill_px": px})
    left = get_cash(con, "repro")
    want_frac = min(qty, cash / px)          # what a fractional-share fill would do
    stranded = left - (cash - want_frac * px)
    print(f"\n--- {label} ---")
    print(f"  cash before        ${cash:>14,.2f}")
    print(f"  order              {qty:.6f} {ticker} @ ${px:,.4f}  "
          f"(notional ${qty * px:,.2f})")
    print(f"  qty applied        {applied:.6f}")
    print(f"  cash after         ${left:>14,.2f}   ({left / cash * 100:.2f}% of the book idle)")
    print(f"  fractional model   would buy {want_frac:.6f} and leave "
          f"${cash - want_frac * px:,.2f}")
    print(f"  STRANDED BY floor() ${stranded:>13,.2f}  "
          f"= {stranded / 39000 * 1e4:.1f} bp of a $39,000 book")
    con.close()


if __name__ == "__main__":
    print(__doc__)
    # A: real line — ew_benchmark ZG buy 17.43663780889092 -> 11 @ 45.4430 (cash $530.36)
    case("A · cash-clamp (ew_benchmark ZG, 2026-08-19 log)",
         cash=530.36, ticker="ZG", qty=17.43663780889092, px=45.4430)
    # B: real line — sweep__momo_stop__n-5__stop_frac-0.9 DRIP buy 0.7027... @ 47988.5430
    case("B · insufficient_cash, whole order killed (momo_stop n=5 DRIP)",
         cash=29569.57, ticker="DRIP", qty=0.7027334085362452, px=47988.5430)
    print("\nBoth cases: sim/portfolio.py:128  `affordable = math.floor(cash / px)`.")
    print("Every other sizing path in sim/ is fractional (base.rebalance_orders:386,")
    print("turtle_breakout:70, pead_ear:104), so the floor() is the only integer")
    print("constraint in the engine and it is not documented as a design choice.")
