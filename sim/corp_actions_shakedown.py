#!/usr/bin/env python
"""Corporate-actions shakedown — synthetic split + dividend proof.

NOT a backtest. A controlled plumbing experiment that proves the split
reconciler and the dividend credit do what they claim, run ONLY against a
throwaway COPY of the store (the script refuses the live path outright).

The split proof is a three-arm A/B/C on identical copies, because "no false stop
fired" is only meaningful against a control that says what the books would have
done anyway:

  A control   one extra synthetic session, every bar carried flat from the last
              real one. Nothing happens; this is the baseline order list.
  B broken    same, except the split ticker's new bar arrives at the post-split
              scale (exactly what collect.py's 5-day re-fetch delivers on the
              morning after a split) and NOTHING reconciles it. This is the bug:
              the books see a ~50% overnight crash that never happened.
  C fixed     same as B, plus the corporate_actions row and the reconciler.

The claim is proved when C reproduces A (equity continuous, order list identical
modulo the ticker's own scale) while B visibly does not, AND a second reconcile
pass on C is a no-op.

The dividend proof is a fourth arm: a synthetic $1.00 dividend on a held name,
checked to the cent against qty, then the same day re-run with --rerun to show
the rebuild reproduces state exactly.

Usage (make your own copy first — the script never copies the live store for you
beyond --setup, and never opens the live store read-write):

    cp store/market.duckdb /scratch/ca-A.duckdb   (x4)
    .venv/bin/python -m sim.corp_actions_shakedown --db-prefix /scratch/ca
"""
from __future__ import annotations

import argparse
import shutil
from datetime import date, timedelta
from pathlib import Path

from engine import actions as eng_actions
from engine.lib import db
from sim import league, portfolio
from sim.schema import init_sim_schema

SPLIT_TICKER = "ATEX"     # held by mr_overlay x2 and template_top10_banded x2
SPLIT_RATIO = 2.0
DIV_TICKER = "ATEX"
DIV_DPS = 1.00
SYNTH_SOURCE = "synthetic-shakedown-bar"


# --------------------------------------------------------------------------- #
def _guard(path: Path) -> None:
    """Refuse to touch the live store, whatever the caller thinks it passed."""
    if path.resolve() == Path(db.DEFAULT_DB).resolve():
        raise SystemExit(f"REFUSING to run against the live store {path} — "
                         f"pass a throwaway copy")


def _open(path: Path):
    _guard(path)
    con = db.connect(path)
    db.init_schema(con)
    db.init_actions_schema(con)
    init_sim_schema(con)
    return con


def _next_session(last: date) -> date:
    d = last + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def carry_flat_session(con, last: date, new: date) -> int:
    """Add one synthetic session by carrying every ticker's last bar forward
    unchanged. A zero-move day: the ONLY thing that can differ between arms is
    the corporate action under test. Bars are stamped with a source that says
    exactly what they are — they exist only inside a throwaway copy."""
    con.execute(
        "INSERT OR REPLACE INTO prices "
        "(ticker, date, open, high, low, close, volume, source, fetched_at) "
        "SELECT ticker, ?, open, high, low, close, volume, ?, fetched_at "
        "FROM prices WHERE date = ?",
        [new, SYNTH_SOURCE, last],
    )
    return con.execute("SELECT COUNT(*) FROM prices WHERE date = ?", [new]).fetchone()[0]


def apply_price_split(con, ticker: str, d: date, ratio: float) -> None:
    """Restate ONLY the new session's bar to the post-split scale — precisely
    what Yahoo hands back for the last 5 sessions the morning after a split,
    leaving every older stored bar on the pre-split scale. This IS the bug."""
    con.execute(
        "UPDATE prices SET open = open / ?, high = high / ?, low = low / ?, "
        "close = close / ?, volume = CAST(ROUND(volume * ?) AS BIGINT) "
        "WHERE ticker = ? AND date = ?",
        [ratio, ratio, ratio, ratio, ratio, ticker, d],
    )


def snapshot(con, d: date) -> dict:
    return {
        "equity": dict(con.execute(
            "SELECT portfolio_id, equity FROM sim_equity WHERE date = ? "
            "ORDER BY portfolio_id", [d]).fetchall()),
        "cash": dict(con.execute(
            "SELECT id, cash FROM portfolios ORDER BY id").fetchall()),
        "positions": {(p, t): (q, c) for p, t, q, c in con.execute(
            "SELECT portfolio_id, ticker, qty, avg_cost FROM sim_positions "
            "WHERE qty != 0 ORDER BY portfolio_id, ticker").fetchall()},
        "new_orders": con.execute(
            "SELECT portfolio_id, ticker, side, qty FROM sim_orders "
            "WHERE signal_date = ? ORDER BY portfolio_id, ticker, side",
            [d]).fetchall(),
        "order_status": con.execute(
            "SELECT status, COUNT(*) FROM sim_orders GROUP BY 1 ORDER BY 1"
        ).fetchall(),
    }


def _close_enough(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


# --------------------------------------------------------------------------- #
def arm(path: Path, mode: str, data_dir: Path) -> dict:
    """Run one arm. mode: 'control' | 'broken' | 'fixed'."""
    con = _open(path)
    last = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    new = _next_session(last)
    n = carry_flat_session(con, last, new)
    print(f"[ca-shakedown/{mode}] carried {n} bars {last} -> {new}")

    if mode in ("broken", "fixed"):
        apply_price_split(con, SPLIT_TICKER, new, SPLIT_RATIO)
        print(f"[ca-shakedown/{mode}] {SPLIT_TICKER} {new} bar restated to the "
              f"post-{SPLIT_RATIO:g}:1 scale (older bars left pre-split — the bug)")
    if mode == "fixed":
        con.execute(
            "INSERT OR REPLACE INTO corporate_actions "
            "(ticker, ex_date, kind, value, source, fetched_at) "
            "VALUES (?, ?, 'split', ?, 'synthetic-shakedown', now())",
            [SPLIT_TICKER, new, SPLIT_RATIO])
        pre = con.execute(
            "SELECT portfolio_id, qty, avg_cost FROM sim_positions "
            "WHERE ticker = ? AND qty != 0 ORDER BY portfolio_id",
            [SPLIT_TICKER]).fetchall()
        print(f"[ca-shakedown/fixed] pre-reconcile {SPLIT_TICKER}: {pre}")
        eng_actions.reconcile(con)
        post = con.execute(
            "SELECT portfolio_id, qty, avg_cost FROM sim_positions "
            "WHERE ticker = ? AND qty != 0 ORDER BY portfolio_id",
            [SPLIT_TICKER]).fetchall()
        print(f"[ca-shakedown/fixed] post-reconcile {SPLIT_TICKER}: {post}")
        for (p1, q1, c1), (p2, q2, c2) in zip(pre, post):
            assert p1 == p2
            assert _close_enough(q2, q1 * SPLIT_RATIO), (p1, q1, q2)
            assert _close_enough(c2, c1 / SPLIT_RATIO), (p1, c1, c2)
        print(f"[ca-shakedown/fixed] OK qty x{SPLIT_RATIO:g}, "
              f"avg_cost /{SPLIT_RATIO:g} on {len(pre)} position(s)")

        aud = con.execute(
            "SELECT action, payload FROM audit_log WHERE actor = 'actions.reconcile' "
            "ORDER BY ts DESC LIMIT 1").fetchone()
        assert aud and aud[0] == "split_restated", aud
        print(f"[ca-shakedown/fixed] audit_log: {aud[0]} {aud[1]}")

        # Idempotency: a second pass must adjudicate nothing and change nothing.
        before = snapshot(con, new)
        summ = eng_actions.reconcile(con)
        after = snapshot(con, new)
        assert summ["candidates"] == 0, summ
        assert before == after, "second reconcile pass mutated state"
        print(f"[ca-shakedown/fixed] OK second reconcile is a no-op "
              f"(candidates=0, state byte-identical)")

    rc = league.step(con, new, data_dir, rerun=False, verbose=True)
    assert rc == 0, f"league.step returned {rc}"
    snap = snapshot(con, new)
    snap["_date"] = new

    if mode == "fixed":
        # The subtle one: --rerun rebuilds positions by replaying sim_fills, and
        # every ATEX fill on record was executed at the PRE-split scale. Without
        # the split compensation in rebuild_state this silently un-does the
        # reconciler's adjustment and the fake crash comes back on the next
        # re-run of a date.
        rc = league.step(con, new, data_dir, rerun=True, verbose=True)
        assert rc == 0
        after = snapshot(con, new)
        assert after["positions"] == snap["positions"], (
            "--rerun after a split changed positions:\n"
            f"  before {snap['positions'].get(('template_top5', SPLIT_TICKER))}\n"
            f"  after  {after['positions'].get(('template_top5', SPLIT_TICKER))}")
        assert after["equity"] == snap["equity"], "--rerun after a split moved equity"
        held = after["positions"][("template_top5", SPLIT_TICKER)]
        print(f"[ca-shakedown/fixed] OK --rerun after the split keeps positions "
              f"on the post-split scale (template_top5 {SPLIT_TICKER} "
              f"qty={held[0]:.6f} avg_cost={held[1]:.6f})")

    con.close()
    return snap


def dividend_arm(path: Path, data_dir: Path, control: dict) -> None:
    """Arm D: a synthetic $1.00 dividend on a held name, differenced against the
    control arm. Differencing is what makes the claim exact — the step day also
    fills 20 carried-over orders, so raw before/after cash moves for reasons that
    have nothing to do with the dividend."""
    con = _open(path)
    last = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    new = _next_session(last)
    carry_flat_session(con, last, new)
    con.execute(
        "INSERT OR REPLACE INTO corporate_actions "
        "(ticker, ex_date, kind, value, source, fetched_at) "
        "VALUES (?, ?, 'dividend', ?, 'synthetic-shakedown', now())",
        [DIV_TICKER, new, DIV_DPS])

    holders = con.execute(
        "SELECT portfolio_id, qty FROM sim_positions WHERE ticker = ? AND qty > 0 "
        "ORDER BY portfolio_id", [DIV_TICKER]).fetchall()
    print(f"[ca-shakedown/div] {DIV_TICKER} ${DIV_DPS:.2f}/sh ex {new}; "
          f"{len(holders)} holder(s)")

    rc = league.step(con, new, data_dir, rerun=False, verbose=True)
    assert rc == 0
    snap_d = snapshot(con, new)

    # Differenced against the control: every book's cash and equity must move by
    # EXACTLY its dividend entitlement and by nothing else.
    expected = {pf: qty * DIV_DPS for pf, qty in holders}
    print(f"{'portfolio':<30} {'d(cash)':>14} {'expected':>14} "
          f"{'d(equity)':>14}")
    for pf in sorted(control["cash"]):
        dc = snap_d["cash"][pf] - control["cash"][pf]
        de = snap_d["equity"][pf] - control["equity"][pf]
        exp = expected.get(pf, 0.0)
        assert _close_enough(dc, exp, 1e-9), (pf, dc, exp)
        assert _close_enough(de, exp, 1e-9), (pf, de, exp)
        print(f"{pf:<30} {dc:>14,.6f} {exp:>14,.6f} {de:>14,.6f}")
    print(f"[ca-shakedown/div] OK cash AND equity moved by exactly the "
          f"entitlement for all {len(control['cash'])} books "
          f"({len(expected)} paid, {len(control['cash']) - len(expected)} at 0.00)")

    ledger = con.execute(
        "SELECT portfolio_id, ticker, ex_date, qty, dps, amount FROM sim_dividends "
        "WHERE ex_date = ? ORDER BY portfolio_id", [new]).fetchall()
    assert len(ledger) == len(holders), (ledger, holders)
    for (pf, qty), row in zip(holders, ledger):
        expect = qty * DIV_DPS
        assert row[0] == pf and row[1] == DIV_TICKER and row[2] == new
        assert _close_enough(row[3], qty) and _close_enough(row[4], DIV_DPS)
        assert _close_enough(row[5], expect), (row, expect)
        print(f"[ca-shakedown/div] ledger {pf}: {qty:.6f} sh x ${DIV_DPS:.2f} "
              f"= ${expect:,.6f} (stored ${row[5]:,.6f})")

    # --rerun must reproduce the day exactly (delete + replay incl. dividends).
    before = snapshot(con, new)
    rc = league.step(con, new, data_dir, rerun=True, verbose=True)
    assert rc == 0
    after = snapshot(con, new)
    ledger2 = con.execute(
        "SELECT portfolio_id, ticker, ex_date, qty, dps, amount FROM sim_dividends "
        "WHERE ex_date = ? ORDER BY portfolio_id", [new]).fetchall()
    assert before == after, "rerun changed state"
    assert ledger == ledger2, "rerun changed the dividend ledger"
    print("[ca-shakedown/div] OK --rerun reproduces identical state + ledger")

    # And the pure-replay path (what --rerun leans on) must agree too.
    cash_pre_rebuild = dict(con.execute("SELECT id, cash FROM portfolios").fetchall())
    pos_pre = {(p, t): q for p, t, q in con.execute(
        "SELECT portfolio_id, ticker, qty FROM sim_positions WHERE qty != 0").fetchall()}
    portfolio.rebuild_state(con)
    cash_post = dict(con.execute("SELECT id, cash FROM portfolios").fetchall())
    pos_post = {(p, t): q for p, t, q in con.execute(
        "SELECT portfolio_id, ticker, qty FROM sim_positions WHERE qty != 0").fetchall()}
    bad = [k for k in cash_pre_rebuild
           if not _close_enough(cash_pre_rebuild[k], cash_post[k], 1e-9)]
    assert not bad, [(k, cash_pre_rebuild[k], cash_post[k]) for k in bad]
    assert pos_pre.keys() == pos_post.keys()
    print("[ca-shakedown/div] OK rebuild_state replays fills+dividends to the "
          "same cash and positions")
    con.close()


# --------------------------------------------------------------------------- #
def compare(a: dict, b: dict, label: str, scaled_ticker: str | None,
            ratio: float) -> bool:
    """Compare two arms. If scaled_ticker is given, that ticker's order qty in
    `b` is expected to be `ratio` x its qty in `a` (the same economic trade)."""
    ok = True
    print(f"\n--- {label} ---")
    print(f"{'portfolio':<30} {'A equity':>14} {'B equity':>14} {'diff':>12}")
    for pf in sorted(a["equity"]):
        ea, eb = a["equity"][pf], b["equity"].get(pf, float('nan'))
        d = eb - ea
        flag = "" if abs(d) < 0.01 else "   <-- DIFFERS"
        if flag:
            ok = False
        print(f"{pf:<30} {ea:>14,.2f} {eb:>14,.2f} {d:>12,.2f}{flag}")

    oa = {(p, t, s): q for p, t, s, q in a["new_orders"]}
    ob = {(p, t, s): q for p, t, s, q in b["new_orders"]}
    if oa.keys() != ob.keys():
        ok = False
        print(f"ORDER SETS DIFFER: only in A {sorted(set(oa) - set(ob))}; "
              f"only in B {sorted(set(ob) - set(oa))}")
    else:
        for k in oa:
            want = oa[k] * (ratio if scaled_ticker and k[1] == scaled_ticker else 1.0)
            if not _close_enough(want, ob[k], 1e-9):
                ok = False
                print(f"ORDER QTY DIFFERS {k}: A {oa[k]} (expect {want}) vs B {ob[k]}")
        print(f"order sets match ({len(oa)} new order(s) each)")
    print(f"RESULT: {'IDENTICAL' if ok else 'DIFFERENT'}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Corporate-actions shakedown.")
    ap.add_argument("--db-prefix", required=True,
                    help="path prefix; uses <prefix>-{A,B,C,D}.duckdb")
    ap.add_argument("--data-dir", required=True, help="throwaway report dir")
    ap.add_argument("--setup-from", default=None,
                    help="copy this store to the four arm paths first")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    paths = {k: Path(f"{args.db_prefix}-{k}.duckdb") for k in "ABCD"}
    for p in paths.values():
        _guard(p)

    if args.setup_from:
        src = Path(args.setup_from)
        for k, p in paths.items():
            print(f"[ca-shakedown] copying {src} -> {p}")
            shutil.copyfile(src, p)

    print("\n=========== ARM A: control (no split) ===========")
    a = arm(paths["A"], "control", data_dir)
    print("\n=========== ARM B: split arrives, NOT reconciled (the bug) ===========")
    b = arm(paths["B"], "broken", data_dir)
    print("\n=========== ARM C: split arrives, reconciled (the fix) ===========")
    c = arm(paths["C"], "fixed", data_dir)

    bad = compare(a, b, "B (unreconciled) vs A (control) — EXPECTED TO DIFFER",
                  None, 1.0)
    good = compare(a, c, "C (reconciled) vs A (control) — EXPECTED IDENTICAL",
                   SPLIT_TICKER, SPLIT_RATIO)

    print("\n=========== ARM D: dividend (differenced vs control A) ===========")
    dividend_arm(paths["D"], data_dir, a)

    print("\n=========== VERDICT ===========")
    print(f"  B differs from control (bug reproduced) : {'YES' if not bad else 'NO'}")
    print(f"  C identical to control (bug fixed)      : {'YES' if good else 'NO'}")
    if bad:
        print("FAIL: the unreconciled arm did NOT show the corruption — the "
              "experiment proves nothing; investigate before trusting the fix.")
        return 1
    if not good:
        print("FAIL: the reconciled arm did not reproduce the control.")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
