"""Executable StudySpec recipes and semantic cache validation."""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from engine.lib.resources import write_text_atomic

from .cache import CacheObject, ResearchCache, repository_containing
from .canonical import canonical_bytes, canonical_sha256, file_sha256
from .sandbox import build_callback_package, prepare_sandbox_runtime, run_sandboxed
from .spec import ResolvedStudy


class ArtifactValidationError(ValueError):
    pass


@dataclass(frozen=True)
class StudyCacheArtifacts:
    features: CacheObject


_LABEL_CAPABILITY_SECRET = object()


@dataclass(frozen=True)
class _LabelBuildCapability:
    secret: object
    attempt_id: str
    predictions_sha256: str
    census_sha256: str
    started_receipt_sha256: str


def _new_label_capability(
    *, attempt_id: str, predictions_sha256: str, census_sha256: str,
    started_receipt_sha256: str,
) -> _LabelBuildCapability:
    return _LabelBuildCapability(
        _LABEL_CAPABILITY_SECRET, attempt_id, predictions_sha256,
        census_sha256, started_receipt_sha256,
    )


def _value_valid(value: object, dtype: str) -> bool:
    if dtype == "float64":
        return (not isinstance(value, bool) and isinstance(value, (int, float))
                and math.isfinite(float(value)))
    if dtype == "int64":
        return type(value) is int
    if dtype == "string":
        return isinstance(value, str)
    if dtype == "bool":
        return type(value) is bool
    if dtype == "date":
        try:
            return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
        except ValueError:
            return False
    if dtype == "datetime":
        try:
            parsed = datetime.fromisoformat(value) if isinstance(value, str) else None
            return parsed is not None and parsed.tzinfo is not None
        except ValueError:
            return False
    raise ArtifactValidationError(f"unsupported declared dtype: {dtype}")


def validate_rows(
    value: object,
    schema: Sequence[Mapping[str, Any]],
    *,
    availability: str | None = None,
    allow_input_availability: bool = False,
    primary_key: Sequence[str] = (),
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ArtifactValidationError("recipe must return a non-empty list of rows")
    columns = [item["name"] for item in schema]
    expected = set(columns) | ({"_availability"} if allow_input_availability else set())
    rows = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict) or set(raw) != expected:
            raise ArtifactValidationError(f"row {index} columns differ from the declaration")
        row = dict(raw)
        for declaration in schema:
            item = row[declaration["name"]]
            if item is None and declaration["nullable"]:
                continue
            if item is None or not _value_valid(item, declaration["dtype"]):
                raise ArtifactValidationError(
                    f"row {index} column {declaration['name']} violates {declaration['dtype']}"
                )
        if availability is not None and row.get(availability) is None:
            raise ArtifactValidationError(f"row {index} lacks declared availability")
        rows.append(row)
    if primary_key:
        keys = [tuple(row[name] for name in primary_key) for row in rows]
        if len(keys) != len(set(keys)):
            raise ArtifactValidationError("recipe emitted duplicate primary keys")
    return rows


def _evidence(resolved: ResolvedStudy) -> dict[str, Any]:
    inputs = resolved.spec.document["inputs"]
    membership_ref = inputs["membership"]["evidence"]
    quality_ref = inputs["quality"]["evidence"]
    for reference in (
        *inputs["feature_parts"], *inputs["outcome_parts"], membership_ref, quality_ref,
    ):
        path = resolved.evidence_paths[reference["path"]]
        if not path.is_file() or file_sha256(path) != reference["sha256"]:
            raise ArtifactValidationError(f"declared evidence changed: {reference['path']}")
    try:
        membership = json.loads(resolved.evidence_paths[membership_ref["path"]].read_text())
        quality = json.loads(resolved.evidence_paths[quality_ref["path"]].read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactValidationError("edge evidence is not valid JSON") from exc
    if (not isinstance(membership, dict)
            or membership.get("point_in_time") != inputs["membership"]["point_in_time"]
            or membership.get("survivor_status") != inputs["survivor_status"]
            or isinstance(membership.get("coverage"), bool)
            or not isinstance(membership.get("coverage"), (int, float))
            or not math.isfinite(float(membership["coverage"]))
            or float(membership["coverage"]) < inputs["coverage"]["minimum"]
            or type(membership.get("expected_rows")) is not int
            or membership["expected_rows"] < 1):
        raise ArtifactValidationError("membership PIT, survivor, or coverage evidence differs")
    if (not isinstance(quality, dict) or quality.get("status") != "accepted"
            or quality.get("version") != inputs["quality"]["version"]
            or quality.get("policy") != inputs["quality"]["policy"]
            or quality.get("invalid_rows") != 0):
        raise ArtifactValidationError("quality evidence differs from the declaration")
    return {"membership": membership, "quality": quality}


def _input_mount(
    resolved: ResolvedStudy,
    execution_root: Path,
    *,
    outcome: bool,
    as_of_session: str | None = None,
    prior_nodes: Mapping[str, list[dict[str, Any]]] | None = None,
) -> tuple[Path, list[dict]]:
    mount = Path(tempfile.mkdtemp(prefix="study-inputs-", dir=execution_root))
    parts_root = mount / "parts"
    parts_root.mkdir()
    declared_rows = []
    manifest = []
    field = "outcome_parts" if outcome else "feature_parts"
    for index, reference in enumerate(resolved.spec.document["inputs"][field]):
        source = resolved.evidence_paths[reference["path"]]
        target = parts_root / f"{index}{source.suffix.lower()}"
        try:
            os.link(source, target)
        except OSError:
            shutil.copyfile(source, target)
        if file_sha256(target) != reference["sha256"]:
            raise ArtifactValidationError("input part changed while mounting")
        manifest.append({
            "declared_path": reference["path"],
            "mounted_path": target.relative_to(mount).as_posix(),
            "sha256": reference["sha256"],
        })
        if reference["format"] == "opaque":
            continue
        if source.suffix.lower() != ".json":
            raise ArtifactValidationError("rows_json input parts must use .json")
        try:
            payload = json.loads(target.read_text())
        except json.JSONDecodeError as exc:
            raise ArtifactValidationError("input part is not valid JSON") from exc
        validated = validate_rows(
            payload,
            resolved.spec.document["inputs"]["schema"],
            allow_input_availability=True,
            primary_key=resolved.spec.document["inputs"]["primary_key"],
        )
        declared_rows.extend(validated)
        if as_of_session is not None and "session" in validated[0]:
            bounded = [row for row in validated if row["session"] <= as_of_session]
            write_text_atomic(target, canonical_bytes(bounded, newline=True).decode())
    if not outcome and not declared_rows:
        raise ArtifactValidationError("StudySpec requires at least one declared rows_json input")
    availability = {
        item["field"]: item["known_at"]
        for item in resolved.spec.document["inputs"]["availability"]
    }
    if not outcome:
        for index, row in enumerate(declared_rows):
            if row["_availability"] != availability:
                raise ArtifactValidationError(f"input row {index} field availability differs")
    write_text_atomic(mount / "manifest.json", canonical_bytes(manifest, newline=True).decode())
    if prior_nodes:
        nodes = mount / "nodes"
        nodes.mkdir()
        for name, rows in prior_nodes.items():
            selected = (rows if as_of_session is None else
                        [row for row in rows if row.get("session", as_of_session) <= as_of_session])
            write_text_atomic(nodes / f"{name}.json", canonical_bytes(selected, newline=True).decode())
    return mount, declared_rows


def _validated_receipt(
    resolved: ResolvedStudy,
    *,
    kind: str,
    recipes: list[dict],
    schemas: Mapping[str, Any],
    row_counts: Mapping[str, int],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "study_identity_sha256": resolved.spec.study_identity_sha256,
        "kind": kind,
        "cache_identity_sha256": resolved.spec.cache_identity(kind)["identity_sha256"],
        "recipes": recipes,
        "schemas": dict(schemas),
        "row_counts": dict(row_counts),
        "edge_evidence_sha256": canonical_sha256(evidence),
    }
    return {**payload, "receipt_sha256": canonical_sha256(payload)}


def validate_study_object(resolved: ResolvedStudy, obj: CacheObject) -> None:
    metadata = obj.manifest.get("metadata")
    receipt = metadata.get("validated_study_receipt") if isinstance(metadata, dict) else None
    if (not isinstance(receipt, dict)
            or receipt.get("study_identity_sha256") != resolved.spec.study_identity_sha256
            or receipt.get("kind") != obj.kind
            or receipt.get("cache_identity_sha256")
            != resolved.spec.cache_identity(obj.kind)["identity_sha256"]):
        raise ArtifactValidationError(f"{obj.kind} object lacks a validated StudySpec receipt")
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if (receipt.get("receipt_sha256") != canonical_sha256(unsigned)
            or receipt.get("content_sha256") != obj.manifest.get("content_sha256")
            or receipt.get("edge_evidence_sha256") != canonical_sha256(_evidence(resolved))):
        raise ArtifactValidationError("StudySpec cache receipt differs")
    latest_fold_end = max(
        date.fromisoformat(fold["end"])
        for fold in resolved.spec.document["evaluation"]["folds"]
    )
    if obj.kind == "feature":
        for node in resolved.spec.document["features"]:
            rows = obj.read_json(f"nodes/{node['name']}.json")
            validate_rows(
                rows, node["output_schema"], availability=node["availability"],
                primary_key=resolved.spec.document["inputs"]["primary_key"],
            )
            if receipt["row_counts"].get(node["name"]) != len(rows):
                raise ArtifactValidationError("feature receipt row count differs")
    elif obj.kind == "label":
        rows = obj.read_json("labels.json")
        outcomes = resolved.spec.document["outcomes"]
        validate_rows(
            rows, outcomes["output_schema"], availability=outcomes["availability"],
            primary_key=resolved.spec.document["inputs"]["primary_key"],
        )
        if "session" not in {column["name"] for column in outcomes["output_schema"]}:
            raise ArtifactValidationError("folded label schemas require a session column")
        if any(datetime.fromisoformat(row[outcomes["availability"]]).date() >= latest_fold_end
               for row in rows):
            raise ArtifactValidationError("label availability exceeds declared fold bounds")
        if receipt["row_counts"].get("labels") != len(rows):
            raise ArtifactValidationError("label receipt row count differs")
    else:
        raise ArtifactValidationError("StudySpec runner accepts only feature and label objects")


def build_study_artifacts(
    cache: ResearchCache,
    resolved: ResolvedStudy,
    execution_root: str | Path,
) -> StudyCacheArtifacts:
    root = Path(execution_root).resolve()
    if repository_containing(root) is not None:
        raise ValueError("study artifact root must be outside every repository")
    root.mkdir(parents=True, exist_ok=True)
    evidence = _evidence(resolved)
    initial_mount, declared_inputs = _input_mount(resolved, root, outcome=False)
    shutil.rmtree(initial_mount)
    decision_sessions = sorted({row["session"] for row in declared_inputs if "session" in row})
    if not decision_sessions:
        decision_sessions = [None]
    prepare_sandbox_runtime(root)
    feature_rows, feature_recipes, feature_schemas, feature_counts = {}, [], {}, {}
    for node in resolved.spec.document["features"]:
        package = build_callback_package(resolved, node["callback"], root)
        rows = []
        for decision_session in decision_sessions:
            mount, _ = _input_mount(
                resolved,
                root,
                outcome=False,
                as_of_session=decision_session,
                prior_nodes=feature_rows,
            )
            try:
                response = run_sandboxed(
                    package,
                    {
                        "callback": node["callback"],
                        "package_sha256": package.digest,
                        "parameters": {
                            **node["parameters"], "_decision_session": decision_session,
                        },
                        "mode": "recipe",
                        "memory_mb": resolved.spec.document["execution"]["memory_mb"],
                    },
                    feature_root=mount,
                    label_root=None,
                    runtime_root=root,
                    timeout=resolved.spec.document["execution"]["expected_seconds"],
                )
            finally:
                shutil.rmtree(mount)
            candidate_rows = validate_rows(
                response["payload"], node["output_schema"], availability=node["availability"],
                primary_key=resolved.spec.document["inputs"]["primary_key"],
            )
            selected = (candidate_rows if decision_session is None else
                        [row for row in candidate_rows if row.get("session") == decision_session])
            if not selected:
                raise ArtifactValidationError(
                    f"feature recipe omitted decision session {decision_session}"
                )
            rows.extend(selected)
        primary_key = resolved.spec.document["inputs"]["primary_key"]
        if len({tuple(row[name] for name in primary_key) for row in rows}) != len(rows):
            raise ArtifactValidationError("feature recipe emitted duplicate decision rows")
        observed_coverage = len(rows) / evidence["membership"]["expected_rows"]
        if observed_coverage < resolved.spec.document["inputs"]["coverage"]["minimum"]:
            raise ArtifactValidationError("actual feature row coverage misses the declared gate")
        if "ticker" in {column["name"] for column in node["output_schema"]}:
            members = evidence["membership"].get("members")
            if not isinstance(members, list) or any(row["ticker"] not in members for row in rows):
                raise ArtifactValidationError("feature row is outside PIT membership evidence")
        feature_rows[node["name"]] = rows
        feature_recipes.append({"name": node["name"], "package_sha256": package.digest})
        feature_schemas[node["name"]] = node["output_schema"]
        feature_counts[node["name"]] = len(rows)
    feature_receipt = _validated_receipt(
        resolved, kind="feature", recipes=feature_recipes, schemas=feature_schemas,
        row_counts=feature_counts, evidence=evidence,
    )

    def write_features(data_root: Path) -> Mapping[str, Any]:
        nodes = data_root / "nodes"
        nodes.mkdir()
        for name, rows in feature_rows.items():
            write_text_atomic(
                nodes / f"{name}.json", canonical_bytes(rows, newline=True).decode()
            )
        return {"validated_study_receipt": feature_receipt}

    features = cache.build_validated(
        "feature", resolved.spec.cache_identity("feature"), write_features,
    )
    validate_study_object(resolved, features)
    return StudyCacheArtifacts(features)


def _build_label_artifact(
    cache: ResearchCache,
    resolved: ResolvedStudy,
    execution_root: str | Path,
    capability: _LabelBuildCapability,
) -> CacheObject:
    if (not isinstance(capability, _LabelBuildCapability)
            or capability.secret is not _LABEL_CAPABILITY_SECRET
            or not capability.attempt_id
            or any(len(value) != 64 for value in (
                capability.predictions_sha256,
                capability.census_sha256,
                capability.started_receipt_sha256,
            ))):
        raise ArtifactValidationError("label construction requires a runner-issued attempt capability")
    root = Path(execution_root).resolve()
    if repository_containing(root) is not None:
        raise ValueError("study artifact root must be outside every repository")
    root.mkdir(parents=True, exist_ok=True)
    evidence = _evidence(resolved)
    mount, _ = _input_mount(resolved, root, outcome=True)
    prepare_sandbox_runtime(root)
    try:
        outcomes = resolved.spec.document["outcomes"]
        package = build_callback_package(resolved, outcomes["callback"], root)
        response = run_sandboxed(
            package,
            {
                "callback": outcomes["callback"],
                "package_sha256": package.digest,
                "parameters": outcomes["parameters"],
                "mode": "recipe",
                "memory_mb": resolved.spec.document["execution"]["memory_mb"],
            },
            feature_root=mount,
            label_root=None,
            runtime_root=root,
            timeout=resolved.spec.document["execution"]["expected_seconds"],
        )
        label_rows = validate_rows(
            response["payload"], outcomes["output_schema"],
            availability=outcomes["availability"],
            primary_key=resolved.spec.document["inputs"]["primary_key"],
        )
        folds = resolved.spec.document["evaluation"]["folds"]
        label_rows = [
            row for row in label_rows
            if any(date.fromisoformat(fold["start"]) <= date.fromisoformat(row["session"])
                   < date.fromisoformat(fold["end"]) for fold in folds)
        ]
        if not label_rows:
            raise ArtifactValidationError("no labels fall inside declared folds")
        label_receipt = _validated_receipt(
            resolved,
            kind="label",
            recipes=[{"name": "labels", "package_sha256": package.digest}],
            schemas={"labels": outcomes["output_schema"]},
            row_counts={"labels": len(label_rows)},
            evidence=evidence,
        )
        label_receipt["attempt_capability"] = {
            "attempt_id": capability.attempt_id,
            "predictions_sha256": capability.predictions_sha256,
            "census_sha256": capability.census_sha256,
            "started_receipt_sha256": capability.started_receipt_sha256,
        }

        def write_labels(data_root: Path) -> Mapping[str, Any]:
            write_text_atomic(
                data_root / "labels.json", canonical_bytes(label_rows, newline=True).decode()
            )
            return {"validated_study_receipt": label_receipt}

        labels = cache.build_validated(
            "label", resolved.spec.cache_identity("label"), write_labels,
        )
        validate_study_object(resolved, labels)
        return labels
    finally:
        shutil.rmtree(mount)


def materialize_decision_features(
    resolved: ResolvedStudy,
    features: CacheObject,
    fold: Mapping[str, Any],
    decision_session: str,
    root: str | Path,
) -> Path:
    """Create a read-only feature view for one decision inside one fold."""
    destination = Path(root).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    nodes = destination / "nodes"
    nodes.mkdir()
    start, end = date.fromisoformat(fold["start"]), date.fromisoformat(fold["end"])
    for node in resolved.spec.document["features"]:
        rows = features.read_json(f"nodes/{node['name']}.json")
        if "session" not in {column["name"] for column in node["output_schema"]}:
            raise ArtifactValidationError("folded feature schemas require a session column")
        decision = date.fromisoformat(decision_session)
        if not start <= decision < end:
            raise ArtifactValidationError("decision session is outside the declared fold")
        selected = [row for row in rows if row["session"] == decision_session]
        if any(datetime.fromisoformat(row[node["availability"]]).date() > decision
               for row in selected):
            raise ArtifactValidationError(
                f"decision {decision_session} contains unavailable features"
            )
        if not selected and "refuse" in resolved.spec.document["evaluation"]["missing_data_policy"]:
            raise ArtifactValidationError(f"fold {fold['name']} has no feature rows")
        write_text_atomic(
            nodes / f"{node['name']}.json", canonical_bytes(selected, newline=True).decode()
        )
    for path in destination.rglob("*"):
        path.chmod(0o555 if path.is_dir() else 0o444)
    return destination


def validate_feature_label_alignment(
    resolved: ResolvedStudy,
    features: CacheObject,
    labels: CacheObject,
) -> None:
    folds = resolved.spec.document["evaluation"]["folds"]
    primary_key = resolved.spec.document["inputs"]["primary_key"]
    label_keys = {
        tuple(row[name] for name in primary_key)
        for row in labels.read_json("labels.json")
    }
    for node in resolved.spec.document["features"]:
        node_keys = set()
        for row in features.read_json(f"nodes/{node['name']}.json"):
            session = date.fromisoformat(row["session"])
            if any(date.fromisoformat(fold["start"]) <= session < date.fromisoformat(fold["end"])
                   for fold in folds):
                node_keys.add(tuple(row[name] for name in primary_key))
        if node_keys != label_keys:
            raise ArtifactValidationError(
                f"feature node {node['name']} and label primary keys are not fold-aligned"
            )
