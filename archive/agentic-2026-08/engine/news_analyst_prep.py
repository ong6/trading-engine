#!/usr/bin/env python3
"""Assemble the news-analyst prompt (input side only) — no model call, no writes
outside the engine repo.

Pure gathering step for engine/news_analyst.sh, following the design's "zero-tool,
wrapper-assembled" shape (trading/trading-engine/news-analyst-design.md): the wrapper
gathers every input and writes every output, so the model call itself is a pure
text -> text transform with no tools and no filesystem surface.

What it does:
  1. Reads the state file (last successful run's watermark) and slices
     ~/news-scraper/data/news.jsonl to records newer than it.
  2. Reads the owner's watchlist.md + market-context.md from the personal data store
     (READ ONLY — this script never writes there).
  3. Queries store/market.duckdb READ ONLY for the paper league's open positions.
     The nightly/farm holds a write lock at times, so this retries briefly and then
     degrades to a stated "unavailable" line rather than failing the run.
  4. Writes prompt.txt (standing instructions + the four inputs) and meta.json.

meta.json = {"new_count", "last_scraped_at", "last_guid", "window_from", "window_to",
             "positions_ok"}.  The caller only advances the state file when the model
call succeeds, so a failed run's headlines are re-covered on the next run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.lib import db
from engine.lib.settings import DATA_DIR, DEFAULT_DB, REPO_ROOT, WATCHLIST_PATH
from engine.lib.settings import NOTES_DIR as STORE

NEWS_JSONL = Path(os.path.expanduser("~/news-scraper/data/news.jsonl"))
WATCHLIST = WATCHLIST_PATH
MARKET_CONTEXT = STORE / "market-context.md"
DB_PATH = DEFAULT_DB
PROMPT_FILE = REPO_ROOT / "engine" / "news_analyst_prompt.md"
# Last-good positions snapshot. DuckDB is single-writer and the farm/nightly can
# hold the write lock for a long drain, so a locked DB degrades to yesterday's
# holdings (clearly dated in the prompt) instead of no holdings at all.
POS_CACHE = DATA_DIR / "news_positions_cache.json"

# Cold-start window when there is no state file yet.
DEFAULT_LOOKBACK_HOURS = 24
# Prompt-size guard: keep the most recent N headlines if a backlog piles up
# (e.g. the analyst was down for a week). ~150/weekday is the normal volume.
MAX_HEADLINES = 400


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def slice_news(since: str) -> list[dict]:
    """Records with scraped_at > `since`, in file order. Malformed lines are skipped
    rather than fatal — the feed is append-only and a torn last line is possible if
    the scraper is mid-write."""
    out = []
    if not NEWS_JSONL.exists():
        return out
    with NEWS_JSONL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if (rec.get("scraped_at") or "") > since:
                out.append(rec)
    return out


def open_positions() -> tuple[str, bool]:
    """Distinct tickers currently held across the active paper-league portfolios.

    Read-only connection with a short retry: engine/queue_runner.py and the nightly
    take a write lock, and DuckDB is single-writer, so a transient conflict is normal
    and must not fail a non-critical news run.
    """
    last_err = None
    for attempt in range(1):  # retry lives in db.connect (~30s window)
        try:
            con = db.connect(DB_PATH, read_only=True, wait_s=30)
        except Exception as e:
            last_err = e
            continue
        try:
            rows = con.execute(
                """
                SELECT p.ticker,
                       COUNT(DISTINCT p.portfolio_id) AS books
                  FROM sim_positions p
                  JOIN portfolios f ON f.id = p.portfolio_id
                 WHERE p.qty > 0 AND f.active
                 GROUP BY p.ticker
                 ORDER BY books DESC, p.ticker
                """
            ).fetchall()
        finally:
            con.close()
        text = (", ".join(f"{t} (in {b} book{'s' if b != 1 else ''})" for t, b in rows)
                if rows else "(no open positions in the paper league)")
        try:
            POS_CACHE.write_text(json.dumps({"as_of": utcnow(), "text": text}, indent=2) + "\n")
        except Exception:
            pass
        return text, True

    cached = read_state(POS_CACHE)
    if cached.get("text"):
        return (f"{cached['text']}\n\n_(engine DB was locked by another process; this is the "
                f"last successful snapshot, taken {cached['as_of']} — treat as slightly stale)_"), False
    return f"(unavailable: DuckDB locked by another engine process — {last_err})", False


def read_store(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return f"(unavailable: {e})"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--prompt-out", required=True)
    ap.add_argument("--meta-out", required=True)
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    ap.add_argument("--lookback-hours", type=int, default=DEFAULT_LOOKBACK_HOURS)
    args = ap.parse_args()

    state = read_state(Path(args.state))
    since = state.get("last_scraped_at")
    if not since:
        cold = datetime.now(timezone.utc) - timedelta(hours=args.lookback_hours)
        since = cold.strftime("%Y-%m-%dT%H:%M:%SZ")

    items = slice_news(since)
    meta = {
        "new_count": len(items),
        "window_from": since,
        "window_to": utcnow(),
        "last_scraped_at": items[-1]["scraped_at"] if items else since,
        "last_guid": (items[-1].get("guid") or items[-1].get("link") or "") if items else state.get("last_guid", ""),
        "positions_ok": True,
        "truncated": False,
    }

    if not items:
        # Nothing to analyse: write meta and stop. The caller skips the model call.
        Path(args.meta_out).write_text(json.dumps(meta, indent=2) + "\n")
        return 0

    if len(items) > MAX_HEADLINES:
        items = items[-MAX_HEADLINES:]
        meta["truncated"] = True

    positions, positions_ok = open_positions()
    meta["positions_ok"] = positions_ok

    headlines = []
    for rec in items:
        title = (rec.get("title") or "").replace("\n", " ").strip()
        if not title:
            continue
        headlines.append(f"- [{rec.get('source', '?')}] {title}")

    parts = [
        read_store(PROMPT_FILE),
        "",
        "---",
        "",
        f"## INPUT A — Headlines collected {meta['window_from']} .. {meta['window_to']} "
        f"({len(headlines)} titles, no article bodies)"
        + ("  \n_(older items beyond the most recent "
           f"{MAX_HEADLINES} were dropped to bound the prompt)_" if meta["truncated"] else ""),
        "",
        "\n".join(headlines),
        "",
        "---",
        "",
        "## INPUT B — Watchlist (owner's, verbatim)",
        "",
        read_store(WATCHLIST),
        "",
        "---",
        "",
        "## INPUT C — Market context (current macro regime read)",
        "",
        read_store(MARKET_CONTEXT),
        "",
        "---",
        "",
        "## INPUT D — Paper-league open positions (engine DB, read-only)",
        "",
        positions,
        "",
        "---",
        "",
        f"Today's date is {args.date}. Write the brief now, following the standing "
        "instructions above. Output markdown only.",
        "",
    ]

    Path(args.prompt_out).write_text("\n".join(parts), encoding="utf-8")
    Path(args.meta_out).write_text(json.dumps(meta, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
