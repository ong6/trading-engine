import importlib
import json

from engine.lib.resources import write_text_atomic
from farm.research.artifacts import ArtifactValidationError, build_study_artifacts
from farm.research.cache import ResearchCache
from farm.research.canonical import file_sha256
from farm.research.spec import StudySpec
from farm.research.tests.support import complete_contract

pytest = importlib.import_module("pytest")


def _resolved(tmp_path, *, feature_function="feature_recipe"):
    base = tmp_path / "contract"
    base.mkdir()
    contract = complete_contract(base)
    callback = __import__(
        "farm.research.tests.fixture_callbacks", fromlist=["fixture_callbacks"]
    )
    contract["features"][0]["callback"]["function"] = feature_function
    contract["features"][0]["callback"]["sha256"] = file_sha256(callback.__file__)
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
        contract["inputs"]["parts"][0]["sha256"] = file_sha256(path)
    resolved = StudySpec.from_dict(contract).resolve(base)
    with pytest.raises(ArtifactValidationError):
        build_study_artifacts(
            ResearchCache(tmp_path / "cache"), resolved, tmp_path / "execution"
        )
