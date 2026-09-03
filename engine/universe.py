#!/usr/bin/env python
"""Build the tradable universe from the Nasdaq Trader symbol directory.

Downloads nasdaqtraded.txt over HTTPS (with a browser UA and retries), verifies
the file is complete via its 'File Creation Time:' footer, filters to common
stocks + ETFs, and upserts into the DuckDB `universe` table. Appends today's
full point-in-time snapshot (append-only) and writes data/universe.csv.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from engine.lib import db
from engine.lib.settings import DATA_DIR, STORE_DIR
from engine.lib.log import get_logger

log = get_logger("universe")
NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqtraded.txt"
FOOTER_PREFIX = "File Creation Time:"
UA = "Mozilla/5.0"


def download_nasdaqtraded(max_retries: int = 5) -> str:
    """Fetch the full symbol directory, verifying the footer. Fail loudly if
    every attempt returns a truncated file."""
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(NASDAQ_URL, headers={"User-Agent": UA}, timeout=120)
            resp.raise_for_status()
            text = resp.text
            # Completeness check: the real file ends with the footer line.
            tail = [ln for ln in text.splitlines() if ln.strip()]
            if tail and tail[-1].startswith(FOOTER_PREFIX):
                return text
            last_err = f"footer '{FOOTER_PREFIX}' missing (got {len(tail)} lines)"
        except requests.RequestException as exc:
            last_err = str(exc)
        backoff = 2 ** attempt
        log.warning(f"[universe] attempt {attempt} failed: {last_err}; retrying in {backoff}s")
        time.sleep(backoff)
    raise RuntimeError(
        f"nasdaqtraded.txt still incomplete after {max_retries} attempts: {last_err}. "
        "Refusing to build a universe from a truncated file."
    )


def cache_raw(text: str) -> Path:
    """Persist the raw file to store/ for provenance."""
    out = STORE_DIR / f"nasdaqtraded-{datetime.now(timezone.utc).date().isoformat()}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    return out


def _word_in(name: str, word: str) -> bool:
    """Case-insensitive whole-word match within a security name."""
    import re

    return re.search(rf"\b{re.escape(word)}\b", name, flags=re.IGNORECASE) is not None


def parse(text: str) -> pd.DataFrame:
    """Parse the pipe-delimited body (skip header + footer) and filter to
    common stocks + ETFs."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    # Drop the footer line.
    if lines and lines[-1].startswith(FOOTER_PREFIX):
        lines = lines[:-1]
    from io import StringIO

    df = pd.read_csv(StringIO("\n".join(lines)), sep="|", dtype=str, keep_default_na=False)
    total = len(df)

    def keep(row: pd.Series) -> bool:
        sym = row["Symbol"]
        name = row["Security Name"]
        if row.get("Test Issue", "") == "Y":
            return False
        if row.get("NextShares", "") == "Y":
            return False
        if "$" in sym:  # preferred shares
            return False
        # Warrants: '.W' or a trailing 'W' when the name says Warrant.
        if (".W" in sym or sym.endswith("W")) and _word_in(name, "Warrant"):
            return False
        if _word_in(name, "Right") or _word_in(name, "Unit"):
            return False
        return True

    kept = df[df.apply(keep, axis=1)].copy()
    kept["yf_ticker"] = kept["Symbol"].str.replace(".", "-", regex=False)
    kept["etf"] = kept["ETF"] == "Y"
    out = pd.DataFrame(
        {
            "ticker": kept["Symbol"],
            "yf_ticker": kept["yf_ticker"],
            "name": kept["Security Name"],
            "exchange": kept["Listing Exchange"],
            "etf": kept["etf"],
        }
    )
    out.attrs["total"] = total
    return out.reset_index(drop=True)


def sync_universe(con, parsed: pd.DataFrame) -> tuple[int, int]:
    """Upsert parsed tickers; deactivate tickers no longer in the file.
    Returns (new_count, deactivated_count)."""
    today = datetime.now(timezone.utc).date()
    con.register("_incoming_univ", parsed)

    existing = set(r[0] for r in con.execute("SELECT ticker FROM universe").fetchall())
    incoming = set(parsed["ticker"])
    new_count = len(incoming - existing)

    # New tickers: full insert with added=today, active=TRUE.
    con.execute(
        """
        INSERT INTO universe (ticker, yf_ticker, name, exchange, etf, member, added, active)
        SELECT i.ticker, i.yf_ticker, i.name, i.exchange, i.etf, NULL, ?, TRUE
        FROM _incoming_univ i
        WHERE i.ticker NOT IN (SELECT ticker FROM universe)
        """,
        [today],
    )
    # Existing tickers still in file: refresh metadata + reactivate, keep flags.
    con.execute(
        """
        UPDATE universe u
        SET yf_ticker = i.yf_ticker,
            name      = i.name,
            exchange  = i.exchange,
            etf       = i.etf,
            active    = TRUE
        FROM _incoming_univ i
        WHERE u.ticker = i.ticker
        """
    )
    # Tickers no longer present: deactivate (never delete).
    deactivated = con.execute(
        """
        SELECT COUNT(*) FROM universe
        WHERE active = TRUE AND ticker NOT IN (SELECT ticker FROM _incoming_univ)
        """
    ).fetchone()[0]
    con.execute(
        """
        UPDATE universe SET active = FALSE
        WHERE ticker NOT IN (SELECT ticker FROM _incoming_univ)
        """
    )
    con.unregister("_incoming_univ")
    return new_count, deactivated


def append_snapshot(con) -> bool:
    """Append today's full universe into universe_snapshot (idempotent).
    Returns True if rows were appended."""
    today = datetime.now(timezone.utc).date()
    exists = con.execute(
        "SELECT COUNT(*) FROM universe_snapshot WHERE snapshot_date = ?", [today]
    ).fetchone()[0]
    if exists:
        return False
    con.execute(
        """
        INSERT INTO universe_snapshot
            (snapshot_date, ticker, name, exchange, etf, member, active, liquid)
        SELECT ?, ticker, name, exchange, etf, member, active, liquid
        FROM universe
        """,
        [today],
    )
    return True


def write_csv(con) -> Path:
    out = DATA_DIR / "universe.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df = con.execute(
        """
        SELECT ticker, yf_ticker, name, exchange, etf, active, liquid
        FROM universe ORDER BY ticker
        """
    ).fetch_df()
    df.to_csv(out, index=False)
    return out


def main() -> int:
    # argparse added 2026-09-03 so `--help` describes the run instead of
    # performing it (a bare `python -m engine.universe --help` used to fetch the
    # Nasdaq file and append today's snapshot to the store).
    import argparse
    ap = argparse.ArgumentParser(
        description="Refresh `universe` from nasdaqtraded.txt and append today's "
                    "point-in-time universe_snapshot; writes data/universe.csv.")
    ap.add_argument("--db", default=str(db.DEFAULT_DB), help="DuckDB path (default: the store)")
    args = ap.parse_args()

    text = download_nasdaqtraded()
    cache_raw(text)
    parsed = parse(text)
    total = parsed.attrs.get("total", 0)

    con = db.connect(args.db)
    db.init_schema(con)
    new_count, deactivated = sync_universe(con, parsed)
    snap = append_snapshot(con)
    write_csv(con)
    kept = len(parsed)
    con.close()

    log.info(
        f"[universe] total parsed={total} kept={kept} new={new_count} "
        f"deactivated={deactivated} snapshot={'appended' if snap else 'exists'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
