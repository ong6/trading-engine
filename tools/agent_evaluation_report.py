"""Publish the bounded canonical agent evaluation report."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from engine.lib import db, resources
from engine.lib.settings import DEFAULT_DB, REPO_ROOT
from server.agent_evaluation_reporting import build_report

DEFAULT_OUTPUT = REPO_ROOT / "data" / "reports" / "agent-evaluation.json"
DEFAULT_CONTAMINATION = (
    REPO_ROOT / "data" / "reports" / "experiments"
    / "agent-2022-replay-v1" / "result.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--contamination", type=Path, default=DEFAULT_CONTAMINATION)
    args = parser.parse_args(argv)
    con = db.connect(args.database, read_only=True, wait_s=0)
    try:
        report = build_report(
            con, generated_at=datetime.now(timezone.utc),
            contamination_path=args.contamination,
        )
    finally:
        con.close()
    resources.write_text_atomic(
        args.output, json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({"status": "complete", "output": str(args.output),
                      "trace_count": report["coverage"]["trace_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
