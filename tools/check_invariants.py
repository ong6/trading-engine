#!/usr/bin/env python3
"""Check the snapshot invariants (``tools/invariants``) against one published snapshot.

``--snapshot latest`` reads the snapshot behind ``store/snapshots/market-latest.duckdb``;
``--snapshot PATH`` must name a published snapshot: a single-link file in a ``snapshots``
directory with a matching manifest, never a live store file. Anything else is refused with
exit 3 before a database is opened. The snapshot is opened read-only with 2 threads, a 2 GB
memory limit and a private temporary directory.

Violations matched by a live entry of ``tools/invariants/baseline.json`` (owner, reason and
expiry each) are accepted; the rest are regressions. ``--publish PATH`` writes the result
atomically. Shadow mode (the default) exits 0 with regressions and reports them; ``--gate``
exits 2 on any regression. Either way exit 3 means the run could not evaluate: a refused
snapshot, an unreadable baseline, or an invariant that could not run.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from engine.lib.resources import write_text_atomic
from engine.lib.snapshots import (
    GENERATION_MANIFEST_SCHEMA_VERSION,
    LATEST_NAME,
    SHA256_PATTERN,
    SNAPSHOT_PATTERN,
    latest_snapshot,
    structural_snapshot_info,
)
from tools import invariants
from tools.invariants import registry

DUCKDB_CONFIG = {"threads": "2", "memory_limit": "2GB"}
CANNOT_EVALUATE = 3


class Refused(Exception):
    """The path is not a published snapshot; nothing was opened."""


@dataclass(frozen=True)
class Snapshot:
    path: Path
    name: str
    sha256: str
    as_of: datetime
    source_data_commit: str | None


def _manifest(path: Path) -> dict:
    manifest_path = path.with_suffix(".json")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise Refused(f"{path.name} has no manifest")
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError) as exc:
        raise Refused(f"{path.name} manifest is unreadable") from exc
    if isinstance(manifest, dict) \
            and manifest.get("manifest_schema_version") == GENERATION_MANIFEST_SCHEMA_VERSION:
        # A revision-16 generation: the hot file's identity is its recorded hot_database.
        info = structural_snapshot_info(path)
        if info is None:
            raise Refused(f"{path.name} manifest does not describe it")
        return {"sha256": info.sha256, "size_bytes": info.size_bytes,
                "as_of": info.as_of.isoformat(),
                "source_data_commit": info.source_data_commit}
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 \
            or manifest.get("snapshot") != path.name \
            or not isinstance(manifest.get("sha256"), str) \
            or SHA256_PATTERN.fullmatch(manifest["sha256"]) is None:
        raise Refused(f"{path.name} manifest does not describe it")
    return manifest


def _live_stores(*roots: Path) -> list[Path]:
    found = []
    for root in roots:
        found += [*root.glob("*.duckdb"), *root.glob("pit/*.duckdb")]
    return found


def resolve_snapshot(spec: str, engine_root: Path) -> Snapshot:
    """Locate and vet a published snapshot using only stat, readlink and its manifest."""
    store = engine_root / "store"
    if spec == "latest":
        info = latest_snapshot(store / "market.duckdb")
        if info is None:
            raise Refused(f"no valid published snapshot behind {LATEST_NAME}")
        path = info.path
    else:
        try:
            path = Path(spec).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise Refused("snapshot path does not exist") from exc
    if path.parent.name != "snapshots" or SNAPSHOT_PATTERN.fullmatch(path.name) is None:
        raise Refused(f"{path.name} is not a published snapshot (store/snapshots/market-*)")
    if path.is_symlink() or not path.is_file():
        raise Refused(f"{path.name} is not a regular file")
    stat = path.stat()
    if stat.st_nlink != 1:
        raise Refused(f"{path.name} has {stat.st_nlink} links; a published snapshot has one")
    for live in _live_stores(store, path.parent.parent):
        try:
            if os.path.samefile(path, live):
                raise Refused(f"{path.name} is a live store file")
        except OSError:
            continue
    manifest = _manifest(path)
    if manifest.get("size_bytes") not in (None, stat.st_size):
        raise Refused(f"{path.name} size differs from its manifest")
    as_of = registry.json_value(manifest.get("as_of"))
    try:
        stamp = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
    except ValueError as exc:
        raise Refused(f"{path.name} manifest has no as_of") from exc
    if stamp.tzinfo is None:
        raise Refused(f"{path.name} manifest as_of has no timezone")
    return Snapshot(path, path.name, manifest["sha256"], stamp.astimezone(UTC),
                    manifest.get("source_data_commit"))


def _result_base(mode: str, started: datetime) -> dict:
    return {"schema_version": registry.RESULT_SCHEMA_VERSION, "mode": mode,
            "checked_at": started.isoformat(timespec="seconds"), "snapshot": None}


def run(snapshot: Snapshot, engine_root: Path, baseline: list[dict], *,
        names: list[str] | None = None, today=None) -> dict:
    import duckdb

    scratch = tempfile.mkdtemp(prefix="invariants-")
    try:
        con = duckdb.connect(str(snapshot.path), read_only=True,
                             config={**DUCKDB_CONFIG, "temp_directory": scratch})
        try:
            ctx = registry.Context(con=con, snapshot_as_of=snapshot.as_of,
                                   engine_root=engine_root)
            return registry.evaluate(ctx, baseline, today=today or datetime.now(UTC).date(),
                                     names=names)
        finally:
            con.close()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _summary(result: dict) -> str:
    snap = result.get("snapshot") or {}
    lines = [f"invariants: {result['status']} ({result['mode']}) snapshot "
             f"{snap.get('name')} as of {snap.get('as_of')} in {result.get('seconds')}s"]
    if result.get("error"):
        lines.append(f"- cannot evaluate: {result['error']}")
    for name, item in result.get("invariants", {}).items():
        lines.append(f"- {name}: {item['status']} ({item['regression_count']} regression(s), "
                     f"{item['baselined_count']} baselined) {json.dumps(item['facts'])[:300]}")
        if item["error"]:
            lines.append(f"    error: {item['error']}")
        lines += [f"    {entry['class']}: {entry['subject']}" for entry in item["regressions"][:10]]
    expired = result.get("baseline", {}).get("expired") or []
    lines += [f"- expired exception: {entry['invariant']} {entry.get('class', '')} "
              f"(owner {entry['owner']}, expired {entry['expires']})" for entry in expired]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshot", required=True, help="'latest' or a published snapshot")
    parser.add_argument("--engine-root", type=Path, default=Path.home() / "trading-engine",
                        help="checkout whose store/snapshots and data/reports are read")
    parser.add_argument("--baseline", type=Path, default=registry.BASELINE_PATH)
    parser.add_argument("--publish", type=Path, help="write the result JSON here atomically")
    parser.add_argument("--gate", action="store_true", help="exit 2 on any regression")
    parser.add_argument("--only", action="append", choices=sorted(invariants.INVARIANTS),
                        help="run only this invariant (repeatable)")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = parser.parse_args(argv)
    started = datetime.now(UTC)
    clock = time.monotonic()
    result = _result_base("gate" if args.gate else "shadow", started)
    code = CANNOT_EVALUATE
    try:
        snapshot = resolve_snapshot(args.snapshot, args.engine_root.expanduser())
        result["snapshot"] = {"name": snapshot.name, "sha256": snapshot.sha256,
                              "as_of": snapshot.as_of.isoformat(timespec="seconds"),
                              "source_data_commit": snapshot.source_data_commit}
        baseline = registry.load_baseline(args.baseline)
    except Refused as exc:
        result.update(status="error", error=f"refused: {exc}")
    except (OSError, ValueError) as exc:
        result.update(status="error", error=f"baseline: {exc}")
    else:
        result.update(run(snapshot, args.engine_root.expanduser(), baseline, names=args.only))
        code = registry.exit_code(result)
        if code == 2 and not args.gate:
            code = 0
    result["seconds"] = round(time.monotonic() - clock, 1)
    if args.publish:
        write_text_atomic(args.publish.expanduser(),
                          json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(json.dumps(result, indent=1, sort_keys=True) if args.json else _summary(result))
    return code


if __name__ == "__main__":
    sys.exit(main())
