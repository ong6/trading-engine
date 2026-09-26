"""Run the frozen incremental collector and checkpoint safe P15 fetch attempts."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from engine import collect
from engine.lib import db
from engine.lib.settings import DEFAULT_DB

from . import p15_price_fetch_attempts


def run(database: Path = DEFAULT_DB, *, now: datetime | None = None) -> dict:
    attempted_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    requested, failed = collect.mode_incremental(database, force=False)
    if requested == 0:
        return {
            "status": "not_session", "requested": requested, "failed": failed,
            "attempt_count": 0,
        }
    con = db.connect(database)
    try:
        market_date = db.latest_operational_market_date(con)
        if market_date is None:
            return {
                "status": "withheld", "reason": "operational_market_date_unavailable",
                "requested": requested, "failed": failed, "attempt_count": 0,
            }
        with db.transaction(con):
            result = p15_price_fetch_attempts.record(
                con, market_date=market_date, attempted_at=attempted_at,
                requested_count=requested, failed_count=failed,
            )
        return {**result, "requested": requested, "failed": failed}
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.database), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
