import importlib
import json

from engine.lib.resources import write_text_atomic
from farm.research.artifacts import (
    ArtifactValidationError,
    _build_label_artifact,
    build_study_artifacts,
    materialize_decision_features,
    validate_feature_label_alignment,
)
from farm.research.cache import CacheError, ResearchCache
from farm.research.canonical import canonical_sha256, file_sha256
from farm.research.spec import StudySpec
from farm.research.tests.support import complete_contract

pytest = importlib.import_module("pytest")


def _resolved(tmp_path, *, feature_function="feature_recipe"):
    base = tmp_path / "contract"
    base.mkdir()
    contract = complete_contract(base)
    contract["features"][0]["callback"]["function"] = feature_function
    return base, contract


def test_studyspec_builder_executes_recipe_and_refuses_declared_schema_mismatch(tmp_path):
    base, contract = _resolved(tmp_path, feature_function="malformed_feature_recipe")
    resolved = StudySpec.from_dict(contract).resolve(base)
    with pytest.raises(ArtifactValidationError, match="columns differ"):
        build_study_artifacts(
            ResearchCache(tmp_path / "cache"), resolved, tmp_path / "execution"
        )


@pytest.mark.parametrize("defect", ["coverage", "pit", "quality", "availability"])
def test_studyspec_builder_refuses_edge_evidence_and_input_availability_drift(
    tmp_path, defect,
):
    base, contract = _resolved(tmp_path)
    if defect in {"coverage", "pit"}:
        path = base / "membership.json"
        evidence = json.loads(path.read_text())
        if defect == "coverage":
            evidence["rows"].append({"session": "2024-01-04", "eligible": True})
        else:
            evidence["point_in_time"] = False
        write_text_atomic(path, json.dumps(evidence) + "\n")
        contract["inputs"]["membership"]["evidence"]["sha256"] = file_sha256(path)
    elif defect == "quality":
        path = base / "quality.json"
        evidence = json.loads(path.read_text())
        evidence["invalid_rows"] = 1
        write_text_atomic(path, json.dumps(evidence) + "\n")
        contract["inputs"]["quality"]["evidence"]["sha256"] = file_sha256(path)
    else:
        path = base / "input.json"
        rows = json.loads(path.read_text())
        rows[0]["_availability"]["close"] = "future close"
        write_text_atomic(path, json.dumps(rows) + "\n")
        contract["inputs"]["feature_parts"][0]["sha256"] = file_sha256(path)
    resolved = StudySpec.from_dict(contract).resolve(base)
    with pytest.raises(ArtifactValidationError):
        build_study_artifacts(
            ResearchCache(tmp_path / "cache"), resolved, tmp_path / "execution"
        )


def test_generic_writer_cannot_forge_validated_receipt_or_future_feature(tmp_path):
    base, contract = _resolved(tmp_path)
    resolved = StudySpec.from_dict(contract).resolve(base)
    cache = ResearchCache(tmp_path / "cache")

    def forged(path):
        nodes = path / "nodes"
        nodes.mkdir()
        write_text_atomic(nodes / "fixture.json", json.dumps([{
            "session": "2024-01-02",
            "score": 999.0,
            "available_at": "2099-01-01T00:00:00+00:00",
        }]) + "\n")
        unsigned = {
            "schema_version": 1,
            "study_identity_sha256": resolved.spec.study_identity_sha256,
            "kind": "feature",
            "cache_identity_sha256": resolved.spec.cache_identity("feature")["identity_sha256"],
            "recipes": [],
            "schemas": {"fixture": resolved.spec.document["features"][0]["output_schema"]},
            "row_counts": {"fixture": 1},
            "edge_evidence_sha256": "0" * 64,
        }
        return {"validated_study_receipt": {
            **unsigned, "receipt_sha256": canonical_sha256(unsigned),
        }}

    with pytest.raises(CacheError, match="generic cache publication"):
        cache.build("feature", resolved.spec.cache_identity("feature"), forged)


def test_feature_recipe_mount_excludes_every_outcome_part(tmp_path):
    base, contract = _resolved(tmp_path, feature_function="probing_feature_recipe")
    contract["features"][0]["output_schema"].insert(2, {
        "name": "outcome_probe_blocked", "dtype": "bool", "nullable": False,
    })
    resolved = StudySpec.from_dict(contract).resolve(base)
    artifacts = build_study_artifacts(
        ResearchCache(tmp_path / "cache"), resolved, tmp_path / "execution",
    )
    rows = artifacts.features.read_json("nodes/fixture.json")
    assert rows[0]["outcome_probe_blocked"] is True


def test_trusted_builder_refuses_feature_published_after_fold_end(tmp_path):
    base, contract = _resolved(tmp_path, feature_function="future_feature_recipe")
    resolved = StudySpec.from_dict(contract).resolve(base)
    artifacts = build_study_artifacts(
        ResearchCache(tmp_path / "cache"), resolved, tmp_path / "execution",
    )
    with pytest.raises(ArtifactValidationError, match="contains unavailable features"):
        materialize_decision_features(
            resolved,
            artifacts.features,
            resolved.spec.document["evaluation"]["folds"][0],
            "2024-01-02",
            tmp_path / "fold",
        )


def test_same_day_post_decision_timestamp_is_refused(tmp_path):
    base, contract = _resolved(tmp_path, feature_function="same_day_late_feature_recipe")
    resolved = StudySpec.from_dict(contract).resolve(base)
    artifacts = build_study_artifacts(
        ResearchCache(tmp_path / "cache"), resolved, tmp_path / "execution",
    )
    with pytest.raises(ArtifactValidationError, match="contains unavailable features"):
        materialize_decision_features(
            resolved, artifacts.features,
            resolved.spec.document["evaluation"]["folds"][0],
            "2024-01-02", tmp_path / "fold",
        )


def test_input_without_timestamp_is_available_only_after_session_close(tmp_path):
    base, contract = _resolved(tmp_path)
    path = base / "input.json"
    rows = json.loads(path.read_text())
    for row in rows:
        row.pop("_availability")
    write_text_atomic(path, json.dumps(rows) + "\n")
    contract["inputs"]["feature_parts"][0]["sha256"] = file_sha256(path)
    with pytest.raises(ArtifactValidationError, match="non-empty list"):
        build_study_artifacts(
            ResearchCache(tmp_path / "cache"), StudySpec.from_dict(contract).resolve(base),
            tmp_path / "execution",
        )


def test_membership_table_is_applied_per_decision_session(tmp_path):
    base, contract = _resolved(tmp_path, feature_function="ticker_feature_recipe")
    input_path = base / "input.json"
    rows = json.loads(input_path.read_text())
    for row in rows:
        row["ticker"] = "BBB"
    write_text_atomic(input_path, json.dumps(rows) + "\n")
    contract["inputs"]["feature_parts"][0]["sha256"] = file_sha256(input_path)
    contract["inputs"]["schema"].append({
        "name": "ticker", "dtype": "string", "nullable": False,
    })
    contract["inputs"]["primary_key"] = ["session", "ticker"]
    contract["features"][0]["output_schema"].insert(1, {
        "name": "ticker", "dtype": "string", "nullable": False,
    })
    contract["outcomes"]["output_schema"].insert(1, {
        "name": "ticker", "dtype": "string", "nullable": False,
    })
    membership_path = base / "membership.json"
    membership = {
        "point_in_time": True,
        "survivor_status": "point_in_time",
        "rows": [
            {"session": "2024-01-02", "ticker": "AAA", "eligible": True},
            {"session": "2024-01-03", "ticker": "BBB", "eligible": True},
        ],
    }
    write_text_atomic(membership_path, json.dumps(membership) + "\n")
    contract["inputs"]["membership"]["evidence"]["sha256"] = file_sha256(membership_path)
    with pytest.raises(ArtifactValidationError, match="non-empty list"):
        build_study_artifacts(
            ResearchCache(tmp_path / "cache"), StudySpec.from_dict(contract).resolve(base),
            tmp_path / "execution",
        )


def test_label_builder_refuses_without_runner_attempt_capability(tmp_path):
    base, contract = _resolved(tmp_path)
    resolved = StudySpec.from_dict(contract).resolve(base)
    with pytest.raises(ArtifactValidationError, match="runner-issued attempt capability"):
        _build_label_artifact(
            ResearchCache(tmp_path / "cache"),
            resolved,
            tmp_path / "labels",
            None,
        )


def test_feature_label_alignment_uses_exact_declared_entity_key(tmp_path):
    base, contract = _resolved(tmp_path)
    contract["inputs"]["schema"].append({
        "name": "ticker", "dtype": "string", "nullable": False,
    })
    contract["inputs"]["primary_key"] = ["session", "ticker"]
    for section in (contract["features"][0], contract["outcomes"]):
        section["output_schema"].insert(1, {
            "name": "ticker", "dtype": "string", "nullable": False,
        })
    resolved = StudySpec.from_dict(contract).resolve(base)

    class FixtureObject:
        def __init__(self, values):
            self.values = values

        def read_json(self, path):
            return self.values[path]

    feature = FixtureObject({"nodes/fixture.json": [{
        "session": "2024-01-02", "ticker": "AAA", "score": 1.0,
        "available_at": "2024-01-02T21:00:00+00:00",
    }]})
    label = FixtureObject({"labels.json": [{
        "session": "2024-01-02", "ticker": "BBB",
        "entry_price": 100.0, "exit_price": 101.0,
        "available_at": "2024-01-02T22:00:00+00:00",
    }]})
    with pytest.raises(ArtifactValidationError, match="primary keys are not fold-aligned"):
        validate_feature_label_alignment(resolved, feature, label)
