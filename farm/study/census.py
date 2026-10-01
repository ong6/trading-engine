"""Study-owned trial-census CSV schema and deterministic atomic writer.

The shared core defines and emits rows; each consuming study owns its census file.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from engine.lib.resources import write_text_atomic

from .protocol import RunIdentity

CENSUS_COLUMNS = (
    "trial_id", "run_identity", "variant", "fold", "phase", "status", "census_n",
    "spec_source_sha256", "parameters_sha256", "core_version", "cost_profile_hashes",
    "data_snapshot_sha256", "secondary_data_snapshot_sha256",
)


@dataclass(frozen=True)
class TrialRow:
    trial_id: str
    run_identity: str
    variant: str
    fold: str
    phase: str
    status: str
    census_n: int
    spec_source_sha256: str
    parameters_sha256: str
    core_version: str
    cost_profile_hashes: str
    data_snapshot_sha256: str
    secondary_data_snapshot_sha256: str = ""

    @classmethod
    def from_identity(cls, trial_id: str, variant: str, fold: str, phase: str,
                      status: str, census_n: int, identity: RunIdentity) -> TrialRow:
        if phase not in {"development", "holdout"} or census_n < 1:
            raise ValueError("invalid trial phase or census N")
        return cls(trial_id, identity.sha256, variant, fold, phase, status, census_n,
                   identity.spec_source_sha256, identity.parameters_sha256,
                   identity.core_version, json.dumps(identity.cost_profile_hashes,
                                                      sort_keys=True, separators=(",", ":")),
                   identity.data_snapshot_sha256,
                   identity.secondary_data_snapshot_sha256 or "")


def append_rows(path: str | Path, rows: Iterable[TrialRow]) -> Path:
    target = Path(path)
    existing = []
    if target.exists():
        with target.open(newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != CENSUS_COLUMNS:
                raise ValueError("census CSV header does not match the documented schema")
            existing = list(reader)
    additions = [asdict(row) for row in rows]
    identities = [row["trial_id"] for row in (*existing, *additions)]
    if not additions or any(not value for value in identities) or len(set(identities)) != len(identities):
        raise ValueError("trial rows must be non-empty with unique trial ids")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CENSUS_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows((*existing, *additions))
    target.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(target, output.getvalue())
    return target
