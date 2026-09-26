"""Run the frozen incremental collector and checkpoint safe P15 fetch attempts."""
from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from yfinance.exceptions import YFPricesMissingError

from engine import collect
from engine.lib import db
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import DEFAULT_DB

from . import p15_price_fetch_attempts

ExactHistory = Callable[[str, date, date], object]
MAX_OPEN_LABEL_FETCHES = 20


def _history(provider_ticker: str, start: date, end: date):
    return collect.yf.Ticker(provider_ticker).history(
        start=start.isoformat(), end=end.isoformat(), interval="1d",
        auto_adjust=False, actions=False, timeout=30, raise_errors=True,
    )


def _fetch_exact(
    obligation: dict, *, requested_at: datetime, history: ExactHistory,
    sleep: Callable[[float], None],
) -> tuple[dict | None, object | None]:
    ticker = obligation["ticker"]
    provider = obligation["provider_ticker"]
    market_date = obligation["market_date"]
    request_sha = p15_price_fetch_attempts.open_label_request_sha256(
        ticker, provider, market_date,
    )
    for attempt in range(2):
        try:
            raw = history(provider, market_date, market_date + timedelta(days=1))
        except YFPricesMissingError as exc:
            normalized_reason = (exc.yahoo_reason or "").strip().casefold()
            if normalized_reason not in {
                "no data found, symbol may be delisted",
                "not found, no data found, symbol may be delisted",
            }:
                if attempt == 0:
                    sleep(2)
                    continue
                return None, None
            response_sha = p15_price_fetch_attempts.open_label_missing_response_sha256()
            return ({**obligation, "status": "missing", "requested_at": requested_at,
                     "outcome_reason": p15_price_fetch_attempts.OPEN_LABEL_MISSING_REASON,
                     "request_sha256": request_sha, "response_sha256": response_sha}, None)
        except Exception:  # noqa: BLE001 - one bounded retry, then no evidence
            if attempt == 0:
                sleep(2)
                continue
            return None, None
        frame = collect._frame_from_sub(raw, ticker)
        if frame is not None:
            exact = frame.loc[frame["date"] == market_date]
            if len(exact) == 1:
                response_sha = canonical_sha256([
                    {
                        key: value.isoformat() if isinstance(value, date) else value
                        for key, value in row.items()
                    }
                    for row in exact.to_dict(orient="records")
                ])
                return ({**obligation, "status": "present", "requested_at": requested_at,
                         "outcome_reason": None,
                         "request_sha256": request_sha,
                         "response_sha256": response_sha}, exact)
        if attempt == 0:
            sleep(2)
    return None, None


def run(
    database: Path = DEFAULT_DB, *, now: datetime | None = None,
    history: ExactHistory = _history, sleep: Callable[[float], None] = time.sleep,
) -> dict:
    requested, failed = collect.mode_incremental(database, force=False)
    attempted_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    collect.write_meta(database, "incremental", requested, failed)
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
        obligations = p15_price_fetch_attempts.open_label_obligations(
            con, through_date=market_date, known_at=attempted_at,
        )
    finally:
        con.close()
    outstanding = len(obligations)
    obligations = obligations[:MAX_OPEN_LABEL_FETCHES]
    receipts = []
    exact_completed = 0
    exact_failed = 0
    for obligation in obligations:
        receipt, frame = _fetch_exact(
            obligation, requested_at=attempted_at, history=history, sleep=sleep,
        )
        if receipt is None:
            exact_failed += 1
            continue
        if frame is not None:
            collect._upsert_batch(database, frame)
        else:
            receipts.append(receipt)
        exact_completed += 1
    completed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    con = db.connect(database)
    try:
        with db.transaction(con):
            result = p15_price_fetch_attempts.record(
                con, market_date=market_date, attempted_at=attempted_at,
                requested_count=requested, failed_count=failed,
            )
            for receipt in receipts:
                p15_price_fetch_attempts.record_open_label_receipt(
                    con, completed_at=completed_at, **receipt,
                )
        return {
            **result, "requested": requested, "failed": failed,
            "open_label_requested": outstanding,
            "open_label_completed": exact_completed,
            "open_label_missing": sum(row["status"] == "missing" for row in receipts),
            "open_label_failed": exact_failed,
            "open_label_deferred": outstanding - len(obligations),
            "open_label_outstanding": outstanding,
        }
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
