import importlib
import json

from engine.lib.resources import write_text_atomic
from farm.research.artifacts import (
    ArtifactValidationError,
    build_study_artifacts,
    materialize_fold_features,
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
        evidence["coverage" if defect == "coverage" else "point_in_time"] = (
            0.1 if defect == "coverage" else False
        )
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
    with pytest.raises(ArtifactValidationError, match="unavailable by its end"):
        materialize_fold_features(
            resolved,
            artifacts.features,
            resolved.spec.document["evaluation"]["folds"][0],
            tmp_path / "fold",
        )
