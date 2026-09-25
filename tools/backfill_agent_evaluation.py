#!/usr/bin/env python3
"""Index complete retained agent artifacts and append newly mature outcome labels."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from engine.lib import db
from engine.lib.settings import DEFAULT_DB, REPO_ROOT
from server import agent_evaluation, daily_opportunity_store
from server.file_utils import read_bytes


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in read_bytes(path, label="agent evaluation JSONL").splitlines() if line]


def run(database: Path = DEFAULT_DB) -> dict:
    con = db.connect(database, wait_s=0)
    indexed, skipped = 0, 0
    try:
        with db.transaction(con):
            daily_opportunity_store.init_schema(con)
            agent_evaluation.init_schema(con)
            for (run_id,) in con.execute(
                "SELECT id FROM daily_opportunity_runs WHERE status='completed' ORDER BY id"
            ).fetchall():
                try:
                    result = agent_evaluation.record_trace(
                        con, agent_evaluation.daily_trace(con, int(run_id))
                    )
                    indexed += not result["replayed"]
                except agent_evaluation.EvaluationError:
                    skipped += 1
            for variant in ("hourly_market_watch_v1", "four_hour_opportunity_review_v1",
                            "hourly_market_watch_v2", "four_hour_opportunity_review_v2",
                            "hourly_market_watch_v3", "four_hour_opportunity_review_v3",
                            "hourly_market_watch_v4", "four_hour_opportunity_review_v4",
                            "hourly_market_watch_v5", "four_hour_opportunity_review_v5"):
                path = REPO_ROOT / "logs" / f"{variant}.jsonl"
                for artifact in _jsonl(path):
                    try:
                        result = agent_evaluation.record_trace(
                            con,
                            agent_evaluation.replay_artifact_trace(
                                artifact,
                                source_identifier=f"{path.name}:{artifact.get('window')}",
                            ),
                        )
                        indexed += not result["replayed"]
                    except (KeyError, TypeError, ValueError, agent_evaluation.EvaluationError):
                        skipped += 1
            labels = agent_evaluation.label_mature(
                con, labeled_at=datetime.now(timezone.utc)
            )
            current = agent_evaluation.status(con)
    finally:
        con.close()
    return {"status": "complete", "new_trace_count": int(indexed),
            "skipped_incomplete_source_count": skipped,
            "new_label_count": labels["inserted"], "evaluation": current}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    print(json.dumps(run(args.database), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
