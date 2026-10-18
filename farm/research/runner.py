"""Fail-closed execution of a resolved StudySpec with structural outcome isolation."""

from __future__ import annotations

import argparse
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from engine.lib.resources import write_text_atomic

from .cache import CacheObject, ResearchCache
from .canonical import canonical_bytes, file_sha256, fsync_tree
from .sandbox import build_callback_package, prepare_sandbox_runtime, run_sandboxed
from .spec import ResolvedStudy, StudySpec
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


def _seal_json(value, target: Path) -> str:
    write_text_atomic(target, canonical_bytes(value, newline=True).decode())
    target.chmod(0o444)
    with target.open("rb") as stream:
        os.fsync(stream.fileno())
    return file_sha256(target)


def _seed(master: int, variant: str, fold: str) -> int:
    material = f"{master}\0{variant}\0{fold}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def _max_concurrency(executions: list[dict]) -> int:
    points = sorted(
        [(row["started_ns"], 1) for row in executions]
        + [(row["finished_ns"], -1) for row in executions],
        key=lambda item: (item[0], item[1]),
    )
    current = peak = 0
    for _, change in points:
        current += change
        peak = max(peak, current)
    return peak


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

            execution = self.resolved.spec.document["execution"]
            strategy = self.resolved.spec.document["strategy"]
            package = build_callback_package(
                self.resolved, strategy["callback"], run_directory,
            )
            prepare_sandbox_runtime(run_directory)
            jobs = [
                {
                    "variant": variant["name"],
                    "fold": fold["name"],
                    "parameters": {
                        **strategy["parameters"],
                        **variant["parameters"],
                        "_study_job": {
                            "variant": variant["name"],
                            "fold": dict(fold),
                        },
                    },
                    "seed": _seed(execution["seed"], variant["name"], fold["name"]),
                }
                for variant in self.resolved.spec.document["evaluation"]["variants"]
                for fold in self.resolved.spec.document["evaluation"]["folds"]
            ]

            def execute_job(job):
                response = run_sandboxed(
                    package,
                    {
                        "callback": strategy["callback"],
                        "package_sha256": package.digest,
                        "parameters": job["parameters"],
                        "seed": job["seed"],
                        "phase": phase,
                        "mode": "strategy",
                        "memory_mb": execution["memory_mb"],
                    },
                    feature_root=features.data_path,
                    label_root=None,
                    runtime_root=run_directory,
                    timeout=execution["expected_seconds"],
                )
                return job, response

            worker_count = min(execution["workers"], len(jobs))
            with ThreadPoolExecutor(max_workers=worker_count) as pool:
                evaluated = list(pool.map(execute_job, jobs))
            executions = [response for _, response in evaluated]
            predictions = {"jobs": [
                {
                    "variant": job["variant"],
                    "fold": job["fold"],
                    "seed": job["seed"],
                    "prediction": response["payload"],
                }
                for job, response in evaluated
            ]}
            predictions_path = run_directory / "predictions.json"
            predictions_sha = _seal_json(predictions, predictions_path)
            result_path, result_sha, outcome_accessed = None, None, False
            if phase != "pilot":
                assert outcomes is not None
                self._cache_object(outcomes, "label")
                outcome_reference = self.resolved.spec.document["outcomes"]["callback"]
                outcome_package = build_callback_package(
                    self.resolved, outcome_reference, run_directory,
                )
                outcome_response = run_sandboxed(
                    outcome_package,
                    {
                        "callback": outcome_reference,
                        "package_sha256": outcome_package.digest,
                        "predictions": predictions,
                        "evaluation": self.resolved.spec.as_dict()["evaluation"],
                        "mode": "evaluation",
                        "memory_mb": execution["memory_mb"],
                    },
                    feature_root=None,
                    label_root=outcomes.data_path,
                    runtime_root=run_directory,
                    timeout=execution["expected_seconds"],
                )
                result = outcome_response["payload"]
                result_path = run_directory / "result.json"
                write_text_atomic(result_path, canonical_bytes(result, newline=True).decode())
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
                "strategy_workers": {
                    "requested": execution["workers"],
                    "used": worker_count,
                    "max_concurrent": _max_concurrency(executions),
                    "pids": [row["host_pid"] for row in executions],
                },
                "worker_pids": [
                    *[row["host_pid"] for row in executions],
                    *([outcome_response["host_pid"]] if outcome_accessed else []),
                ],
            }
            receipt_path = run_directory / "receipt.json"
            write_text_atomic(receipt_path, canonical_bytes(receipt, newline=True).decode())
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
