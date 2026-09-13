#!/usr/bin/env python
"""Explicitly activate or resolve a confirmed primary price-data quarantine.

This is an adjudication tool, not an automatic verifier hook. Cross-source
disagreement alone is insufficient; the operator must provide the evidence and
reason that establish a defect in the primary store.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from engine.lib import db
from engine.lib.settings import DEFAULT_DB
from sim.schema import init_sim_schema


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
