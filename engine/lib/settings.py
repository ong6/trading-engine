"""One place for repo paths and their environment overrides.

Everything else imports these names instead of recomputing
`Path(__file__).resolve().parents[N]` per file (refactor step 3, 2026-09-03).
Nothing here touches the filesystem beyond path arithmetic.

Environment overrides (all optional; relative paths resolve against REPO_ROOT):

  TRADING_ENGINE_DB           DuckDB store file      (default store/market.duckdb)
  TRADING_ENGINE_DATA_DIR     committed outputs dir  (default data/)
  TRADING_ENGINE_STORE_DIR    the owner's private notes dir that holds the
                              watchlist + market context — historically the
                              personal-data-store `trading/` folder, NOT the
                              DuckDB `store/` dir (name kept for compatibility
                              with the retired news_analyst_prep.py, now in
                              archive/agentic-2026-08/engine/)
  TRADING_ENGINE_WATCHLIST    watchlist.md (default <NOTES_DIR>/watchlist.md)
  TRADING_ENGINE_LOCK_WAIT_S  seconds a locked DuckDB open keeps retrying
                              (default 60; read at call time by engine.lib.db)
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    if not raw:
        return default
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (REPO_ROOT / p)


DEFAULT_DB = _env_path("TRADING_ENGINE_DB", REPO_ROOT / "store" / "market.duckdb")
STORE_DIR = DEFAULT_DB.parent           # disk-watchdog target (the DuckDB's directory)
DATA_DIR = _env_path("TRADING_ENGINE_DATA_DIR", REPO_ROOT / "data")
META_PATH = DATA_DIR / "_meta.json"
SCRATCH_DIR = REPO_ROOT / "scratch"
LOGS_DIR = REPO_ROOT / "logs"
# Retired 2026-08-18; the tree lives in archive/agentic-2026-08/agents/. The
# default stays `agents/` so a `git mv` back re-enables the gate read without a
# code change; sim.strategies.base treats a missing directory as a no-op.
AGENTS_DIR = _env_path("TRADING_ENGINE_AGENTS_DIR", REPO_ROOT / "agents")

# The owner's private notes (watchlist, market context) live in a sibling repo.
NOTES_DIR = _env_path("TRADING_ENGINE_STORE_DIR",
                      REPO_ROOT.parent / "personal-data-store" / "trading")
WATCHLIST_PATH = _env_path("TRADING_ENGINE_WATCHLIST", NOTES_DIR / "watchlist.md")

LOCK_WAIT_ENV = "TRADING_ENGINE_LOCK_WAIT_S"
LOCK_WAIT_DEFAULT_S = 60.0


def lock_wait_s() -> float:
    """Default lock-retry window, read at call time so tests/drivers can set it late."""
    return float(os.environ.get(LOCK_WAIT_ENV, LOCK_WAIT_DEFAULT_S))
