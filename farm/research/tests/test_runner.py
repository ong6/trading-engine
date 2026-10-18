import importlib
import json
import os
from copy import deepcopy

from engine.lib.resources import write_text_atomic
from farm.research.artifacts import build_study_artifacts
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
    strategy_parameters=None, job_shape=(1, 1), reconcile=True,
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
    preliminary = StudySpec.from_dict(contract)
    ledger_path = base / "census.jsonl"
    ledger_path.unlink()
    ledger = JsonlTrialLedger(ledger_path)
    identity = trial_id(
        preliminary.study_identity_sha256, contract["strategy"]["parameters"]
    )
    ledger.register(
        trial=identity,
        study_sha256=preliminary.study_identity_sha256,
        source_ref={"path": "contract.json", "sha256": preliminary.study_identity_sha256},
        selection_start=140,
    )
    if reconcile:
        ledger.reconcile({"fixture": "f" * 64}, event_id="fixture-reconciliation")
        receipt = ledger.reconciliation_receipt()
        contract["evaluation"]["dsr_census"].update({
            "sha256": file_sha256(ledger_path),
            "selection_n": receipt["selection_n"],
            "register_sha256": receipt["register_sha256"],
            "row_sha256": receipt["row_sha256"],
        })
    else:
        contract["evaluation"]["dsr_census"]["sha256"] = file_sha256(ledger_path)
    spec = StudySpec.from_dict(contract)
    assert spec.study_identity_sha256 == preliminary.study_identity_sha256
    resolved = spec.resolve(base)
    cache = ResearchCache(tmp_path / "cache")

    artifacts = build_study_artifacts(
        cache, resolved, tmp_path / "artifact-build", include_labels=True,
    )
    features, outcomes = artifacts.features, artifacts.labels
    assert outcomes is not None
    runner = StudyRunner(resolved, ledger=ledger, work_root=tmp_path / "work")
    return spec, ledger, runner, identity, features, outcomes


def test_runner_records_start_before_outcome_mount_and_seals_child_predictions(tmp_path):
    spec, ledger, runner, identity, features, outcomes = _setup(tmp_path)

    class OutcomeSentinel:
        def __init__(self, wrapped, seal):
            self.wrapped = wrapped
            self.seal = seal

        def __getattr__(self, name):
            if name == "data_path" and not self.seal.is_file():
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
    assert [row["kind"] for row in rows] == [
        "registered", "inventory_reconciliation", "evaluation_started", "evaluated",
    ]
    assert rows[2]["payload"]["source_ref"]["feature_sha256"] == features.digest
    assert run.outcome_accessed and run.result_path is not None
    predictions = json.loads(run.predictions_path.read_text())
    prediction = predictions["jobs"][0]["prediction"]
    assert prediction["pid"] != os.getpid()
    assert prediction["features"][0]["score"] == 1.0
    result = json.loads(run.result_path.read_text())
    assert result["verdict"] == "admit"
    assert result["evaluation"]["labels"][0]["return_h1"] == pytest.approx(0.01)
    assert run.predictions_path.stat().st_mode & 0o222 == 0


def test_pilot_cannot_mount_outcomes_and_produces_no_result(tmp_path):
    _, ledger, runner, identity, features, outcomes = _setup(tmp_path, phase="pilot")
    with pytest.raises(StudyRunError, match="cannot receive"):
        runner.run(trial=identity, attempt="bad-pilot", features=features, outcomes=outcomes)
    run = runner.run(trial=identity, attempt="pilot-1", features=features)
    assert not run.outcome_accessed and run.result_path is None
    assert [row["kind"] for row in ledger.read()] == [
        "registered", "inventory_reconciliation", "evaluation_started", "evaluated",
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
    assert [row["kind"] for row in ledger.read()] == [
        "registered", "inventory_reconciliation",
    ]

    changed = deepcopy(spec.cache_identity("label"))
    changed["inputs"]["generation_sha256"] = "9" * 64
    same_cache = ResearchCache(features.path.parents[3])
    def late_writer(path):
        write_text_atomic(path / "labels.json", "{}\n")
        return {"schema": "late"}

    late = same_cache.build("label", changed, late_writer)
    with pytest.raises(StudyRunError, match="identity differs"):
        runner.run(trial=identity, attempt="late-label", features=features, outcomes=late)
    assert [row["kind"] for row in ledger.read()] == [
        "registered", "inventory_reconciliation", "evaluation_started", "failed",
    ]


def test_runner_refuses_generic_cache_object_even_with_exact_claimed_identity(tmp_path):
    spec, ledger, runner, identity, _, outcomes = _setup(tmp_path)
    cache = ResearchCache(tmp_path / "forged-cache")

    def writer(path):
        nodes = path / "nodes"
        nodes.mkdir()
        write_text_atomic(nodes / "fixture.json", "[]\n")
        return {"format": "forged"}

    forged = cache.build("feature", spec.cache_identity("feature"), writer)
    with pytest.raises(Exception, match="validated StudySpec receipt"):
        runner.run(
            trial=identity, attempt="forged", features=forged, outcomes=outcomes,
        )
    assert [row["kind"] for row in ledger.read()] == [
        "registered", "inventory_reconciliation",
    ]


def test_holdout_crash_consumes_one_shot_lease_and_retry_is_refused(tmp_path):
    _, ledger, runner, identity, features, outcomes = _setup(
        tmp_path, phase="holdout", callback="crashing_strategy",
    )
    with pytest.raises(Exception, match="sandboxed callback failed"):
        runner.run(trial=identity, attempt="holdout-crash", features=features, outcomes=outcomes)
    assert [row["kind"] for row in ledger.read()] == [
        "registered", "inventory_reconciliation", "evaluation_started", "holdout_opened", "failed",
    ]
    ledger.reconcile({"fixture": "f" * 64}, event_id="post-crash-reconciliation")
    receipt = ledger.reconciliation_receipt()
    document = runner.resolved.spec.as_dict()
    document["evaluation"]["dsr_census"].update({
        "sha256": file_sha256(ledger.path),
        "selection_n": receipt["selection_n"],
        "register_sha256": receipt["register_sha256"],
        "row_sha256": receipt["row_sha256"],
    })
    updated = StudySpec.from_dict(document).resolve(runner.resolved.base_dir)
    runner = StudyRunner(updated, ledger=ledger, work_root=tmp_path / "work")
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
    assert prediction["feature"][0]["score"] == 1.0
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


def test_runner_refuses_output_under_resolved_private_repository_from_other_cwd(
    tmp_path, monkeypatch,
):
    private = tmp_path / "private"
    private.mkdir()
    write_text_atomic(private / ".git", "gitdir: elsewhere\n")
    contract_root = private / "contract"
    contract_root.mkdir()
    contract = complete_contract(contract_root)
    spec = StudySpec.from_dict(contract)
    resolved = spec.resolve(contract_root)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)
    with pytest.raises(ValueError, match="outside"):
        StudyRunner(
            resolved,
            ledger=JsonlTrialLedger(tmp_path / "events.jsonl"),
            work_root=private / "runs",
        )


@pytest.mark.parametrize("state", ["unreconciled", "stale"])
def test_outcome_access_is_impossible_without_current_reconciled_census(tmp_path, state):
    _, ledger, runner, identity, features, outcomes = _setup(
        tmp_path, reconcile=state != "unreconciled",
    )
    if state == "stale":
        ledger.register(
            trial="later-selection",
            study_sha256="d" * 64,
            source_ref={"path": "later.json", "sha256": "e" * 64},
            selection_start=141,
        )

    class OutcomeSentinel:
        def __getattribute__(self, name):
            raise AssertionError(f"outcome touched while census was {state}: {name}")

    with pytest.raises(Exception, match=state):
        runner.run(
            trial=identity,
            attempt=state,
            features=features,
            outcomes=OutcomeSentinel(),
        )
    assert not any(row["kind"] == "evaluation_started" for row in ledger.read())
