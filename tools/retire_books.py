"""Preview or atomically retire league books while retaining their history and holdings.

Dry runs read the published snapshot. Applying uses the normal engine writer connection.
Repeat --book, --reason and --evidence in matching order for a batch.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from engine.lib.db import connect

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = Path.home() / "trading-engine/store/snapshots/market-latest.duckdb"
ALPHA_ROOT = Path.home() / "trading-alpha"
ACTOR = "operator.retire_books"
# Historical AI books and their paired controls remain protected even when inactive.
PROTECTED = frozenset({
    "p15_ai_ranked", "p15_hybrid_veto", "p15_rule_control",
    "news_gated_momo", "momo_stopped", "earnings_context_pead", "pead_ear",
    "adaptive_mr", "adaptive_mr_frozen", "agentic_alloc", "agentic_alloc_frozen",
    "stop_tuner_turtle", "turtle_breakout", "daily_opportunity_agent_v1",
    "agent_dual_momentum_shadow_v1", "hybrid_dual_momentum_veto_shadow_v1",
    "dual_momentum", "spy_benchmark", "ew_benchmark",
})
TERMINAL_ORDER_STATES = ("filled", "p15_filled", "p16_filled", "rejected", "cancelled", "expired")


@dataclass(frozen=True)
class Retirement:
    book: str
    reason: str
    evidence: Path


def protected_books(book_ids: list[str], alpha_root: Path = ALPHA_ROOT) -> set[str]:
    """Read public registrations and private references; never open an alpha store.

    Exact book identifiers in registration/trial text count as references, including
    historical ones. Missing private inputs refuse the operation rather than silently
    treating uninspected books as unprotected.
    """
    private_paths = []
    for name in ("live", "registrations", "trials"):
        directory = alpha_root / name
        if not directory.is_dir():
            raise ValueError(f"cannot check protected books: missing alpha {name} directory")
        private_paths.extend(p for p in directory.rglob("*")
                             if p.is_file() and p.suffix in {".json", ".jsonl", ".md", ".csv"})
    public_paths = sorted((ROOT / "server").glob("*registration*.json"))
    referenced = set(PROTECTED)
    patterns = {book: re.compile(r"(?<![A-Za-z0-9_.-])" + re.escape(book)
                                + r"(?![A-Za-z0-9_.-])") for book in book_ids}
    for path in [*public_paths, *sorted(private_paths)]:
        content = path.read_text()
        referenced.update(book for book, pattern in patterns.items() if pattern.search(content))
    # Reserved AI identities also stay protected before registration activation.
    referenced.update(book for book in book_ids if book.startswith(("p15_", "p16_", "p7_")))
    return referenced


def retire_books(
    requests: list[Retirement], *, apply: bool = False, database: Path | None = None,
    alpha_root: Path = ALPHA_ROOT,
) -> list[dict]:
    """Return the exact planned changes; commit the whole batch only with apply=True."""
    if not requests or len({r.book for r in requests}) != len(requests):
        raise ValueError("supply distinct books in a nonempty batch")
    for request in requests:
        if not request.book.strip() or not request.reason.strip():
            raise ValueError("book and reason must be nonempty")
        if not request.evidence.is_file() or not request.evidence.stat().st_size:
            raise ValueError(f"evidence must be a nonempty file: {request.evidence}")
    con = connect(database if database is not None else (None if apply else SNAPSHOT),
                  read_only=not apply)
    try:
        con.execute("BEGIN TRANSACTION")
        try:
            ids = [row[0] for row in con.execute("SELECT id FROM portfolios ORDER BY id").fetchall()]
            protected = protected_books(ids, alpha_root)
            changes = []
            at = datetime.now(timezone.utc)
            for request in requests:
                row = con.execute("SELECT active FROM portfolios WHERE id=?",
                                  [request.book]).fetchone()
                if row is None:
                    raise ValueError(f"unknown book: {request.book}")
                if not row[0]:
                    raise ValueError(f"already retired: {request.book}")
                if request.book in protected:
                    raise ValueError(f"protected book: {request.book}")
                placeholders = ",".join("?" for _ in TERMINAL_ORDER_STATES)
                open_orders = con.execute(
                    "SELECT COUNT(*) FROM sim_orders WHERE portfolio_id=? "
                    f"AND (status IS NULL OR status NOT IN ({placeholders}))",
                    [request.book, *TERMINAL_ORDER_STATES],
                ).fetchone()[0]
                if open_orders:
                    raise ValueError(f"open orders: {request.book} ({open_orders})")
                latest = con.execute("SELECT MAX(date) FROM sim_equity WHERE portfolio_id=?",
                                     [request.book]).fetchone()[0]
                if latest is not None:
                    close = datetime.combine(latest, time(16), ZoneInfo("America/New_York"))
                    if at <= close:
                        raise ValueError(f"session has not closed: {request.book} ({latest})")
                positions = con.execute(
                    "SELECT COUNT(*) FROM sim_positions WHERE portfolio_id=? AND qty != 0",
                    [request.book],
                ).fetchone()[0]
                payload = {
                    "portfolio_id": request.book, "reason": request.reason,
                    "positions_kept": positions, "pending_cancelled": 0,
                    "precedent": "2026-08-18", "evidence": request.evidence.as_posix(),
                }
                changes.append({
                    "book": request.book, "active": {"from": True, "to": False},
                    "audit_row": {"ts": at.isoformat(), "actor": ACTOR,
                                  "action": "portfolio_retired", "payload": payload},
                })
            if apply:
                for change in changes:
                    audit = change["audit_row"]
                    con.execute("UPDATE portfolios SET active=FALSE WHERE id=?", [change["book"]])
                    con.execute("INSERT INTO audit_log (ts,actor,action,payload) VALUES (?,?,?,?)", [
                        at.replace(tzinfo=None), audit["actor"], audit["action"],
                        json.dumps(audit["payload"], sort_keys=True),
                    ])
                con.execute("COMMIT")
            else:
                con.execute("ROLLBACK")
            return changes
        except BaseException:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", action="append", required=True)
    parser.add_argument("--reason", action="append", required=True)
    parser.add_argument("--evidence", action="append", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="commit through the engine writer")
    parser.add_argument("--db", type=Path, help="explicit store (default dry run: published snapshot)")
    parser.add_argument("--alpha-root", type=Path, default=ALPHA_ROOT,
                        help="private reference checkout to inspect read-only")
    args = parser.parse_args(argv)
    if not len(args.book) == len(args.reason) == len(args.evidence):
        parser.error("--book, --reason and --evidence must occur equally often")
    requests = [Retirement(*row) for row in zip(args.book, args.reason, args.evidence, strict=True)]
    try:
        changes = retire_books(requests, apply=args.apply, database=args.db,
                               alpha_root=args.alpha_root)
    except (ValueError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"mode": "applied" if args.apply else "dry-run", "changes": changes},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
