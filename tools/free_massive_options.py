#!/usr/bin/env python3
"""Capture a bounded free Massive option reference and daily-bar universe."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse

import requests

from engine import free_massive_options as options
from engine import free_sources
from engine.lib import db
from engine.lib.settings import REPO_ROOT
from tools import free_sources as daily_capture

CONTRACTS_ENDPOINT = "https://api.massive.com/v3/reference/options/contracts"
DAILY_ENDPOINT = "https://api.massive.com/v2/aggs/ticker/O:{occ}/range/1/day/{start}/{end}"
MANIFEST_PATH = REPO_ROOT / "server/options-capture-manifest.json"
HTTP_TIMEOUT_SECONDS = 60


def _manifest_identity(payload: dict) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    return hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise free_sources.FreeSourceError("Massive options manifest is invalid") from exc
    expected = {
        "schema_version", "source", "underlyings", "expiry_days_min", "expiry_days_max",
        "strike_band_fraction", "contracts_page_limit", "max_contract_pages_per_underlying",
        "daily_bar_request_cap", "daily_bar_lookback_calendar_days", "manifest_sha256",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != expected
        or payload.get("schema_version") != 1
        or payload.get("source") != "massive_free_options"
        or payload.get("underlyings") != ["SPY", "QQQ", "IWM"]
        or payload.get("expiry_days_min") != 20
        or payload.get("expiry_days_max") != 60
        or payload.get("strike_band_fraction") != 0.05
        or payload.get("contracts_page_limit") != 1000
        or payload.get("max_contract_pages_per_underlying") != 4
        or payload.get("daily_bar_request_cap") != 400
        or payload.get("daily_bar_lookback_calendar_days") != 5
        or payload.get("manifest_sha256") != _manifest_identity(payload)
    ):
        raise free_sources.FreeSourceError("Massive options manifest identity is invalid")
    return payload


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "api.massive.com"
        or parsed.username is not None
        or parsed.password is not None
        or not (
            parsed.path == "/v3/reference/options/contracts"
            or parsed.path.startswith("/v2/aggs/ticker/O:")
        )
    ):
        raise free_sources.FreeSourceError("Massive options URL is unsafe")


def _request_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def _cached_body(database: Path, data_dir: Path, url: str) -> tuple[bytes, datetime] | None:
    if not database.exists():
        return None
    con = db.connect(database, read_only=True)
    try:
        exists = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name='option_capture_receipts'"
        ).fetchone()[0]
        if not exists:
            return None
        receipt = con.execute(
            "SELECT source_sha256,fetched_at FROM option_capture_receipts WHERE request_key=?",
            [_request_key(url)],
        ).fetchone()
    finally:
        con.close()
    if receipt is None:
        return None
    source_sha, fetched_at = receipt
    try:
        raw = (data_dir / f"{source_sha}.json").read_bytes()
    except OSError as exc:
        raise free_sources.FreeSourceError(
            "Massive option cached response file is missing or unreadable"
        ) from exc
    if hashlib.sha256(raw).hexdigest() != source_sha:
        raise free_sources.FreeSourceError("Massive option cached response hash is invalid")
    return raw, fetched_at.replace(tzinfo=timezone.utc)


def _fetch(
    *, database: Path, data_dir: Path, url: str, api_key: str,
    session: requests.Session, now: Callable[[], datetime],
    rate_limit: Callable[[], object] | None,
) -> tuple[bytes, datetime, str, bool]:
    cached = _cached_body(database, data_dir, url)
    if cached is not None:
        body, fetched_at = cached
        return body, fetched_at, hashlib.sha256(body).hexdigest(), True
    _validate_url(url)
    daily_capture._require_network_window(now())
    if rate_limit is None:
        free_sources.wait_for_massive_rate_limit(
            check=lambda: daily_capture._require_network_window(now())
        )
    else:
        rate_limit()
        daily_capture._require_network_window(now())
    try:
        response = session.get(
            url, timeout=HTTP_TIMEOUT_SECONDS, allow_redirects=False,
            headers={
                "Authorization": f"Bearer {api_key}",
                "User-Agent": daily_capture.USER_AGENT,
                "Accept": "application/json",
            },
        )
    except requests.RequestException as exc:
        raise free_sources.FreeSourceError("Massive options request failed") from exc
    body = daily_capture._response_body(response, "Massive options")
    fetched_at = now()
    source_sha = hashlib.sha256(body).hexdigest()
    daily_capture._write_private_atomic(data_dir / f"{source_sha}.json", body)
    return body, fetched_at, source_sha, False


def _contracts_url(
    underlying: str, *, as_of: date, expiry_min: date, expiry_max: date,
    strike_min: float, strike_max: float,
) -> str:
    query = urlencode({
        "underlying_ticker": underlying,
        "as_of": as_of.isoformat(),
        "expiration_date.gte": expiry_min.isoformat(),
        "expiration_date.lte": expiry_max.isoformat(),
        "strike_price.gte": f"{strike_min:.6f}",
        "strike_price.lte": f"{strike_max:.6f}",
        "limit": options.MAX_CONTRACT_RESULTS,
        "sort": "ticker",
        "order": "asc",
    })
    return f"{CONTRACTS_ENDPOINT}?{query}"


def _daily_url(occ: str, start: date, end: date) -> str:
    base = DAILY_ENDPOINT.format(
        occ=quote(occ, safe=""), start=start.isoformat(), end=end.isoformat()
    )
    return f"{base}?{urlencode({'adjusted': 'true', 'sort': 'asc', 'limit': 50000})}"


def prior_closes(database: Path, underlyings: list[str], as_of: date) -> dict[str, float]:
    if not database.is_file():
        raise free_sources.FreeSourceError("Massive options daily-bar store is unavailable")
    con = db.connect(database, read_only=True)
    try:
        view_exists = con.execute(
            """SELECT COUNT(*) FROM information_schema.tables
            WHERE table_name='free_daily_bars_adjusted'"""
        ).fetchone()[0]
        if not view_exists:
            raise free_sources.FreeSourceError(
                "Massive options adjusted daily-bar view is unavailable"
            )
        rows = con.execute(
            """SELECT ticker, arg_max(c, date)
            FROM free_daily_bars_adjusted_asof(?)
            WHERE ticker IN (SELECT UNNEST(?)) AND date < ?
            GROUP BY ticker""",
            [as_of, underlyings, as_of],
        ).fetchall()
    finally:
        con.close()
    result = {ticker: float(close) for ticker, close in rows}
    missing = sorted(set(underlyings) - set(result))
    if missing:
        raise free_sources.FreeSourceError(
            f"Massive options prior close is missing for: {', '.join(missing)}"
        )
    return result


def _select_daily_contracts(
    con, *, as_of: date, underlyings: list[str], closes: Mapping[str, float], cap: int,
) -> list[str]:
    """Share the daily budget equally, preferring 31-60 DTE then near-money strikes."""
    if cap < 1 or not underlyings:
        return []
    per_underlying = cap // len(underlyings)
    if per_underlying < 1:
        raise free_sources.FreeSourceError(
            "Massive options daily request cap is below the underlying count"
        )
    selected = []
    for underlying in underlyings:
        close = float(closes[underlying])
        rows = con.execute(
            """SELECT occ,expiry,strike,"right" FROM option_contracts
            WHERE as_of=? AND underlying=?""",
            [as_of, underlying],
        ).fetchall()
        rows.sort(key=lambda row: (
            0 if 31 <= (row[1] - as_of).days <= 60 else 1,
            abs(float(row[2]) - close) / close,
            row[1], row[3], row[0],
        ))
        selected.extend(row[0] for row in rows[:per_underlying])
    return selected


def _store_contract_page(
    database: Path, *, body: bytes, url: str, source_sha: str, fetched_at: datetime,
    as_of: date, underlying: str, expiry_min: date, expiry_max: date,
    strike_min: float, strike_max: float,
) -> dict:
    con = db.connect(database, wait_s=0)
    try:
        with db.transaction(con):
            result = options.load_contracts_page(
                con, body, as_of=as_of, underlying=underlying,
                expiry_min=expiry_min, expiry_max=expiry_max,
                strike_min=strike_min, strike_max=strike_max,
                fetched_at=fetched_at, expected_sha256=source_sha,
            )
            options.record_receipt(
                con, request_key=_request_key(url), url=url, source_sha256=source_sha,
                fetched_at=fetched_at, row_count=result["row_count"],
            )
        return result
    finally:
        con.close()


def _store_daily_page(
    database: Path, *, body: bytes, url: str, source_sha: str, fetched_at: datetime,
    occ: str, start: date, end: date,
) -> dict:
    con = db.connect(database, wait_s=0)
    try:
        with db.transaction(con):
            result = options.load_daily_bars_page(
                con, body, occ=occ, start=start, end=end, fetched_at=fetched_at,
                expected_sha256=source_sha,
            )
            if result["next_url"] is not None:
                raise free_sources.FreeSourceError(
                    "Massive option daily response unexpectedly paginated"
                )
            options.record_receipt(
                con, request_key=_request_key(url), url=url, source_sha256=source_sha,
                fetched_at=fetched_at, row_count=result["row_count"],
            )
        return result
    finally:
        con.close()


def capture(
    *, database: Path, data_dir: Path, daily_database: Path,
    manifest_path: Path = MANIFEST_PATH, api_key: str | None = None,
    session: requests.Session | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    as_of: date | None = None, selected_underlyings: tuple[str, ...] | None = None,
    limit_pages: int | None = None, contracts_only: bool = False,
    rate_limit: Callable[[], object] | None = None,
    close_overrides: Mapping[str, float] | None = None,
) -> dict:
    manifest = load_manifest(manifest_path)
    capture_date = now().astimezone(timezone.utc).date() if as_of is None else as_of
    underlyings = list(selected_underlyings or manifest["underlyings"])
    if not underlyings or any(item not in manifest["underlyings"] for item in underlyings):
        raise free_sources.FreeSourceError("Massive options underlying selection is invalid")
    page_limit = manifest["max_contract_pages_per_underlying"]
    if limit_pages is not None:
        if limit_pages < 1:
            raise free_sources.FreeSourceError("Massive options page limit must be positive")
        page_limit = min(page_limit, limit_pages)
    closes = dict(close_overrides or prior_closes(daily_database, underlyings, capture_date))
    key = daily_capture._load_massive_key() if api_key is None else api_key
    client = session or requests.Session()
    expiry_min = capture_date + timedelta(days=manifest["expiry_days_min"])
    expiry_max = capture_date + timedelta(days=manifest["expiry_days_max"])
    summary = {"contract_pages": 0, "contracts": 0, "daily_requests": 0, "daily_bars": 0}
    truncated = []
    try:
        for underlying in underlyings:
            close = closes.get(underlying)
            if close is None or not math.isfinite(float(close)) or float(close) <= 0:
                raise free_sources.FreeSourceError("Massive options prior close is invalid")
            band = manifest["strike_band_fraction"]
            strike_min, strike_max = float(close) * (1 - band), float(close) * (1 + band)
            url = _contracts_url(
                underlying, as_of=capture_date, expiry_min=expiry_min,
                expiry_max=expiry_max, strike_min=strike_min, strike_max=strike_max,
            )
            for page in range(page_limit):
                _validate_url(url)
                body, fetched_at, source_sha, _cached = _fetch(
                    database=database, data_dir=data_dir, url=url, api_key=key,
                    session=client, now=now, rate_limit=rate_limit,
                )
                loaded = _store_contract_page(
                    database, body=body, url=url, source_sha=source_sha,
                    fetched_at=fetched_at, as_of=capture_date, underlying=underlying,
                    expiry_min=expiry_min, expiry_max=expiry_max,
                    strike_min=strike_min, strike_max=strike_max,
                )
                summary["contract_pages"] += 1
                summary["contracts"] += loaded["row_count"]
                if loaded["next_url"] is None:
                    break
                _validate_url(loaded["next_url"])
                url = loaded["next_url"]
                if page + 1 == page_limit:
                    truncated.append(underlying)
        if contracts_only:
            return {**summary, "as_of": capture_date.isoformat(), "truncated": truncated}
        con = db.connect(database, read_only=True)
        try:
            contracts = _select_daily_contracts(
                con, as_of=capture_date, underlyings=underlyings, closes=closes,
                cap=manifest["daily_bar_request_cap"],
            )
        finally:
            con.close()
        start = capture_date - timedelta(days=manifest["daily_bar_lookback_calendar_days"])
        for occ in contracts:
            url = _daily_url(occ, start, capture_date)
            body, fetched_at, source_sha, _cached = _fetch(
                database=database, data_dir=data_dir, url=url, api_key=key,
                session=client, now=now, rate_limit=rate_limit,
            )
            loaded = _store_daily_page(
                database, body=body, url=url, source_sha=source_sha,
                fetched_at=fetched_at, occ=occ, start=start, end=capture_date,
            )
            summary["daily_requests"] += 1
            summary["daily_bars"] += loaded["row_count"]
        return {**summary, "as_of": capture_date.isoformat(), "truncated": truncated}
    finally:
        if session is None:
            client.close()


def _close_overrides(values: list[str] | None) -> dict[str, float] | None:
    if values is None:
        return None
    result = {}
    try:
        for value in values:
            ticker, raw_close = value.split("=", 1)
            close = float(raw_close)
            if ticker in result or not ticker or not math.isfinite(close) or close <= 0:
                raise ValueError
            result[ticker] = close
    except (TypeError, ValueError) as exc:
        raise free_sources.FreeSourceError(
            "--prior-close must be a unique TICKER=POSITIVE_PRICE"
        ) from exc
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=options.default_database())
    parser.add_argument("--data-dir", type=Path, default=options.default_data_dir())
    parser.add_argument("--daily-database", type=Path, default=free_sources.default_database())
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--underlying", action="append")
    parser.add_argument("--limit-pages", type=int)
    parser.add_argument("--contracts-only", action="store_true")
    parser.add_argument(
        "--prior-close", action="append",
        help="verified TICKER=PRICE override for an isolated contracts smoke run",
    )
    args = parser.parse_args(argv)
    try:
        result = capture(
            database=args.database, data_dir=args.data_dir,
            daily_database=args.daily_database, manifest_path=args.manifest,
            as_of=args.as_of,
            selected_underlyings=None if args.underlying is None else tuple(args.underlying),
            limit_pages=args.limit_pages, contracts_only=args.contracts_only,
            close_overrides=_close_overrides(args.prior_close),
        )
    except free_sources.FreeSourceError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"status": "complete", "result": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
