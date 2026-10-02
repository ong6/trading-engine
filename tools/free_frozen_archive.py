#!/usr/bin/env python3
"""Run the offline census for P3's frozen public-domain price archive."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine import free_frozen_archive
from engine.lib.resources import write_text_atomic

DEFAULT_ARCHIVE_DIR = Path.home() / "trading-engine/store/pit/frozen-archive"
DEFAULT_REFERENCE_DATABASE = Path.home() / "trading-engine/store/pit/free-sources.duckdb"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--reference-database", type=Path, default=DEFAULT_REFERENCE_DATABASE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = free_frozen_archive.build_census(args.archive, args.reference_database)
        if args.archive.stem != result["source_sha256"]:
            raise free_frozen_archive.FrozenArchiveError(
                "archive filename must be its SHA-256"
            )
        output = args.output or DEFAULT_ARCHIVE_DIR / f"{result['source_sha256']}.census.json"
        write_text_atomic(output, json.dumps(result, indent=2, sort_keys=True) + "\n")
    except (OSError, free_frozen_archive.FrozenArchiveError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 2
    summary = {
        "status": "complete",
        "archive_sha256": result["source_sha256"],
        "tickers": result["canonical_files"],
        "nonempty_tickers": result["canonical_files"] - result["empty_files"],
        "ended_share": result["ended_share"],
        "sample_coverage": result["reference_comparison"]["sample_coverage"],
        "recommendation": result["recommendation"],
        "rows_loaded": result["rows_loaded"],
        "output": str(output),
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
