import importlib
import json
import os
from copy import deepcopy

from engine.lib.resources import write_text_atomic
from farm.research.cache import ResearchCache
from farm.research.canonical import file_sha256
from farm.research.runner import StudyRunError, StudyRunner
from farm.research.sandbox import build_callback_package
from farm.research.spec import StudySpec
from farm.research.tests.support import complete_contract
from farm.research.trials import JsonlTrialLedger, trial_id

pytest = importlib.import_module("pytest")


def _setup(
    tmp_path, *, phase="development", callback="strategy", workers=1,
    strategy_parameters=None, job_shape=(1, 1),
):
    base = tmp_path / "contract"
    base.mkdir(parents=True)
    contract = complete_contract(base)
    contract["study"]["phase"] = phase
    contract["execution"]["workers"] = workers
    if strategy_parameters is not None:
        contract["strategy"]["parameters"] = strategy_parameters
    contract["evaluation"]["variants"] = [
        {"name": f"variant-{index}", "parameters": {"variant_value": index}}
        for index in range(job_shape[0])
    ]
    contract["evaluation"]["folds"] = [
        {"name": f"fold-{index}", "start": "2024-01-01", "end": "2024-07-01"}
        for index in range(job_shape[1])
    ]
    callback_path = __import__(
        "farm.research.tests.fixture_callbacks", fromlist=["fixture_callbacks"]
    ).__file__
    contract["strategy"]["callback"]["function"] = callback
    contract["strategy"]["callback"]["sha256"] = file_sha256(callback_path)
    contract["features"][0]["callback"]["sha256"] = file_sha256(callback_path)
    contract["outcomes"]["callback"]["sha256"] = file_sha256(callback_path)
    spec = StudySpec.from_dict(contract)
    resolved = spec.resolve(base)
    cache = ResearchCache(tmp_path / "cache")

    def feature_writer(path):
        write_text_atomic(path / "features.json", '{"scores":[1,2,3]}\n')
        return {"schema": "fixture-feature-v1"}

    def label_writer(path):
        write_text_atomic(path / "labels.json", '{"returns":[0.1,-0.1,0.2]}\n')
        return {"schema": "fixture-label-v1"}

    features = cache.build("feature", spec.cache_identity("feature"), feature_writer)
    outcomes = cache.build("label", spec.cache_identity("label"), label_writer)
    ledger = JsonlTrialLedger(tmp_path / "events.jsonl")
    identity = trial_id(spec.sha256, contract["strategy"]["parameters"])
    ledger.register(
        trial=identity, study_sha256=spec.sha256,
        source_ref={"path": "contract.json", "sha256": spec.sha256},
        selection_start=140,
    )
    runner = StudyRunner(resolved, ledger=ledger, work_root=tmp_path / "work")
    return spec, ledger, runner, identity, features, outcomes


def test_runner_records_start_before_outcome_mount_and_seals_child_predictions(tmp_path):
    spec, ledger, runner, identity, features, outcomes = _setup(tmp_path)

    class OutcomeSentinel:
        def __init__(self, wrapped, seal):
            self.wrapped = wrapped
            self.seal = seal

        def __getattr__(self, name):
            if not self.seal.is_file():
                raise AssertionError("outcome object was touched before predictions were sealed")
            return getattr(self.wrapped, name)

    guarded_outcomes = OutcomeSentinel(
        outcomes,
        tmp_path / "work" / "synthetic-contract" / "v1" / "development-1" / "predictions.json",
    )
    run = runner.run(
        trial=identity, attempt="development-1", features=features, outcomes=guarded_outcomes,
    )
    rows = ledger.read()
    assert [row["kind"] for row in rows] == ["registered", "evaluation_started", "evaluated"]
    assert rows[1]["payload"]["source_ref"]["feature_sha256"] == features.digest
    assert run.outcome_accessed and run.result_path is not None
    predictions = json.loads(run.predictions_path.read_text())
    prediction = predictions["jobs"][0]["prediction"]
    assert prediction["pid"] != os.getpid()
    assert prediction["features"] == {"scores": [1, 2, 3]}
    assert json.loads(run.result_path.read_text())["labels"] == {"returns": [0.1, -0.1, 0.2]}
    assert run.predictions_path.stat().st_mode & 0o222 == 0


def test_pilot_cannot_mount_outcomes_and_produces_no_result(tmp_path):
    _, ledger, runner, identity, features, outcomes = _setup(tmp_path, phase="pilot")
    with pytest.raises(StudyRunError, match="cannot receive"):
        runner.run(trial=identity, attempt="bad-pilot", features=features, outcomes=outcomes)
    run = runner.run(trial=identity, attempt="pilot-1", features=features)
    assert not run.outcome_accessed and run.result_path is None
    assert [row["kind"] for row in ledger.read()] == [
        "registered", "evaluation_started", "evaluated",
    ]


def test_wrong_feature_or_late_label_identity_refuses_before_evaluation(tmp_path):
    spec, ledger, runner, identity, features, outcomes = _setup(tmp_path)
    cache = ResearchCache(tmp_path / "other-cache")

    def wrong_writer(path):
        write_text_atomic(path / "features.json", "{}\n")
        return {"schema": "wrong"}

    wrong = cache.build("feature", {"wrong": True}, wrong_writer)
    with pytest.raises(StudyRunError, match="identity differs"):
        runner.run(trial=identity, attempt="wrong-feature", features=wrong, outcomes=outcomes)
    assert [row["kind"] for row in ledger.read()] == ["registered"]

    changed = deepcopy(spec.cache_identity("label"))
    changed["source"]["generation_sha256"] = "9" * 64
    def late_writer(path):
        write_text_atomic(path / "labels.json", "{}\n")
        return {"schema": "late"}

    late = cache.build("label", changed, late_writer)
    with pytest.raises(StudyRunError, match="identity differs"):
        runner.run(trial=identity, attempt="late-label", features=features, outcomes=late)
    assert [row["kind"] for row in ledger.read()] == [
        "registered", "evaluation_started", "failed",
    ]


def test_holdout_crash_consumes_one_shot_lease_and_retry_is_refused(tmp_path):
    _, ledger, runner, identity, features, outcomes = _setup(
        tmp_path, phase="holdout", callback="crashing_strategy",
    )
    with pytest.raises(Exception, match="sandboxed callback failed"):
        runner.run(trial=identity, attempt="holdout-crash", features=features, outcomes=outcomes)
    assert [row["kind"] for row in ledger.read()] == [
        "registered", "evaluation_started", "holdout_opened", "failed",
    ]
    with pytest.raises(StudyRunError, match="already been opened"):
        runner.run(trial=identity, attempt="holdout-retry", features=features, outcomes=outcomes)
    assert [row["kind"] for row in ledger.read()][-2:] == ["evaluation_started", "failed"]


def test_serial_parallel_declarations_produce_identical_prediction_and_result_bytes(tmp_path):
    first = _setup(
        tmp_path / "serial", callback="slow_strategy", workers=1, job_shape=(2, 2),
    )
    second = _setup(
        tmp_path / "parallel", callback="slow_strategy", workers=4, job_shape=(2, 2),
    )
    run_one = first[2].run(
        trial=first[3], attempt="run", features=first[4], outcomes=first[5],
    )
    run_two = second[2].run(
        trial=second[3], attempt="run", features=second[4], outcomes=second[5],
    )
    assert run_one.predictions_path.read_bytes() == run_two.predictions_path.read_bytes()
    assert run_one.result_path.read_bytes() == run_two.result_path.read_bytes()
    serial_receipt = json.loads((run_one.run_directory / "receipt.json").read_text())
    parallel_receipt = json.loads((run_two.run_directory / "receipt.json").read_text())
    assert serial_receipt["strategy_workers"]["max_concurrent"] == 1
    assert parallel_receipt["strategy_workers"]["used"] == 4
    assert parallel_receipt["strategy_workers"]["max_concurrent"] >= 2
    assert len(set(parallel_receipt["strategy_workers"]["pids"])) == 4


def test_pilot_callback_cannot_escape_os_sandbox_to_outcomes_network_or_processes(tmp_path):
    absolute_outcome = tmp_path / "outside" / "labels.txt"
    absolute_outcome.parent.mkdir()
    write_text_atomic(absolute_outcome, "ABSOLUTE_OUTCOME_BYTES\n")
    _, _, runner, identity, features, _ = _setup(
        tmp_path,
        phase="pilot",
        callback="adversarial_strategy",
        strategy_parameters={"absolute_outcome": str(absolute_outcome)},
    )
    run = runner.run(trial=identity, attempt="adversarial", features=features)
    predictions = json.loads(run.predictions_path.read_text())
    prediction = predictions["jobs"][0]["prediction"]
    assert prediction["feature"] == {"scores": [1, 2, 3]}
    assert all(item["blocked"] for item in prediction["checks"].values())
    assert "OUTCOME_BYTES" not in run.predictions_path.read_text()


@pytest.mark.parametrize("section", ["strategy", "outcomes"])
def test_execution_package_refuses_dependency_drift_after_resolve(
    tmp_path, monkeypatch, section,
):
    base = tmp_path / "contract"
    base.mkdir()
    dependency = tmp_path / "round2_dependency.py"
    callback = tmp_path / "round2_callback.py"
    write_text_atomic(dependency, "VALUE = 1\n")
    write_text_atomic(
        callback,
        "from round2_dependency import VALUE\n"
        "def strategy(features, parameters, seed, mode):\n    return {'value': VALUE}\n"
        "def outcomes(predictions, labels, evaluation):\n    return {'value': VALUE}\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    contract = complete_contract(base)
    reference = {
        "module": "round2_callback",
        "function": "strategy" if section == "strategy" else "outcomes",
        "sha256": file_sha256(callback),
        "dependencies": [{
            "module": "round2_dependency",
            "sha256": file_sha256(dependency),
        }],
    }
    contract[section]["callback"] = reference
    spec = StudySpec.from_dict(contract)
    resolved = spec.resolve(base)
    write_text_atomic(dependency, "VALUE = 2\n")
    with pytest.raises(Exception, match="dependency changed after resolution"):
        build_callback_package(resolved, reference, tmp_path / "execution")
