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

from .cache import CacheObject, ResearchCache
from .canonical import canonical_bytes, canonical_sha256, file_sha256
from .sandbox import build_callback_package, prepare_sandbox_runtime, run_sandboxed
from .spec import ResolvedStudy


class ArtifactValidationError(ValueError):
    pass


@dataclass(frozen=True)
class StudyCacheArtifacts:
    features: CacheObject
    labels: CacheObject | None


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
    return rows


def _evidence(resolved: ResolvedStudy) -> dict[str, Any]:
    inputs = resolved.spec.document["inputs"]
    membership_ref = inputs["membership"]["evidence"]
    quality_ref = inputs["quality"]["evidence"]
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
            or float(membership["coverage"]) < inputs["coverage"]["minimum"]):
        raise ArtifactValidationError("membership PIT, survivor, or coverage evidence differs")
    if (not isinstance(quality, dict) or quality.get("status") != "accepted"
            or quality.get("version") != inputs["quality"]["version"]
            or quality.get("policy") != inputs["quality"]["policy"]
            or quality.get("invalid_rows") != 0):
        raise ArtifactValidationError("quality evidence differs from the declaration")
    return {"membership": membership, "quality": quality}


def _input_mount(resolved: ResolvedStudy, execution_root: Path) -> tuple[Path, list[dict]]:
    mount = Path(tempfile.mkdtemp(prefix="study-inputs-", dir=execution_root))
    parts_root = mount / "parts"
    parts_root.mkdir()
    declared_rows = []
    manifest = []
    for index, reference in enumerate(resolved.spec.document["inputs"]["parts"]):
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
        declared_rows.extend(validate_rows(
            payload,
            resolved.spec.document["inputs"]["schema"],
            allow_input_availability=True,
        ))
    if not declared_rows:
        raise ArtifactValidationError("StudySpec requires at least one declared rows_json input")
    availability = {
        item["field"]: item["known_at"]
        for item in resolved.spec.document["inputs"]["availability"]
    }
    for index, row in enumerate(declared_rows):
        if row["_availability"] != availability:
            raise ArtifactValidationError(f"input row {index} field availability differs")
    write_text_atomic(mount / "manifest.json", canonical_bytes(manifest, newline=True).decode())
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
    if receipt.get("receipt_sha256") != canonical_sha256(unsigned):
        raise ArtifactValidationError("StudySpec cache receipt differs")
    if obj.kind == "feature":
        for node in resolved.spec.document["features"]:
            rows = obj.read_json(f"nodes/{node['name']}.json")
            validate_rows(rows, node["output_schema"], availability=node["availability"])
            if receipt["row_counts"].get(node["name"]) != len(rows):
                raise ArtifactValidationError("feature receipt row count differs")
    elif obj.kind == "label":
        rows = obj.read_json("labels.json")
        outcomes = resolved.spec.document["outcomes"]
        validate_rows(rows, outcomes["output_schema"], availability=outcomes["availability"])
        if receipt["row_counts"].get("labels") != len(rows):
            raise ArtifactValidationError("label receipt row count differs")
    else:
        raise ArtifactValidationError("StudySpec runner accepts only feature and label objects")


def build_study_artifacts(
    cache: ResearchCache,
    resolved: ResolvedStudy,
    execution_root: str | Path,
    *,
    include_labels: bool = True,
) -> StudyCacheArtifacts:
    root = Path(execution_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    evidence = _evidence(resolved)
    mount, _ = _input_mount(resolved, root)
    prepare_sandbox_runtime(root)
    try:
        feature_rows, feature_recipes, feature_schemas, feature_counts = {}, [], {}, {}
        for node in resolved.spec.document["features"]:
            package = build_callback_package(resolved, node["callback"], root)
            response = run_sandboxed(
                package,
                {
                    "callback": node["callback"],
                    "package_sha256": package.digest,
                    "parameters": node["parameters"],
                    "mode": "recipe",
                    "memory_mb": resolved.spec.document["execution"]["memory_mb"],
                },
                feature_root=mount,
                label_root=None,
                runtime_root=root,
                timeout=resolved.spec.document["execution"]["expected_seconds"],
            )
            rows = validate_rows(
                response["payload"], node["output_schema"], availability=node["availability"]
            )
            feature_rows[node["name"]] = rows
            feature_recipes.append({"name": node["name"], "package_sha256": package.digest})
            feature_schemas[node["name"]] = node["output_schema"]
            feature_counts[node["name"]] = len(rows)
            nodes = mount / "nodes"
            nodes.mkdir(exist_ok=True)
            write_text_atomic(
                nodes / f"{node['name']}.json", canonical_bytes(rows, newline=True).decode()
            )
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

        features = cache.build("feature", resolved.spec.cache_identity("feature"), write_features)
        validate_study_object(resolved, features)
        labels = None
        if include_labels:
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
            )
            label_receipt = _validated_receipt(
                resolved,
                kind="label",
                recipes=[{"name": "labels", "package_sha256": package.digest}],
                schemas={"labels": outcomes["output_schema"]},
                row_counts={"labels": len(label_rows)},
                evidence=evidence,
            )

            def write_labels(data_root: Path) -> Mapping[str, Any]:
                write_text_atomic(
                    data_root / "labels.json", canonical_bytes(label_rows, newline=True).decode()
                )
                return {"validated_study_receipt": label_receipt}

            labels = cache.build("label", resolved.spec.cache_identity("label"), write_labels)
            validate_study_object(resolved, labels)
        return StudyCacheArtifacts(features, labels)
    finally:
        shutil.rmtree(mount)
