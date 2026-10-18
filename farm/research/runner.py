"""Fail-closed execution of a resolved StudySpec with structural outcome isolation."""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cache import CacheObject, ResearchCache
from .canonical import canonical_bytes, file_sha256, fsync_tree
from .mounts import ReadOnlyMount
from .spec import ContractError, ResolvedStudy, StudySpec
from .trials import JsonlTrialLedger, TrialLedgerError


class StudyRunError(RuntimeError):
    pass


@dataclass(frozen=True)
class StudyRun:
    run_directory: Path
    predictions_path: Path
    predictions_sha256: str
    result_path: Path | None
    result_sha256: str | None
    outcome_accessed: bool


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _import_callback(reference: dict[str, Any], expected_path: Path):
    module = importlib.import_module(reference["module"])
    path = Path(module.__file__ or "").resolve()
    if path != expected_path or file_sha256(path) != reference["sha256"]:
        raise ContractError(f"callback module changed after resolution: {reference['module']}")
    function = getattr(module, reference["function"], None)
    if (not inspect.isfunction(function) or function.__closure__
            or "<locals>" in function.__qualname__):
        raise ContractError("callback must be an importable function without a closure")
    return function


def _link_tree(source: Path, target: Path) -> None:
    target.mkdir()
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        destination = target / relative
        if path.is_symlink():
            raise StudyRunError("cache object contains a symbolic link")
        if path.is_dir():
            destination.mkdir()
        elif path.is_file():
            os.link(path, destination)
    for path in sorted(target.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    target.chmod(0o555)


def _seal_json(source: Path, target: Path) -> tuple[dict[str, Any], str]:
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StudyRunError("worker did not produce canonical JSON") from exc
    encoded = canonical_bytes(value, newline=True)
    if source.read_bytes() != encoded:
        raise StudyRunError("worker output is not canonical JSON")
    digest = file_sha256(source)
    os.replace(source, target)
    target.chmod(0o444)
    with target.open("rb") as stream:
        os.fsync(stream.fileno())
    return value, digest


class StudyRunner:
    def __init__(
        self,
        resolved: ResolvedStudy,
        *,
        ledger: JsonlTrialLedger,
        work_root: str | Path,
    ):
        self.resolved = resolved
        self.ledger = ledger
        self.work_root = Path(work_root).resolve()
        repository = _repo_root().resolve()
        if self.work_root.is_relative_to(repository):
            raise ValueError("study output root must be outside the repository")

    def _registered(self, trial: str) -> None:
        rows = [row for row in self.ledger.read()
                if row["kind"] == "registered" and row["trial_id"] == trial]
        if len(rows) != 1 or rows[0]["payload"]["study_sha256"] != self.resolved.spec.sha256:
            raise TrialLedgerError("study must be registered with this exact contract before running")

    def _cache_object(self, obj: CacheObject, kind: str) -> None:
        expected_identity = self.resolved.spec.cache_identity(kind)
        expected = ResearchCache.digest(kind, expected_identity)
        if obj.kind != kind or obj.digest != expected or obj.manifest["identity"] != expected_identity:
            raise StudyRunError(f"{kind} cache identity differs from the study contract")

    def _open_holdout(self, trial: str, run_directory: Path) -> None:
        holdout = self.resolved.spec.document["evaluation"]["holdout"]
        marker = (self.work_root / holdout["marker"]).resolve()
        if not marker.is_relative_to(self.work_root):
            raise StudyRunError("holdout marker escaped the output root")
        marker.parent.mkdir(parents=True, exist_ok=True)
        payload = canonical_bytes({
            "lease_id": holdout["lease_id"],
            "study_sha256": self.resolved.spec.sha256,
            "trial_id": trial,
        }, newline=True)
        try:
            descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        except FileExistsError as exc:
            raise StudyRunError("holdout lease has already been opened") from exc
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        self.ledger.append(
            kind="holdout_opened",
            event_id=f"holdout:{holdout['lease_id']}",
            trial=trial,
            payload={
                "source_ref": {
                    "lease_id": holdout["lease_id"],
                    "marker_sha256": file_sha256(marker),
                    "run_directory": run_directory.name,
                }
            },
        )

    def run(
        self,
        *,
        trial: str,
        attempt: str,
        features: CacheObject,
        outcomes: CacheObject | None = None,
    ) -> StudyRun:
        self._registered(trial)
        self._cache_object(features, "feature")
        phase = self.resolved.spec.document["study"]["phase"]
        if phase == "pilot" and outcomes is not None:
            raise StudyRunError("pilot runs cannot receive an outcome object")
        if phase != "pilot" and outcomes is None:
            raise StudyRunError("result-bearing runs require a separate label object")
        output_subdir = self.resolved.spec.document["execution"]["output_subdir"]
        output_root = (self.work_root / output_subdir).resolve()
        if not output_root.is_relative_to(self.work_root):
            raise StudyRunError("study output escaped its private root")
        run_directory = output_root / attempt
        run_directory.mkdir(parents=True, exist_ok=False)
        started_recorded = False
        try:
            self.ledger.append(
                kind="evaluation_started",
                event_id=f"evaluation_started:{attempt}",
                trial=trial,
                attempt=attempt,
                payload={
                    "source_ref": {
                        "study_sha256": self.resolved.spec.sha256,
                        "feature_sha256": features.digest,
                        "phase": phase,
                    }
                },
            )
            started_recorded = True
            if phase == "holdout":
                self._open_holdout(trial, run_directory)

            feature_mount = run_directory / "features"
            _link_tree(features.data_path, feature_mount)
            child_output = run_directory / f"predictions.{uuid.uuid4().hex}.tmp"
            request_path = run_directory / "worker-request.json"
            execution = self.resolved.spec.document["execution"]
            strategy = self.resolved.spec.document["strategy"]
            request = {
                "callback": strategy["callback"],
                "feature_root": str(feature_mount),
                "parameters": strategy["parameters"],
                "seed": execution["seed"],
                "mode": phase,
                "memory_mb": execution["memory_mb"],
            }
            request_path.write_bytes(canonical_bytes(request, newline=True))
            environment = {
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": os.pathsep.join((str(_repo_root()), str(self.resolved.base_dir))),
                "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "TMPDIR": str(run_directory),
                "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
            }
            subprocess.run(
                [sys.executable, "-m", "farm.research.worker", "--request", str(request_path),
                 "--output", str(child_output)],
                cwd=run_directory,
                env=environment,
                check=True,
                timeout=execution["expected_seconds"],
                capture_output=True,
                text=True,
            )
            predictions_path = run_directory / "predictions.json"
            predictions, predictions_sha = _seal_json(child_output, predictions_path)
            result_path, result_sha, outcome_accessed = None, None, False
            if phase != "pilot":
                assert outcomes is not None
                self._cache_object(outcomes, "label")
                outcome_reference = self.resolved.spec.document["outcomes"]["callback"]
                outcome_callback = _import_callback(
                    outcome_reference,
                    self.resolved.callback_paths[outcome_reference["module"]],
                )
                result = outcome_callback(
                    predictions,
                    ReadOnlyMount(outcomes.data_path),
                    self.resolved.spec.as_dict()["evaluation"],
                )
                result_path = run_directory / "result.json"
                result_path.write_bytes(canonical_bytes(result, newline=True))
                result_path.chmod(0o444)
                result_sha = file_sha256(result_path)
                outcome_accessed = True
            receipt = {
                "attempt_id": attempt,
                "feature_sha256": features.digest,
                "label_sha256": outcomes.digest if outcome_accessed and outcomes else None,
                "outcome_accessed": outcome_accessed,
                "phase": phase,
                "predictions_sha256": predictions_sha,
                "result_sha256": result_sha,
                "study_sha256": self.resolved.spec.sha256,
                "trial_id": trial,
            }
            receipt_path = run_directory / "receipt.json"
            receipt_path.write_bytes(canonical_bytes(receipt, newline=True))
            receipt_path.chmod(0o444)
            fsync_tree(run_directory)
            self.ledger.append(
                kind="evaluated",
                event_id=f"evaluated:{attempt}",
                trial=trial,
                attempt=attempt,
                payload={"source_ref": receipt},
            )
            return StudyRun(
                run_directory, predictions_path, predictions_sha,
                result_path, result_sha, outcome_accessed,
            )
        except Exception as exc:
            if started_recorded:
                try:
                    self.ledger.append(
                        kind="failed",
                        event_id=f"failed:{attempt}",
                        trial=trial,
                        attempt=attempt,
                        payload={"source_ref": {
                            "error": type(exc).__name__,
                            "message": str(exc)[:500],
                            "study_sha256": self.resolved.spec.sha256,
                        }},
                    )
                except TrialLedgerError:
                    pass
            raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--trial", required=True)
    parser.add_argument("--attempt", required=True)
    args = parser.parse_args(argv)
    spec = StudySpec.from_path(args.spec)
    resolved = spec.resolve(args.base_dir)
    cache = ResearchCache(args.cache_root)
    features = cache.get("feature", spec.cache_identity("feature"))
    outcomes = None if spec.document["study"]["phase"] == "pilot" else cache.get(
        "label", spec.cache_identity("label")
    )
    if features is None or (spec.document["study"]["phase"] != "pilot" and outcomes is None):
        parser.error("required content-addressed cache objects are unavailable")
    StudyRunner(
        resolved, ledger=JsonlTrialLedger(args.ledger), work_root=args.work_root,
    ).run(trial=args.trial, attempt=args.attempt, features=features, outcomes=outcomes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
