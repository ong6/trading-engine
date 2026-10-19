"""Fail-closed execution of a resolved StudySpec with structural outcome isolation."""

from __future__ import annotations

import argparse
import hashlib
import math
import operator
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from engine.lib.resources import write_text_atomic

from .artifacts import (
    build_label_artifact,
    build_study_artifacts,
    materialize_fold_features,
    validate_feature_label_alignment,
    validate_study_object,
)
from .cache import CacheObject, ResearchCache, repository_containing
from .canonical import canonical_bytes, canonical_sha256, file_sha256, fsync_tree
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


def _verdict(result: object, evaluation: dict) -> str:
    if not isinstance(result, dict) or not isinstance(result.get("metrics"), dict):
        raise StudyRunError("evaluation callback must return a metrics object")
    statistics = result.get("statistics")
    controls = result.get("controls")
    costs = result.get("cost_profile_hashes")
    if (not isinstance(statistics, dict)
            or set(statistics) != set(evaluation["statistics"])
            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not math.isfinite(float(value)) for value in statistics.values())):
        raise StudyRunError("evaluation callback did not account for every declared statistic")
    if (not isinstance(controls, dict) or set(controls) != set(evaluation["controls"])):
        raise StudyRunError("evaluation callback did not account for every declared control")
    expected_costs = {
        item["name"]: item["sha256"] for item in evaluation["_declared_cost_profiles"]
    }
    if costs != expected_costs:
        raise StudyRunError("evaluation callback did not bind every declared cost profile")
    operations = {
        ">": operator.gt, ">=": operator.ge, "<": operator.lt,
        "<=": operator.le, "==": operator.eq, "!=": operator.ne,
    }
    matched = []
    for name in ("pass", "admit", "kill"):
        rule = evaluation["rules"][name]
        value = result["metrics"].get(rule["metric"])
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(float(value))):
            raise StudyRunError(f"evaluation metric is unavailable or non-finite: {rule['metric']}")
        if operations[rule["operator"]](float(value), rule["threshold"]):
            matched.append(name)
    if not matched:
        raise StudyRunError("evaluation rules did not derive a verdict")
    return matched[0]


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
        if repository_containing(self.work_root) is not None:
            raise ValueError("study output root must be outside the repository")

    def _registered(self, trial: str) -> None:
        rows = [row for row in self.ledger.read()
                if row["kind"] == "registered" and row["trial_id"] == trial]
        if (len(rows) != 1 or rows[0]["payload"]["study_sha256"]
                != self.resolved.spec.study_identity_sha256):
            raise TrialLedgerError("study must be registered with this exact contract before running")

    def _reconciliation(self) -> dict:
        declared = self.resolved.spec.document["evaluation"]["dsr_census"]
        evidence_path = self.resolved.evidence_paths[declared["path"]]
        if self.ledger.path.resolve() != evidence_path.resolve():
            raise TrialLedgerError("runner ledger differs from the StudySpec census source")
        receipt = self.ledger.reconciliation_receipt()
        if (file_sha256(evidence_path) != declared["sha256"]
                or receipt["selection_n"] != declared["selection_n"]
                or receipt["register_sha256"] != declared["register_sha256"]
                or receipt["row_sha256"] != declared["row_sha256"]):
            raise TrialLedgerError("StudySpec census seal differs from the complete ledger")
        return receipt

    def _reconciliation_still_bounds_attempt(
        self, receipt: dict, *, trial: str, attempt: str,
    ) -> None:
        records = self.ledger.read()
        tail = records[receipt["reconciliation_sequence"]:]
        allowed = all(
            row["trial_id"] == trial
            and (row["kind"] == "evaluation_started" and row["attempt_id"] == attempt
                 or row["kind"] == "holdout_opened" and row["attempt_id"] is None)
            for row in tail
        )
        if (not allowed or self.ledger.summary().selection_n != receipt["selection_n"]):
            raise TrialLedgerError("trial census changed after evaluation started")

    def _cache_object(self, obj: CacheObject, kind: str) -> None:
        expected_identity = self.resolved.spec.cache_identity(kind)
        expected = ResearchCache.digest(kind, expected_identity)
        if obj.kind != kind or obj.digest != expected or obj.manifest["identity"] != expected_identity:
            raise StudyRunError(f"{kind} cache identity differs from the study contract")
        validate_study_object(self.resolved, obj)

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
    ) -> StudyRun:
        self._registered(trial)
        reconciliation = self._reconciliation()
        self._cache_object(features, "feature")
        phase = self.resolved.spec.document["study"]["phase"]
        pin_objects = [features]
        cache_root = features.path.parents[3]
        cache = ResearchCache(cache_root)
        cache.pin(
            f"study:{trial}",
            pin_objects,
            {key: reconciliation[key] for key in (
                "status", "row_sha256", "register_sha256", "selection_n"
            )},
        )
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
            arms = [
                {"kind": "variant", "name": variant["name"], "parameters": variant["parameters"]}
                for variant in self.resolved.spec.document["evaluation"]["variants"]
            ] + [
                {"kind": "control", "name": control, "parameters": {}}
                for control in self.resolved.spec.document["evaluation"]["controls"]
            ]
            jobs = [
                {
                    "kind": arm["kind"],
                    "name": arm["name"],
                    "fold": fold["name"],
                    "parameters": {
                        **strategy["parameters"],
                        **arm["parameters"],
                        "_study_job": {
                            "kind": arm["kind"],
                            "name": arm["name"],
                            "fold": dict(fold),
                        },
                    },
                    "seed": _seed(execution["seed"], f"{arm['kind']}:{arm['name']}", fold["name"]),
                    "feature_root": materialize_fold_features(
                        self.resolved,
                        features,
                        fold,
                        run_directory / "fold-features" / canonical_sha256({
                            "kind": arm["kind"], "name": arm["name"], "fold": fold["name"],
                        })[:16],
                    ),
                }
                for arm in arms
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
                    feature_root=job["feature_root"],
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
                    "kind": job["kind"],
                    "name": job["name"],
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
                self._reconciliation_still_bounds_attempt(
                    reconciliation, trial=trial, attempt=attempt,
                )
                outcomes = build_label_artifact(
                    cache, self.resolved, run_directory / "outcome-build",
                )
                self._cache_object(outcomes, "label")
                validate_feature_label_alignment(self.resolved, features, outcomes)
                cache.pin(
                    f"study:{trial}",
                    [features, outcomes],
                    {key: reconciliation[key] for key in (
                        "status", "row_sha256", "register_sha256", "selection_n"
                    )},
                )
                outcome_reference = self.resolved.spec.document["evaluation"]["callback"]
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
                evaluation_result = outcome_response["payload"]
                evaluation_contract = self.resolved.spec.as_dict()["evaluation"]
                evaluation_contract["_declared_cost_profiles"] = self.resolved.spec.as_dict()[
                    "costs"]["profiles"]
                result = {
                    "evaluation": evaluation_result,
                    "verdict": _verdict(
                        evaluation_result, evaluation_contract,
                    ),
                    "accounting": {
                        "benchmark_mode": self.resolved.spec.document["evaluation"]["benchmark_mode"],
                        "costs": self.resolved.spec.document["costs"],
                        "job_count": len(jobs),
                        "missing_data_policy": self.resolved.spec.document[
                            "evaluation"]["missing_data_policy"],
                    },
                }
                result_path = run_directory / "result.json"
                write_text_atomic(result_path, canonical_bytes(result, newline=True).decode())
                result_path.chmod(0o444)
                result_sha = file_sha256(result_path)
                outcome_accessed = True
            receipt = {
                "attempt_id": attempt,
                "feature_sha256": features.digest,
                "label_sha256": outcomes.digest if outcome_accessed else None,
                "outcome_accessed": outcome_accessed,
                "phase": phase,
                "predictions_sha256": predictions_sha,
                "result_sha256": result_sha,
                "study_sha256": self.resolved.spec.sha256,
                "trial_id": trial,
                "census_reconciliation": reconciliation,
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
            valid_terminal = self.ledger.append_terminal_cas(
                reconciliation,
                trial=trial,
                attempt=attempt,
                payload={"source_ref": receipt},
                invalid_payload={"source_ref": {
                    "error": "CensusChanged",
                    "message": "trial census changed before terminal append",
                    "study_sha256": self.resolved.spec.sha256,
                }},
            )
            if not valid_terminal:
                quarantine = run_directory / "result.quarantined.json"
                if result_path is not None:
                    os.replace(result_path, quarantine)
                raise TrialLedgerError("trial census changed; computed result was quarantined")
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
    runner = StudyRunner(
        resolved, ledger=JsonlTrialLedger(args.ledger), work_root=args.work_root,
    )
    artifacts = build_study_artifacts(
        cache,
        resolved,
        args.work_root / "artifact-build",
    )
    runner.run(
        trial=args.trial,
        attempt=args.attempt,
        features=artifacts.features,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
