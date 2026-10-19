import importlib
import json
from pathlib import Path

from engine.lib.resources import write_text_atomic
from farm.research.artifacts import build_study_artifacts
from farm.research.cache import ResearchCache
from farm.research.canonical import file_sha256
from farm.research.runner import StudyRunError, StudyRunner, _verdict, main
from farm.research.sandbox import SandboxError, build_callback_package, run_sandboxed
from farm.research.spec import StudySpec
from farm.research.tests.support import complete_contract

pytest = importlib.import_module("pytest")


def _setup(
    tmp_path, *, phase="development", callback="strategy", workers=1,
    strategy_parameters=None, job_shape=(1, 1),
    label_callback="label_recipe", statistics=None,
):
    base = tmp_path / "contract"
    base.mkdir(parents=True)
    contract = complete_contract(base)
    contract["study"]["phase"] = phase
    contract["execution"]["workers"] = workers
    if strategy_parameters is not None:
        contract["strategy"]["parameters"] = strategy_parameters
    if statistics is not None:
        contract["evaluation"]["statistics"] = statistics
    contract["evaluation"]["variants"] = [
        {"name": f"variant-{index}", "parameters": {"variant_value": index}}
        for index in range(job_shape[0])
    ]
    boundaries = [("2024-01-01", "2024-01-03"), ("2024-01-03", "2024-07-01")]
    contract["evaluation"]["folds"] = [
        {"name": f"fold-{index}", "start": boundaries[index][0], "end": boundaries[index][1]}
        for index in range(job_shape[1])
    ]
    callback_path = base / "callbacks" / "study_fixture_callbacks.py"
    contract["strategy"]["callback"]["function"] = callback
    contract["strategy"]["callback"]["sha256"] = file_sha256(callback_path)
    contract["features"][0]["callback"]["sha256"] = file_sha256(callback_path)
    contract["outcomes"]["callback"]["function"] = label_callback
    contract["outcomes"]["callback"]["sha256"] = file_sha256(callback_path)
    spec = StudySpec.from_dict(contract)
    resolved = spec.resolve(base)
    cache = ResearchCache(tmp_path / "cache")
    features = build_study_artifacts(
        cache, resolved, tmp_path / "artifact-build",
    ).features
    runner = StudyRunner(resolved, work_root=tmp_path / "work")
    return spec, runner, features


def test_runner_seals_start_and_predictions_before_issuing_label_capability(tmp_path, monkeypatch):
    import farm.research.runner as runner_module

    _, runner, features = _setup(tmp_path)
    original = runner_module._build_label_artifact

    def checked_builder(cache, resolved, root, capability):
        run = tmp_path / "work" / "synthetic-contract" / "v1" / "development-1"
        assert (run / "attempt-started.json").is_file()
        assert (run / "predictions.json").is_file()
        assert capability.attempt_id == "development-1"
        assert capability.predictions_sha256 == file_sha256(run / "predictions.json")
        return original(cache, resolved, root, capability)

    monkeypatch.setattr(runner_module, "_build_label_artifact", checked_builder)
    result = runner.run(attempt="development-1", features=features)
    assert result.outcome_accessed and result.result_path is not None
    prediction = json.loads(result.predictions_path.read_text())["jobs"][0]["prediction"]
    assert prediction == {"positions": [{"session": "2024-01-02", "weight": 1.0}]}
    assert json.loads(result.result_path.read_text())["variant_verdicts"] == [
        {"name": "variant-0", "verdict": "admit"},
    ]
    evaluation = json.loads(result.result_path.read_text())["evaluation"]
    assert evaluation["jobs"][0]["gross_return"] == pytest.approx(0.01)
    assert result.predictions_path.stat().st_mode & 0o222 == 0


def test_label_cache_receipt_is_bound_to_the_current_attempt(tmp_path):
    _, runner, features = _setup(tmp_path)
    first = runner.run(attempt="attempt-one", features=features)
    second = runner.run(attempt="attempt-two", features=features)
    cache_root = features.path.parents[3]
    receipts = []
    label_digests = []
    for result, attempt in ((first, "attempt-one"), (second, "attempt-two")):
        run_receipt = json.loads((result.run_directory / "receipt.json").read_text())
        label_digest = run_receipt["label_sha256"]
        label_digests.append(label_digest)
        manifest = json.loads((
            cache_root / "outcomes" / "objects" / "sha256" / label_digest / "manifest.json"
        ).read_text())
        capability = manifest["metadata"]["validated_study_receipt"]["attempt_capability"]
        assert capability["attempt_id"] == attempt
        assert capability["predictions_sha256"] == result.predictions_sha256
        assert manifest["identity"]["attempt_capability"] == capability
        receipts.append(capability)
    assert label_digests[0] != label_digests[1]
    assert receipts[0] != receipts[1]


def test_attempt_start_and_holdout_directories_are_fsynced_before_callbacks(
    tmp_path, monkeypatch,
):
    import farm.research.runner as runner_module

    _, runner, features = _setup(tmp_path, phase="holdout")
    synced = []
    original_fsync_directory = runner_module._fsync_directory
    original_run_sandboxed = runner_module.run_sandboxed
    run_directory = (
        tmp_path / "work" / "synthetic-contract" / "v1" / "durable-holdout"
    ).resolve()
    holdout_directory = (tmp_path / "work" / "holdout").resolve()

    def recording_fsync(path):
        original_fsync_directory(path)
        synced.append(Path(path).resolve())

    def checked_run_sandboxed(*args, **kwargs):
        assert run_directory in synced
        assert holdout_directory in synced
        return original_run_sandboxed(*args, **kwargs)

    monkeypatch.setattr(runner_module, "_fsync_directory", recording_fsync)
    monkeypatch.setattr(runner_module, "run_sandboxed", checked_run_sandboxed)
    runner.run(attempt="durable-holdout", features=features)


def test_pilot_never_builds_label_object(tmp_path):
    spec, runner, features = _setup(tmp_path, phase="pilot")
    result = runner.run(attempt="pilot-1", features=features)
    assert not result.outcome_accessed and result.result_path is None
    assert ResearchCache(features.path.parents[3]).get("label", spec.cache_identity("label")) is None


def test_wrong_feature_identity_and_generic_object_are_refused(tmp_path):
    spec, runner, _ = _setup(tmp_path)
    cache = ResearchCache(tmp_path / "other-cache")

    def wrong_writer(path):
        write_text_atomic(path / "features.json", "{}\n")
        return {"schema": "wrong"}

    wrong = cache.build("feature", {"wrong": True}, wrong_writer)
    with pytest.raises(StudyRunError, match="identity differs"):
        runner.run(attempt="wrong-feature", features=wrong)

    def forged_writer(path):
        nodes = path / "nodes"
        nodes.mkdir()
        write_text_atomic(nodes / "fixture.json", "[]\n")
        return {"format": "forged"}

    forged = cache.build("feature", spec.cache_identity("feature"), forged_writer)
    with pytest.raises(Exception, match="validated StudySpec receipt"):
        runner.run(attempt="forged", features=forged)


def test_holdout_crash_consumes_one_shot_lease(tmp_path):
    _, runner, features = _setup(tmp_path, phase="holdout", callback="crashing_strategy")
    with pytest.raises(Exception, match="sandboxed callback failed"):
        runner.run(attempt="holdout-crash", features=features)
    with pytest.raises(StudyRunError, match="already been opened"):
        runner.run(attempt="holdout-retry", features=features)


def test_serial_parallel_fold_control_jobs_are_identical_and_decision_bounded(tmp_path):
    first = _setup(tmp_path / "serial", callback="slow_strategy", workers=1, job_shape=(2, 2))
    second = _setup(tmp_path / "parallel", callback="slow_strategy", workers=4, job_shape=(2, 2))
    run_one = first[1].run(attempt="run", features=first[2])
    run_two = second[1].run(attempt="run", features=second[2])
    assert run_one.predictions_path.read_bytes() == run_two.predictions_path.read_bytes()
    assert run_one.result_path.read_bytes() == run_two.result_path.read_bytes()
    serial = json.loads((run_one.run_directory / "receipt.json").read_text())
    parallel = json.loads((run_two.run_directory / "receipt.json").read_text())
    assert serial["strategy_workers"]["max_concurrent"] == 1
    assert parallel["strategy_workers"]["used"] == 4
    assert parallel["strategy_workers"]["max_concurrent"] >= 2
    jobs = json.loads(run_two.predictions_path.read_text())["jobs"]
    assert len(jobs) == 6 and {job["kind"] for job in jobs} == {"variant", "control"}
    for job in jobs:
        if job["kind"] == "control":
            assert job["prediction"] == {"positions": []}
        else:
            assert job["prediction"] == {
                "positions": [{"session": job["decision_session"], "weight": 1.0}]
            }


def test_variants_receive_separate_metrics_verdicts_and_distinct_decision_counts(tmp_path):
    _, runner, features = _setup(
        tmp_path, callback="variant_direction_strategy", job_shape=(2, 1),
        statistics=["mean_net_return", "observation_count"],
    )
    run = runner.run(attempt="variant-verdicts", features=features)
    result = json.loads(run.result_path.read_text())

    assert "verdict" not in result
    assert result["variant_verdicts"] == [
        {"name": "variant-0", "verdict": "admit"},
        {"name": "variant-1", "verdict": "kill"},
    ]
    variants = {row["name"]: row for row in result["evaluation"]["variants"]}
    assert variants["variant-0"]["metrics"]["observation_count"] == 1.0
    assert variants["variant-1"]["metrics"]["observation_count"] == 1.0
    assert variants["variant-0"]["metrics"]["mean_net_return"] > 0
    assert variants["variant-1"]["metrics"]["mean_net_return"] < 0


def test_strategy_children_receive_exactly_one_decision_view(tmp_path):
    _, runner, features = _setup(
        tmp_path, callback="single_decision_strategy", job_shape=(1, 2),
    )
    run = runner.run(attempt="one-decision", features=features)
    assert len(json.loads(run.predictions_path.read_text())["jobs"]) == 4


def test_census_is_one_immutable_snapshot_for_the_whole_attempt(tmp_path):
    _, runner, features = _setup(tmp_path)
    census_path = runner.resolved.evidence_paths[
        runner.resolved.spec.document["evaluation"]["dsr_census"]["path"]
    ]
    snapshot = runner.census
    write_text_atomic(census_path, '{"selection_n":999}\n')
    result = runner.run(attempt="immutable-census", features=features)
    receipt = json.loads((result.run_directory / "receipt.json").read_text())
    assert receipt["census_snapshot"] == snapshot.__dict__
    with pytest.raises(StudyRunError, match="census snapshot bytes differ"):
        StudyRunner(runner.resolved, work_root=tmp_path / "other-work")


def test_misaligned_labels_refuse_result(tmp_path):
    _, runner, features = _setup(
        tmp_path / "alignment", job_shape=(1, 2), label_callback="misaligned_label_recipe",
    )
    with pytest.raises(Exception, match="primary keys are not fold-aligned"):
        runner.run(attempt="misaligned", features=features)


def test_pass_precedes_overlapping_admit_threshold(tmp_path):
    spec, _, _ = _setup(tmp_path)
    evaluation = spec.as_dict()["evaluation"]
    evaluation["rules"]["pass"]["threshold"] = 0.02
    evaluation["rules"]["admit"]["threshold"] = 0.005
    assert _verdict({"metrics": {"mean_net_return": 0.03}}, evaluation) == "pass"


def test_runner_computes_gross_fill_return_and_applies_cost_registry(tmp_path):
    _, runner, features = _setup(tmp_path)
    result = runner.run(attempt="costed", features=features)
    row = next(
        item for item in json.loads(result.result_path.read_text())["evaluation"]["jobs"]
        if item["kind"] == "variant"
    )
    assert row["gross_return"] == pytest.approx(0.01)
    assert row["cost_returns"]["ibkr_tiered_auction_v1"] == pytest.approx(
        5.142455445544554 / 10_000
    )
    assert row["net_returns"]["ibkr_tiered_auction_v1"] == pytest.approx(
        0.01 - 5.142455445544554 / 10_000
    )


def test_strategy_cannot_supply_or_override_gross_returns(tmp_path):
    _, runner, features = _setup(tmp_path, callback="invented_return_strategy")
    with pytest.raises(StudyRunError, match="return only a positions list"):
        runner.run(attempt="invented-return", features=features)


@pytest.mark.parametrize("attempt", ["../escape", "a/b", ".", "..", ""])
def test_attempt_id_must_be_a_token_and_cannot_write_outside_root(tmp_path, attempt):
    _, runner, features = _setup(tmp_path)
    with pytest.raises(StudyRunError, match="safe 1-64 character token"):
        runner.run(attempt=attempt, features=features)
    assert not (tmp_path / "escape").exists()


def test_absolute_attempt_token_cannot_discard_output_root(tmp_path):
    _, runner, features = _setup(tmp_path)
    escaped = tmp_path / "absolute-escape"
    with pytest.raises(StudyRunError, match="safe 1-64 character token"):
        runner.run(attempt=str(escaped), features=features)
    assert not escaped.exists()


def test_pilot_callback_cannot_escape_sandbox(tmp_path):
    secret = tmp_path / "outside" / "labels.txt"
    secret.parent.mkdir()
    write_text_atomic(secret, "ABSOLUTE_OUTCOME_BYTES\n")
    _, runner, features = _setup(
        tmp_path, phase="pilot", callback="adversarial_strategy",
        strategy_parameters={"absolute_outcome": str(secret)},
    )
    run = runner.run(attempt="adversarial", features=features)
    prediction = json.loads(run.predictions_path.read_text())["jobs"][0]["prediction"]
    assert prediction == {"positions": []}


@pytest.mark.parametrize("section", ["strategy", "outcomes"])
def test_execution_package_refuses_dependency_drift(tmp_path, section):
    base = tmp_path / "contract"
    base.mkdir()
    contract = complete_contract(base)
    dependency = base / "callbacks" / "round2_dependency.py"
    callback = base / "callbacks" / "round2_callback.py"
    write_text_atomic(dependency, "VALUE = 1\n")
    write_text_atomic(
        callback,
        "from round2_dependency import VALUE\n"
        "def strategy(features, parameters, seed, mode):\n    return {'value': VALUE}\n"
        "def outcomes(predictions, labels, evaluation):\n    return {'value': VALUE}\n",
    )
    reference = {
        "module": "round2_callback", "function": "strategy" if section == "strategy" else "outcomes",
        "source": "callbacks/round2_callback.py", "kind": "module",
        "sha256": file_sha256(callback),
        "dependencies": [{
            "module": "round2_dependency", "source": "callbacks/round2_dependency.py",
            "kind": "module", "sha256": file_sha256(dependency),
        }],
    }
    contract[section]["callback"] = reference
    resolved = StudySpec.from_dict(contract).resolve(base)
    write_text_atomic(dependency, "VALUE = 2\n")
    with pytest.raises(Exception, match="dependency changed after resolution"):
        build_callback_package(resolved, reference, tmp_path / "execution")


def test_sandbox_refuses_undeclared_runtime_import(tmp_path):
    base = tmp_path / "contract"
    base.mkdir()
    contract = complete_contract(base)
    callback = base / "callbacks" / "undeclared_callback.py"
    write_text_atomic(callback, "import numpy\ndef strategy(features, parameters, seed, mode):\n    return {}\n")
    reference = {
        "module": "undeclared_callback", "function": "strategy",
        "source": "callbacks/undeclared_callback.py", "kind": "module",
        "sha256": file_sha256(callback), "dependencies": [],
    }
    contract["strategy"]["callback"] = reference
    resolved = StudySpec.from_dict(contract).resolve(base)
    package = build_callback_package(resolved, reference, tmp_path / "execution")
    feature_root = tmp_path / "features"
    feature_root.mkdir()
    with pytest.raises(SandboxError, match="undeclared callback import: numpy"):
        run_sandboxed(
            package,
            {"callback": {
                 **reference, "runtime_identity": resolved.spec.document["execution"],
             }, "package_sha256": package.digest, "parameters": {},
             "seed": 1, "phase": "pilot", "mode": "strategy", "memory_mb": 256},
            feature_root=feature_root, label_root=None,
            runtime_root=tmp_path / "execution", timeout=5,
        )


def test_repository_roots_refuse_before_writes(tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir()
    write_text_atomic(private / ".git", "gitdir: elsewhere\n")
    base = tmp_path / "contract"
    base.mkdir()
    contract = complete_contract(base)
    spec_path = base / "study.json"
    write_text_atomic(spec_path, json.dumps(contract))
    resolved = StudySpec.from_dict(contract).resolve(base)
    with pytest.raises(ValueError, match="outside"):
        StudyRunner(resolved, work_root=private / "runs")
    with pytest.raises(ValueError, match="outside"):
        main([
            "--spec", str(spec_path), "--base-dir", str(base),
            "--cache-root", str(tmp_path / "cache"), "--work-root", str(private / "runs"),
            "--attempt", "attempt",
        ])
    assert not (private / "runs").exists()
