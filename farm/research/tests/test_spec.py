import importlib
import json
from pathlib import Path

from engine.lib.resources import write_text_atomic
from farm.research.canonical import distribution_sha256, file_sha256
from farm.research.sandbox import build_callback_package, run_sandboxed
from farm.research.spec import ContractError, StudySpec
from farm.research.tests.support import complete_contract

pytest = importlib.import_module("pytest")


def test_complete_contract_has_canonical_golden_bytes_and_derived_markdown(tmp_path):
    contract = complete_contract(tmp_path)
    first = StudySpec.from_dict(contract)
    second = StudySpec.from_dict(json.loads(first.canonical_bytes))
    assert first.canonical_bytes == second.canonical_bytes
    assert first.sha256 == second.sha256
    assert first.sha256 == "c47527a6c5efda3c4370a506ba0bac74f29c3deb0666606bc2ff3c2e55c2c15b"
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


@pytest.mark.parametrize(
    ("mutation", "kind"),
    [
        (lambda value: value["inputs"].__setitem__("timezone", "UTC"), "feature"),
        (lambda value: value["inputs"]["coverage"].__setitem__("minimum", 0.95), "feature"),
        (lambda value: value["inputs"]["coverage"].__setitem__("unit", "rows"), "feature"),
        (lambda value: value["inputs"].__setitem__("survivor_status", "unknown"), "feature"),
        (lambda value: value["inputs"].__setitem__("price_basis", "raw"), "panel"),
        (lambda value: value["inputs"]["calendar"].__setitem__("version", "fixture-v2"), "panel"),
        (lambda value: value["inputs"]["availability"][0].__setitem__("known_at", "prior day"), "feature"),
        (lambda value: value["inputs"]["schema"][0].__setitem__("nullable", True), "feature"),
        (lambda value: value["inputs"]["membership"].__setitem__("point_in_time", False), "universe"),
        (lambda value: value["inputs"]["quality"].__setitem__("version", "fixture-v2"), "feature"),
        (lambda value: value["strategy"].__setitem__("universe_rule", "changed universe"), "feature"),
        (lambda value: value["strategy"].__setitem__("liquidity_rule", "changed liquidity"), "feature"),
    ],
)
def test_every_semantic_input_and_universe_declaration_moves_cache_identity(
    tmp_path, mutation, kind,
):
    baseline_document = complete_contract(tmp_path)
    changed_document = complete_contract(tmp_path)
    mutation(changed_document)
    baseline = StudySpec.from_dict(baseline_document).cache_identity(kind)
    changed = StudySpec.from_dict(changed_document).cache_identity(kind)
    assert changed["identity_sha256"] != baseline["identity_sha256"]


def test_resolve_and_package_never_execute_parent_initializer_on_host(tmp_path):
    base = tmp_path / "contract"
    base.mkdir()
    contract = complete_contract(base)
    marker = tmp_path / "host-initializer-executed"
    package = base / "callbacks" / "import_probe"
    package.mkdir()
    initializer = package / "__init__.py"
    callback = package / "callback.py"
    write_text_atomic(
        initializer,
        "from pathlib import Path\n"
        "try:\n"
        f"    Path({str(marker)!r}).write_text('executed')\n"
        "except Exception:\n"
        "    pass\n",
    )
    write_text_atomic(callback, "def strategy(features, parameters, seed, mode):\n    return {}\n")
    reference = {
        "module": "import_probe.callback",
        "function": "strategy",
        "source": "callbacks/import_probe/callback.py",
        "kind": "module",
        "sha256": file_sha256(callback),
        "dependencies": [{
            "module": "import_probe",
            "source": "callbacks/import_probe/__init__.py",
            "kind": "package",
            "sha256": file_sha256(initializer),
        }],
    }
    contract["strategy"]["callback"] = reference
    resolved = StudySpec.from_dict(contract).resolve(base)
    packaged = build_callback_package(resolved, reference, tmp_path / "execution")
    assert not marker.exists()
    features = tmp_path / "features"
    features.mkdir()
    response = run_sandboxed(
        packaged,
        {
            "callback": reference,
            "package_sha256": packaged.digest,
            "parameters": {},
            "seed": 1,
            "phase": "pilot",
            "mode": "strategy",
            "memory_mb": 256,
        },
        feature_root=features,
        label_root=None,
        runtime_root=tmp_path / "execution",
        timeout=5,
    )
    assert response["payload"] == {}
    assert not marker.exists()


def test_resolution_refuses_interpreter_identity_drift(tmp_path):
    contract = complete_contract(tmp_path)
    contract["execution"]["python_sha256"] = "f" * 64
    with pytest.raises(ContractError, match="interpreter identity differs"):
        StudySpec.from_dict(contract).resolve(tmp_path)
    contract = complete_contract(tmp_path)
    contract["execution"]["python_runtime_sha256"] = "f" * 64
    with pytest.raises(ContractError, match="runtime closure differs"):
        StudySpec.from_dict(contract).resolve(tmp_path)


def test_feature_parts_must_use_temporal_rows_adapter(tmp_path):
    contract = complete_contract(tmp_path)
    contract["inputs"]["feature_parts"][0]["format"] = "opaque"
    with pytest.raises(ContractError, match="temporal rows_json adapter"):
        StudySpec.from_dict(contract)


def test_runtime_distribution_identity_moves_when_any_submodule_moves(tmp_path, monkeypatch):
    import farm.research.canonical as canonical

    package = tmp_path / "site" / "fixture_runtime"
    package.mkdir(parents=True)
    write_text_atomic(package / "__init__.py", "VALUE = 1\n")
    write_text_atomic(package / "submodule.py", "VALUE = 2\n")

    class Distribution:
        files = (Path("fixture_runtime/__init__.py"), Path("fixture_runtime/submodule.py"))

        def locate_file(self, item):
            return tmp_path / "site" / item

    monkeypatch.setattr(canonical.importlib.metadata, "distribution", lambda name: Distribution())
    distribution_sha256.cache_clear()
    before = distribution_sha256("fixture-runtime")
    write_text_atomic(package / "submodule.py", "VALUE = 3\n")
    distribution_sha256.cache_clear()
    after = distribution_sha256("fixture-runtime")
    assert before != after
