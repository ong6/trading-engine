#!/usr/bin/env python
"""E1 FORWARD-phase runner — the out-of-sample record (design §12.3).

Sibling of `farm/experiment.py`, which owns the BACKTEST phase (in-sample +
the locked holdout, computed once at publication). This module owns the other
half of the §12.3 protocol: the **forward window that starts with the paper
league**, one row per out-of-sample Monday, accumulating toward the frozen kill
criterion (40 Mondays, then mean <= 0 or t < 0.5 kills it — no re-optimization).

What it does, every night:
  * reads the frozen forward registration (farm/experiments/<id>.forward.json),
  * finds every SETTLED Monday SPY bar on/after `oos_start` that is not already
    recorded, computes gross (close/open - 1) and net under the frozen
    compatibility execution profile (`baseline_v1`: 10bp/side, 20bp round-trip
    for SPY's liquidity tier),
  * APPENDS one row per Monday to `experiment_results`
    (partition = 'oos:<date>', trade_date/gross_ret/net_ret populated),
  * regenerates data/reports/experiments/<id>-forward.md from the table.

Invariants:
  * **Append-only and idempotent.** A Monday already in the table is never
    recomputed and never overwritten; a re-run appends nothing.
  * **No partial bars.** A Monday is recorded only once its session has settled
    (>= 21:15 UTC that day, past the 16:00 ET close in both DST regimes). The
    table is append-only, so recording a mid-session close would be permanent.
  * **No fabricated bars.** Only Mondays with a real stored open+close are
    recorded; holiday Mondays are simply absent (no trade that week).
  * **No look-ahead.** Entry is the Monday open, exit is the same bar's close
    (the registered mechanics); the cost tier is derived from bars STRICTLY
    before that Monday (`median_dollar_vol` uses date < as_of).
  * **Backtest context never mixes in.** Pre-oos_start Mondays are computed for
    the report's context section only and are never written as forward rows.
  * **The frozen configs are frozen.** The parent YAML's hash is recomputed and
    checked against the pin in the forward config before anything is written;
    forward rows carry that same hash as their params_hash, so
    `farm/experiment.py`'s immutability check keeps seeing exactly one hash.

Entry points:
  CLI:   farm/experiment_runner.py --id e1-spy-monday [--db PATH] [--report-only]
  Queue: run_job(params, con, meta_path=None) — job kind 'experiment_forward'.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from pathlib import Path

from engine.lib import db as enginedb  # engine/lib/db.py — the lock-retrying connect factory
from engine.lib import resources
from engine.lib.log import get_logger
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import DATA_DIR, DEFAULT_DB, REPO_ROOT
from farm import experiment as E  # farm/experiment.py — shared config/hash/table helpers
from sim import execution, nyse
from sim.fills import median_dollar_vol, slippage_bps_for

log = get_logger("e1")

FARM_DIR = Path(__file__).resolve().parent
EXPERIMENTS_DIR = FARM_DIR / "experiments"
REPORTS_DIR = DATA_DIR / "reports" / "experiments"
CHECKPOINT_SCHEMA_VERSION = 2
LEGACY_CHECKPOINT_SCHEMA_VERSION = 1
EXPECTED_LEGACY_OBSERVATIONS = 7
EXPECTED_LEGACY_THROUGH = "2026-08-31"
EXPECTED_LEGACY_PREFIX_SHA256 = (
    "e2603b7c85f5e24e3b019a4ee7058c6732a792647b0c1c2e62a0d111fdf360ad"
)
RUNTIME_CONTRACT_VERSION = 6
SUPERSEDED_RUNTIME_CONTRACT_SHA256 = (
    "31ff0e06dad3ee1063dc25210cf049df5dffba1662621bc6a97de30e535420a2"
)
RUNTIME_CONTRACT_MIGRATION = (
    "2026-09-13 interruption-safe transaction cleanup: every explicit DuckDB transaction now "
    "rolls back process-level interruptions, preserves the original failure if cleanup also "
    "fails, and leaves borrowed connections reusable; the frozen seven-observation E1 prefix, "
    "strategy, execution economics, and verdict rules are unchanged"
)
RUNTIME_CONTRACT_FILES = (
    "engine/lib/db.py",
    "engine/lib/provenance.py",
    "engine/lib/resources.py",
    "farm/experiment.py",
    "farm/experiment_runner.py",
    "sim/calendar.py",
    "sim/execution.py",
    "sim/fills.py",
    "sim/nyse.py",
)
# Filled after the dependency list was frozen. The self-file digest normalizes
# this literal so the contract can cover its own validation and verdict code.
EXPECTED_RUNTIME_CONTRACT_SHA256 = (
    "5a665966f7bad78474dab9367618aab4016ea847fec8bba9a92966e7706e5612"
)
PRIOR_RUNTIME_CONTRACT_VERSION = 5
PRIOR_RUNTIME_CONTRACT_SHA256 = SUPERSEDED_RUNTIME_CONTRACT_SHA256
PRIOR_SUPERSEDED_RUNTIME_CONTRACT_SHA256 = (
    "da752d28c1b9bb18e3520139bbce71c885b89b192a47d00d5cd8fbfa0f1399ae"
)
PRIOR_RUNTIME_CONTRACT_MIGRATION = (
    "2026-09-13 exception-safe temporary DataFrame registration cleanup: transient DuckDB views "
    "are now unregistered after failed statements; the frozen seven-observation E1 prefix, "
    "strategy, execution economics, and verdict rules are unchanged"
)
PRIOR_RUNTIME_CONTRACT_FILES = RUNTIME_CONTRACT_FILES

# A Monday's daily bar is trusted only after its session has closed. 16:00 ET is
# 20:00 UTC under EDT and 21:00 UTC under EST; 21:15 UTC clears both with margin
# and still lands well before the 22:30 UTC nightly.
SETTLE_UTC = dtime(21, 15)

WEEKDAY = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4}
OOS_PREFIX = "oos:"
EXECUTION_PROFILE = execution.BASELINE
EXECUTION_PROFILE_SHA256 = canonical_sha256(EXECUTION_PROFILE.as_dict())
EXPECTED_EXECUTION_PROFILE_SHA256 = (
    "6340e47066716dbc6d3d221007033fb67069faf9cc9ec04aa95c89ec4de574db"
)
EXPECTED_ROUNDTRIP_BPS = 20.0
LEGACY_PROFILE_CUTOFF = date(2026, 8, 31)


# --------------------------------------------------------------------------- #
# frozen config
# --------------------------------------------------------------------------- #
def forward_config_path(cfg_id: str) -> Path:
    return EXPERIMENTS_DIR / f"{cfg_id}.forward.json"


def load_forward_config(cfg_id: str | None, cfg_path: str | None) -> tuple[dict, Path]:
    p = Path(cfg_path) if cfg_path else forward_config_path(cfg_id or "")
    if not p.exists():
        raise SystemExit(f"[e1] forward config not found: {p}")
    cfg = json.loads(p.read_text())
    for key in ("id", "oos_start", "params", "kill_criterion", "parent_config_hash"):
        if key not in cfg:
            raise SystemExit(f"[e1] forward config {p} is missing '{key}'")
    return cfg, p


def params_hash_for(cfg: dict) -> str:
    """The hash stored with every result row.

    Deliberately the PARENT (pre-registered YAML) hash, not this file's: the
    experiment is one pre-registration, and `farm/experiment.py.check_immutable`
    refuses to run if `experiment_results` holds two different hashes under one
    id. Recomputing it here is also the tripwire that the frozen YAML has not
    been edited since the forward phase was registered.
    """
    parent = REPO_ROOT / cfg["parent_config"]
    if not parent.exists():
        raise SystemExit(f"[e1] parent config missing: {parent}")
    live = E.config_hash(E.load_config(parent))
    pinned = cfg["parent_config_hash"]
    if live != pinned:
        raise SystemExit(
            f"[e1] FROZEN CONFIG CHANGED: {cfg['parent_config']} now hashes to "
            f"{live[:16]}, but the forward registration pinned {pinned[:16]}. "
            f"A pre-registered config is immutable once results exist. Refusing "
            f"to write forward rows."
        )
    return live


def forward_config_hash(cfg: dict) -> str:
    """Hash of THIS file's parsed content — recorded in meta_json so a reader can
    verify the forward registration (oos_start, cost model, kill rule) was frozen
    before the evidence accumulated."""
    return E.config_hash({k: v for k, v in cfg.items() if k != "_comment"})


def _runtime_contract_sha256(repo_root: Path = REPO_ROOT) -> str:
    """Hash the source files that select, price, store, and judge E1 rows."""
    digest = hashlib.sha256()
    for relative in sorted(RUNTIME_CONTRACT_FILES):
        path = repo_root / relative
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"E1 runtime contract file unavailable: {relative}") from exc
        if relative == "farm/experiment_runner.py":
            content = content.replace(
                EXPECTED_RUNTIME_CONTRACT_SHA256.encode(),
                b"<EXPECTED_RUNTIME_CONTRACT_SHA256>",
            )
        encoded = relative.encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _validate_runtime_contract() -> None:
    if _runtime_contract_sha256() != EXPECTED_RUNTIME_CONTRACT_SHA256:
        raise ValueError(
            "E1 runtime source changed; register an explicit contract migration "
            "before recording or reporting more evidence"
        )


# --------------------------------------------------------------------------- #
# schema — additive, append-only
# --------------------------------------------------------------------------- #
def ensure_forward_columns(con) -> None:
    """Add the per-trade columns the forward phase needs.

    `experiment_results` was shaped for per-PARTITION statistics (n_trades,
    mean_ret, t_stat, ...). A forward row is a single dated trade, so it needs
    a date and a gross/net pair that are returns, not annualized figures. These
    are additive: existing backtest rows keep every value they had and simply
    read NULL here, which is also how the two series are told apart in SQL
    (`trade_date IS NULL` = backtest stats, `IS NOT NULL` = a forward Monday).
    """
    for col, typ in (("trade_date", "DATE"), ("gross_ret", "DOUBLE"), ("net_ret", "DOUBLE")):
        con.execute(f'ALTER TABLE experiment_results ADD COLUMN IF NOT EXISTS {col} {typ}')


# --------------------------------------------------------------------------- #
# the trade computation
# --------------------------------------------------------------------------- #
def _mondays(con, ticker: str, weekday: int, start: date, end: date | None):
    """Real stored bars for the target weekday in [start, end]. Never fabricates:
    a bar must have a positive open and a non-null close to be tradeable."""
    sql = ("SELECT date, open, close FROM prices WHERE ticker = ? AND date >= ? "
           "AND open IS NOT NULL AND close IS NOT NULL AND open > 0 ")
    args: list = [ticker, start]
    if end is not None:
        sql += "AND date <= ? "
        args.append(end)
    sql += "ORDER BY date"
    return [(d, float(o), float(c)) for d, o, c in con.execute(sql, args).fetchall()
            if d.weekday() == weekday]


def _validate_trade_date_coverage(
    con,
    ticker: str,
    weekday: int,
    start: date,
    bars: list[tuple[date, float, float]],
    through: date | None = None,
) -> None:
    """Fail closed when a scheduled trade session is absent from stored bars."""
    latest = through or con.execute(
        "SELECT MAX(date) FROM prices WHERE ticker = ?", [ticker]
    ).fetchone()[0]
    if latest is None or latest < start:
        return
    available = {row[0] for row in bars}
    missing = []
    d = start
    while d <= latest:
        if d.weekday() == weekday and nyse.is_session(d) and d not in available:
            missing.append(d)
        d += timedelta(days=1)
    if missing:
        rendered = ", ".join(day.isoformat() for day in missing[:5])
        suffix = " …" if len(missing) > 5 else ""
        raise ValueError(f"E1 missing required {ticker} trade bar(s): {rendered}{suffix}")


def frozen_sample_end(cfg: dict) -> date:
    """Calendar date of the final pre-registered eligible observation."""
    start = date.fromisoformat(cfg["oos_start"])
    weekday = WEEKDAY[str(cfg["params"]["weekday"]).lower()]
    target = int(cfg["kill_criterion"]["n_oos_mondays"])
    if target <= 0:
        raise ValueError("E1 frozen sample size must be positive")
    found = 0
    d = start
    while True:
        if d.weekday() == weekday and nyse.is_session(d):
            found += 1
            if found == target:
                return d
        d += timedelta(days=1)


def validate_oos_schedule(
    cfg: dict,
    oos: list[dict],
    bars: list[tuple[date, float, float]],
    now: datetime,
) -> list[date]:
    """Require stored rows to be an exact prefix of eligible settled sessions."""
    target = int(cfg["kill_criterion"]["n_oos_mondays"])
    eligible = [d for d, _open, _close in bars if is_settled(d, now)][:target]
    actual = [row["date"] for row in oos]
    if actual != eligible[:len(actual)]:
        raise ValueError("E1 forward record is not the expected settled-date prefix")
    return eligible


def is_settled(d: date, now: datetime) -> bool:
    """True once day `d`'s US session has certainly closed (see SETTLE_UTC)."""
    return now >= datetime.combine(d, SETTLE_UTC, tzinfo=timezone.utc)


def compute_trade(con, ticker: str, d: date, open_px: float, close_px: float) -> dict:
    """gross = close/open - 1; net applies the paper league's own fill model.

    Slippage is the league's per-side figure for this name's liquidity tier
    (sim/fills.py), measured from bars strictly before `d`: buy the open up,
    sell the close down.
    """
    if EXECUTION_PROFILE_SHA256 != EXPECTED_EXECUTION_PROFILE_SHA256:
        raise RuntimeError(
            "E1 baseline_v1 execution profile changed; register a new experiment ID"
        )
    mdv = median_dollar_vol(con, ticker, d)
    side_bps = slippage_bps_for(mdv, EXECUTION_PROFILE)
    if not math.isclose(2.0 * side_bps, EXPECTED_ROUNDTRIP_BPS, abs_tol=1e-12):
        raise RuntimeError(
            "E1 frozen 20bp round-trip cost changed; register a new experiment ID"
        )
    s = side_bps / 1e4
    gross = close_px / open_px - 1.0
    net = (close_px * (1.0 - s)) / (open_px * (1.0 + s)) - 1.0
    return {"date": d, "open": open_px, "close": close_px, "gross": gross, "net": net,
            "slip_bps_side": side_bps, "mdv": mdv,
            "execution_profile": EXECUTION_PROFILE.id,
            "execution_profile_sha256": EXECUTION_PROFILE_SHA256}


def net_at_bps(open_px: float, close_px: float, roundtrip_bps: float) -> float:
    h = (roundtrip_bps / 2.0) / 1e4
    return (close_px * (1.0 - h)) / (open_px * (1.0 + h)) - 1.0


# --------------------------------------------------------------------------- #
# persistence
# --------------------------------------------------------------------------- #
def _has_results_table(con) -> bool:
    return con.execute(
        "SELECT COUNT(*) FROM duckdb_tables() WHERE table_name = 'experiment_results'"
    ).fetchone()[0] > 0


def append_oos_rows(con, cfg: dict, phash: str, trades: list[dict], run_at: datetime) -> int:
    """One append-only row per new out-of-sample Monday. Never updates."""
    if not trades:
        return 0
    fhash = forward_config_hash(cfg)
    hypo = " ".join(str(cfg.get("hypothesis", "")).split())[:900]
    rt = float(cfg["cost_model"]["roundtrip_bps"])
    n_target = cfg["kill_criterion"]["n_oos_mondays"]
    records = []
    for t in trades:
        meta = {
            "phase": "forward", "oos_start": cfg["oos_start"],
            "forward_config_hash": fhash,
            "open": t["open"], "close": t["close"],
            "slippage_bps_per_side": t["slip_bps_side"],
            "execution_profile": t["execution_profile"],
            "execution_profile_sha256": t["execution_profile_sha256"],
            "median_dollar_vol": t["mdv"],
            "net_ret_registered_3bp": net_at_bps(
                t["open"], t["close"],
                float(cfg["cost_model"]["registered_roundtrip_bps"])),
            "cost_model": cfg["cost_model"]["source"],
        }
        # Named columns only. The stat columns a per-PARTITION backtest row fills
        # (std_ret, t_stat, the CAGR/Sharpe family, ...) are meaningless for a
        # single dated trade and are deliberately left NULL rather than filled
        # with a one-observation figure that would read like a result.
        records.append({
            "experiment_id": cfg["id"],
            "config_hash": phash,
            "run_at": run_at,
            "partition": f"{OOS_PREFIX}{t['date']}",
            "n_trades": 1,
            "mean_ret": t["net"],       # a 1-trade partition's mean IS its net return
            "cost_roundtrip_bps": rt,
            "hypothesis": hypo,
            "verdict": (f"out-of-sample Monday {t['date']} (forward phase; "
                        f"no verdict until n={n_target})"),
            "meta_json": json.dumps(meta, default=str),
            "trade_date": t["date"],
            "gross_ret": t["gross"],
            "net_ret": t["net"],
        })
    cols = list(records[0].keys())
    quoted = ", ".join('"%s"' % c for c in cols)
    placeholders = ", ".join(["?"] * len(cols))
    con.executemany(
        f"INSERT INTO experiment_results ({quoted}) VALUES ({placeholders})",
        [[r[c] for c in cols] for r in records],
    )
    return len(records)


def load_oos_series(con, cfg: dict, phash: str) -> list[dict]:
    """Read and validate the full append-only out-of-sample record.

    The table's historical primary key includes ``run_at``, so it cannot by
    itself enforce one row per trade date. Fail closed on duplicates or on any
    row that is inconsistent with the frozen registration and its own stored
    prices. Price history is deliberately not re-read here: a later vendor
    restatement must not silently rewrite an already published forward trade.
    """
    rows = con.execute(
        "SELECT config_hash, partition, trade_date, n_trades, mean_ret, gross_ret, "
        "net_ret, cost_roundtrip_bps, meta_json, run_at "
        "FROM experiment_results WHERE experiment_id = ? AND partition LIKE ? "
        "ORDER BY trade_date, run_at",
        [cfg["id"], OOS_PREFIX + "%"],
    ).fetchall()
    expected_fhash = forward_config_hash(cfg)
    expected_start = date.fromisoformat(cfg["oos_start"])
    expected_weekday = WEEKDAY[str(cfg["params"]["weekday"]).lower()]
    expected_rt = float(cfg["cost_model"]["roundtrip_bps"])
    registered_rt = float(cfg["cost_model"]["registered_roundtrip_bps"])
    target = int(cfg["kill_criterion"]["n_oos_mondays"])
    out = []
    seen: set[date] = set()
    for row in rows:
        config_hash, partition, d, n_trades, mean_ret, gross, net, rt, meta, run_at = row
        try:
            m = json.loads(meta)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("E1 forward row has invalid metadata") from exc
        if not isinstance(m, dict):
            raise ValueError("E1 forward row has invalid metadata")
        if not isinstance(d, date) or d in seen:
            raise ValueError("E1 forward record has a duplicate or invalid trade date")
        seen.add(d)
        expected_partition = f"{OOS_PREFIX}{d.isoformat()}"
        numeric = (mean_ret, gross, net, rt, m.get("open"), m.get("close"),
                   m.get("slippage_bps_per_side"), m.get("median_dollar_vol"))
        if (
            config_hash != phash
            or partition != expected_partition
            or d < expected_start
            or d.weekday() != expected_weekday
            or n_trades != 1
            or any(not isinstance(value, (int, float)) or not math.isfinite(value)
                   for value in numeric)
            or float(m["open"]) <= 0
            or float(m["close"]) <= 0
            or float(m["median_dollar_vol"]) <= 0
            or m.get("phase") != "forward"
            or m.get("oos_start") != cfg["oos_start"]
            or m.get("forward_config_hash") != expected_fhash
            or m.get("cost_model") != cfg["cost_model"]["source"]
            or not math.isclose(float(rt), expected_rt, abs_tol=1e-12)
            or not math.isclose(
                2.0 * float(m["slippage_bps_per_side"]), expected_rt, abs_tol=1e-12
            )
            or not math.isclose(float(mean_ret), float(net), abs_tol=1e-12)
            or not math.isclose(
                float(gross), float(m["close"]) / float(m["open"]) - 1.0,
                abs_tol=1e-12,
            )
            or not math.isclose(
                float(net),
                net_at_bps(float(m["open"]), float(m["close"]), expected_rt),
                abs_tol=1e-12,
            )
            or not math.isclose(
                float(m.get("net_ret_registered_3bp", math.nan)),
                net_at_bps(float(m["open"]), float(m["close"]), registered_rt),
                abs_tol=1e-12,
            )
        ):
            raise ValueError("E1 forward row is inconsistent with its frozen registration")
        profile = m.get("execution_profile")
        profile_hash = m.get("execution_profile_sha256")
        if (profile is None) != (profile_hash is None) or (
            profile is None and d > LEGACY_PROFILE_CUTOFF
        ) or (
            profile is not None
            and (profile != EXECUTION_PROFILE.id
                 or profile_hash != EXPECTED_EXECUTION_PROFILE_SHA256)
        ):
            raise ValueError("E1 forward row has an inconsistent execution profile")
        out.append({"date": d, "gross": float(gross), "net": float(net),
                    "roundtrip_bps": float(rt), "run_at": run_at, "meta": m})
    if len(out) > target:
        raise ValueError("E1 forward record exceeds its frozen sample size")
    return out


def checkpoint_path(cfg: dict) -> Path:
    return REPORTS_DIR / f"{cfg['id']}-forward.json"


def _oos_payload(oos: list[dict]) -> list[dict]:
    return [
        {
            "date": row["date"].isoformat(),
            "gross": row["gross"],
            "net": row["net"],
            "roundtrip_bps": row["roundtrip_bps"],
            "run_at": row["run_at"].isoformat(),
            "meta": row["meta"],
        }
        for row in oos
    ]


def _checkpoint_payload(cfg: dict, phash: str, oos: list[dict]) -> dict:
    rows = _oos_payload(oos)
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "experiment_id": cfg["id"],
        "paper_only": True,
        "automatic_action": "none",
        "parent_config_sha256": phash,
        "forward_config_sha256": forward_config_hash(cfg),
        "runtime_contract_version": RUNTIME_CONTRACT_VERSION,
        "runtime_contract_sha256": EXPECTED_RUNTIME_CONTRACT_SHA256,
        "runtime_contract_files": list(RUNTIME_CONTRACT_FILES),
        "superseded_runtime_contract_sha256": SUPERSEDED_RUNTIME_CONTRACT_SHA256,
        "runtime_contract_migration": RUNTIME_CONTRACT_MIGRATION,
        "observations": len(rows),
        "through": rows[-1]["date"] if rows else None,
        "prefix_sha256": canonical_sha256(rows),
    }


def _validate_checkpoint(
    cfg: dict,
    phash: str,
    oos: list[dict],
    *,
    require_current: bool = False,
) -> dict | None:
    path = checkpoint_path(cfg)
    if not path.exists():
        if oos:
            raise ValueError("E1 forward checkpoint is missing for an existing record")
        return None
    try:
        checkpoint = json.loads(path.read_text())
        count = checkpoint["observations"]
        if (
            checkpoint["schema_version"] != CHECKPOINT_SCHEMA_VERSION
            or checkpoint["experiment_id"] != cfg["id"]
            or checkpoint["paper_only"] is not True
            or checkpoint["automatic_action"] != "none"
            or checkpoint["parent_config_sha256"] != phash
            or checkpoint["forward_config_sha256"] != forward_config_hash(cfg)
            or checkpoint["runtime_contract_version"] != RUNTIME_CONTRACT_VERSION
            or checkpoint["runtime_contract_sha256"]
            != EXPECTED_RUNTIME_CONTRACT_SHA256
            or checkpoint["runtime_contract_files"] != list(RUNTIME_CONTRACT_FILES)
            or checkpoint["superseded_runtime_contract_sha256"]
            != SUPERSEDED_RUNTIME_CONTRACT_SHA256
            or checkpoint["runtime_contract_migration"] != RUNTIME_CONTRACT_MIGRATION
            or _runtime_contract_sha256() != EXPECTED_RUNTIME_CONTRACT_SHA256
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count < 0
            or count > len(oos)
            or (require_current and count != len(oos))
        ):
            raise ValueError("E1 forward checkpoint is invalid")
        prefix = _oos_payload(oos[:count])
        through = prefix[-1]["date"] if prefix else None
        if (
            checkpoint["through"] != through
            or checkpoint["prefix_sha256"] != canonical_sha256(prefix)
        ):
            raise ValueError("previously published E1 forward prefix changed")
        return checkpoint
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("previously published"):
            raise
        raise ValueError("E1 forward checkpoint is invalid") from exc


def migrate_runtime_contract(con, cfg: dict) -> dict:
    """Validate a schema-v1 or prior-v2 checkpoint and replace only contract metadata.

    Checkpoint schema v1 anchored the evidence prefix and both config hashes but
    did not identify the source code governing future rows. Runtime contracts
    subsequently added that digest. Both accepted predecessor forms must anchor
    the exact same audited evidence prefix; migration is explicit and fails
    before writing otherwise.
    """
    _validate_runtime_contract()
    phash = params_hash_for(cfg)
    if not _has_results_table(con):
        raise ValueError("E1 results table is unavailable for runtime migration")
    oos = load_oos_series(con, cfg, phash)
    path = checkpoint_path(cfg)
    try:
        checkpoint = json.loads(path.read_text())
        count = checkpoint["observations"]
        common_invalid = (
            checkpoint["experiment_id"] != cfg["id"]
            or checkpoint["paper_only"] is not True
            or checkpoint["automatic_action"] != "none"
            or checkpoint["parent_config_sha256"] != phash
            or checkpoint["forward_config_sha256"] != forward_config_hash(cfg)
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count != EXPECTED_LEGACY_OBSERVATIONS
            or count != len(oos)
        )
        is_legacy = checkpoint["schema_version"] == LEGACY_CHECKPOINT_SCHEMA_VERSION
        is_prior_contract = (
            checkpoint["schema_version"] == CHECKPOINT_SCHEMA_VERSION
            and checkpoint.get("runtime_contract_version") == PRIOR_RUNTIME_CONTRACT_VERSION
            and checkpoint.get("runtime_contract_sha256") == PRIOR_RUNTIME_CONTRACT_SHA256
            and checkpoint.get("runtime_contract_files")
            == list(PRIOR_RUNTIME_CONTRACT_FILES)
            and checkpoint.get("superseded_runtime_contract_sha256")
            == PRIOR_SUPERSEDED_RUNTIME_CONTRACT_SHA256
            and checkpoint.get("runtime_contract_migration")
            == PRIOR_RUNTIME_CONTRACT_MIGRATION
        )
        if common_invalid or not (is_legacy or is_prior_contract):
            raise ValueError("prior E1 checkpoint is invalid")
        prefix = _oos_payload(oos)
        through = prefix[-1]["date"] if prefix else None
        if (
            checkpoint["through"] != EXPECTED_LEGACY_THROUGH
            or checkpoint["through"] != through
            or checkpoint["prefix_sha256"] != EXPECTED_LEGACY_PREFIX_SHA256
            or checkpoint["prefix_sha256"] != canonical_sha256(prefix)
        ):
            raise ValueError("previously published E1 forward prefix changed")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("previously published"):
            raise
        raise ValueError("prior E1 checkpoint is invalid") from exc

    _write_checkpoint(cfg, phash, oos)
    migrated = _validate_checkpoint(cfg, phash, oos, require_current=True)
    if migrated is None:  # pragma: no cover - _write_checkpoint guarantees existence
        raise ValueError("E1 runtime migration did not create a checkpoint")
    return migrated


def _write_checkpoint(cfg: dict, phash: str, oos: list[dict]) -> Path:
    path = checkpoint_path(cfg)
    resources.write_text_atomic(
        path,
        json.dumps(_checkpoint_payload(cfg, phash, oos), indent=2, sort_keys=True) + "\n",
    )
    return path


# --------------------------------------------------------------------------- #
# statistics (deliberately small-n honest: no annualization, no CAGR)
# --------------------------------------------------------------------------- #
def series_stats(vals: list[float]) -> dict:
    n = len(vals)
    if n == 0:
        return {"n": 0, "mean": None, "std": None, "t": None, "cum": 0.0, "wins": 0}
    mean = sum(vals) / n
    cum = 1.0
    for v in vals:
        cum *= (1.0 + v)
    cum -= 1.0
    wins = sum(1 for v in vals if v > 0)
    if n < 2:
        return {"n": n, "mean": mean, "std": None, "t": None, "cum": cum, "wins": wins}
    var = sum((v - mean) ** 2 for v in vals) / (n - 1)
    std = math.sqrt(var)
    t = (mean / (std / math.sqrt(n))) if std > 0 else None
    return {"n": n, "mean": mean, "std": std, "t": t, "cum": cum, "wins": wins}


def frozen_verdict(stats: dict, target: int) -> str | None:
    if stats["n"] < target:
        return None
    if stats["n"] != target:
        raise ValueError("E1 forward record exceeds its frozen sample size")
    return (
        "KILL"
        if stats["mean"] <= 0 or stats["t"] is None or stats["t"] < 0.5
        else "SURVIVE"
    )


def backtest_context(con, cfg: dict, oos_start: date) -> list[dict]:
    """Report-only context: the same computation over the pre-oos lookback window.
    Never written to experiment_results, never mixed into the forward stats."""
    years = int(cfg.get("backtest_context", {}).get("lookback_years", 2))
    start = date(oos_start.year - years, oos_start.month, oos_start.day)
    wd = WEEKDAY[str(cfg["params"]["weekday"]).lower()]
    bars = _mondays(con, cfg["params"]["ticker"], wd, start, oos_start - timedelta(days=1))
    return [compute_trade(con, cfg["params"]["ticker"], d, o, c) for d, o, c in bars]


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
def _pct(v, dp=4):
    return "—" if v is None else f"{v * 100:+.{dp}f}%"


def _num(v, dp=2):
    return "—" if v is None else f"{v:.{dp}f}"


def render_report(cfg: dict, phash: str, oos: list[dict], ctx: list[dict],
                  run_at: datetime, storage_note: str) -> str:
    kill = cfg["kill_criterion"]
    n_target = int(kill["n_oos_mondays"])
    net_s = series_stats([r["net"] for r in oos])
    gross_s = series_stats([r["gross"] for r in oos])
    reg_rt = float(cfg["cost_model"]["registered_roundtrip_bps"])
    reg_s = series_stats([r["meta"].get("net_ret_registered_3bp") for r in oos]
                         if all(r["meta"].get("net_ret_registered_3bp") is not None
                                for r in oos) else [])
    remaining = max(0, n_target - net_s["n"])
    decision = frozen_verdict(net_s, n_target)
    exp = cfg["expectation"]

    L: list[str] = []
    L.append(f"# Experiment {cfg['id']} — FORWARD (out-of-sample) record")
    L.append("")
    L.append(f"*Forward phase registered {cfg.get('registered', '?')} · report generated "
             f"{run_at:%Y-%m-%d %H:%M UTC} · params hash `{phash[:16]}` · "
             f"forward-config hash `{forward_config_hash(cfg)[:16]}`*")
    L.append("")
    if decision is None:
        L.append(f"> **NO RESULT YET — {net_s['n']} of {n_target} out-of-sample Mondays.** "
                 f"This experiment is not evaluated until the pre-registered sample is "
                 f"complete. Anything below is an accumulating record, **not** a verdict: "
                 f"reading a mean or a t-stat at n={net_s['n']} and calling it a finding is "
                 f"exactly the peeking the §12.3 protocol exists to prevent. "
                 f"**{remaining} Mondays to go.**")
    else:
        verdict = "KILLED" if decision == "KILL" else "SURVIVED THE FROZEN KILL GATE"
        L.append(f"> **FINAL FROZEN VERDICT — {verdict}.** Exactly {n_target} "
                 f"out-of-sample Mondays were recorded. This result permits no automatic "
                 f"promotion, portfolio change, or live-capital action.")
    L.append("")

    # --- frozen registration -------------------------------------------------
    L.append("## Frozen registration")
    L.append("")
    L.append("| Field | Value |")
    L.append("|---|---|")
    L.append(f"| Hypothesis | {' '.join(str(cfg.get('hypothesis', '')).split())} |")
    L.append(f"| Instrument / rule | {cfg['params']['ticker']} only — enter "
             f"**{cfg['params']['weekday']} {cfg['params']['entry']}**, exit "
             f"**same-bar {cfg['params']['exit']}** |")
    L.append(f"| Expectation | {exp['direction']}, ~{exp['gross_annual'] * 100:.0f}%/yr "
             f"**gross** vs ~{exp['cost_annual_range'][0] * 100:.1f}–"
             f"{exp['cost_annual_range'][1] * 100:.1f}%/yr costs (decayed prior, not fitted) |")
    L.append(f"| **Kill criterion** | {kill['rule']} — evaluated on **{kill['series']}**. "
             f"No re-optimization. |")
    L.append(f"| Out-of-sample start | **{cfg['oos_start']}** — first out-of-sample Monday "
             f"is the first Monday on or after it (2026-07-20) |")
    L.append(f"| Cost model | `{cfg['cost_model']['source']}` → "
             f"**{cfg['cost_model']['roundtrip_bps']:.0f}bp round-trip** "
             f"({cfg['cost_model']['roundtrip_bps'] / 2:.0f}bp/side) |")
    L.append(f"| Params hash | `{phash}` |")
    L.append(f"| Runtime contract | v{RUNTIME_CONTRACT_VERSION} "
             f"`{EXPECTED_RUNTIME_CONTRACT_SHA256}` |")
    L.append(f"| Runtime migration | {RUNTIME_CONTRACT_MIGRATION} |")
    L.append("")
    L.append(f"Registration source: `farm/experiments/{cfg['id']}.yaml` (pre-registered "
             f"2026-07-18, frozen) + `farm/experiments/{cfg['id']}.forward.json` (forward "
             f"phase, frozen). Design authority: trading-engine-design.md §12.3.")
    L.append("")

    # --- the out-of-sample record -------------------------------------------
    L.append("## Out-of-sample record (the only series that counts)")
    L.append("")
    if not oos:
        L.append("_No settled out-of-sample Monday yet._")
    else:
        L.append("| # | Monday | open | close | gross | net (20bp) | cum gross | cum net |")
        L.append("|--:|---|--:|--:|--:|--:|--:|--:|")
        cg = cn = 1.0
        for i, r in enumerate(oos, 1):
            cg *= (1.0 + r["gross"])
            cn *= (1.0 + r["net"])
            m = r["meta"]
            L.append(f"| {i} | {r['date']} | {m.get('open', float('nan')):.2f} | "
                     f"{m.get('close', float('nan')):.2f} | {_pct(r['gross'])} | "
                     f"{_pct(r['net'])} | {_pct(cg - 1)} | {_pct(cn - 1)} |")
    L.append("")
    L.append("_Every row is one real stored SPY daily bar; holiday Mondays have no bar and "
             "are simply absent (no trade that week). Rows are append-only — a Monday is "
             "written once, after its session has settled, and never revised. The published "
             "machine-readable checkpoint hashes the complete stored prefix._")
    L.append("")

    # --- running stats -------------------------------------------------------
    heading = "Final statistics" if decision else "Running statistics"
    suffix = "" if decision else f" (informational until n = {n_target})"
    L.append("## " + heading + suffix)
    L.append("")
    L.append("| Series | n | mean/Monday | sd | t-stat | cumulative | win rate |")
    L.append("|---|--:|--:|--:|--:|--:|--:|")
    for label, s in (("gross", gross_s),
                     (f"**net — {cfg['cost_model']['roundtrip_bps']:.0f}bp r/t "
                      f"(kill series)**", net_s),
                     (f"net — {reg_rt:.0f}bp r/t (registered)", reg_s)):
        if s["n"] == 0 and label.startswith("net — "):
            continue
        wr = f"{s['wins']}/{s['n']}" if s["n"] else "—"
        L.append(f"| {label} | {s['n']} | {_pct(s['mean'])} | "
                 f"{('—' if s['std'] is None else f'{s['std'] * 100:.4f}%')} | "
                 f"{_num(s['t'])} | {_pct(s['cum'], 3)} | {wr} |")
    L.append("")
    L.append(f"- **Mondays recorded:** {net_s['n']} / {n_target} · "
             f"**Mondays to kill-evaluation:** **{remaining}**.")
    if decision:
        L.append(f"- **Frozen kill test:** mean {_pct(net_s['mean'])}, "
                 f"t {_num(net_s['t'])}; verdict **{decision}**.")
    else:
        L.append(f"- **Kill test (runs once, at n = {n_target}):** kill if "
                 f"`mean <= 0` **or** `t < 0.5` on the net series. "
                 + (f"Current standing — mean {_pct(net_s['mean'])}, "
                    f"t {_num(net_s['t'])} — **would "
                    f"{'KILL' if (net_s['mean'] is not None and (net_s['mean'] <= 0 or (net_s['t'] is not None and net_s['t'] < 0.5))) else 'SURVIVE'}** "
                    f"if the criterion were applied today, which it is **not**."
                    if net_s["n"] else "No data yet."))
    L.append(f"- **Frozen cost sensitivity:** net uses compatibility profile "
             f"`{EXECUTION_PROFILE.id}` (`{EXECUTION_PROFILE_SHA256}`), "
             f"{cfg['cost_model']['roundtrip_bps']:.0f}bp round-trip "
             f"for SPY's liquidity tier — {cfg['cost_model']['roundtrip_bps'] / reg_rt:.1f}× "
             f"stricter than the {reg_rt:.0f}bp the backtest registered. The registered-cost "
             f"row is shown so the forward record can also be read against the original "
             f"pre-registration.")
    L.append("")

    # --- backtest context ----------------------------------------------------
    L.append("## Backtest context — NOT part of the out-of-sample record")
    L.append("")
    yrs = cfg.get("backtest_context", {}).get("lookback_years", 2)
    if ctx:
        c_net = series_stats([t["net"] for t in ctx])
        c_gross = series_stats([t["gross"] for t in ctx])
        L.append(f"The identical computation over the **{yrs} years of Mondays immediately "
                 f"before the out-of-sample start** ({ctx[0]['date']} → {ctx[-1]['date']}). "
                 f"This is history the rule was registered against; it has **no bearing on "
                 f"the kill decision** and is never written to `experiment_results` as a "
                 f"forward row.")
        L.append("")
        L.append("| Series | n | mean/Monday | sd | t-stat | cumulative | win rate |")
        L.append("|---|--:|--:|--:|--:|--:|--:|")
        for label, s in (("gross", c_gross), ("net (20bp r/t)", c_net)):
            L.append(f"| {label} | {s['n']} | {_pct(s['mean'])} | "
                     f"{s['std'] * 100:.4f}% | {_num(s['t'])} | {_pct(s['cum'], 2)} | "
                     f"{s['wins']}/{s['n']} |")
        L.append("")
    else:
        L.append("_No pre-oos_start bars in the store for the context window._")
        L.append("")
    L.append(f"The full pre-registered backtest (1990→2026, in-sample vs a locked holdout, "
             f"deflated Sharpe, subperiod and regime splits) lives in the sibling report "
             f"[`{cfg['id']}.md`](./{cfg['id']}.md). **Neither that backtest nor this "
             f"context window can rescue or condemn the rule** — only the {n_target} "
             f"out-of-sample Mondays above can.")
    L.append("")

    # --- method / honesty ----------------------------------------------------
    L.append("## Method & honesty notes")
    L.append("- **Gross** = close/open − 1 on the stored Monday daily bar. **Net** applies "
             "the frozen `baseline_v1` compatibility profile multiplicatively: buy at "
             "open·(1+s), sell at close·(1−s), s = per-side cost/1e4. For SPY, "
             "the profile's tiered spread plus fixed adverse component is 10.0 bp/side "
             "(60-bar median dollar volume ~$36bn, far above the $50M top tier) → "
             "**20bp round-trip**.")
    L.append("- **No look-ahead.** The entry is the Monday open and the exit is that same "
             "bar's close — the registered mechanics, and the open is known before the "
             "close. Nothing else is read at or after the open; even the slippage tier "
             "comes from bars strictly *before* the Monday.")
    L.append("- **No fabricated bars.** A Monday without a real stored open+close (market "
             "holiday) produces no row at all, rather than a synthetic flat trade.")
    L.append("- **No peeking-driven change.** The config, the cost model, the kill rule and "
             "the sample size were all frozen before this evidence existed. If E1 is killed "
             "at n=40 it is killed; there is no re-optimization branch.")
    L.append("- **Negative results are published exactly like positive ones** — the farm "
             "exists to kill bad ideas cheaply (§12.3).")
    L.append(f"- **Storage:** {storage_note}")
    L.append("")
    return "\n".join(L) + "\n"


def write_report(cfg: dict, text: str) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    p = REPORTS_DIR / f"{cfg['id']}-forward.md"
    resources.write_text_atomic(p, text)
    return p


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
def run(
    con,
    cfg: dict,
    *,
    now: datetime | None = None,
    read_only: bool = False,
    bootstrap_checkpoint: bool = False,
) -> dict:
    """Record any new settled out-of-sample Mondays, then regenerate the report."""
    _validate_runtime_contract()
    now = now or datetime.now(timezone.utc)
    phash = params_hash_for(cfg)
    oos_start = date.fromisoformat(cfg["oos_start"])
    ticker = cfg["params"]["ticker"]
    wd = WEEKDAY[str(cfg["params"]["weekday"]).lower()]
    if not math.isclose(
        float(cfg["cost_model"]["roundtrip_bps"]),
        EXPECTED_ROUNDTRIP_BPS,
        abs_tol=1e-12,
    ):
        raise ValueError("E1 forward config no longer specifies its frozen 20bp cost")

    if read_only:
        # A read-only connection cannot create/alter; if the table is not there
        # yet there is simply nothing to report.
        oos = load_oos_series(con, cfg, phash) if _has_results_table(con) else []
    else:
        E.ensure_results_table(con)
        ensure_forward_columns(con)
        oos = load_oos_series(con, cfg, phash)
    sample_end = frozen_sample_end(cfg)
    candidates = _mondays(con, ticker, wd, oos_start, sample_end)
    latest_market_date = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    coverage_end = (
        None if latest_market_date is None else min(latest_market_date, sample_end)
    )
    _validate_trade_date_coverage(
        con, ticker, wd, oos_start, candidates, through=coverage_end
    )
    validate_oos_schedule(cfg, oos, candidates, now)
    if bootstrap_checkpoint:
        if read_only:
            raise ValueError("E1 checkpoint bootstrap requires a writable run")
        if checkpoint_path(cfg).exists():
            raise ValueError("E1 forward checkpoint already exists")
        _write_checkpoint(cfg, phash, oos)
    _validate_checkpoint(cfg, phash, oos, require_current=read_only)
    have = {row["date"] for row in oos}
    remaining_slots = max(0, int(cfg["kill_criterion"]["n_oos_mondays"]) - len(oos))

    new: list[dict] = []
    skipped_unsettled: list[date] = []
    for d, o, c in candidates:
        if d in have:
            continue
        if not is_settled(d, now):
            skipped_unsettled.append(d)
            continue
        if len(new) < remaining_slots:
            new.append(compute_trade(con, ticker, d, o, c))

    appended = 0
    if new and not read_only:
        appended = append_oos_rows(con, cfg, phash, new, now)
    for t in new:
        log.info(f"[e1] +oos {t['date']}: open {t['open']:.4f} close {t['close']:.4f} "
              f"gross {t['gross'] * 100:+.4f}% net {t['net'] * 100:+.4f}% "
              f"(slip {t['slip_bps_side']:.1f}bp/side)")
    for d in skipped_unsettled:
        log.warning(f"[e1] {d} not settled yet (before {SETTLE_UTC} UTC) — not recorded")

    if read_only and new:
        note = (f"store was LOCKED — {len(new)} new Monday(s) NOT appended; report "
                f"regenerated from the rows already stored. They will be picked up "
                f"on the next run (the runner is idempotent).")
    elif appended:
        note = (f"{appended} row(s) appended to `experiment_results` (append-only, "
                f"partition `oos:<date>`) at {now:%Y-%m-%d %H:%M UTC}.")
    else:
        note = ("no new settled Mondays — nothing appended; the report was regenerated "
                "from `experiment_results` (re-running is a no-op by design).")
    log.info(f"[e1] {note}")

    oos = load_oos_series(con, cfg, phash) if _has_results_table(con) else []
    if not read_only:
        _write_checkpoint(cfg, phash, oos)
    ctx = backtest_context(con, cfg, oos_start)
    p = write_report(cfg, render_report(cfg, phash, oos, ctx, now, note))
    log.info(f"[e1] report → {p} ({len(oos)} out-of-sample Monday(s), "
          f"{max(0, int(cfg['kill_criterion']['n_oos_mondays']) - len(oos))} to kill-eval)")
    return {"appended": appended, "n_oos": len(oos), "report": str(p)}


def run_job(params: dict, con, meta_path=None) -> None:
    """Queue dispatch entry point (job kind 'experiment_forward')."""
    cfg, _ = load_forward_config(params.get("id"), params.get("config"))
    run(con, cfg)


def main() -> int:
    ap = argparse.ArgumentParser(description="E1 forward (out-of-sample) experiment runner.")
    ap.add_argument("--id", default="e1-spy-monday", help="experiment id")
    ap.add_argument("--config", default=None, help="explicit forward-config path")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="DuckDB path")
    ap.add_argument("--report-only", action="store_true",
                    help="never write: regenerate the report from stored rows only")
    ap.add_argument(
        "--bootstrap-checkpoint",
        action="store_true",
        help="one-time: anchor an audited existing forward prefix before normal operation",
    )
    ap.add_argument(
        "--migrate-runtime-contract",
        action="store_true",
        help="one-time: validate the exact prior checkpoint and replace only contract metadata",
    )
    args = ap.parse_args()

    cfg, path = load_forward_config(args.id, args.config)
    log.info(f"[e1] forward config {path} (hash {forward_config_hash(cfg)[:16]})")

    if args.bootstrap_checkpoint and args.migrate_runtime_contract:
        ap.error("--bootstrap-checkpoint and --migrate-runtime-contract are mutually exclusive")

    if args.migrate_runtime_contract:
        con = enginedb.connect(args.db, read_only=True)
        try:
            migrated = migrate_runtime_contract(con, cfg)
            run(con, cfg, read_only=True)
        finally:
            con.close()
        log.info(
            f"[e1] checkpoint migrated to schema {migrated['schema_version']} "
            f"with runtime contract {migrated['runtime_contract_sha256']}"
        )
        return 0

    if args.report_only:
        con = enginedb.connect(args.db, read_only=True)
        try:
            run(
                con,
                cfg,
                read_only=True,
                bootstrap_checkpoint=args.bootstrap_checkpoint,
            )
        finally:
            con.close()
        return 0

    try:
        con = enginedb.connect(args.db)
    except Exception as exc:  # noqa: BLE001 — reporting must never block the nightly
        log.info(f"[e1] store locked ({exc}); falling back to a read-only report refresh")
        con = enginedb.connect(args.db, read_only=True)
        try:
            run(con, cfg, read_only=True)
        finally:
            con.close()
        return 0
    try:
        run(con, cfg, bootstrap_checkpoint=args.bootstrap_checkpoint)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
