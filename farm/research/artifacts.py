"""Executable StudySpec recipes and semantic cache validation."""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

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


def _capability_payload(capability: _LabelBuildCapability) -> dict[str, str]:
    return {
        "attempt_id": capability.attempt_id,
        "predictions_sha256": capability.predictions_sha256,
        "census_sha256": capability.census_sha256,
        "started_receipt_sha256": capability.started_receipt_sha256,
    }


def label_cache_identity(
    resolved: ResolvedStudy, capability: _LabelBuildCapability,
) -> dict[str, Any]:
    base = resolved.spec.cache_identity("label")
    identity = {
        key: value for key, value in base.items() if key != "identity_sha256"
    }
    identity["attempt_capability"] = _capability_payload(capability)
    identity["identity_sha256"] = canonical_sha256(identity)
    return identity


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
    expected = set(columns)
    rows = []
    for index, raw in enumerate(value):
        observed = set(raw) if isinstance(raw, dict) else set()
        valid_fields = (frozenset(observed) in {
            frozenset(expected), frozenset(expected | {"_availability"})}
                        if allow_input_availability else observed == expected)
        if not isinstance(raw, dict) or not valid_fields:
            raise ArtifactValidationError(f"row {index} columns differ from the declaration")
        row = dict(raw)
        if allow_input_availability and "_availability" in row \
                and not isinstance(row["_availability"], dict):
            raise ArtifactValidationError(f"row {index} availability must be a timestamp mapping")
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
        if any(row.get(name) is None for name in primary_key):
            raise ArtifactValidationError(f"row {index} has a null primary key")
        rows.append(row)
    if primary_key:
        keys = [tuple(row[name] for name in primary_key) for row in rows]
        if len(keys) != len(set(keys)):
            raise ArtifactValidationError("recipe emitted duplicate primary keys")
    return rows


def _decision_at(resolved: ResolvedStudy, session: str) -> datetime:
    decision = resolved.spec.document["strategy"]["decision"]
    hour, minute = map(int, decision["time"].split(":"))
    return datetime.combine(
        date.fromisoformat(session), time(hour, minute), ZoneInfo(decision["timezone"])
    )


def _fallback_available_at(resolved: ResolvedStudy, session: str) -> datetime:
    inputs = resolved.spec.document["inputs"]
    hour, minute = map(int, inputs["calendar"]["session_close"].split(":"))
    return datetime.combine(
        date.fromisoformat(session), time(hour, minute), ZoneInfo(inputs["timezone"])
    ) + timedelta(microseconds=1)


def _available_at(resolved: ResolvedStudy, row: Mapping[str, Any], field: str) -> datetime:
    raw = row.get("_availability", {}).get(field)
    if raw is None:
        return _fallback_available_at(resolved, row["session"])
    if isinstance(raw, str):
        try:
            declared_date = date.fromisoformat(raw)
        except ValueError:
            declared_date = None
        if declared_date is not None and declared_date.isoformat() == raw:
            inputs = resolved.spec.document["inputs"]
            hour, minute = map(int, inputs["calendar"]["session_close"].split(":"))
            return datetime.combine(
                declared_date, time(hour, minute), ZoneInfo(inputs["timezone"])
            )
    try:
        value = datetime.fromisoformat(raw)
    except (TypeError, ValueError) as exc:
        raise ArtifactValidationError(f"{field} availability is not an ISO timestamp") from exc
    if value.tzinfo is None:
        raise ArtifactValidationError(f"{field} availability needs an explicit timezone")
    return value.astimezone(ZoneInfo(resolved.spec.document["inputs"]["timezone"]))


def _declared_available_at(
    resolved: ResolvedStudy, raw: object, field: str,
) -> datetime:
    timezone = ZoneInfo(resolved.spec.document["inputs"]["timezone"])
    if isinstance(raw, str):
        try:
            declared_date = date.fromisoformat(raw)
        except ValueError:
            declared_date = None
        if declared_date is not None and declared_date.isoformat() == raw:
            hour, minute = map(
                int, resolved.spec.document["inputs"]["calendar"]["session_close"].split(":")
            )
            return datetime.combine(declared_date, time(hour, minute), timezone)
    try:
        value = datetime.fromisoformat(raw)
    except (TypeError, ValueError) as exc:
        raise ArtifactValidationError(f"{field} availability is not an ISO date/timestamp") from exc
    if value.tzinfo is None:
        raise ArtifactValidationError(f"{field} availability needs an explicit timezone")
    return value.astimezone(timezone)


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
            or set(membership) != {"point_in_time", "survivor_status", "rows"}
            or membership.get("point_in_time") != inputs["membership"]["point_in_time"]
            or membership.get("survivor_status") != inputs["survivor_status"]
            or not isinstance(membership.get("rows"), list) or not membership["rows"]):
        raise ArtifactValidationError("membership PIT, survivor, or coverage evidence differs")
    key_fields = tuple(inputs["primary_key"])
    input_schema = {column["name"]: column for column in inputs["schema"]}
    membership_keys = []
    for index, row in enumerate(membership["rows"]):
        if (not isinstance(row, dict) or set(row) != {*key_fields, "eligible"}
                or type(row["eligible"]) is not bool
                or any(
                    row[field] is None
                    or not _value_valid(row[field], input_schema[field]["dtype"])
                    for field in key_fields
                )):
            raise ArtifactValidationError(f"membership row {index} differs")
        membership_keys.append(tuple(row[field] for field in key_fields))
    if len(membership_keys) != len(set(membership_keys)):
        raise ArtifactValidationError("membership table has duplicate decision keys")
    eligible_keys = [key for key, row in zip(membership_keys, membership["rows"], strict=True)
                     if row["eligible"]]
    if not eligible_keys:
        raise ArtifactValidationError("membership table has no eligible decision keys")
    if (not isinstance(quality, dict) or quality.get("status") != "accepted"
            or quality.get("version") != inputs["quality"]["version"]
            or quality.get("policy") != inputs["quality"]["policy"]
            or quality.get("invalid_rows") != 0):
        raise ArtifactValidationError("quality evidence differs from the declaration")
    return {
        "membership": {**membership, "eligible_keys": eligible_keys},
        "quality": quality,
    }


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
        for row in validated:
            unknown = set(row.get("_availability", {})) - set(
                resolved.spec.document["inputs"]["availability"]
            )
            if unknown:
                raise ArtifactValidationError(
                    f"input availability has undeclared fields: {sorted(unknown)}"
                )
            for field_name in resolved.spec.document["inputs"]["availability"]:
                _available_at(resolved, row, field_name)
        declared_rows.extend(validated)
        if as_of_session is not None and "session" in validated[0]:
            decision_at = _decision_at(resolved, as_of_session)
            availability_fields = resolved.spec.document["inputs"]["availability"]
            eligible = set(_evidence(resolved)["membership"]["eligible_keys"])
            primary_key = resolved.spec.document["inputs"]["primary_key"]
            bounded = [
                row for row in validated
                if row["session"] <= as_of_session
                and tuple(row[name] for name in primary_key) in eligible
                and all(_available_at(resolved, row, name) <= decision_at
                        for name in availability_fields)
            ]
            write_text_atomic(target, canonical_bytes(bounded, newline=True).decode())
    primary_key = resolved.spec.document["inputs"]["primary_key"]
    combined_keys = [tuple(row[name] for name in primary_key) for row in declared_rows]
    if len(combined_keys) != len(set(combined_keys)):
        raise ArtifactValidationError("input parts contain duplicate primary keys across parts")
    if not outcome and not declared_rows:
        raise ArtifactValidationError("StudySpec requires at least one declared rows_json input")
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
    cache_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    selected_identity = cache_identity or resolved.spec.cache_identity(kind)
    payload = {
        "schema_version": 1,
        "study_identity_sha256": resolved.spec.study_identity_sha256,
        "kind": kind,
        "cache_identity_sha256": selected_identity["identity_sha256"],
        "recipes": recipes,
        "schemas": dict(schemas),
        "row_counts": dict(row_counts),
        "edge_evidence_sha256": canonical_sha256(evidence),
    }
    return {**payload, "receipt_sha256": canonical_sha256(payload)}


def validate_study_object(
    resolved: ResolvedStudy,
    obj: CacheObject,
    *,
    cache_identity: Mapping[str, Any] | None = None,
    capability: _LabelBuildCapability | None = None,
) -> None:
    expected_identity = cache_identity or resolved.spec.cache_identity(obj.kind)
    metadata = obj.manifest.get("metadata")
    receipt = metadata.get("validated_study_receipt") if isinstance(metadata, dict) else None
    if (not isinstance(receipt, dict)
            or receipt.get("study_identity_sha256") != resolved.spec.study_identity_sha256
            or receipt.get("kind") != obj.kind
            or receipt.get("cache_identity_sha256")
            != expected_identity["identity_sha256"]
            or obj.manifest.get("identity") != expected_identity):
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
        if capability is None or receipt.get("attempt_capability") != _capability_payload(capability):
            raise ArtifactValidationError("label receipt differs from the current attempt capability")
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
    session_index = resolved.spec.document["inputs"]["primary_key"].index("session")
    eligible_sessions = {
        key[session_index] for key in evidence["membership"]["eligible_keys"]
    }
    decision_sessions = sorted({
        row["session"] for row in declared_inputs
        if "session" in row and row["session"] in eligible_sessions
    })
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
                        "callback": {
                            **node["callback"],
                            "runtime_identity": resolved.spec.document["execution"],
                        },
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
        eligible_keys = {tuple(key) for key in evidence["membership"]["eligible_keys"]}
        row_keys = {tuple(row[name] for name in primary_key) for row in rows}
        if not row_keys <= eligible_keys:
            raise ArtifactValidationError("feature row is outside session-keyed PIT membership")
        observed_coverage = len(row_keys) / len(eligible_keys)
        if observed_coverage < resolved.spec.document["inputs"]["coverage"]["minimum"]:
            raise ArtifactValidationError("actual feature row coverage misses the declared gate")
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
                "callback": {
                    **outcomes["callback"],
                    "runtime_identity": resolved.spec.document["execution"],
                },
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
        identity = label_cache_identity(resolved, capability)
        label_receipt = _validated_receipt(
            resolved,
            kind="label",
            recipes=[{"name": "labels", "package_sha256": package.digest}],
            schemas={"labels": outcomes["output_schema"]},
            row_counts={"labels": len(label_rows)},
            evidence=evidence,
            cache_identity=identity,
        )
        label_receipt["attempt_capability"] = _capability_payload(capability)

        def write_labels(data_root: Path) -> Mapping[str, Any]:
            write_text_atomic(
                data_root / "labels.json", canonical_bytes(label_rows, newline=True).decode()
            )
            return {"validated_study_receipt": label_receipt}

        labels = cache.build_validated(
            "label", identity, write_labels,
        )
        validate_study_object(
            resolved, labels, cache_identity=identity, capability=capability,
        )
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
        decision_at = _decision_at(resolved, decision_session)
        if any(
            _declared_available_at(resolved, row[node["availability"]], node["availability"])
            > decision_at for row in selected
        ):
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
