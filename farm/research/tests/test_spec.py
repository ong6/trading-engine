import importlib
import json

from engine.lib.resources import write_text_atomic
from farm.research.spec import ContractError, StudySpec
from farm.research.tests.support import complete_contract

pytest = importlib.import_module("pytest")


def test_complete_contract_has_canonical_golden_bytes_and_derived_markdown(tmp_path):
    contract = complete_contract(tmp_path)
    first = StudySpec.from_dict(contract)
    second = StudySpec.from_dict(json.loads(first.canonical_bytes))
    assert first.canonical_bytes == second.canonical_bytes
    assert first.sha256 == second.sha256
    assert first.sha256 == "e6a8a524a6b1ceb4f8e645d8260ce7f2b293a2d0fd76ceec719529893077f8d9"
    assert first.resolve(tmp_path).spec == first
    markdown = first.to_markdown()
    assert f"Contract SHA-256: `{first.sha256}`" in markdown
    assert "DSR census N: 140" in markdown
    assert "derived from the canonical JSON contract" in markdown


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.pop("outcomes"), "missing.*outcomes"),
        (lambda value: value["study"].__setitem__("extra", True), "unknown.*extra"),
        (lambda value: value["features"][0].__setitem__("mystery", 1), "unknown.*mystery"),
        (lambda value: value["outcomes"].__setitem__("horizons", [5, 1]), "sorted and unique"),
    ],
)
def test_contract_refuses_missing_unknown_and_noncanonical_fields(tmp_path, mutation, message):
    contract = complete_contract(tmp_path)
    mutation(contract)
    with pytest.raises(ContractError, match=message):
        StudySpec.from_dict(contract)


def test_resolution_refuses_source_recipe_and_evidence_hash_drift(tmp_path):
    contract = complete_contract(tmp_path)
    spec = StudySpec.from_dict(contract)
    write_text_atomic(tmp_path / "input.json", '{"rows":3}\n')
    with pytest.raises(ContractError, match="evidence hash differs"):
        spec.resolve(tmp_path)

    contract = complete_contract(tmp_path)
    contract["strategy"]["callback"]["sha256"] = "f" * 64
    with pytest.raises(ContractError, match="callback module hash differs"):
        StudySpec.from_dict(contract).resolve(tmp_path)

    contract = complete_contract(tmp_path)
    contract["strategy"]["callback"]["function"] = "not_defined"
    with pytest.raises(ContractError, match="not defined at module scope"):
        StudySpec.from_dict(contract).resolve(tmp_path)


def test_contract_identity_moves_with_late_revision_quality_calendar_or_callback(tmp_path):
    base = complete_contract(tmp_path)
    baseline = StudySpec.from_dict(base)
    mutations = []
    for section, field, value in (
        ("inputs", "generation_sha256", "4" * 64),
        ("inputs", "calendar", {"name": "XNYS", "version": "fixture-v2"}),
        ("inputs", "quality", base["inputs"]["quality"] | {"version": "fixture-v2"}),
    ):
        changed = complete_contract(tmp_path)
        changed[section][field] = value
        mutations.append(StudySpec.from_dict(changed))
    changed = complete_contract(tmp_path)
    changed["features"][0]["callback"]["sha256"] = "5" * 64
    mutations.append(StudySpec.from_dict(changed))
    assert all(item.sha256 != baseline.sha256 for item in mutations)
    assert all(
        item.cache_identity("feature")["identity_sha256"]
        != baseline.cache_identity("feature")["identity_sha256"]
        for item in mutations
    )
