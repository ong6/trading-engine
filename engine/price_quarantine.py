#!/usr/bin/env python
"""Explicitly activate or resolve a confirmed primary price-data quarantine.

This is an adjudication tool, not an automatic verifier hook. Cross-source
disagreement alone is insufficient; the operator must provide the evidence and
reason that establish a defect in the primary store.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd

from engine.lib import db
from engine.lib.data_quality import (
    observation_reasons,
    provisional_open_only_fault,
    session_schedule,
)
from engine.lib.settings import DEFAULT_DB
from sim.schema import init_sim_schema


def cleanup_hard_invalid_prices(con, *, dry_run: bool = True) -> dict:
    """One-off revision-15 cleanup. Default is read-only; never repairs a tuple.

    Scan scalar invariants in SQL and historical calendar dates once. Applying
    appends each original observation and deletes its cache key atomically.
    Basis candidates and valid REAL-ineligible bars are outside this cleanup.
    """
    dates = [row[0] for row in con.execute("SELECT DISTINCT date FROM prices").fetchall()]
    off_calendar = [day for day in dates if pd.Timestamp(day) not in session_schedule(day.year).index]
    scalar = " OR ".join(
        [f"{f} IS NULL OR NOT isfinite({f}) OR {f} <= 0"
         for f in ("open", "high", "low", "close")]
        + ["high < greatest(open,close,low)", "low > least(open,close,high)",
           "volume IS NULL OR volume < 0"]
    )
    with db.registered_frame(con, "_off_calendar_dates", pd.DataFrame(
        {"date": pd.Series(off_calendar, dtype="datetime64[ns]")},
    )):
        originals = db.observation_rows(con.execute(
            f"SELECT p.* FROM prices p WHERE ({scalar}) "
            "OR date IN (SELECT date FROM _off_calendar_dates) ORDER BY ticker,date"
        ))
    reasons = [observation_reasons(row) for row in originals]
    if any(not reason for reason in reasons):
        raise ValueError("cleanup SQL and validator disagree; no rows moved")
    # A same-night bar whose only fault is its open is admissible as fetched, so the
    # cleanup leaves it for the next night's settled re-fetch, exactly as ingest does.
    # A stale one (dated before the newest stored session, never re-fetched) is
    # judged as settled and moves like any other hard-invalid bar.
    latest = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    kept = [provisional_open_only_fault(row, reason, latest)
            for row, reason in zip(originals, reasons, strict=True)]
    originals = [row for row, keep in zip(originals, kept, strict=True) if not keep]
    reasons = [reason for reason, keep in zip(reasons, kept, strict=True) if not keep]
    report = {
        "dry_run": dry_run, "invalid_rows": len(originals), "provisional_kept": sum(kept),
        "tickers": len({row["ticker"] for row in originals}),
        "by_date": dict(sorted(Counter(str(row["date"]) for row in originals).items())),
        "by_reason": dict(sorted(Counter(r for items in reasons for r in items).items())),
        "moved": 0,
    }
    if dry_run or not originals:
        return report
    batch_id = str(uuid4())
    with db.transaction(con):
        for row, reason in zip(originals, reasons, strict=True):
            db.append_price_observations(con, [row], reason=",".join(reason), batch_id=batch_id)
        with db.registered_frame(con, "_invalid_price_keys", pd.DataFrame(originals)[["ticker", "date"]]):
            moved = con.execute(
                "DELETE FROM prices USING _invalid_price_keys i "
                "WHERE prices.ticker=i.ticker AND prices.date=i.date RETURNING ticker"
            ).fetchall()
        if len(moved) != len(originals):
            raise ValueError("cleanup count changed; rolled back")
        report["moved"] = len(moved)
    return report


def set_quarantine(con, ticker: str, *, reason: str, evidence: str) -> None:
    ticker = ticker.upper().strip()
    if not ticker or not reason.strip() or not evidence.strip():
        raise ValueError("ticker, reason, and evidence are required")
    now = datetime.now(timezone.utc)
    payload = {"ticker": ticker, "reason": reason, "evidence": evidence}
    with db.transaction(con):
        con.execute(
            "INSERT OR REPLACE INTO price_quarantine "
            "(ticker, status, reason, evidence, confirmed_at, resolved_at, resolution) "
            "VALUES (?, 'active', ?, ?, ?, NULL, NULL)",
            [ticker, reason, evidence, now],
        )
        con.execute(
            "INSERT INTO audit_log (ts, actor, action, payload) VALUES (?, ?, ?, ?)",
            [now, "price_quarantine", "activate", json.dumps(payload, sort_keys=True)],
        )


def resolve_quarantine(con, ticker: str, *, resolution: str) -> None:
    ticker = ticker.upper().strip()
    if not ticker or not resolution.strip():
        raise ValueError("ticker and resolution are required")
    active = con.execute(
        "SELECT 1 FROM price_quarantine WHERE ticker = ? AND status = 'active'",
        [ticker],
    ).fetchone()
    if not active:
        raise ValueError(f"{ticker} has no active quarantine")
    now = datetime.now(timezone.utc)
    payload = {"ticker": ticker, "resolution": resolution}
    with db.transaction(con):
        con.execute(
            "UPDATE price_quarantine SET status = 'resolved', resolved_at = ?, "
            "resolution = ? WHERE ticker = ?", [now, resolution, ticker])
        con.execute(
            "INSERT INTO audit_log (ts, actor, action, payload) VALUES (?, ?, ?, ?)",
            [now, "price_quarantine", "resolve", json.dumps(payload, sort_keys=True)],
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--ticker", required=True)
    action = ap.add_mutually_exclusive_group(required=True)
    action.add_argument("--activate", action="store_true")
    action.add_argument("--resolve", action="store_true")
    ap.add_argument("--reason", help="confirmed primary-store defect")
    ap.add_argument("--evidence", help="audit evidence supporting activation")
    ap.add_argument("--resolution", help="how the defect was repaired/adjudicated")
    args = ap.parse_args()

    con = db.connect(args.db)
    try:
        init_sim_schema(con)
        if args.activate:
            set_quarantine(con, args.ticker, reason=args.reason or "",
                           evidence=args.evidence or "")
        else:
            resolve_quarantine(con, args.ticker,
                               resolution=args.resolution or "")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
