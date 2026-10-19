"""Exact-schema, content-resolved declaration for one research study."""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .canonical import (
    canonical_bytes,
    canonical_sha256,
    distribution_sha256,
    file_sha256,
    python_runtime_sha256,
)

SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"[0-9a-f]{64}")
PHASES = frozenset({"pilot", "development", "holdout"})
SURVIVOR_STATES = frozenset({"point_in_time", "current_listings_only", "unknown"})
COST_STATES = frozenset({"included", "zero", "inapplicable", "unverified", "excluded"})
COST_COMPONENTS = (
    "execution",
    "commission",
    "borrow_funding",
    "fx",
    "tax",
    "data",
)


class ContractError(ValueError):
    """A study declaration is incomplete, ambiguous, or differs from its evidence."""


def _mapping(value: object, path: str, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{path} must be an object")
    result = dict(value)
    expected, observed = set(fields), set(result)
    if observed != expected:
        missing, unknown = sorted(expected - observed), sorted(observed - expected)
        details = []
        if missing:
            details.append(f"missing {missing}")
        if unknown:
            details.append(f"unknown {unknown}")
        raise ContractError(f"{path} has {' and '.join(details)}")
    return result


def _list(value: object, path: str, *, nonempty: bool = True) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        suffix = "non-empty list" if nonempty else "list"
        raise ContractError(f"{path} must be a {suffix}")
    return value


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{path} must be a non-empty string")
    return value


def _sha(value: object, path: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ContractError(f"{path} must be a lowercase SHA-256")
    return value


def _integer(value: object, path: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ContractError(f"{path} must be an integer >= {minimum}")
    return value


def _number(value: object, path: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{path} must be a number")
    result = float(value)
    if not (-float("inf") < result < float("inf")) or (positive and result <= 0):
        requirement = "finite and positive" if positive else "finite"
        raise ContractError(f"{path} must be {requirement}")
    return result


def _json_mapping(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{path} must be an object")
    try:
        encoded = canonical_bytes(value)
        result = json.loads(encoded)
    except ValueError as exc:
        raise ContractError(f"{path} must contain finite JSON values") from exc
    return result


def _unique_strings(value: object, path: str, *, nonempty: bool = True) -> tuple[str, ...]:
    rows = _list(value, path, nonempty=nonempty)
    result = tuple(_string(item, f"{path}[{index}]") for index, item in enumerate(rows))
    if len(result) != len(set(result)):
        raise ContractError(f"{path} must not contain duplicates")
    return result


def _relative_path(value: object, path: str) -> str:
    raw = _string(value, path)
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts or candidate == Path("."):
        raise ContractError(f"{path} must be a relative path without '..'")
    return candidate.as_posix()


def _file_ref(value: object, path: str) -> dict[str, str]:
    row = _mapping(value, path, ("path", "sha256", "format"))
    format_ = _string(row["format"], f"{path}.format")
    if format_ not in {"rows_json", "opaque"}:
        raise ContractError(f"{path}.format must be rows_json or opaque")
    return {
        "path": _relative_path(row["path"], f"{path}.path"),
        "sha256": _sha(row["sha256"], f"{path}.sha256"),
        "format": format_,
    }


def _evidence_ref(value: object, path: str) -> dict[str, str]:
    row = _mapping(value, path, ("path", "sha256"))
    return {
        "path": _relative_path(row["path"], f"{path}.path"),
        "sha256": _sha(row["sha256"], f"{path}.sha256"),
    }


def _module_ref(value: object, path: str) -> dict[str, str]:
    row = _mapping(value, path, ("module", "source", "kind", "sha256"))
    kind = _string(row["kind"], f"{path}.kind")
    if kind not in {"module", "package", "runtime"}:
        raise ContractError(f"{path}.kind must be module, package, or runtime")
    return {
        "module": _string(row["module"], f"{path}.module"),
        "source": _relative_path(row["source"], f"{path}.source"),
        "kind": kind,
        "sha256": _sha(row["sha256"], f"{path}.sha256"),
    }


def _callback(value: object, path: str) -> dict[str, Any]:
    row = _mapping(
        value, path, ("module", "function", "source", "kind", "sha256", "dependencies")
    )
    dependencies = [
        _module_ref(item, f"{path}.dependencies[{index}]")
        for index, item in enumerate(_list(row["dependencies"], f"{path}.dependencies", nonempty=False))
    ]
    modules = [item["module"] for item in dependencies]
    if len(modules) != len(set(modules)):
        raise ContractError(f"{path}.dependencies must not contain duplicate modules")
    primary = _module_ref({key: row[key] for key in ("module", "source", "kind", "sha256")}, path)
    parents = [".".join(primary["module"].split(".")[:index])
               for index in range(1, len(primary["module"].split(".")))]
    declared_packages = {item["module"] for item in dependencies if item["kind"] == "package"}
    if any(parent not in declared_packages for parent in parents):
        raise ContractError(f"{path} must declare every parent package initializer")
    return {
        **primary,
        "function": _string(row["function"], f"{path}.function"),
        "dependencies": dependencies,
    }


def _column(value: object, path: str) -> dict[str, Any]:
    row = _mapping(value, path, ("name", "dtype", "nullable"))
    if type(row["nullable"]) is not bool:
        raise ContractError(f"{path}.nullable must be boolean")
    return {
        "name": _string(row["name"], f"{path}.name"),
        "dtype": _string(row["dtype"], f"{path}.dtype"),
        "nullable": row["nullable"],
    }


def _columns(value: object, path: str) -> list[dict[str, Any]]:
    result = [_column(item, f"{path}[{index}]") for index, item in enumerate(_list(value, path))]
    names = [item["name"] for item in result]
    if len(names) != len(set(names)):
        raise ContractError(f"{path} has duplicate column names")
    return result


def _study(value: object) -> dict[str, Any]:
    path = "study"
    row = _mapping(value, path, ("id", "version", "hypothesis", "phase", "owner", "prior", "parents"))
    phase = _string(row["phase"], f"{path}.phase")
    if phase not in PHASES:
        raise ContractError(f"{path}.phase must be one of {sorted(PHASES)}")
    parents = _list(row["parents"], f"{path}.parents", nonempty=False)
    parent_hashes = [_sha(item, f"{path}.parents[{index}]") for index, item in enumerate(parents)]
    if len(parent_hashes) != len(set(parent_hashes)):
        raise ContractError(f"{path}.parents must not contain duplicates")
    return {
        "id": _string(row["id"], f"{path}.id"),
        "version": _string(row["version"], f"{path}.version"),
        "hypothesis": _string(row["hypothesis"], f"{path}.hypothesis"),
        "phase": phase,
        "owner": _string(row["owner"], f"{path}.owner"),
        "prior": _unique_strings(row["prior"], f"{path}.prior", nonempty=False),
        "parents": parent_hashes,
    }


def _inputs(value: object) -> dict[str, Any]:
    path = "inputs"
    row = _mapping(value, path, (
        "generation_sha256", "feature_parts", "outcome_parts", "schema", "availability",
        "primary_key", "price_basis", "timezone", "calendar", "membership", "coverage",
        "survivor_status", "quality",
    ))
    feature_parts = [
        _file_ref(item, f"{path}.feature_parts[{index}]")
        for index, item in enumerate(_list(row["feature_parts"], f"{path}.feature_parts"))
    ]
    outcome_parts = [
        _file_ref(item, f"{path}.outcome_parts[{index}]")
        for index, item in enumerate(_list(
            row["outcome_parts"], f"{path}.outcome_parts", nonempty=False,
        ))
    ]
    part_paths = [item["path"] for item in (*feature_parts, *outcome_parts)]
    if len(part_paths) != len(set(part_paths)):
        raise ContractError(f"{path} feature/outcome parts have duplicate paths")
    if any(item["format"] != "rows_json" for item in feature_parts):
        raise ContractError("feature_parts must use the temporal rows_json adapter")
    availability = []
    for index, item in enumerate(_list(row["availability"], f"{path}.availability")):
        item_path = f"{path}.availability[{index}]"
        field = _mapping(item, item_path, ("field", "known_at"))
        availability.append({
            "field": _string(field["field"], f"{item_path}.field"),
            "known_at": _string(field["known_at"], f"{item_path}.known_at"),
        })
    if len(availability) != len({item["field"] for item in availability}):
        raise ContractError(f"{path}.availability has duplicate fields")
    timezone_name = _string(row["timezone"], f"{path}.timezone")
    try:
        ZoneInfo(timezone_name)
    except Exception as exc:
        raise ContractError(f"{path}.timezone is unknown") from exc
    calendar = _mapping(row["calendar"], f"{path}.calendar", ("name", "version"))
    membership = _mapping(
        row["membership"], f"{path}.membership", ("point_in_time", "evidence")
    )
    if type(membership["point_in_time"]) is not bool:
        raise ContractError(f"{path}.membership.point_in_time must be boolean")
    coverage = _mapping(row["coverage"], f"{path}.coverage", ("minimum", "unit"))
    minimum = _number(coverage["minimum"], f"{path}.coverage.minimum")
    if not 0 <= minimum <= 1:
        raise ContractError(f"{path}.coverage.minimum must be between 0 and 1")
    quality = _mapping(row["quality"], f"{path}.quality", ("version", "policy", "evidence"))
    survivor = _string(row["survivor_status"], f"{path}.survivor_status")
    if survivor not in SURVIVOR_STATES:
        raise ContractError(f"{path}.survivor_status must be one of {sorted(SURVIVOR_STATES)}")
    schema = _columns(row["schema"], f"{path}.schema")
    primary_key = _unique_strings(row["primary_key"], f"{path}.primary_key")
    if any(key not in {column["name"] for column in schema} for key in primary_key):
        raise ContractError(f"{path}.primary_key must name declared input columns")
    return {
        "generation_sha256": _sha(row["generation_sha256"], f"{path}.generation_sha256"),
        "feature_parts": feature_parts,
        "outcome_parts": outcome_parts,
        "schema": schema,
        "availability": availability,
        "primary_key": primary_key,
        "price_basis": _string(row["price_basis"], f"{path}.price_basis"),
        "timezone": timezone_name,
        "calendar": {
            "name": _string(calendar["name"], f"{path}.calendar.name"),
            "version": _string(calendar["version"], f"{path}.calendar.version"),
        },
        "membership": {
            "point_in_time": membership["point_in_time"],
            "evidence": _evidence_ref(membership["evidence"], f"{path}.membership.evidence"),
        },
        "coverage": {
            "minimum": minimum,
            "unit": _string(coverage["unit"], f"{path}.coverage.unit"),
        },
        "survivor_status": survivor,
        "quality": {
            "version": _string(quality["version"], f"{path}.quality.version"),
            "policy": _string(quality["policy"], f"{path}.quality.policy"),
            "evidence": _evidence_ref(quality["evidence"], f"{path}.quality.evidence"),
        },
    }


def _features(value: object) -> list[dict[str, Any]]:
    rows, names = [], set()
    for index, item in enumerate(_list(value, "features")):
        path = f"features[{index}]"
        row = _mapping(item, path, (
            "name", "callback", "dependencies", "availability", "output_schema", "parameters",
        ))
        name = _string(row["name"], f"{path}.name")
        if name in names:
            raise ContractError("features has duplicate node names")
        dependencies = _unique_strings(row["dependencies"], f"{path}.dependencies", nonempty=False)
        if any(dependency not in names for dependency in dependencies):
            raise ContractError(f"{path}.dependencies must name earlier feature nodes")
        names.add(name)
        output_schema = _columns(row["output_schema"], f"{path}.output_schema")
        availability = _string(row["availability"], f"{path}.availability")
        schema_by_name = {column["name"]: column for column in output_schema}
        if (availability not in schema_by_name
                or schema_by_name[availability]["dtype"] not in {"date", "datetime"}):
            raise ContractError(f"{path}.availability must name a date/datetime output column")
        rows.append({
            "name": name,
            "callback": _callback(row["callback"], f"{path}.callback"),
            "dependencies": dependencies,
            "availability": availability,
            "output_schema": output_schema,
            "parameters": _json_mapping(row["parameters"], f"{path}.parameters"),
        })
    return rows


def _outcomes(value: object) -> dict[str, Any]:
    path = "outcomes"
    row = _mapping(
        value, path, ("callback", "parameters", "horizons", "availability", "output_schema")
    )
    horizons = [_integer(item, f"{path}.horizons[{index}]", minimum=1)
                for index, item in enumerate(_list(row["horizons"], f"{path}.horizons"))]
    if horizons != sorted(set(horizons)):
        raise ContractError(f"{path}.horizons must be sorted and unique")
    output_schema = _columns(row["output_schema"], f"{path}.output_schema")
    availability = _string(row["availability"], f"{path}.availability")
    schema_by_name = {column["name"]: column for column in output_schema}
    if (availability not in schema_by_name
            or schema_by_name[availability]["dtype"] not in {"date", "datetime"}):
        raise ContractError(f"{path}.availability must name a date/datetime output column")
    return {
        "callback": _callback(row["callback"], f"{path}.callback"),
        "parameters": _json_mapping(row["parameters"], f"{path}.parameters"),
        "horizons": horizons,
        "availability": availability,
        "output_schema": output_schema,
    }


def _strategy(value: object) -> dict[str, Any]:
    path = "strategy"
    row = _mapping(value, path, (
        "callback", "parameters", "decision_rule", "fill_rule", "exit_rule", "universe_rule",
        "liquidity_rule", "capital",
    ))
    return {
        "callback": _callback(row["callback"], f"{path}.callback"),
        "parameters": _json_mapping(row["parameters"], f"{path}.parameters"),
        "decision_rule": _string(row["decision_rule"], f"{path}.decision_rule"),
        "fill_rule": _string(row["fill_rule"], f"{path}.fill_rule"),
        "exit_rule": _string(row["exit_rule"], f"{path}.exit_rule"),
        "universe_rule": _string(row["universe_rule"], f"{path}.universe_rule"),
        "liquidity_rule": _string(row["liquidity_rule"], f"{path}.liquidity_rule"),
        "capital": _number(row["capital"], f"{path}.capital", positive=True),
    }


def _evaluation(value: object) -> dict[str, Any]:
    path = "evaluation"
    row = _mapping(value, path, (
        "callback", "variants", "controls", "folds", "benchmark_mode", "statistics",
        "dsr_census", "rules", "holdout", "missing_data_policy",
    ))
    variants = []
    for index, item in enumerate(_list(row["variants"], f"{path}.variants")):
        item_path = f"{path}.variants[{index}]"
        variant = _mapping(item, item_path, ("name", "parameters"))
        variants.append({
            "name": _string(variant["name"], f"{item_path}.name"),
            "parameters": _json_mapping(variant["parameters"], f"{item_path}.parameters"),
        })
    if len(variants) != len({item["name"] for item in variants}):
        raise ContractError(f"{path}.variants has duplicate names")
    folds = []
    for index, item in enumerate(_list(row["folds"], f"{path}.folds")):
        item_path = f"{path}.folds[{index}]"
        fold = _mapping(item, item_path, ("name", "start", "end"))
        try:
            start, end = date.fromisoformat(fold["start"]), date.fromisoformat(fold["end"])
        except (TypeError, ValueError) as exc:
            raise ContractError(f"{item_path} dates must use YYYY-MM-DD") from exc
        if start >= end:
            raise ContractError(f"{item_path}.start must precede end")
        folds.append({
            "name": _string(fold["name"], f"{item_path}.name"),
            "start": start.isoformat(),
            "end": end.isoformat(),
        })
    if len(folds) != len({item["name"] for item in folds}):
        raise ContractError(f"{path}.folds has duplicate names")
    census = _mapping(row["dsr_census"], f"{path}.dsr_census", (
        "path", "sha256", "selection_n",
    ))
    rules = _mapping(row["rules"], f"{path}.rules", ("pass", "admit", "kill"))
    normalized_rules = {}
    for name in ("pass", "admit", "kill"):
        item_path = f"{path}.rules.{name}"
        item = _mapping(rules[name], item_path, ("metric", "operator", "threshold"))
        operator = _string(item["operator"], f"{item_path}.operator")
        if operator not in {">", ">=", "<", "<=", "==", "!="}:
            raise ContractError(f"{item_path}.operator is unsupported")
        normalized_rules[name] = {
            "metric": _string(item["metric"], f"{item_path}.metric"),
            "operator": operator,
            "threshold": _number(item["threshold"], f"{item_path}.threshold"),
        }
    holdout = _mapping(row["holdout"], f"{path}.holdout", ("lease_id", "marker"))
    missing_policy = _string(row["missing_data_policy"], f"{path}.missing_data_policy")
    if missing_policy not in {"refuse", "drop"}:
        raise ContractError(f"{path}.missing_data_policy must be refuse or drop")
    return {
        "callback": _callback(row["callback"], f"{path}.callback"),
        "variants": variants,
        "controls": _unique_strings(row["controls"], f"{path}.controls"),
        "folds": folds,
        "benchmark_mode": _string(row["benchmark_mode"], f"{path}.benchmark_mode"),
        "statistics": _unique_strings(row["statistics"], f"{path}.statistics"),
        "dsr_census": {
            "path": _relative_path(census["path"], f"{path}.dsr_census.path"),
            "sha256": _sha(census["sha256"], f"{path}.dsr_census.sha256"),
            "selection_n": _integer(census["selection_n"], f"{path}.dsr_census.selection_n", minimum=1),
        },
        "rules": normalized_rules,
        "holdout": {
            "lease_id": _string(holdout["lease_id"], f"{path}.holdout.lease_id"),
            "marker": _relative_path(holdout["marker"], f"{path}.holdout.marker"),
        },
        "missing_data_policy": missing_policy,
    }


def _costs(value: object) -> dict[str, Any]:
    path = "costs"
    row = _mapping(value, path, ("profiles", "scope"))
    profiles = []
    for index, item in enumerate(_list(row["profiles"], f"{path}.profiles")):
        item_path = f"{path}.profiles[{index}]"
        profile = _mapping(item, item_path, ("name", "sha256", "rate_bps"))
        rate = _number(profile["rate_bps"], f"{item_path}.rate_bps")
        if rate < 0:
            raise ContractError(f"{item_path}.rate_bps cannot be negative")
        profiles.append({
            "name": _string(profile["name"], f"{item_path}.name"),
            "sha256": _sha(profile["sha256"], f"{item_path}.sha256"),
            "rate_bps": rate,
        })
    if len(profiles) != len({item["name"] for item in profiles}):
        raise ContractError(f"{path}.profiles has duplicate names")
    scope = _mapping(row["scope"], f"{path}.scope", COST_COMPONENTS)
    normalized_scope = {}
    for component in COST_COMPONENTS:
        item_path = f"{path}.scope.{component}"
        item = _mapping(scope[component], item_path, ("status", "reason", "sha256"))
        status = _string(item["status"], f"{item_path}.status")
        if status not in COST_STATES:
            raise ContractError(f"{item_path}.status must be one of {sorted(COST_STATES)}")
        normalized_scope[component] = {
            "status": status,
            "reason": _string(item["reason"], f"{item_path}.reason"),
            "sha256": _sha(item["sha256"], f"{item_path}.sha256"),
        }
    return {"profiles": profiles, "scope": normalized_scope}


def _execution(value: object) -> dict[str, Any]:
    path = "execution"
    row = _mapping(value, path, (
        "seed", "workers", "memory_mb", "expected_seconds", "output_subdir", "python_sha256",
        "python_runtime_sha256",
    ))
    return {
        "seed": _integer(row["seed"], f"{path}.seed"),
        "workers": _integer(row["workers"], f"{path}.workers", minimum=1),
        "memory_mb": _integer(row["memory_mb"], f"{path}.memory_mb", minimum=1),
        "expected_seconds": _number(
            row["expected_seconds"], f"{path}.expected_seconds", positive=True
        ),
        "output_subdir": _relative_path(row["output_subdir"], f"{path}.output_subdir"),
        "python_sha256": _sha(row["python_sha256"], f"{path}.python_sha256"),
        "python_runtime_sha256": _sha(
            row["python_runtime_sha256"], f"{path}.python_runtime_sha256"
        ),
    }


def _module_path(base: Path, reference: Mapping[str, Any]) -> Path:
    if reference["kind"] == "runtime":
        if distribution_sha256(reference["source"]) != reference["sha256"]:
            raise ContractError(f"runtime distribution identity differs: {reference['source']}")
        distribution = importlib.metadata.distribution(reference["source"])
        candidates = [Path(distribution.locate_file(""))]
    else:
        candidates = [(base / reference["source"]).resolve()]
    paths = [path.resolve() for path in candidates if path.exists()]
    if len(paths) != 1 or (reference["kind"] != "runtime" and not paths[0].is_file()) \
            or (reference["kind"] != "runtime" and not paths[0].is_relative_to(base)):
        raise ContractError(f"callback source cannot be resolved exactly: {reference['module']}")
    return paths[0]


def _function_defined(path: Path, function: str) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        raise ContractError(f"callback module source cannot be parsed: {path.name}") from exc
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function
        for node in tree.body
    )


@dataclass(frozen=True)
class ResolvedStudy:
    spec: "StudySpec"
    base_dir: Path
    evidence_paths: Mapping[str, Path]
    callback_paths: Mapping[str, Path]


@dataclass(frozen=True)
class StudySpec:
    """Validated, detached declaration whose JSON bytes are its identity."""

    document: Mapping[str, Any]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StudySpec":
        root = _mapping(value, "contract", (
            "schema_version", "study", "inputs", "features", "outcomes", "strategy",
            "evaluation", "costs", "execution",
        ))
        if root["schema_version"] != SCHEMA_VERSION:
            raise ContractError(f"schema_version must be {SCHEMA_VERSION}")
        normalized = {
            "schema_version": SCHEMA_VERSION,
            "study": _study(root["study"]),
            "inputs": _inputs(root["inputs"]),
            "features": _features(root["features"]),
            "outcomes": _outcomes(root["outcomes"]),
            "strategy": _strategy(root["strategy"]),
            "evaluation": _evaluation(root["evaluation"]),
            "costs": _costs(root["costs"]),
            "execution": _execution(root["execution"]),
        }
        keys = set(normalized["inputs"]["primary_key"])
        for index, node in enumerate(normalized["features"]):
            if not keys <= {column["name"] for column in node["output_schema"]}:
                raise ContractError(f"features[{index}].output_schema must include every primary key")
        if not keys <= {column["name"] for column in normalized["outcomes"]["output_schema"]}:
            raise ContractError("outcomes.output_schema must include every primary key")
        detached = json.loads(canonical_bytes(normalized))
        return cls(detached)

    @classmethod
    def from_path(cls, path: str | Path) -> "StudySpec":
        source = Path(path)
        try:
            value = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(f"cannot read study contract: {source}") from exc
        if not isinstance(value, dict):
            raise ContractError("study contract root must be an object")
        return cls.from_dict(value)

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_bytes(self.document, newline=True)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self.document)).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return json.loads(canonical_bytes(self.document))

    @property
    def study_identity_sha256(self) -> str:
        return self.sha256

    def resolve(self, base_dir: str | Path) -> ResolvedStudy:
        base = Path(base_dir).resolve()
        if file_sha256(Path(sys.executable).resolve()) != self.document["execution"]["python_sha256"]:
            raise ContractError("declared Python interpreter identity differs")
        if python_runtime_sha256() != self.document["execution"]["python_runtime_sha256"]:
            raise ContractError("declared Python runtime closure differs")
        evidence: dict[str, Path] = {}
        refs = [
            *self.document["inputs"]["feature_parts"],
            *self.document["inputs"]["outcome_parts"],
        ]
        refs.extend((
            self.document["inputs"]["membership"]["evidence"],
            self.document["inputs"]["quality"]["evidence"],
            self.document["evaluation"]["dsr_census"],
        ))
        for reference in refs:
            relative = reference["path"]
            path = (base / relative).resolve()
            if not path.is_relative_to(base) or not path.is_file():
                raise ContractError(f"evidence path is unavailable: {relative}")
            observed = file_sha256(path)
            if observed != reference["sha256"]:
                raise ContractError(f"evidence hash differs: {relative}")
            evidence[relative] = path
        callbacks = [node["callback"] for node in self.document["features"]]
        callbacks.extend((
            self.document["strategy"]["callback"],
            self.document["outcomes"]["callback"],
            self.document["evaluation"]["callback"],
        ))
        resolved_callbacks: dict[str, Path] = {}
        for callback in callbacks:
            references = [{key: callback[key] for key in ("module", "source", "kind", "sha256")},
                          *callback["dependencies"]]
            for reference in references:
                module, expected = reference["module"], reference["sha256"]
                path = _module_path(base, reference)
                observed = (distribution_sha256(reference["source"])
                            if reference["kind"] == "runtime" else file_sha256(path))
                if observed != expected:
                    raise ContractError(f"callback module hash differs: {module}")
                previous = resolved_callbacks.setdefault(module, path)
                if previous != path:
                    raise ContractError(f"callback module resolved inconsistently: {module}")
            callback_path = resolved_callbacks[callback["module"]]
            if not _function_defined(callback_path, callback["function"]):
                raise ContractError(
                    f"callback function is not defined at module scope: "
                    f"{callback['module']}:{callback['function']}"
                )
        return ResolvedStudy(
            self,
            base,
            MappingProxyType(evidence),
            MappingProxyType(resolved_callbacks),
        )

    def to_markdown(self) -> str:
        document, study = self.document, self.document["study"]
        lines = [
            f"# Study {study['id']} {study['version']}",
            "",
            f"Contract SHA-256: `{self.sha256}`",
            "",
            "## Study",
            "",
            f"- Phase: {study['phase']}",
            f"- Owner: {study['owner']}",
            f"- Hypothesis: {study['hypothesis']}",
            "",
            "## Inputs",
            "",
            f"- Generation: `{document['inputs']['generation_sha256']}`",
            f"- Calendar: {document['inputs']['calendar']['name']} "
            f"{document['inputs']['calendar']['version']}",
            f"- Survivor status: {document['inputs']['survivor_status']}",
            "",
            "## Recipes",
            "",
        ]
        lines.extend(f"- Feature: {node['name']} ({node['callback']['module']})"
                     for node in document["features"])
        lines.extend((
            f"- Strategy: {document['strategy']['callback']['module']}",
            f"- Outcome: {document['outcomes']['callback']['module']}",
            "",
            "## Evaluation",
            "",
            f"- Variants: {', '.join(item['name'] for item in document['evaluation']['variants'])}",
            f"- Controls: {', '.join(document['evaluation']['controls'])}",
            f"- DSR census N: {document['evaluation']['dsr_census']['selection_n']}",
            "",
            "This Markdown is derived from the canonical JSON contract.",
            "",
        ))
        return "\n".join(lines)

    def cache_identity(self, kind: str) -> dict[str, Any]:
        if kind not in {"panel", "universe", "feature", "label"}:
            raise ContractError(f"unknown cache object kind: {kind}")
        identity: dict[str, Any] = {
            "kind": kind,
            "inputs": self.document["inputs"],
            "universe_rule": self.document["strategy"]["universe_rule"],
            "liquidity_rule": self.document["strategy"]["liquidity_rule"],
        }
        if kind == "universe":
            identity["recipe"] = self.document["strategy"]["universe_rule"]
        elif kind == "feature":
            identity["recipe"] = self.document["features"]
        elif kind == "label":
            identity["recipe"] = self.document["outcomes"]
        else:
            identity["recipe"] = "normalized-panel-v1"
        identity["identity_sha256"] = canonical_sha256(identity)
        return identity
