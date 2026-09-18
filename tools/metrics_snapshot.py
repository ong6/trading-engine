#!/usr/bin/env python3
"""Drift metrics: one dated JSON snapshot of code size, commit shape, ledger hygiene, and
research progress, plus a check of the frozen-layer budget in ``docs/scope-budget.json``.

Runs from committed artifacts and Git only (no DuckDB, no network), so it works on any clone.
``python -m tools.metrics_snapshot`` publishes ``data/reports/metrics/<date>.json`` and
regenerates the sibling ``README.md`` table. ``--check-budget`` exits nonzero when a frozen
layer is over its ceiling. See ``docs/metrics.md`` for what each number means.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from engine.lib.resources import write_text_atomic

REPO_ROOT = Path(__file__).resolve().parents[1]
BUDGET_PATH = REPO_ROOT / "docs" / "scope-budget.json"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "reports" / "metrics"
BUILDLOG_PATH = REPO_ROOT / "BUILDLOG.md"
BUILDLOG_TAIL_MARKER = "<!-- append-only-tail:"
BUILDLOG_V2_MARKER = "<!-- buildlog-format-v2 -->"

PY_LAYERS = ("engine", "sim", "farm", "server", "tools", "tests")
UI_SUFFIXES = {".js", ".jsx", ".ts", ".tsx"}
RESEARCH_PREFIXES = (
    "sim/strategies/",
    "farm/",
    "docs/charters/",
    "docs/plans/",
    "data/reports/experiments/",
    "data/reports/forward/",
)
SHA256 = re.compile(r"\b[0-9a-f]{64}\b")
SCREEN_COMMIT = re.compile(r"^screen: \d{4}-\d{2}-\d{2}")
ENTRY_HEADER = re.compile(r"^## \d{4}-\d{2}-\d{2}", re.MULTILINE)
COMMIT_WINDOW_DAYS = 30
RECENT_ENTRIES = 10


def _count_lines(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        with path.open("rb") as handle:
            total += sum(1 for _ in handle)
    return total


def _layer_files(root: Path, layer: str) -> list[Path]:
    base = root / layer
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)


def code_size(root: Path = REPO_ROOT) -> dict[str, int]:
    """Lines of Python per layer, UI source lines, docs and BUILDLOG lines."""
    sizes = {layer: _count_lines(_layer_files(root, layer)) for layer in PY_LAYERS}
    ui_app = root / "ui" / "app"
    ui_files = [
        p for p in ui_app.rglob("*") if p.suffix in UI_SUFFIXES and "node_modules" not in p.parts
    ] if ui_app.is_dir() else []
    sizes["ui_app"] = _count_lines(sorted(ui_files))
    docs_files = sorted((root / "docs").rglob("*.md"))
    sizes["docs_md"] = _count_lines(docs_files)
    sizes["buildlog"] = _count_lines([root / "BUILDLOG.md"])
    sizes["product"] = sizes["engine"] + sizes["sim"] + sizes["farm"]
    return sizes


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False, timeout=60
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def _commit_records(root: Path, since: date) -> list[dict[str, Any]]:
    raw = _git(
        root, "log", f"--since={since.isoformat()}", "--format=%x1e%h%x1f%s", "--numstat"
    )
    records: list[dict[str, Any]] = []
    for chunk in raw.split("\x1e"):
        if not chunk.strip():
            continue
        head, _, body = chunk.partition("\n")
        sha, _, subject = head.partition("\x1f")
        files: list[str] = []
        insertions = 0
        for line in body.splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            added, _removed, name = parts
            files.append(name)
            if added.isdigit():
                insertions += int(added)
        records.append(
            {"sha": sha, "subject": subject, "files": files, "insertions": insertions}
        )
    return records


def _is_research(files: list[str]) -> bool:
    return any(name.startswith(RESEARCH_PREFIXES) for name in files)


def _is_product(files: list[str]) -> bool:
    return any(name.startswith(("engine/", "sim/", "farm/")) for name in files)


def commit_shape(root: Path = REPO_ROOT, today: date | None = None) -> dict[str, Any]:
    """Shape of the last 30 days of non-screen commits: size, and how many touched research."""
    today = today or datetime.now(timezone.utc).date()
    records = [
        r
        for r in _commit_records(root, today - timedelta(days=COMMIT_WINDOW_DAYS))
        if not SCREEN_COMMIT.match(r["subject"])
    ]
    count = len(records)
    research = sum(1 for r in records if _is_research(r["files"]))
    product = sum(1 for r in records if _is_product(r["files"]))
    largest = max(records, key=lambda r: r["insertions"], default=None)
    return {
        "window_days": COMMIT_WINDOW_DAYS,
        "non_screen_commits": count,
        "research_touching": research,
        "product_touching": product,
        "support_only": count - product,
        "largest_insertions": largest["insertions"] if largest else 0,
        "largest_sha": largest["sha"] if largest else None,
        "largest_subject": largest["subject"] if largest else None,
    }


def buildlog_entries(text: str) -> list[str]:
    """Entries under dated ``## YYYY-MM-DD`` headers, excluding the tail marker line."""
    body = text.split(BUILDLOG_TAIL_MARKER, 1)[0]
    starts = [m.start() for m in ENTRY_HEADER.finditer(body)]
    ends = [*starts[1:], len(body)]
    return [body[a:b].rstrip("\n") for a, b in zip(starts, ends, strict=True)]


def buildlog_v2_entries(text: str) -> list[str]:
    """Entries written after the format-v2 marker; these must obey the entry budget."""
    if BUILDLOG_V2_MARKER not in text:
        return []
    return buildlog_entries(text.split(BUILDLOG_V2_MARKER, 1)[1])


def ledger_hygiene(root: Path = REPO_ROOT) -> dict[str, Any]:
    text = (root / "BUILDLOG.md").read_text()
    recent = buildlog_entries(text)[-RECENT_ENTRIES:]
    lengths = [len(entry.splitlines()) for entry in recent]
    hashes = [len(SHA256.findall(entry)) for entry in recent]
    v2 = buildlog_v2_entries(text)
    return {
        "entries_total": len(buildlog_entries(text)),
        "recent_entries": len(recent),
        "recent_mean_lines": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        "recent_max_lines": max(lengths, default=0),
        "recent_sha256_mentions": sum(hashes),
        "v2_entries": len(v2),
        "v2_max_lines": max((len(e.splitlines()) for e in v2), default=0),
        "v2_max_sha256": max((len(SHA256.findall(e)) for e in v2), default=0),
    }


def _first_int(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else None


def research_progress(root: Path = REPO_ROOT, today: date | None = None) -> dict[str, Any]:
    """Progress counters read from the committed forward reports and league snapshot."""
    today = today or datetime.now(timezone.utc).date()
    reports = root / "data" / "reports"

    def read(rel: str) -> str:
        path = reports / rel
        return path.read_text() if path.is_file() else ""

    sector = read("forward/sector_momentum.md")
    xs = read("forward/xs_momentum_12_1.md")
    e1 = read("experiments/e1-spy-monday-forward.md")
    league = read("league.md")
    league_date = re.search(r"# Paper League — (\d{4}-\d{2}-\d{2})", league)
    stale_days = None
    if league_date:
        stale_days = (today - date.fromisoformat(league_date.group(1))).days
    return {
        "sector_shared_sessions": _first_int(r"Shared observations: \*\*(\d+)\*\*", sector),
        "sector_status": (re.search(r"Status \*\*([A-Z_-]+)\*\*", sector) or [None, None])[1],
        "xs_status": (re.search(r"Status \*\*([A-Z_-]+)\*\*", xs) or [None, None])[1],
        "e1_observations": _first_int(r"(\d+) of 40", e1),
        "league_date": league_date.group(1) if league_date else None,
        "league_stale_days": stale_days,
        "active_books": len(re.findall(r"^\| \d+ \|", league, re.MULTILINE)),
    }


def load_budget(path: Path = BUDGET_PATH) -> dict[str, Any]:
    return json.loads(path.read_text())


def budget_check(sizes: dict[str, int], hygiene: dict[str, Any],
                 budget: dict[str, Any]) -> dict[str, Any]:
    """Compare frozen-layer sizes and ledger format against the committed ceilings."""
    over: list[str] = []
    for layer, ceiling in budget["loc_ceiling"].items():
        if sizes.get(layer, 0) > ceiling:
            over.append(f"{layer}: {sizes[layer]} > {ceiling}")
    entry = budget["buildlog_entry"]
    if hygiene["v2_max_lines"] > entry["max_lines"]:
        over.append(f"buildlog v2 entry lines: {hygiene['v2_max_lines']} > {entry['max_lines']}")
    if hygiene["v2_max_sha256"] > entry["max_sha256"]:
        over.append(f"buildlog v2 sha256: {hygiene['v2_max_sha256']} > {entry['max_sha256']}")
    return {"ok": not over, "violations": over}


def snapshot(root: Path = REPO_ROOT, today: date | None = None) -> dict[str, Any]:
    today = today or datetime.now(timezone.utc).date()
    sizes = code_size(root)
    hygiene = ledger_hygiene(root)
    budget = load_budget(root / "docs" / "scope-budget.json")
    return {
        "date": today.isoformat(),
        "code_size": sizes,
        "commit_shape": commit_shape(root, today),
        "ledger": hygiene,
        "research": research_progress(root, today),
        "budget": budget_check(sizes, hygiene, budget),
    }


def _previous(out_dir: Path, today: str) -> dict[str, Any] | None:
    older = sorted(p for p in out_dir.glob("*.json") if p.stem < today)
    if not older:
        return None
    return json.loads(older[-1].read_text())


def _delta(current: int | None, previous: int | None) -> str:
    if current is None or previous is None:
        return "—"
    diff = current - previous
    return f"{diff:+d}" if diff else "0"


def render_readme(out_dir: Path) -> str:
    rows = [json.loads(p.read_text()) for p in sorted(out_dir.glob("*.json"))][-12:]
    lines = [
        "# Drift metrics",
        "",
        "Generated by `python -m tools.metrics_snapshot`; definitions in "
        "[`docs/metrics.md`](../../../docs/metrics.md). One row per snapshot, newest last.",
        "",
        "| Date | server LOC | tools LOC | product LOC | tests LOC | non-screen commits (30d) "
        "| support-only | largest commit | BUILDLOG mean lines | sha256 mentions "
        "| sector sessions | E1 obs | books | budget |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        size, shape, ledger, research = (
            row["code_size"], row["commit_shape"], row["ledger"], row["research"]
        )
        lines.append(
            f"| {row['date']} | {size['server']} | {size['tools']} | {size['product']} "
            f"| {size['tests']} | {shape['non_screen_commits']} | {shape['support_only']} "
            f"| {shape['largest_insertions']} | {ledger['recent_mean_lines']} "
            f"| {ledger['recent_sha256_mentions']} | {research['sector_shared_sessions']} "
            f"| {research['e1_observations']} | {research['active_books']} "
            f"| {'ok' if row['budget']['ok'] else 'OVER'} |"
        )
    if len(rows) >= 2:
        cur, prev = rows[-1]["code_size"], rows[-2]["code_size"]
        lines += [
            "",
            f"Since {rows[-2]['date']}: server {_delta(cur['server'], prev['server'])}, "
            f"tools {_delta(cur['tools'], prev['tools'])}, "
            f"product {_delta(cur['product'], prev['product'])}, "
            f"tests {_delta(cur['tests'], prev['tests'])}.",
        ]
    if rows and not rows[-1]["budget"]["ok"]:
        lines += ["", "**Budget violations:** " + "; ".join(rows[-1]["budget"]["violations"])]
    return "\n".join(lines) + "\n"


def publish(out_dir: Path, snap: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{snap['date']}.json"
    previous = _previous(out_dir, snap["date"])
    if previous is not None:
        snap["previous_date"] = previous["date"]
    write_text_atomic(target, json.dumps(snap, indent=2, sort_keys=True) + "\n")
    write_text_atomic(out_dir / "README.md", render_readme(out_dir))
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--check-budget", action="store_true",
                        help="exit 1 when a frozen layer exceeds docs/scope-budget.json")
    parser.add_argument("--dry-run", action="store_true", help="print JSON, publish nothing")
    args = parser.parse_args(argv)

    snap = snapshot(REPO_ROOT, args.date)
    if args.dry_run:
        print(json.dumps(snap, indent=2, sort_keys=True))
    else:
        target = publish(args.out_dir, snap)
        print(f"published {target.relative_to(REPO_ROOT) if target.is_relative_to(REPO_ROOT) else target}")
    for violation in snap["budget"]["violations"]:
        print(f"BUDGET: {violation}", file=sys.stderr)
    if args.check_budget and not snap["budget"]["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
