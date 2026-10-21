#!/usr/bin/env python
"""Repair price-integrity defects already stored (P24, snapshot-invariant findings).

Dry-run is the default: it opens the store read-only, asks the source for the
evidence and reports what --apply would change. Every step is idempotent (a second
run finds nothing to do) and never invents a number: a bar changes only to the
source's own settled bar, or by the reconciler's own split arithmetic (or its exact
inverse) where the source's current history proves which scale each stored bar is
on. Every change appends the replaced originals to `price_observation_rejects` and
an `audit_log` row (actor `repair_integrity`; a restatement also writes the
reconciler's own `split_restated` row).

Steps (--steps, default all, in this order):

  double      bars an applied split restatement divided twice (WLFC 2026-07-15
              under 3:1): a new-scale island in the pre-break window whose stored
              bar times the ratio equals the source's current bar, with every
              neighbour equal to the source, is multiplied back.
  unrecorded  split-sized breaks with no split row (invariant
              `split_recorded_vs_restated`): record those names' corporate actions
              through the nightly actions path. A new split whose verdict cannot
              restate is recorded as the nightly reconcile would (`decide_split`);
              one that could goes through the evidence below instead.
  splits      splits whose stored break the reconciler skipped (`skipped_already_
              adjusted`: ETHA 1:3, CRWU 1:10, whose rule-3 stamps were rewritten by
              the 5d re-fetch before first_fetched_at was preserved; `skipped_
              sanity`: a real move on the break day) or that a new split row would
              restate. Restated through `actions._restate` only when the source's
              current history classifies EVERY stored bar before the break as old
              scale (stored/source = ratio) or already new scale (= 1, kept, e.g.
              RUSHA's glitch bars 08-05 and 08-10), and every bar after it as 1.
              A new split whose evidence fails is recorded
              `skipped_source_mismatch` so no reconcile restates it blind.
  stale       never-settled same-night bars and the holes their removal left
              (DDS, SUNC 2026-10-12; CIB 2026-10-16): ask the source again for each
              key since --since, store its settled bar, retire what is still
              inadmissible (`collect.settle_stale_provisional`, the nightly path).
              Last, so a re-fetched bar meets a series already on one basis.

Usage (never while the nightly or a queue job runs; --apply takes the writer):

    .venv/bin/python -m engine.repair_integrity --db <copy>                  # dry-run
    .venv/bin/python -m engine.repair_integrity --db <copy> --apply --report out.json
"""
from __future__ import annotations

import argparse
import json
import math
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from engine import actions, collect
from engine.lib import db
from engine.lib.data_quality import observation_reasons
from engine.lib.log import get_logger
from engine.lib.util import table_exists

log = get_logger("repair-integrity")

ACTOR = "repair_integrity"
STEPS = ("double", "unrecorded", "splits", "stale")
DEFAULT_SINCE = date(2026, 7, 16)   # the post-backfill era of restamped fetch stamps
# Stored and source bars come from the same source and parameters, so a bar on a
# known scale sits within 1% (log) of the expected factor.
EVIDENCE_TOL_LOG = math.log(1.01)
MIN_EVIDENCE_BARS = 3
POST_BREAK_SESSIONS = 10
MAX_HISTORY_START = "1970-01-01"
SKIPPED_OUTCOMES = ("skipped_already_adjusted", "skipped_sanity")
RESTATABLE = ("applied_pending", *SKIPPED_OUTCOMES)
MISMATCH = "skipped_source_mismatch"


def source_closes(yf_ticker: str, canon: str, start: date | None) -> dict[date, float]:
    """The source's current closes (full history when `start` is None)."""
    raw = collect._download([yf_ticker], period=None if start else "max",
                            start=start.isoformat() if start else None)
    df, _got = collect._extract_long(raw, {yf_ticker: canon})
    if df.empty and start is None:
        # period="max" can ask for a 1927 start and get nothing back (WLFC).
        raw = collect._download([yf_ticker], period=None, start=MAX_HISTORY_START)
        df, _got = collect._extract_long(raw, {yf_ticker: canon})
    if df.empty:
        return {}
    df = df.dropna(subset=["close"])
    return {day: float(close) for day, close in zip(df.date, df.close, strict=True)
            if close > 0}


def _yf(con, ticker: str) -> str:
    row = con.execute("SELECT yf_ticker FROM universe WHERE ticker = ?", [ticker]).fetchone()
    return row[0] if row and row[0] else ticker


def _at(ratio: float, factor: float) -> bool:
    return ratio > 0 and abs(math.log(ratio) - math.log(factor)) <= EVIDENCE_TOL_LOG


def _audit(con, action: str, payload: dict) -> None:
    con.execute("INSERT INTO audit_log (ts, actor, action, payload) VALUES (?, ?, ?, ?)",
                [datetime.now(timezone.utc), ACTOR, action,
                 json.dumps(payload, sort_keys=True, default=str)])


def _closes(con, ticker: str) -> list[tuple[date, float]]:
    return con.execute("SELECT date, close FROM prices WHERE ticker = ? AND close > 0 "
                       "ORDER BY date", [ticker]).fetchall()


# --------------------------------------------------------------------------- double
def double_candidates(con, since: date) -> list[dict]:
    """Applied splits whose pre-break window still holds a new-scale island."""
    if not table_exists(con, "split_adjustments"):
        return []
    out = []
    for ticker, ex, ratio, brk in con.execute(
        "SELECT ticker, ex_date, ratio, break_date FROM split_adjustments "
        "WHERE outcome = 'applied' AND ex_date >= ? AND break_date IS NOT NULL "
        "ORDER BY ex_date, ticker", [since]).fetchall():
        win = [(d, c) for d, c, _f, _ff in actions._session_window(con, ticker, ex) if d < brk]
        islands = actions.new_scale_islands(win, float(ratio))
        if islands:
            out.append({"kind": "double", "ticker": ticker, "ex_date": ex,
                        "ratio": float(ratio), "break_date": brk, "dates": islands,
                        "window": [d for d, _c in win]})
    return out


def double_evidence(con, cand: dict, source: dict[date, float]) -> dict:
    stored = {d: c for d, c in _closes(con, cand["ticker"])
              if cand["window"][0] <= d <= cand["window"][-1]}
    island = {d: stored[d] * cand["ratio"] / source[d] for d in cand["dates"]
              if d in source and d in stored}
    others = {d: stored[d] / source[d] for d in cand["window"]
              if d not in cand["dates"] and d in source and d in stored}
    proven = (len(island) == len(cand["dates"]) and len(others) >= MIN_EVIDENCE_BARS
              and all(_at(r, 1.0) for r in (*island.values(), *others.values())))
    return {"proven": proven, "neighbours_compared": len(others),
            "island_restored_over_source": {str(d): round(r, 6) for d, r in island.items()}}


def apply_double(con, cand: dict, evidence: dict) -> int:
    dates, ratio = cand["dates"], cand["ratio"]
    marks = ",".join("?" * len(dates))
    with db.transaction(con):
        previous = db.observation_rows(con.execute(
            f"SELECT * FROM prices WHERE ticker = ? AND date IN ({marks})",
            [cand["ticker"], *dates]))
        for bar in previous:
            restored = {**bar, **{f: bar[f] * ratio for f in ("open", "high", "low", "close")},
                        "volume": round(bar["volume"] / ratio)}
            if observation_reasons(restored):
                raise ValueError(f"invalid restored bar: {cand['ticker']} {bar['date']}")
        db.append_price_observations(
            con, previous, reason="split_restatement_predecessor",
            batch_id=f"{ACTOR}:double:{cand['ticker']}:{cand['ex_date']}")
        n = len(con.execute(
            "UPDATE prices SET open = open * ?, high = high * ?, low = low * ?, "
            "close = close * ?, volume = CAST(ROUND(volume / ?) AS BIGINT) "
            f"WHERE ticker = ? AND date IN ({marks}) RETURNING ticker",
            [ratio] * 5 + [cand["ticker"], *dates]).fetchall())
        _audit(con, "split_double_restatement_reverted", {
            "ticker": cand["ticker"], "ex_date": cand["ex_date"], "ratio": ratio,
            "break_date": cand["break_date"], "dates": dates, "rows": n, **evidence})
    return n


# --------------------------------------------------------------------------- splits
def split_candidate(con, ticker: str, ex: date, ratio: float, *, new: bool) -> dict | None:
    """A split the stored series could be restated for, with the reconciler's verdict."""
    verdict = actions._adjudicate(con, ticker, ex, ratio)
    if verdict["outcome"] not in RESTATABLE:
        return None
    win = [d for d, *_rest in actions._session_window(con, ticker, ex)]
    return {"kind": "splits", "ticker": ticker, "ex_date": ex, "ratio": ratio, "new": new,
            "verdict": verdict["outcome"], "break_date": verdict["break_date"],
            "window": win}


def recorded_skips(con, since: date) -> list[dict]:
    if not table_exists(con, "split_adjustments"):
        return []
    rows = con.execute(
        "SELECT s.ticker, s.ex_date, s.ratio FROM split_adjustments s "
        "JOIN universe u ON u.ticker = s.ticker AND u.liquid "
        f"WHERE s.outcome IN ({','.join('?' * len(SKIPPED_OUTCOMES))}) AND s.ex_date >= ? "
        "ORDER BY s.ex_date, s.ticker", [*SKIPPED_OUTCOMES, since]).fetchall()
    found = (split_candidate(con, t, ex, float(r), new=False) for t, ex, r in rows)
    return [cand for cand in found if cand is not None]


def split_evidence(con, cand: dict, source: dict[date, float]) -> dict:
    """Classify every stored bar against the source's current, restated history.

    The break is the reconciler's when it found one, else (a real move on the
    break day) the first window bar from which every stored bar equals the source.
    """
    stored = _closes(con, cand["ticker"])
    ratios = [(d, c / source[d] if d in source else None) for d, c in stored]
    brk = cand["break_date"]
    if brk is None:
        tail = len(ratios)
        while tail > 0 and ratios[tail - 1][1] is not None and _at(ratios[tail - 1][1], 1.0):
            tail -= 1
        brk = ratios[tail][0] if tail < len(ratios) and ratios[tail][0] in cand["window"] \
            else None
    report = {"proven": False, "break_date": str(brk) if brk else None}
    if brk is None:
        return {**report, "reason": "no break where the source flips to the stored scale"}
    pre = [(d, r) for d, r in ratios if d < brk]
    post = [(d, r) for d, r in ratios if d >= brk][:POST_BREAK_SESSIONS]
    old = [d for d, r in pre if r is not None and _at(r, cand["ratio"])]
    kept = [d for d, r in pre if r is not None and _at(r, 1.0)]
    other = [str(d) for d, r in pre if r is None or not (_at(r, cand["ratio"]) or _at(r, 1.0))]
    post_off = [str(d) for d, r in post if r is None or not _at(r, 1.0)]
    proven = len(old) >= MIN_EVIDENCE_BARS and len(post) >= MIN_EVIDENCE_BARS \
        and not other and not post_off
    return {**report, "proven": proven, "break": brk, "keep": kept,
            "pre_stored": len(pre), "pre_old_scale": len(old),
            "pre_new_scale": [str(d) for d in kept], "pre_unproven": other[:20],
            "post_compared": len(post), "post_off": post_off[:20]}


def apply_split(con, cand: dict, evidence: dict) -> int:
    if not evidence["proven"]:
        if cand["new"]:
            actions._mark(con, cand["ticker"], cand["ex_date"], cand["ratio"],
                          {"outcome": MISMATCH, "observed": None, "break_date": None})
            _audit(con, f"split_{MISMATCH}", {
                "ticker": cand["ticker"], "ex_date": cand["ex_date"],
                "ratio": cand["ratio"], **_public(evidence)})
        return 0
    n = actions._restate(con, cand["ticker"], cand["ex_date"], cand["ratio"],
                         evidence["break"], keep=evidence["keep"])
    actions._resolve_split_quarantine(con, cand["ticker"], cand["ex_date"])
    _audit(con, "split_restated_with_source_evidence", {
        "ticker": cand["ticker"], "ex_date": cand["ex_date"], "ratio": cand["ratio"],
        "rows_restated": n, "replaces_outcome": None if cand["new"] else cand["verdict"],
        **_public(evidence)})
    return n


def _public(evidence: dict) -> dict:
    return {k: v for k, v in evidence.items() if k not in ("break", "keep")}


# --------------------------------------------------------------------------- unrecorded
def unrecorded_breaks(con) -> list[dict]:
    from tools.invariants import market_data, registry

    ctx = registry.Context(con=con, snapshot_as_of=datetime.now(timezone.utc),
                           engine_root=Path("."))
    _facts, found = market_data.split_recorded_vs_restated(ctx)
    return [{"ticker": item["subject"].split(" ")[0], "date": item["detail"]["date"],
             "ratio": item["detail"]["ratio"]} for item in found]


def _unadjudicated(con, tickers: list[str]) -> list[tuple[str, date, float]]:
    if not tickers:
        return []
    return [(t, ex, float(r)) for t, ex, r in con.execute(
        "SELECT c.ticker, c.ex_date, c.value FROM corporate_actions c "
        "LEFT JOIN split_adjustments s ON s.ticker = c.ticker AND s.ex_date = c.ex_date "
        "WHERE c.kind = 'split' AND s.ticker IS NULL "
        "AND c.ex_date <= (SELECT MAX(date) FROM prices) AND c.ticker IN "
        f"({','.join('?' * len(tickers))}) ORDER BY c.ex_date, c.ticker", tickers).fetchall()]


def record_unrecorded(db_path: Path, names: list[str], *, apply: bool, since: date,
                      fetch_actions) -> tuple[dict, list[dict]]:
    """Record the flagged names' splits; return (report, split candidates)."""
    found: dict[str, list[dict]] = {name: [] for name in names}
    if apply and names:
        meta = Path(tempfile.mkdtemp(prefix="repair-integrity-")) / "_meta.json"
        actions.run_connection_narrowed(
            {"mode": "incremental", "tickers": ",".join(names), "top_n": 0,
             "rolling_slices": 0, "resume": False}, db_path=db_path, meta_path=meta)
    con = db.connect(db_path, read_only=not apply)
    try:
        if apply:
            pending = _unadjudicated(con, names)
        else:
            pending = []
            for name in names:
                rows = actions._rows_from_actions(name, fetch_actions(_yf(con, name)))
                pending += [(name, row["ex_date"], row["value"]) for row in rows
                            if row["kind"] == "split" and row["ex_date"] >= since
                            and not con.execute(
                                "SELECT 1 FROM split_adjustments WHERE ticker = ? "
                                "AND ex_date = ?", [name, row["ex_date"]]).fetchone()]
        cands = []
        for ticker, ex, ratio in pending:
            cand = split_candidate(con, ticker, ex, ratio, new=True)
            item = {"ex_date": ex.isoformat(), "ratio": ratio}
            if cand is not None:
                cands.append(cand)
                item["verdict"] = cand["verdict"]
            elif apply:
                item["outcome"] = actions.decide_split(con, ticker, ex, ratio)[0]
            else:
                item["verdict"] = actions._adjudicate(con, ticker, ex, ratio)["outcome"]
            found[ticker].append(item)
    finally:
        con.close()
    return found, cands


# --------------------------------------------------------------------------- driver
def _item(cand: dict, evidence: dict, rows: int) -> dict:
    keep = ("ticker", "ex_date", "ratio", "break_date", "dates", "verdict", "new")
    out = {k: (str(v) if isinstance(v, date) else v) for k, v in cand.items() if k in keep}
    if "dates" in out:
        out["dates"] = [str(d) for d in out["dates"]]
    return {**out, "evidence": _public(evidence), "rows_changed": rows}


def run(db_path: Path, *, apply: bool, steps: tuple[str, ...] = STEPS,
        since: date = DEFAULT_SINCE, today: date | None = None,
        source=source_closes, fetch_actions=actions._fetch_actions) -> dict:
    today = today or datetime.now(timezone.utc).date()
    report: dict = {"db": Path(db_path).name, "apply": apply, "since": since.isoformat(),
                    "steps": list(steps)}
    con = db.connect(db_path, read_only=True)
    try:
        breaks = unrecorded_breaks(con) if "unrecorded" in steps else []
        double = double_candidates(con, since) if "double" in steps else []
    finally:
        con.close()
    names = sorted({b["ticker"] for b in breaks})
    if "unrecorded" in steps:
        report["unrecorded"] = {"breaks": breaks}

    new_splits: list[dict] = []
    if "unrecorded" in steps:
        report["unrecorded"]["splits"], new_splits = record_unrecorded(
            db_path, names, apply=apply, since=since, fetch_actions=fetch_actions)

    con = db.connect(db_path, read_only=True)
    try:
        splits = recorded_skips(con, since) if "splits" in steps else []
        splits += new_splits if "splits" in steps else []
        evidence = {}
        for cand in (*double, *splits):
            history = source(_yf(con, cand["ticker"]), cand["ticker"],
                             cand["window"][0] if cand["kind"] == "double" else None)
            check = double_evidence if cand["kind"] == "double" else split_evidence
            evidence[id(cand)] = check(con, cand, history)
    finally:
        con.close()

    con = db.connect(db_path, read_only=not apply)
    try:
        for name, cands, apply_one in (("double", double, apply_double),
                                       ("splits", splits, apply_split)):
            if name in steps:
                report[name] = [_item(c, evidence[id(c)], apply_one(con, c, evidence[id(c)])
                                      if apply else 0) for c in cands]
    finally:
        con.close()

    # Last, so a re-fetched bar meets a series already on one basis (a bar the
    # source has since restated would otherwise be held as basis_unverified).
    if "stale" in steps:
        report["stale"] = collect.settle_stale_provisional(
            db_path, today=today, lookback_days=(today - since).days, dry_run=not apply)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    ap.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    ap.add_argument("--steps", default=",".join(STEPS),
                    help=f"comma list from {','.join(STEPS)}")
    ap.add_argument("--since", type=date.fromisoformat, default=DEFAULT_SINCE,
                    help="earliest bar date / ex-date the steps consider")
    ap.add_argument("--report", type=Path, help="also write the JSON report here")
    args = ap.parse_args()
    steps = tuple(s for s in args.steps.split(",") if s)
    if set(steps) - set(STEPS):
        ap.error(f"unknown steps: {sorted(set(steps) - set(STEPS))}")
    report = run(Path(args.db), apply=args.apply, steps=steps, since=args.since)
    text = json.dumps(report, indent=1, sort_keys=True, default=str)
    if args.report:
        args.report.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
