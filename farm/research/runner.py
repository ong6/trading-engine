"""Fail-closed execution of a resolved StudySpec with structural outcome isolation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import operator
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from engine.lib.resources import write_text_atomic

from .artifacts import (
    _build_label_artifact,
    _new_label_capability,
    build_study_artifacts,
    materialize_decision_features,
    validate_feature_label_alignment,
    validate_study_object,
)
from .cache import CacheObject, ResearchCache, repository_containing
from .canonical import canonical_bytes, canonical_sha256, file_sha256, fsync_tree
from .sandbox import build_callback_package, prepare_sandbox_runtime, run_sandboxed
from .spec import ResolvedStudy, StudySpec


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


@dataclass(frozen=True)
class CensusSnapshot:
    sha256: str
    selection_n: int
    size: int


def _census_snapshot(resolved: ResolvedStudy) -> CensusSnapshot:
    declared = resolved.spec.document["evaluation"]["dsr_census"]
    path = resolved.evidence_paths[declared["path"]]
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != declared["sha256"]:
        raise StudyRunError("census snapshot bytes differ")
    try:
        if path.suffix.lower() == ".csv":
            rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
            values = {int(row["selection_n"]) for row in rows if row.get("selection_n")}
            observed = max(values) if values else None
        else:
            payload = json.loads(raw)
            observed = payload.get("selection_n") if isinstance(payload, dict) else None
    except (UnicodeDecodeError, csv.Error, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise StudyRunError("census snapshot cannot be parsed") from exc
    if type(observed) is not int or observed != declared["selection_n"]:
        raise StudyRunError("census selection N differs from the contract")
    return CensusSnapshot(digest, observed, len(raw))


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


def _reduce_evaluation(callback_result: object, predictions: dict, evaluation: dict,
                       costs: dict) -> dict:
    if (not isinstance(callback_result, dict)
            or set(callback_result) - {"job_results", "details"}
            or not isinstance(callback_result.get("job_results"), list)):
        raise StudyRunError("evaluation callback must return job_results and optional details")
    fields = {"kind", "name", "fold", "decision_session", "gross_return", "missing"}
    expected = {
        (job["kind"], job["name"], job["fold"], job["decision_session"])
        for job in predictions["jobs"]
    }
    observed = {}
    for row in callback_result["job_results"]:
        if not isinstance(row, dict) or set(row) != fields:
            raise StudyRunError("per-job evaluation schema differs")
        key = (row["kind"], row["name"], row["fold"], row["decision_session"])
        if key in observed:
            raise StudyRunError("per-job evaluation is duplicated")
        if (type(row["missing"]) is not bool or isinstance(row["gross_return"], bool)
                or not isinstance(row["gross_return"], (int, float))
                or not math.isfinite(float(row["gross_return"]))):
            raise StudyRunError("per-job return or missing flag differs")
        observed[key] = row
    if set(observed) != expected:
        raise StudyRunError("evaluation callback omitted or invented a fold/control job")
    if evaluation["missing_data_policy"] == "refuse" and any(
            row["missing"] for row in observed.values()):
        raise StudyRunError("missing-data policy refused an incomplete job")
    profiles = costs["profiles"]
    profile_hashes = {item["name"]: item["sha256"] for item in profiles}
    rows = []
    for key in sorted(expected):
        source = observed[key]
        if source["missing"] and evaluation["missing_data_policy"] == "drop":
            continue
        net = {
            item["name"]: float(source["gross_return"]) - item["rate_bps"] / 10_000
            for item in profiles
        }
        rows.append({
            "kind": key[0], "name": key[1], "fold": key[2],
            "decision_session": key[3], "gross_return": float(source["gross_return"]),
            "net_returns": net,
        })
    primary = profiles[0]["name"]
    variants = [row for row in rows if row["kind"] == "variant"]
    controls = [row for row in rows if row["kind"] == "control"]
    if not variants or not controls:
        raise StudyRunError("trusted reduction needs variant and control observations")
    control_by_key = {}
    for row in controls:
        key = row["fold"], row["decision_session"]
        control_by_key.setdefault(key, []).append(row["net_returns"][primary])
    excess = [
        row["net_returns"][primary]
        - sum(control_by_key[(row["fold"], row["decision_session"])])
        / len(control_by_key[(row["fold"], row["decision_session"])])
        for row in variants
    ]
    available_statistics = {
        "mean_net_return": sum(row["net_returns"][primary] for row in variants) / len(variants),
        "mean_excess_return": sum(excess) / len(excess),
        "observation_count": float(len(variants)),
    }
    unknown = set(evaluation["statistics"]) - set(available_statistics)
    if unknown:
        raise StudyRunError(f"unsupported trusted statistics: {sorted(unknown)}")
    statistics = {name: available_statistics[name] for name in evaluation["statistics"]}
    return {
        "metrics": statistics,
        "statistics": statistics,
        "controls": {
            name: sum(row["net_returns"][primary] for row in controls if row["name"] == name)
            / sum(row["name"] == name for row in controls)
            for name in evaluation["controls"]
        },
        "cost_profile_hashes": profile_hashes,
        "jobs": rows,
        "details": callback_result.get("details"),
    }


class StudyRunner:
    def __init__(
        self,
        resolved: ResolvedStudy,
        *,
        work_root: str | Path,
    ):
        self.resolved = resolved
        self.census = _census_snapshot(resolved)
        self.work_root = Path(work_root).resolve()
        if repository_containing(self.work_root) is not None:
            raise ValueError("study output root must be outside the repository")

    def _cache_object(self, obj: CacheObject, kind: str) -> None:
        expected_identity = self.resolved.spec.cache_identity(kind)
        expected = ResearchCache.digest(kind, expected_identity)
        if obj.kind != kind or obj.digest != expected or obj.manifest["identity"] != expected_identity:
            raise StudyRunError(f"{kind} cache identity differs from the study contract")
        validate_study_object(self.resolved, obj)

    def _open_holdout(self, attempt: str, run_directory: Path) -> None:
        holdout = self.resolved.spec.document["evaluation"]["holdout"]
        marker = (self.work_root / holdout["marker"]).resolve()
        if not marker.is_relative_to(self.work_root):
            raise StudyRunError("holdout marker escaped the output root")
        marker.parent.mkdir(parents=True, exist_ok=True)
        payload = canonical_bytes({
            "lease_id": holdout["lease_id"],
            "study_sha256": self.resolved.spec.sha256,
            "attempt_id": attempt,
        }, newline=True)
        try:
            descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        except FileExistsError as exc:
            raise StudyRunError("holdout lease has already been opened") from exc
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

    def run(
        self,
        *,
        attempt: str,
        features: CacheObject,
    ) -> StudyRun:
        self._cache_object(features, "feature")
        phase = self.resolved.spec.document["study"]["phase"]
        cache_root = features.path.parents[3]
        cache = ResearchCache(cache_root)
        output_subdir = self.resolved.spec.document["execution"]["output_subdir"]
        output_root = (self.work_root / output_subdir).resolve()
        if not output_root.is_relative_to(self.work_root):
            raise StudyRunError("study output escaped its private root")
        run_directory = output_root / attempt
        run_directory.mkdir(parents=True, exist_ok=False)
        started_receipt = {
            "attempt_id": attempt,
            "census": self.census.__dict__,
            "feature_sha256": features.digest,
            "phase": phase,
            "study_sha256": self.resolved.spec.sha256,
        }
        started_path = run_directory / "attempt-started.json"
        started_sha = _seal_json(started_receipt, started_path)
        try:
            if phase == "holdout":
                self._open_holdout(attempt, run_directory)

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
            session_rows = features.read_json(
                f"nodes/{self.resolved.spec.document['features'][0]['name']}.json"
            )
            sessions_by_fold = {
                fold["name"]: sorted({
                    row["session"] for row in session_rows
                    if fold["start"] <= row["session"] < fold["end"]
                })
                for fold in self.resolved.spec.document["evaluation"]["folds"]
            }
            jobs = [
                {
                    "kind": arm["kind"],
                    "name": arm["name"],
                    "fold": fold["name"],
                    "decision_session": decision_session,
                    "parameters": {
                        **strategy["parameters"],
                        **arm["parameters"],
                        "_study_job": {
                            "kind": arm["kind"],
                            "name": arm["name"],
                            "fold": dict(fold),
                            "decision_session": decision_session,
                        },
                    },
                    "seed": _seed(
                        execution["seed"], f"{arm['kind']}:{arm['name']}",
                        f"{fold['name']}:{decision_session}",
                    ),
                    "feature_root": materialize_decision_features(
                        self.resolved,
                        features,
                        fold,
                        decision_session,
                        run_directory / "fold-features" / canonical_sha256({
                            "kind": arm["kind"], "name": arm["name"], "fold": fold["name"],
                            "decision_session": decision_session,
                        })[:16],
                    ),
                }
                for arm in arms
                for fold in self.resolved.spec.document["evaluation"]["folds"]
                for decision_session in sessions_by_fold[fold["name"]]
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
                    "decision_session": job["decision_session"],
                    "seed": job["seed"],
                    "prediction": response["payload"],
                }
                for job, response in evaluated
            ]}
            predictions_path = run_directory / "predictions.json"
            predictions_sha = _seal_json(predictions, predictions_path)
            result_path, result_sha, outcome_accessed = None, None, False
            if phase != "pilot":
                capability = _new_label_capability(
                    attempt_id=attempt,
                    predictions_sha256=predictions_sha,
                    census_sha256=self.census.sha256,
                    started_receipt_sha256=started_sha,
                )
                outcomes = _build_label_artifact(
                    cache, self.resolved, run_directory / "outcome-build", capability,
                )
                self._cache_object(outcomes, "label")
                validate_feature_label_alignment(self.resolved, features, outcomes)
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
                        "evaluation": {
                            **self.resolved.spec.as_dict()["evaluation"],
                            "_census_snapshot": self.census.__dict__,
                        },
                        "mode": "evaluation",
                        "memory_mb": execution["memory_mb"],
                    },
                    feature_root=None,
                    label_root=outcomes.data_path,
                    runtime_root=run_directory,
                    timeout=execution["expected_seconds"],
                )
                evaluation_result = _reduce_evaluation(
                    outcome_response["payload"],
                    predictions,
                    self.resolved.spec.as_dict()["evaluation"],
                    self.resolved.spec.as_dict()["costs"],
                )
                evaluation_contract = self.resolved.spec.as_dict()["evaluation"]
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
                "census_snapshot": self.census.__dict__,
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
            return StudyRun(
                run_directory, predictions_path, predictions_sha,
                result_path, result_sha, outcome_accessed,
            )
        except Exception as exc:
            failure = {
                "attempt_id": attempt,
                "error": type(exc).__name__,
                "message": str(exc)[:500],
                "study_sha256": self.resolved.spec.sha256,
            }
            write_text_atomic(
                run_directory / "attempt-failed.json",
                canonical_bytes(failure, newline=True).decode(),
            )
            raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--attempt", required=True)
    args = parser.parse_args(argv)
    spec = StudySpec.from_path(args.spec)
    resolved = spec.resolve(args.base_dir)
    cache = ResearchCache(args.cache_root)
    runner = StudyRunner(resolved, work_root=args.work_root)
    artifacts = build_study_artifacts(
        cache,
        resolved,
        args.work_root / "artifact-build",
    )
    runner.run(
        attempt=args.attempt,
        features=artifacts.features,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
