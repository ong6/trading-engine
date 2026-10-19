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
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from engine.lib.resources import write_text_atomic
from farm.study.costs import calculate
from sim import nyse
from sim.order_types import MARKET_OPEN

from .artifacts import (
    _build_label_artifact,
    _new_label_capability,
    build_study_artifacts,
    label_cache_identity,
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


_ATTEMPT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


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


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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
        raise StudyRunError("trusted evaluation must produce a metrics object")
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


def _expected_fill_instants(
    decision_session: str, inputs: dict, strategy: dict,
) -> tuple[datetime, datetime]:
    if inputs["calendar"]["name"] not in {"XNYS", "NYSE"}:
        raise StudyRunError("trusted fill timing requires the XNYS exchange calendar")
    exchange_zone = ZoneInfo(inputs["timezone"])
    decision = strategy["decision"]
    hour, minute = map(int, decision["time"].split(":"))
    decision_at = datetime.combine(
        date.fromisoformat(decision_session), time(hour, minute),
        ZoneInfo(decision["timezone"]),
    )
    entry_session = decision_at.astimezone(exchange_zone).date()
    entry_at = datetime.combine(entry_session, MARKET_OPEN, exchange_zone)
    if not nyse.is_session(entry_session) or entry_at <= decision_at:
        entry_session = nyse.next_session(entry_session)
        entry_at = datetime.combine(entry_session, MARKET_OPEN, exchange_zone)
    exit_session = entry_session
    for _ in range(strategy["fill_rule"]["horizon_sessions"] - 1):
        exit_session = nyse.next_session(exit_session)
    exit_at = datetime.combine(exit_session, nyse.session_close(exit_session), exchange_zone)
    return entry_at, exit_at


def _aware_instant(value: object, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError as exc:
        raise StudyRunError(f"outcome {field} is not an aware timestamp") from exc
    if result is None or result.tzinfo is None or result.utcoffset() is None:
        raise StudyRunError(f"outcome {field} is not an aware timestamp")
    return result


def _reduce_evaluation(predictions: dict, labels: list[dict], evaluation: dict,
                       costs: dict, inputs: dict, strategy: dict) -> dict:
    primary_key = inputs["primary_key"]
    fill_rule = strategy["fill_rule"]
    capital = strategy["capital"]
    label_map = {}
    label_instants = {}
    for row in labels:
        key = tuple(row[name] for name in primary_key)
        if key in label_map:
            raise StudyRunError("outcomes contain duplicate primary keys")
        expected_entry, expected_exit = _expected_fill_instants(
            row["session"], inputs, strategy,
        )
        entry_at = _aware_instant(row.get("entry_at"), "entry_at")
        exit_at = _aware_instant(row.get("exit_at"), "exit_at")
        if entry_at != expected_entry:
            raise StudyRunError("outcome entry_at is not the first exchange-session open")
        if exit_at != expected_exit:
            raise StudyRunError("outcome exit_at does not match the declared horizon")
        label_map[key] = row
        label_instants[key] = entry_at, exit_at
    profiles = costs["profiles"]
    profile_hashes = {item["name"]: item["sha256"] for item in profiles}
    rows = []
    for job in predictions["jobs"]:
        prediction = job["prediction"]
        if not isinstance(prediction, dict) or set(prediction) != {"positions"} \
                or not isinstance(prediction["positions"], list):
            raise StudyRunError("strategy callback must return only a positions list")
        positions = {}
        for position in prediction["positions"]:
            fields = {*primary_key, "weight"}
            if not isinstance(position, dict) or set(position) != fields:
                raise StudyRunError("position schema differs")
            key = tuple(position[name] for name in primary_key)
            weight = position["weight"]
            if (key in positions or isinstance(weight, bool)
                    or not isinstance(weight, (int, float)) or not math.isfinite(float(weight))):
                raise StudyRunError("position key or weight differs")
            if position["session"] != job["decision_session"]:
                raise StudyRunError("position session differs from its decision job")
            positions[key] = float(weight)
        exposure = sum(abs(weight) for weight in positions.values())
        if exposure > 1 + 1e-12:
            raise StudyRunError("position gross exposure exceeds one")
        missing = [key for key in positions if key not in label_map]
        if missing and evaluation["missing_data_policy"] == "refuse":
            raise StudyRunError("missing-data policy refused a position without prices")
        if missing and evaluation["missing_data_policy"] == "drop":
            continue
        gross = 0.0
        for key, weight in positions.items():
            label = label_map[key]
            entry = label[fill_rule["entry_price_field"]]
            exit_ = label[fill_rule["exit_price_field"]]
            if (isinstance(entry, bool) or isinstance(exit_, bool)
                    or not isinstance(entry, (int, float)) or not isinstance(exit_, (int, float))
                    or not math.isfinite(float(entry)) or not math.isfinite(float(exit_))
                    or entry <= 0 or exit_ <= 0):
                raise StudyRunError("fill prices must be finite and positive")
            gross += weight * (float(exit_) / float(entry) - 1)
        cost_returns = {}
        for profile in profiles:
            total = 0.0
            for key, weight in positions.items():
                label = label_map[key]
                entry = float(label[fill_rule["entry_price_field"]])
                exit_ = float(label[fill_rule["exit_price_field"]])
                notional = capital * abs(weight)
                if notional:
                    entry_side, exit_side = (("buy", "sell") if weight > 0 else ("sell", "buy"))
                    entry_at, exit_at = label_instants[key]
                    exchange_zone = ZoneInfo(inputs["timezone"])
                    total += calculate(
                        profile["name"], side=entry_side, notional=notional,
                        fill_price=entry, mdv60=label.get("mdv60"),
                        session_date=entry_at.astimezone(exchange_zone).date(),
                        fill_kind="next_open",
                    ).total
                    total += calculate(
                        profile["name"], side=exit_side, notional=notional,
                        fill_price=exit_, mdv60=label.get("mdv60"),
                        session_date=exit_at.astimezone(exchange_zone).date(),
                        fill_kind="moc",
                    ).total
            cost_returns[profile["name"]] = total / capital
        net = {name: gross - cost for name, cost in cost_returns.items()}
        rows.append({
            "kind": job["kind"], "name": job["name"], "fold": job["fold"],
            "decision_session": job["decision_session"], "gross_return": gross,
            "gross_exposure": exposure, "cost_returns": cost_returns, "net_returns": net,
        })
    primary = profiles[0]["name"]
    controls = [row for row in rows if row["kind"] == "control"]
    if not any(row["kind"] == "variant" for row in rows) or not controls:
        raise StudyRunError("trusted reduction needs variant and control observations")
    control_by_key = {}
    for row in controls:
        key = row["fold"], row["decision_session"]
        control_by_key.setdefault(key, []).append(row["net_returns"][primary])
    variant_results = []
    for declaration in evaluation["variants"]:
        variants = [
            row for row in rows
            if row["kind"] == "variant" and row["name"] == declaration["name"]
        ]
        if not variants:
            raise StudyRunError(f"variant has no observations: {declaration['name']}")
        decision_keys = {row["decision_session"] for row in variants}
        if len(decision_keys) != len(variants):
            raise StudyRunError(
                f"variant has duplicate decision keys: {declaration['name']}"
            )
        excess = [
            row["net_returns"][primary]
            - sum(control_by_key[(row["fold"], row["decision_session"])])
            / len(control_by_key[(row["fold"], row["decision_session"])])
            for row in variants
        ]
        available_statistics = {
            "mean_net_return": (
                sum(row["net_returns"][primary] for row in variants) / len(variants)
            ),
            "mean_excess_return": sum(excess) / len(excess),
            "observation_count": float(len(decision_keys)),
        }
        unknown = set(evaluation["statistics"]) - set(available_statistics)
        if unknown:
            raise StudyRunError(f"unsupported trusted statistics: {sorted(unknown)}")
        statistics = {
            name: available_statistics[name] for name in evaluation["statistics"]
        }
        variant_results.append({
            "name": declaration["name"],
            "metrics": statistics,
            "statistics": statistics,
        })
    return {
        "variants": variant_results,
        "controls": {
            name: sum(row["net_returns"][primary] for row in controls if row["name"] == name)
            / sum(row["name"] == name for row in controls)
            for name in evaluation["controls"]
        },
        "cost_profile_hashes": profile_hashes,
        "jobs": rows,
        "details": {"labels": labels},
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

    def _cache_object(self, obj: CacheObject, kind: str, *, capability=None) -> None:
        expected_identity = (
            label_cache_identity(self.resolved, capability)
            if kind == "label" and capability is not None
            else self.resolved.spec.cache_identity(kind)
        )
        expected = ResearchCache.digest(kind, expected_identity)
        if obj.kind != kind or obj.digest != expected or obj.manifest["identity"] != expected_identity:
            raise StudyRunError(f"{kind} cache identity differs from the study contract")
        validate_study_object(
            self.resolved, obj, cache_identity=expected_identity, capability=capability,
        )

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
        _fsync_directory(marker.parent)

    def run(
        self,
        *,
        attempt: str,
        features: CacheObject,
    ) -> StudyRun:
        if _ATTEMPT_ID.fullmatch(attempt) is None or attempt in {".", ".."}:
            raise StudyRunError("attempt id must be a safe 1-64 character token")
        self._cache_object(features, "feature")
        phase = self.resolved.spec.document["study"]["phase"]
        cache_root = features.path.parents[3]
        cache = ResearchCache(cache_root)
        output_subdir = self.resolved.spec.document["execution"]["output_subdir"]
        output_root = (self.work_root / output_subdir).resolve()
        if not output_root.is_relative_to(self.work_root):
            raise StudyRunError("study output escaped its private root")
        run_directory = output_root / attempt
        if not run_directory.resolve().is_relative_to(output_root):
            raise StudyRunError("attempt path escaped the study output root")
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
        _fsync_directory(run_directory)
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
                        "callback": {
                            **strategy["callback"], "runtime_identity": execution,
                        },
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
            _fsync_directory(run_directory)
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
                self._cache_object(outcomes, "label", capability=capability)
                validate_feature_label_alignment(self.resolved, features, outcomes)
                evaluation_result = _reduce_evaluation(
                    predictions,
                    outcomes.read_json("labels.json"),
                    self.resolved.spec.as_dict()["evaluation"],
                    self.resolved.spec.as_dict()["costs"],
                    self.resolved.spec.as_dict()["inputs"],
                    self.resolved.spec.as_dict()["strategy"],
                )
                evaluation_contract = self.resolved.spec.as_dict()["evaluation"]
                variant_verdicts = [{
                    "name": variant["name"],
                    "verdict": _verdict(variant, evaluation_contract),
                } for variant in evaluation_result["variants"]]
                result = {
                    "evaluation": evaluation_result,
                    "variant_verdicts": variant_verdicts,
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
