#!/usr/bin/env python3
"""Recorded provider fixtures, contract replay and the runtime-environment contract.

  harvest    copy small, redacted samples of archived provider responses (*.json, *.zip
             only; never a DuckDB file) into tests/contracts/fixtures
  replay     drive a checkout's public ingest entry points with those fixtures, offline
  env-check  resolve every executable the units, drivers and runbooks call against the
             systemd user manager PATH and a clean `env -i` PATH

The module imports only the standard library at top level so `replay --root` can load the
engine of any checkout in a child process.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import io
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = REPO_ROOT / "tests/contracts"
FIXTURES_DIR = CONTRACTS_DIR / "fixtures"
ENV_RECORD = CONTRACTS_DIR / "systemd_env.json"

# Provider archives inside a checkout, read-only. Only these suffixes are ever opened.
ARCHIVE_DIRS = {
    "massive": "store/pit/free-sources/massive",
    "tiingo": "store/pit/free-sources/tiingo",
    "options": "store/pit/options",
}
ARCHIVE_SUFFIXES = frozenset({".json", ".zip"})
KNOWN_SECRET_FILES = (".config/trading-engine/massive.key",)
GROUPED_FIXTURE_ROWS = 120
GROUPED_FIXTURE_VIOLATIONS = 2  # kept if the archive ever carries OHLC violations
SPLIT_PAGE_ROWS = 5
CONTRACT_ROWS = 4
TIINGO_ADMITTED_ROWS = 12
TIINGO_OTHER_ROWS = 6


class ContractError(RuntimeError):
    """A harvest, replay or environment contract cannot be honoured safely."""


# --------------------------------------------------------------------------- secrets
SECRET_PARAM = re.compile(
    r"(?i)^(api[_-]?key|apikey|key|token|access[_-]?token|auth|authorization|secret|"
    r"client[_-]?secret|signature|sig|password|passwd)$"
)
REDACTED = "REDACTED"
_SECRET_PATTERNS = (
    ("credential assignment", re.compile(
        r"(?i)(api[_-]?key|apikey|access[_-]?token|client[_-]?secret|password|passwd)"
        r"[\"']?\s*[=:]\s*[\"']?(?!REDACTED)[^\"'&\s,}]{6,}")),
    ("bearer token", re.compile(r"(?i)\bbearer\s+(?!REDACTED)[A-Za-z0-9._~+/-]{8,}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("cloud key", re.compile(r"\b(AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abpr]-[\w-]{10,})")),
    ("home path", re.compile(r"/(home|data00|Users|root)/")),
    ("email address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")),
)
_TOKEN = re.compile(r"[A-Za-z0-9_\-]{28,}")
_HEX_ID = re.compile(r"[A-Za-z]?[0-9a-f]+")


def _safe_cursor(token: str) -> bool:
    """A provider cursor is allowed when it decodes to a query string with no credential."""
    try:
        decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    if not decoded.isprintable() or "=" not in decoded:
        return False
    pairs = parse_qsl(decoded, keep_blank_values=True)
    return bool(pairs) and not any(SECRET_PARAM.match(name) for name, _ in pairs)


def find_secrets(data: bytes, known: tuple[bytes, ...] = ()) -> list[str]:
    """Return a reason per secret-like span; empty means the bytes are safe to commit."""
    text = data.decode("utf-8", errors="replace")
    found = [f"{label}: {match.group(0)[:12]}..."
             for label, pattern in _SECRET_PATTERNS for match in pattern.finditer(text)]
    for match in _TOKEN.finditer(text):
        token = match.group(0)
        mixed = (re.search(r"[a-z]", token) and re.search(r"[A-Z]", token)
                 and re.search(r"[0-9]", token))
        if mixed and not _HEX_ID.fullmatch(token) and not _safe_cursor(token):
            found.append(f"high-entropy token: {token[:6]}...")
    found += ["known credential" for secret in known if secret and secret in data]
    return found


def redact_url(url: str) -> str:
    """Replace credential query values; refuse a cursor that carries one."""
    parsed = urlparse(url)
    if parsed.username or parsed.password:
        raise ContractError("provider URL carries user info")
    pairs = []
    for name, value in parse_qsl(parsed.query, keep_blank_values=True):
        if name == "cursor" and not SECRET_PARAM.match(name) and not _safe_cursor(value):
            raise ContractError("provider cursor does not decode to a credential-free query")
        pairs.append((name, REDACTED if SECRET_PARAM.match(name) else value))
    return urlunparse(parsed._replace(query=urlencode(pairs, safe=":/")))


def _redact(value):
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return redact_url(value)
    return value


def _known_secrets(home: Path) -> tuple[bytes, ...]:
    values = []
    for relative in KNOWN_SECRET_FILES:
        try:
            raw = (home / relative).read_bytes().strip()
        except OSError:
            continue
        if raw:
            values.append(raw)
    return tuple(values)


# --------------------------------------------------------------------------- harvest
def _archive_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        Path(entry.path) for entry in os.scandir(directory)
        if entry.is_file(follow_symlinks=False) and Path(entry.name).suffix in ARCHIVE_SUFFIXES
    )


def _read_archive(path: Path) -> bytes:
    if path.suffix not in ARCHIVE_SUFFIXES or "duckdb" in path.name:
        raise ContractError(f"refusing to open a non-response file: {path.name}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as handle:
        return handle.read()


def _dump(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode()


def _geometry(row: dict) -> str | None:
    """Classify one grouped-daily bar: ohlc (a violation), vwap_outside, flat or ok."""
    values = [row.get(key) for key in ("o", "h", "l", "c")]
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in values):
        return None
    o, high, low, close = values
    if low > min(o, high, close) or high < max(o, low, close):
        return "ohlc"
    vwap = row.get("vw")
    if isinstance(vwap, (int, float)) and not low <= vwap <= high:
        return "vwap_outside"
    return "flat" if high == low else "ok"


def _harvest_grouped(root: Path) -> tuple[dict, dict]:
    """Sample the newest archived day; summarise bar geometry over every archived day."""
    base = root / ARCHIVE_DIRS["massive"]
    totals, days, latest = {"ohlc": 0, "vwap_outside": 0, "flat": 0, "ok": 0, None: 0}, [], None
    for entry in sorted(os.scandir(base), key=lambda item: item.name):
        receipt_path = Path(entry.path) / "receipt.json"
        if (not entry.is_dir(follow_symlinks=False)
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry.name) or not receipt_path.is_file()):
            continue
        receipt = json.loads(_read_archive(receipt_path))
        payload = json.loads(_read_archive(Path(entry.path) / receipt["raw_file"]))
        results = [row for row in payload.get("results") or [] if isinstance(row, dict)]
        counts = {key: 0 for key in totals}
        for row in results:
            counts[_geometry(row)] += 1
        for key, value in counts.items():
            totals[key] += value
        days.append((entry.name, len(results), counts))
        if results:
            latest = (entry.name, receipt, payload)
    if latest is None:
        raise ContractError("no archived grouped-daily day")
    session, receipt, payload = latest
    rows = payload["results"]
    kinds = [_geometry(row) for row in rows]
    quota = {"ohlc": GROUPED_FIXTURE_VIOLATIONS, "vwap_outside": 6, "flat": 2}
    kept = []
    for kind, limit in quota.items():
        kept += [index for index, item in enumerate(kinds) if item == kind][:limit]
    kept += [index for index, item in enumerate(kinds) if item == "ok"][
        :GROUPED_FIXTURE_ROWS - len(kept)]
    sample = [rows[index] for index in sorted(kept)]
    body = {**payload, "results": sample, "resultsCount": len(sample)}
    for field in ("queryCount", "count"):
        if field in body:
            body[field] = len(sample)
    measured = [(name, count, counts) for name, count, counts in days if count]
    summary = {
        "days": len(days), "rows": sum(count for _name, count, _counts in days),
        "ohlc_violations": totals["ohlc"], "vwap_outside_high_low": totals["vwap_outside"],
        "flat_bars": totals["flat"], "invalid_numbers": totals[None],
        "max_day_ohlc_share": round(max(c["ohlc"] / n for _d, n, c in measured), 6),
        "max_day_vwap_outside_share": round(
            max(c["vwap_outside"] / n for _d, n, c in measured), 6),
    }
    fixture = {
        "file": "massive-grouped-daily.json", "session_date": session,
        "fetched_at": receipt["fetched_at"], "source_sha256": receipt["source_sha256"],
        "source_rows": len(rows), "rows": len(sample),
        "ohlc_violations": sum(1 for row in sample if _geometry(row) == "ohlc"),
        "vwap_outside_high_low": sum(1 for row in sample if _geometry(row) == "vwap_outside"),
        "_body": _redact(body),
    }
    return fixture, summary


def _harvest_splits(root: Path) -> dict:
    pages = []
    for path in _archive_files(root / ARCHIVE_DIRS["massive"] / "splits"):
        payload = json.loads(_read_archive(path))
        results = payload.get("results") or []
        if payload.get("status") == "OK" and results:
            pages.append((results[0]["execution_date"], path.stat().st_mtime, path, payload))
    if not pages:
        raise ContractError("no archived Massive split page")
    runs = []  # pages written within an hour of each other belong to one capture run
    for item in sorted(pages, key=lambda item: item[1]):
        if runs and item[1] - runs[-1][-1][1] < 3600:
            runs[-1].append(item)
        else:
            runs.append([item])

    def bound(run):
        return len(run) + (1 if "next_url" in max(run, key=lambda item: item[0])[3] else 0)

    # The longest chain is the evidence the page bound must cover; ties take the newest.
    run = sorted(max(runs, key=lambda run: (bound(run), run[-1][1])), key=lambda item: item[:2])
    files, chain = [], []
    for index, (_first, mtime, path, payload) in enumerate(run, 1):
        rows = payload["results"]
        kept = rows[:SPLIT_PAGE_ROWS - 2] + rows[-2:] if len(rows) > SPLIT_PAGE_ROWS else rows
        body = _redact({**payload, "results": kept})
        name = f"massive-splits-page-{index}.json"
        files.append((name, body))
        chain.append({
            "file": name, "source_sha256": path.stem, "source_rows": len(rows),
            "rows": len(kept), "has_next_url": "next_url" in payload,
            "fetched_at": datetime.fromtimestamp(mtime, timezone.utc).isoformat(),
        })
    observed = len(chain) + (1 if chain[-1]["has_next_url"] else 0)
    return {"pages": chain, "chain_length_lower_bound": observed,
            "terminal": "synthetic empty OK page after the last recorded next_url",
            "_files": files}


def _harvest_options(root: Path) -> dict:
    contracts, daily = {}, []
    for path in _archive_files(root / ARCHIVE_DIRS["options"]):
        payload = json.loads(_read_archive(path))
        results = payload.get("results") or []
        mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if str(payload.get("ticker", "")).startswith("O:"):
            daily.append((payload.get("status") != "DELAYED", path, payload, mtime))
        elif results and "contract_type" in results[0]:
            contracts[results[0]["underlying_ticker"]] = (path, payload, mtime)
    if not daily or not contracts:
        raise ContractError("archived option contracts and daily bars are both required")
    _ok, daily_path, daily_payload, daily_at = sorted(daily, key=lambda item: item[:2])[0]
    occ = daily_payload["ticker"]
    files, pages = [], []
    for underlying, (path, payload, _mtime) in sorted(contracts.items()):
        rows = payload["results"]
        kept = rows[:CONTRACT_ROWS]
        kept += [row for row in rows if row["ticker"] == occ and row not in kept]
        kept.sort(key=rows.index)
        strikes = [row["strike_price"] for row in rows]
        name = f"massive-option-contracts-{underlying}.json"
        files.append((name, _redact({**payload, "results": kept})))
        pages.append({
            "file": name, "underlying": underlying, "source_sha256": path.stem,
            "source_rows": len(rows), "rows": len(kept),
            # The midpoint of the recorded strike band reproduces the request's prior close.
            "close": round((min(strikes) / 0.95 + max(strikes) / 1.05) / 2, 6),
            "expiry_min": min(row["expiration_date"] for row in rows),
            "expiry_max": max(row["expiration_date"] for row in rows),
        })
    files.append(("massive-option-daily.json", _redact(daily_payload)))
    return {
        "as_of": daily_at.date().isoformat(), "now": daily_at.isoformat(),
        "contracts": pages,
        "daily": {"file": "massive-option-daily.json", "occ": occ.removeprefix("O:"),
                  "status": daily_payload.get("status"), "source_sha256": daily_path.stem,
                  "rows": len(daily_payload.get("results") or [])},
        "_files": files,
    }


def _harvest_tiingo(root: Path) -> tuple[dict, bytes]:
    archives = _archive_files(root / ARCHIVE_DIRS["tiingo"])
    if not archives:
        raise ContractError("no archived Tiingo ticker archive")
    path = archives[-1]
    with zipfile.ZipFile(io.BytesIO(_read_archive(path))) as archive:
        member = archive.infolist()[0]
        lines = archive.read(member).decode("utf-8-sig").splitlines()
    header, rows = lines[0], lines[1:]
    admitted = [line for line in rows if ",Stock,USD," in line
                and line.split(",")[1] in {"NYSE", "NASDAQ", "NYSE ARCA", "NYSE MKT", "BATS"}]
    other = [line for line in rows if ",USD," not in line or ",Stock," not in line]
    kept = sorted(set(admitted[:TIINGO_ADMITTED_ROWS] + other[:TIINGO_OTHER_ROWS]), key=rows.index)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo(member.filename, date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, "\n".join([header, *kept]) + "\n")
    fixture = {"file": "tiingo-supported-tickers.zip", "source_sha256": path.stem,
               "source_rows": len(rows), "rows": len(kept),
               "fetched_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}
    return fixture, buffer.getvalue()


def harvest(source_root: Path, out: Path, *, home: Path | None = None) -> dict:
    """Write the fixture set atomically; any secret-like byte aborts before a file lands."""
    home = Path.home() if home is None else home
    source_root = source_root.resolve()
    grouped, summary = _harvest_grouped(source_root)
    splits = _harvest_splits(source_root)
    options = _harvest_options(source_root)
    tiingo, tiingo_zip = _harvest_tiingo(source_root)
    files = {grouped["file"]: _dump(grouped.pop("_body")), tiingo["file"]: tiingo_zip}
    files.update((name, _dump(body)) for name, body in splits.pop("_files"))
    files.update((name, _dump(body)) for name, body in options.pop("_files"))
    manifest = {
        "schema_version": 1,
        "harvested_on": datetime.now(timezone.utc).date().isoformat(),
        "grouped_daily": grouped, "grouped_daily_archive": summary,
        "splits": splits, "options": options, "tiingo": tiingo,
    }
    files["manifest.json"] = (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode()
    known = _known_secrets(home)
    for name, data in files.items():
        scanned = data
        if name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                scanned = b"".join(archive.read(item) for item in archive.namelist())
        problems = find_secrets(scanned, known) + find_secrets(name.encode())
        if problems:
            raise ContractError(f"{name} is not safe to commit: {problems[0]}")
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out) as staging:
        for name, data in files.items():
            with open(Path(staging) / name, "wb") as handle:
                handle.write(data)
        for name in files:
            os.replace(Path(staging) / name, out / name)
    return {"files": sorted(files), "grouped_daily_archive": summary,
            "split_chain_lower_bound": splits["chain_length_lower_bound"]}


# --------------------------------------------------------------------------- replay
class _Response:
    def __init__(self, body: bytes, status_code: int = 200):
        self.content = body
        self.status_code = status_code


class _FixtureSession:
    """Serve recorded bodies by URL; anything unrecorded is an HTTP 404."""

    def __init__(self, route):
        self.route = route
        self.urls: list[str] = []

    def get(self, url, params=None, **_kwargs):
        if params:
            url = f"{url}?{urlencode(params)}"
        self.urls.append(url)
        body = self.route(url)
        return _Response(b'{"status":"NOT_FOUND"}', 404) if body is None else _Response(body)

    def close(self):
        return None


def _manifest(fixtures: Path) -> dict:
    return json.loads((fixtures / "manifest.json").read_text())


def _instant(raw: str) -> datetime:
    return datetime.fromisoformat(raw).astimezone(timezone.utc)


def case_tiingo_security_master(fixtures: Path, work: Path) -> str:
    from tools import free_sources as capture
    spec = _manifest(fixtures)["tiingo"]
    body = (fixtures / spec["file"]).read_bytes()
    session = _FixtureSession(lambda url: body if url == capture.TIINGO_URL else None)
    result = capture.capture_tiingo(database=work / "free.duckdb", data_dir=work / "raw",
                                    session=session, now=lambda: _instant(spec["fetched_at"]))
    if not 0 < result["row_count"] < spec["rows"]:
        raise ContractError(f"admitted {result['row_count']} of {spec['rows']} recorded rows")
    return f"{result['row_count']} admitted of {spec['rows']} recorded rows"


def case_massive_grouped_daily_geometry(fixtures: Path, work: Path) -> str:
    from engine import free_sources
    from tools import free_sources as capture
    spec = _manifest(fixtures)["grouped_daily"]
    body = (fixtures / spec["file"]).read_bytes()
    session_date = date.fromisoformat(spec["session_date"])
    fetched_at = _instant(spec["fetched_at"])
    session = _FixtureSession(lambda url: body if session_date.isoformat() in url else None)
    result = capture.capture_massive_dates(
        [session_date], api_key="fixture-key", database=work / "free.duckdb",
        data_dir=work / "raw", session=session, now=lambda: fetched_at,
        monotonic=lambda: 0.0, sleep=lambda _seconds: None, rate_limit=lambda: None,
        window=(session_date, session_date),
    )[0]
    _rows, rejects = free_sources.parse_massive_grouped_daily_with_rejects(body, session_date)
    reasons = {item["reason"] for item in rejects}
    expected = (spec["rows"] - spec["ohlc_violations"], spec["ohlc_violations"])
    if (result["row_count"], result["rejected"]) != expected or not reasons <= {"ohlc_relationship"}:
        raise ContractError(f"loaded {result['row_count']} rejected {result['rejected']} "
                            f"({sorted(reasons)}); expected {expected}")
    return (f"{result['row_count']} bars ({spec['vwap_outside_high_low']} with VWAP outside "
            f"high-low), {result['rejected']} OHLC rejects")


def case_massive_splits_chain(fixtures: Path, work: Path) -> str:
    from tools import free_sources as capture
    spec = _manifest(fixtures)["splits"]
    pages = [(fixtures / page["file"]).read_bytes() for page in spec["pages"]]
    terminal = _dump({"status": "OK", "request_id": "synthetic-terminal", "results": []})
    links = {}
    for index, body in enumerate(pages):
        next_url = json.loads(body).get("next_url")
        if next_url:
            links[next_url] = pages[index + 1] if index + 1 < len(pages) else terminal
    first = []

    def route(url):
        if url in links:
            return links[url]
        if not first:
            first.append(url)
            return pages[0]
        return None

    session = _FixtureSession(route)
    fetched_at = _instant(spec["pages"][-1]["fetched_at"])
    result = capture.capture_massive_splits(
        database=work / "free.duckdb", data_dir=work / "raw", api_key="fixture-key",
        session=session, now=lambda: fetched_at, rate_limit=lambda: None,
    )
    expected = spec["chain_length_lower_bound"]
    if result.get("status") != "complete" or len(session.urls) != expected:
        raise ContractError(f"{len(session.urls)} requests for a {expected}-page chain")
    return f"{len(session.urls)}-page chain complete"


def _options_capture(fixtures: Path, work: Path, *, contracts_only: bool):
    from tools import free_massive_options as capture
    spec = _manifest(fixtures)["options"]
    occ = spec["daily"]["occ"]
    daily = (fixtures / spec["daily"]["file"]).read_bytes()
    bodies = {page["underlying"]: json.loads((fixtures / page["file"]).read_bytes())
              for page in spec["contracts"]}
    underlying = re.match(r"[A-Z.]+?(?=\d{6}[CP])", occ).group(0)
    underlyings = tuple(sorted(bodies)) if contracts_only else (underlying,)
    if not contracts_only:  # only the contract with a recorded daily response is asked for
        payload = bodies[underlyings[0]]
        bodies[underlyings[0]] = {**payload, "results": [
            row for row in payload["results"] if row["ticker"] == f"O:{occ}"]}

    def route(url):
        parsed = urlparse(url)
        if parsed.path == "/v3/reference/options/contracts":
            underlying = dict(parse_qsl(parsed.query)).get("underlying_ticker")
            return _dump(bodies[underlying]) if underlying in bodies else None
        return daily if parsed.path.startswith(f"/v2/aggs/ticker/O:{occ}/") else None

    closes = {page["underlying"]: page["close"] for page in spec["contracts"]}
    # The contract is the recorded responses' parse, not the schedule: collection is paused
    # for live runs until a registered reader exists, so the offline replay lifts the pause.
    paused, capture.COLLECTION_ENABLED = capture.COLLECTION_ENABLED, True
    try:
        result = capture.capture(
            database=work / "options.duckdb", data_dir=work / "raw",
            daily_database=work / "unused.duckdb", api_key="fixture-key",
            session=_FixtureSession(route), now=lambda: _instant(spec["now"]),
            as_of=date.fromisoformat(spec["as_of"]), selected_underlyings=underlyings,
            contracts_only=contracts_only, rate_limit=lambda: None,
            close_overrides={key: closes[key] for key in underlyings},
        )
    finally:
        capture.COLLECTION_ENABLED = paused
    return result, spec


def case_massive_option_contracts(fixtures: Path, work: Path) -> str:
    result, spec = _options_capture(fixtures, work, contracts_only=True)
    expected = sum(page["rows"] for page in spec["contracts"])
    if result["contracts"] != expected or result["truncated"]:
        raise ContractError(f"loaded {result['contracts']} of {expected} recorded contracts")
    return f"{result['contracts']} contracts over {result['contract_pages']} pages"


def case_massive_option_daily_delayed(fixtures: Path, work: Path) -> str:
    result, spec = _options_capture(fixtures, work, contracts_only=False)
    if result["daily_bars"] != spec["daily"]["rows"]:
        raise ContractError(f"loaded {result['daily_bars']} of {spec['daily']['rows']} bars")
    return f"{result['daily_bars']} {spec['daily']['status']} bars"


PROVIDER_CASES = {
    "tiingo_security_master": case_tiingo_security_master,
    "massive_grouped_daily_geometry": case_massive_grouped_daily_geometry,
    "massive_splits_chain": case_massive_splits_chain,
    "massive_option_contracts": case_massive_option_contracts,
    "massive_option_daily_delayed": case_massive_option_daily_delayed,
}


def run_provider_cases(fixtures: Path, work: Path) -> dict:
    """Run every provider case in this interpreter; the network is refused throughout."""
    import requests

    def refuse(*_args, **_kwargs):
        raise AssertionError("contract replay must not reach the network")

    original = requests.Session.request
    requests.Session.request = refuse
    results = {}
    try:
        for name, case in PROVIDER_CASES.items():
            (work / name).mkdir(parents=True, exist_ok=True)
            try:
                results[name] = {"ok": True, "detail": case(fixtures, work / name)}
            except Exception as exc:  # noqa: BLE001 - each case reports its own failure
                results[name] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    finally:
        requests.Session.request = original
    return results


def replay(root: Path, *, fixtures: Path = FIXTURES_DIR, record: Path = ENV_RECORD,
           python: str = sys.executable) -> dict:
    """Replay the fixtures through `root`'s own code in a child, then its runtime contract."""
    root = root.resolve()
    with tempfile.TemporaryDirectory(prefix="provider-replay-") as work:
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("TRADING_ENGINE_")}
        env.update(PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE="1", TZ="UTC",
                   TRADING_ENGINE_FREE_SOURCES_DB=str(Path(work) / "env-free.duckdb"),
                   TRADING_ENGINE_FREE_SOURCES_DIR=str(Path(work) / "env-free"),
                   TRADING_ENGINE_MASSIVE_OPTIONS_DB=str(Path(work) / "env-options.duckdb"),
                   TRADING_ENGINE_MASSIVE_OPTIONS_DIR=str(Path(work) / "env-options"))
        child = subprocess.run(
            [python, "-P", str(Path(__file__).resolve()), "_provider-cases",
             "--fixtures", str(fixtures.resolve()), "--work", work],
            cwd=root, env=env, capture_output=True, text=True, timeout=600, check=False,
        )
    if child.returncode != 0:
        raise ContractError(f"replay child failed: {child.stderr.strip()[-2000:]}")
    results = json.loads(child.stdout)
    problems = environment_problems(root, load_record(record))
    results["runtime_environment"] = {
        "ok": not problems,
        "detail": "; ".join(problems) if problems else "every executable resolves",
    }
    return results


# --------------------------------------------------------------------------- env-check
SHELL_BUILTINS = frozenset("""
. : [ alias bg break builtin caller cd command compgen complete continue declare dirs disown
echo enable eval exec exit export false fc fg getopts hash help history jobs kill let local
logout mapfile popd printf pushd pwd read readarray readonly return set shift shopt source
suspend test times trap true type typeset ulimit umask unalias unset wait
""".split())
SHELL_KEYWORDS = frozenset("if then else elif fi do done while until in ! { } time".split())
WRAPPER_OPTIONS = {  # wrapper -> options that consume a value
    "xargs": {"-n", "-I", "-d", "-L", "-P", "-s", "-E", "-a"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
    "nice": {"-n"}, "nohup": set(), "env": {"-u", "-C", "-S"}, "setsid": set(),
}
_OPS = ("&&", "||", ";;", "|&", ";", "|", "&", "(", ")")
_REDIRECT = re.compile(r"&>>|&>|<<<|<<-|<<|<>|>>|>\||>&|<&|>|<")


class _Lexer:
    """Enough of bash to find command words: quotes, comments, substitutions, heredocs."""

    def __init__(self, text: str, line: int):
        self.text, self.base_line = text, line
        self.subs: list[list] = []

    def line_of(self, index: int) -> int:
        return self.base_line + self.text.count("\n", 0, index)

    def _skip_arith(self, i: int) -> int:
        depth = 0
        while i < len(self.text):
            if self.text[i] == "(":
                depth += 1
            elif self.text[i] == ")":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        return i

    def _brace(self, i: int) -> int:
        depth = 0
        while i < len(self.text):
            if self.text[i] == "{":
                depth += 1
            elif self.text[i] == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        return i

    def _heredoc_bodies(self, i: int, pending: list, tokens: list) -> int:
        for delimiter, strip, slot in pending:
            lines = []
            while i < len(self.text):
                end = self.text.find("\n", i)
                end = len(self.text) if end < 0 else end
                line = self.text[i:end]
                i = end + 1
                if (line.lstrip("\t") if strip else line) == delimiter:
                    break
                lines.append(line)
            tokens[slot] = ("heredoc", ("\n".join(lines), self.line_of(i) - len(lines) - 1))
        pending.clear()
        return i

    def lex(self, i: int = 0, *, until_paren: bool = False) -> tuple[list, int]:
        text, tokens, pending = self.text, [], []
        word, start, depth = None, 0, 0

        def flush():
            nonlocal word
            if word is not None:
                tokens.append(("word", ("".join(word), start)))
                word = None

        def add(chars, at):
            nonlocal word, start
            if word is None:
                word, start = [], at
            word.append(chars)

        while i < len(text):
            c = text[i]
            if c == "\\" and i + 1 < len(text):
                if text[i + 1] != "\n":
                    add(text[i + 1], i)
                i += 2
            elif c == "'":
                end = text.find("'", i + 1)
                end = len(text) if end < 0 else end
                add(text[i + 1:end], i)
                i = end + 1
            elif c == '"':
                add("", i)
                i += 1
                while i < len(text) and text[i] != '"':
                    if text[i] == "\\" and i + 1 < len(text):
                        word.append(text[i + 1])
                        i += 2
                    elif text.startswith("$((", i):
                        end = self._skip_arith(i + 1)
                        word.append("$((...))")
                        i = end
                    elif text.startswith("$(", i):
                        sub, end = self.lex(i + 2, until_paren=True)
                        self.subs.append(sub)
                        word.append("$(...)")
                        i = end
                    elif text.startswith("${", i):
                        end = self._brace(i + 1)
                        word.append(text[i:end])
                        i = end
                    else:
                        word.append(text[i])
                        i += 1
                i += 1
            elif text.startswith("$((", i):
                add("$((...))", i)
                i = self._skip_arith(i + 1)
            elif text.startswith("$(", i) or (word is None and text.startswith(("<(", ">("), i)):
                sub, end = self.lex(i + 2, until_paren=True)
                self.subs.append(sub)
                add("$(...)", i)
                i = end
            elif text.startswith("${", i):
                end = self._brace(i + 1)
                add(text[i:end], i)
                i = end
            elif c == "#" and word is None:
                end = text.find("\n", i)
                i = len(text) if end < 0 else end
            elif c in " \t":
                flush()
                i += 1
            elif c == "\n":
                flush()
                tokens.append(("op", "\n"))
                i = self._heredoc_bodies(i + 1, pending, tokens) if pending else i + 1
            elif c == "(" and word is not None and "".join(word).endswith("="):
                end = self._skip_arith(i)  # array literal: VAR=( ... )
                word.append(text[i:end])
                i = end
            elif c == "(" and word is None and text.startswith("((", i) and (
                    not tokens or tokens[-1][0] == "op"
                    or (tokens[-1][0] == "word" and tokens[-1][1][0] in SHELL_KEYWORDS)):
                end = self._skip_arith(i)
                tokens.append(("word", ("((...))", i)))
                i = end
            elif (c in "<>" or text.startswith("&>", i)) and not text.startswith(("<(", ">("), i):
                if word is not None and re.fullmatch(r"\d+|\{\w+\}", "".join(word)):
                    word = None  # a file-descriptor prefix, not a word
                flush()
                op = _REDIRECT.match(text, i).group(0)
                i += len(op)
                if op in ("<<", "<<-"):
                    while text[i] in " \t":
                        i += 1
                    match = re.match(r"(['\"]?)([\w-]+)\1", text[i:])
                    pending.append((match.group(2), op == "<<-", len(tokens)))
                    tokens.append(("heredoc", None))
                    i += match.end()
                else:
                    tokens.append(("redirect", op))
            elif any(text.startswith(op, i) for op in _OPS):
                op = next(op for op in _OPS if text.startswith(op, i))
                flush()
                if until_paren and op == "(":
                    depth += 1
                elif until_paren and op == ")":
                    if depth == 0:
                        return tokens, i + 1
                    depth -= 1
                tokens.append(("op", op))
                i += len(op)
            else:
                add(c, i)
                i += 1
        flush()
        return tokens, i


def _simple_commands(tokens: list) -> list[dict]:
    commands, current, i, case_pattern = [], None, 0, False

    def finish():
        nonlocal current
        if current and (current["words"] or current["heredocs"] or "function" in current):
            commands.append(current)
        current = None

    while i < len(tokens):
        kind, value = tokens[i]
        if current is None:
            current = {"words": [], "redirects": [], "heredocs": []}
        if kind == "op":
            if case_pattern and value != "\n":
                if value == ")":
                    case_pattern = False
                    current = None
                i += 1
                continue
            if value == "(" and len(current["words"]) == 1 and i + 1 < len(tokens) \
                    and tokens[i + 1] == ("op", ")"):
                current["function"] = current["words"][0][0]
                current["words"] = []
                i += 2
                finish()
                continue
            finish()
            if value == ";;":
                case_pattern = True
            i += 1
        elif kind == "redirect":
            target = tokens[i + 1][1][0] if i + 1 < len(tokens) and tokens[i + 1][0] == "word" else ""
            current["redirects"].append((value, target))
            i += 2
        elif kind == "heredoc":
            current["heredocs"].append(value)
            i += 1
        else:
            word = value[0]
            if case_pattern:
                if word == "esac":
                    case_pattern = False
                i += 1
                continue
            if word == "[[" and all(item[0] in SHELL_KEYWORDS for item in current["words"]):
                i += 1
                while i < len(tokens) and not (tokens[i][0] == "word" and tokens[i][1][0] == "]]"):
                    i += 1
                i += 1
                continue
            current["words"].append(value)
            if [item[0] for item in current["words"][:1]] == ["case"] and word == "in":
                current, case_pattern = None, True
                i += 1
                while i < len(tokens) and tokens[i] == ("op", "\n"):
                    i += 1
                continue
            i += 1
    finish()
    return commands


def shell_commands(text: str, line: int = 1) -> tuple[list[tuple[int, list[str]]], set[str]]:
    """Return (line, words) for every simple command, plus the functions the text defines."""
    lexer = _Lexer(text, line)
    tokens, _end = lexer.lex()
    found, functions = [], set()
    for piece in [tokens, *lexer.subs]:
        for command in _simple_commands(piece):
            if "function" in command:
                functions.add(command["function"])
                continue
            words = [(lexer.line_of(at), word) for word, at in command["words"]]
            found += _command_words(words)
            for body in command["heredocs"]:
                targets = [target for op, target in command["redirects"] if ">" in op]
                if body and words and words[0][1] == "cat" and any(
                        target.endswith((".bash", ".sh")) for target in targets):
                    nested, defined = shell_commands(*body)
                    found += nested
                    functions |= defined
    return found, functions


def _command_words(words: list[tuple[int, str]]) -> list[tuple[int, list[str]]]:
    while words and (words[0][1] in SHELL_KEYWORDS or re.match(r"^[A-Za-z_]\w*\+?=", words[0][1])):
        words = words[1:]
    if not words or words[0][1] in ("for", "case", "select", "function"):
        return []
    line, first = words[0]
    if first in ("exec", "command", "nohup", "setsid") or first in WRAPPER_OPTIONS:
        rest, index = words[1:], 0
        takes = WRAPPER_OPTIONS.get(first, set())
        while index < len(rest) and (rest[index][1].startswith("-") or "=" in rest[index][1]
                                     or (first == "timeout" and re.fullmatch(r"[\d.]+[smhd]?", rest[index][1]))
                                     or (first == "nice" and re.fullmatch(r"-?\d+", rest[index][1]))):
            index += 2 if rest[index][1] in takes else 1
        inner = _command_words(rest[index:])
        return ([] if first in ("exec", "command") else [(line, [first])]) + inner
    plain = [word for _line, word in words]
    if first.rsplit("/", 1)[-1] in ("bash", "sh") and "-c" in plain[1:]:
        script = plain[plain.index("-c") + 1] if plain.index("-c") + 1 < len(plain) else ""
        return [(line, plain)] + shell_commands(script, line)[0]
    return [(line, plain)]


def _unit_commands(text: str) -> tuple[list[tuple[int, list[str]]], str | None]:
    commands, path = [], None
    for number, raw in enumerate(text.splitlines(), 1):
        key, _sep, value = raw.partition("=")
        if key.strip() == "Environment":
            for item in shlex.split(value):
                if item.startswith("PATH="):
                    path = item[5:]
        elif key.strip().startswith("Exec") and value.strip():
            words = shlex.split(value.strip().lstrip("-@:+!|"))
            commands.append((number, words))
    return commands, path


def _runbook_blocks(text: str) -> list[tuple[int, str]]:
    blocks, current, start = [], None, 0
    for number, line in enumerate(text.splitlines(), 1):
        if current is None and re.fullmatch(r"```(bash|sh|shell)\s*", line):
            current, start = [], number + 1
        elif current is not None and line.startswith("```"):
            blocks.append((start, "\n".join(current) + "\n"))
            current = None
        elif current is not None:
            current.append(line)
    return blocks


def contract_sources(root: Path) -> list[dict]:
    """Every executable reference in a checkout, with where it runs."""
    sources = []
    for unit in sorted((root / "server").glob("*.service")):
        commands, path = _unit_commands(unit.read_text())
        sources.append({"file": unit.relative_to(root).as_posix(), "context": "unit",
                        "path": path, "commands": commands, "functions": set()})
    scripts = sorted({*(root / "engine").glob("*.sh"), root / "engine/lib/driver.sh",
                      *(root / "server").glob("run_*.sh")})
    for script in scripts:
        if script.is_file():
            commands, functions = shell_commands(script.read_text())
            sources.append({"file": script.relative_to(root).as_posix(), "context": "script",
                            "path": None, "commands": commands, "functions": functions})
    for runbook in sorted((root / "docs").glob("*runbook*.md")):
        commands, functions = [], set()
        for line, block in _runbook_blocks(runbook.read_text()):
            found, defined = shell_commands(block, line)
            commands += found
            functions |= defined
        sources.append({"file": runbook.relative_to(root).as_posix(), "context": "runbook",
                        "path": None, "commands": commands, "functions": functions})
    shared = set().union(*(source["functions"] for source in sources))
    for source in sources:
        source["functions"] = shared
    return sources


_HOME_FORMS = re.compile(r"^(%h|\$HOME|\$\{HOME\}|~)(/|$)")
_DEFAULTED = re.compile(r"^\$\{(\w+):-([^}]*)\}(/.*)?$")


def classify(word: str, functions: set[str]) -> tuple[str, str]:
    """Return (kind, target): builtin|function|dynamic|elision|venv|repo|home|absolute|bare."""
    if word in SHELL_BUILTINS or word in SHELL_KEYWORDS or word in ("[[", "((...))"):
        return "builtin", word
    if word in functions:
        return "function", word
    if re.fullmatch(r"\.{3,}", word):
        return "elision", word
    defaulted = _DEFAULTED.match(word)
    if defaulted:  # "${NODE_BIN:-$HOME/tools/node/bin}/node": the documented default decides
        word = defaulted.group(2) + (defaulted.group(3) or "")
    if _HOME_FORMS.match(word):
        return "home", _HOME_FORMS.sub("", word, count=1)
    if "$" in word:
        return "dynamic", word
    if word.startswith("/"):
        return "absolute", word
    if word.startswith(".venv/"):
        return "venv", word
    if "/" in word:
        return "repo", word.removeprefix("./")
    return "bare", word


def _references(root: Path):
    for source in contract_sources(root):
        for line, words in source["commands"]:
            if words:
                kind, target = classify(words[0], source["functions"])
                yield source, line, words[0], kind, target


def _resolve_on(path: str, name: str) -> str | None:
    for directory in path.split(":"):
        candidate = Path(directory) / name
        if directory.startswith("/") and candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def host_paths() -> dict[str, str]:
    shown = subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True,
                           text=True, check=True, timeout=30).stdout
    manager = next(line[5:] for line in shown.splitlines() if line.startswith("PATH="))
    clean = subprocess.run(["env", "-i", "/bin/bash", "--noprofile", "--norc", "-c",
                            'printf %s "$PATH"'], capture_output=True, text=True,
                           check=True, timeout=30).stdout
    return {"systemd_user": manager, "env_i": clean}


def record_environment(root: Path, paths: dict[str, str], previous: dict | None = None) -> dict:
    """The committed record: both PATHs and how each referenced name resolved on them.

    Names from a previous record are kept and re-resolved, so recording an older checkout
    first keeps its bare names (a removed `node`, say) visible to replays of that checkout.
    """
    home = str(Path.home())
    previous = previous or {}
    references = list(_references(root))
    names = sorted({target for _s, _l, _w, kind, target in references if kind == "bare"}
                   | set(previous.get("commands", {})))
    absolute = sorted({target for _s, _l, _w, kind, target in references if kind == "absolute"}
                      | set(previous.get("absolute", {})))
    record = {
        "schema_version": 1,
        "recorded_on": datetime.now(timezone.utc).date().isoformat(),
        "paths": paths,
        "commands": {name: {label: _resolve_on(path, name) for label, path in paths.items()}
                     for name in names},
        "absolute": {path: os.path.isfile(path) and os.access(path, os.X_OK)
                     for path in absolute},
    }
    rendered = json.dumps(record)
    if home in rendered or find_secrets(rendered.encode()):
        raise ContractError("the environment record would carry a home path or a secret")
    return record


def load_record(path: Path = ENV_RECORD) -> dict:
    return json.loads(path.read_text())


def environment_problems(root: Path, record: dict, *, host_home: Path | None = None) -> list[str]:
    """Every executable that would not start under the recorded (or live) environment.

    With host_home set the check is live: home-relative and venv paths must exist. Without
    it (CI) they are accepted as host-provisioned and only the recorded PATHs decide.
    """
    root = root.resolve()
    problems = []
    for source, line, word, kind, target in _references(root):
        where = f"{source['file']}:{line}"
        if kind == "bare":
            # A unit runs under the manager PATH (or its own Environment=PATH); drivers and
            # runbook blocks must also survive a clean `env -i` shell.
            labels = ("systemd_user",) if source["context"] == "unit" else ("systemd_user", "env_i")
            if host_home:
                paths = {"unit": source["path"]} if source["path"] else {
                    label: record["paths"][label] for label in labels}
                ok = {label: _resolve_on(path, target) for label, path in paths.items()}
            elif target not in record["commands"]:
                problems.append(f"{where}: {target} is not in the environment record "
                                "(re-record with env-check --record on the host)")
                continue
            else:
                ok = {label: record["commands"][target].get(label) for label in labels}
            missing = sorted(label for label, resolved in ok.items() if not resolved)
            if missing:
                problems.append(f"{where}: bare `{target}` is not on the {' or '.join(missing)} PATH")
        elif kind == "absolute":
            present = (os.path.isfile(target) and os.access(target, os.X_OK)) if host_home \
                else record["absolute"].get(target)
            if not present:
                problems.append(f"{where}: {target} is not an executable on the host")
        elif kind == "home":
            if target.startswith("trading-engine/"):
                local = root / target.removeprefix("trading-engine/")
                if target.startswith("trading-engine/.venv/"):
                    if host_home and not os.access(local, os.X_OK):
                        problems.append(f"{where}: {word} is missing from the checkout venv")
                elif not (local.is_file() and os.access(local, os.X_OK)):
                    problems.append(f"{where}: {word} is not an executable file in the checkout")
            elif host_home and not os.access(host_home / target, os.X_OK):
                problems.append(f"{where}: {word} is not executable on the host")
        elif kind == "venv" and host_home and not os.access(root / target, os.X_OK):
            problems.append(f"{where}: {target} is missing from the checkout venv")
        elif kind == "repo" and not (root / target).is_file():
            problems.append(f"{where}: {target} is not a file in the checkout")
    return problems


# --------------------------------------------------------------------------- CLI
def _print_results(results: dict) -> int:
    width = max(len(name) for name in results)
    for name, result in results.items():
        print(f"{'PASS' if result['ok'] else 'FAIL'}  {name:<{width}}  {result['detail']}")
    return 0 if all(result["ok"] for result in results.values()) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    harvest_cmd = commands.add_parser("harvest", help="refresh the redacted fixtures")
    harvest_cmd.add_argument("--source-root", type=Path, required=True,
                             help="checkout whose archived provider responses are sampled")
    harvest_cmd.add_argument("--out", type=Path, default=FIXTURES_DIR)
    replay_cmd = commands.add_parser("replay", help="replay fixtures through a checkout")
    replay_cmd.add_argument("--root", type=Path, required=True)
    replay_cmd.add_argument("--fixtures", type=Path, default=FIXTURES_DIR)
    replay_cmd.add_argument("--python", default=sys.executable)
    env_cmd = commands.add_parser("env-check", help="resolve executables on the live host")
    env_cmd.add_argument("--root", type=Path, default=REPO_ROOT)
    env_cmd.add_argument("--record", type=Path,
                         help="also write the environment record (tests/contracts/systemd_env.json)")
    child = commands.add_parser("_provider-cases")
    child.add_argument("--fixtures", type=Path, required=True)
    child.add_argument("--work", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "harvest":
            print(json.dumps(harvest(args.source_root, args.out), indent=1, sort_keys=True))
            return 0
        if args.command == "_provider-cases":
            print(json.dumps(run_provider_cases(args.fixtures, args.work), sort_keys=True))
            return 0
        if args.command == "replay":
            return _print_results(replay(args.root, fixtures=args.fixtures, python=args.python))
        paths = host_paths()
        print(json.dumps({"paths": paths}, indent=1))
        if args.record:
            previous = load_record(args.record) if args.record.is_file() else None
            record = record_environment(args.root, paths, previous)
            from engine.lib.resources import write_text_atomic
            write_text_atomic(args.record, json.dumps(record, indent=1, sort_keys=True) + "\n")
        problems = environment_problems(args.root, {"paths": paths}, host_home=Path.home())
        for problem in problems:
            print(f"FAIL  {problem}")
        print(f"{'PASS' if not problems else 'FAIL'}  runtime environment "
              f"({len(list(_references(args.root)))} executable references)")
        return 1 if problems else 0
    except ContractError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
