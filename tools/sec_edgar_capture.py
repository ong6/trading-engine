"""Capture bounded SEC filing evidence for the latest opportunity cohort."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.lib import db
from engine.lib.settings import DEFAULT_DB
from engine.lib.util import table_exists
from server import sec_edgar_capture


def _latest_tickers(con) -> list[str]:
    if not table_exists(con, "daily_opportunity_runs"):
        return []
    row = con.execute(
        "SELECT id FROM daily_opportunity_runs WHERE status='completed' "
        "ORDER BY market_date DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return []
    return [item[0] for item in con.execute(
        "SELECT ticker FROM daily_opportunity_assessments WHERE run_id=? ORDER BY id LIMIT ?",
        [row[0], sec_edgar_capture.MAX_TICKERS],
    ).fetchall()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--tickers", default=None, help="comma-separated bounded override")
    args = parser.parse_args(argv)
    con = db.connect(args.database, wait_s=0)
    try:
        tickers = ([item.strip().upper() for item in args.tickers.split(",") if item.strip()]
                   if args.tickers is not None else _latest_tickers(con))
        if not tickers:
            result = {"status": "waiting", "ticker_count": 0,
                      "historical_membership_authority": False,
                      "execution_authority": "none"}
        else:
            result = sec_edgar_capture.capture(
                con, tickers
            )
    finally:
        con.close()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {"complete", "waiting"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
