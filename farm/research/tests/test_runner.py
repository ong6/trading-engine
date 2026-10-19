import importlib
import json
import os

from engine.lib.resources import write_text_atomic
from farm.research.artifacts import build_study_artifacts
from farm.research.cache import ResearchCache
from farm.research.canonical import file_sha256
from farm.research.runner import StudyRunError, StudyRunner, main
from farm.research.sandbox import SandboxError, build_callback_package, run_sandboxed
from farm.research.spec import StudySpec
from farm.research.tests.support import complete_contract
from farm.research.trials import JsonlTrialLedger, TrialLedgerError, trial_id

pytest = importlib.import_module("pytest")


def _setup(
    tmp_path, *, phase="development", callback="strategy", workers=1,
    strategy_parameters=None, job_shape=(1, 1), reconcile=True,
    evaluation_callback="evaluation_recipe", label_callback="label_recipe",
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
    boundaries = [
        ("2024-01-01", "2024-01-03"),
        ("2024-01-03", "2024-07-01"),
    ]
    contract["evaluation"]["folds"] = [
        {"name": f"fold-{index}", "start": boundaries[index][0], "end": boundaries[index][1]}
        for index in range(job_shape[1])
    ]
    callback_path = base / "callbacks" / "study_fixture_callbacks.py"
    contract["strategy"]["callback"]["function"] = callback
    contract["strategy"]["callback"]["sha256"] = file_sha256(callback_path)
    contract["features"][0]["callback"]["sha256"] = file_sha256(callback_path)
    contract["outcomes"]["callback"]["sha256"] = file_sha256(callback_path)
    contract["outcomes"]["callback"]["function"] = label_callback
    contract["evaluation"]["callback"]["function"] = evaluation_callback
    contract["evaluation"]["callback"]["sha256"] = file_sha256(callback_path)
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

    artifacts = build_study_artifacts(cache, resolved, tmp_path / "artifact-build")
    features = artifacts.features
    runner = StudyRunner(resolved, ledger=ledger, work_root=tmp_path / "work")
    return spec, ledger, runner, identity, features


def test_runner_records_start_and_seals_predictions_before_building_labels(tmp_path, monkeypatch):
    import farm.research.runner as runner_module

    spec, ledger, runner, identity, features = _setup(tmp_path)
    original = runner_module.build_label_artifact

    def checked_builder(*args, **kwargs):
        seal = tmp_path / "work" / "synthetic-contract" / "v1" / "development-1" / "predictions.json"
        assert seal.is_file()
        assert any(row["kind"] == "evaluation_started" for row in ledger.read())
        return original(*args, **kwargs)

    monkeypatch.setattr(runner_module, "build_label_artifact", checked_builder)
    run = runner.run(trial=identity, attempt="development-1", features=features)
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


def test_pilot_never_builds_label_object_and_produces_no_result(tmp_path):
    spec, ledger, runner, identity, features = _setup(tmp_path, phase="pilot")
    run = runner.run(trial=identity, attempt="pilot-1", features=features)
    assert not run.outcome_accessed and run.result_path is None
    assert ResearchCache(features.path.parents[3]).get(
        "label", spec.cache_identity("label")
    ) is None
    assert [row["kind"] for row in ledger.read()] == [
        "registered", "inventory_reconciliation", "evaluation_started", "evaluated",
    ]


def test_wrong_feature_identity_refuses_before_evaluation(tmp_path):
    _, ledger, runner, identity, _, = _setup(tmp_path)
    cache = ResearchCache(tmp_path / "other-cache")

    def wrong_writer(path):
        write_text_atomic(path / "features.json", "{}\n")
        return {"schema": "wrong"}

    wrong = cache.build("feature", {"wrong": True}, wrong_writer)
    with pytest.raises(StudyRunError, match="identity differs"):
        runner.run(trial=identity, attempt="wrong-feature", features=wrong)
    assert [row["kind"] for row in ledger.read()] == [
        "registered", "inventory_reconciliation",
    ]



def test_runner_refuses_generic_cache_object_even_with_exact_claimed_identity(tmp_path):
    spec, ledger, runner, identity, _ = _setup(tmp_path)
    cache = ResearchCache(tmp_path / "forged-cache")

    def writer(path):
        nodes = path / "nodes"
        nodes.mkdir()
        write_text_atomic(nodes / "fixture.json", "[]\n")
        return {"format": "forged"}

    forged = cache.build("feature", spec.cache_identity("feature"), writer)
    with pytest.raises(Exception, match="validated StudySpec receipt"):
        runner.run(
            trial=identity, attempt="forged", features=forged,
        )
    assert [row["kind"] for row in ledger.read()] == [
        "registered", "inventory_reconciliation",
    ]


def test_holdout_crash_consumes_one_shot_lease_and_retry_is_refused(tmp_path):
    _, ledger, runner, identity, features = _setup(
        tmp_path, phase="holdout", callback="crashing_strategy",
    )
    with pytest.raises(Exception, match="sandboxed callback failed"):
        runner.run(trial=identity, attempt="holdout-crash", features=features)
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
        runner.run(trial=identity, attempt="holdout-retry", features=features)
    assert [row["kind"] for row in ledger.read()][-2:] == ["evaluation_started", "failed"]


def test_serial_parallel_declarations_produce_identical_prediction_and_result_bytes(tmp_path):
    first = _setup(
        tmp_path / "serial", callback="slow_strategy", workers=1, job_shape=(2, 2),
    )
    second = _setup(
        tmp_path / "parallel", callback="slow_strategy", workers=4, job_shape=(2, 2),
    )
    run_one = first[2].run(
        trial=first[3], attempt="run", features=first[4],
    )
    run_two = second[2].run(
        trial=second[3], attempt="run", features=second[4],
    )
    assert run_one.predictions_path.read_bytes() == run_two.predictions_path.read_bytes()
    assert run_one.result_path.read_bytes() == run_two.result_path.read_bytes()
    serial_receipt = json.loads((run_one.run_directory / "receipt.json").read_text())
    parallel_receipt = json.loads((run_two.run_directory / "receipt.json").read_text())
    assert serial_receipt["strategy_workers"]["max_concurrent"] == 1
    assert parallel_receipt["strategy_workers"]["used"] == 4
    assert parallel_receipt["strategy_workers"]["max_concurrent"] >= 2
    assert len(set(parallel_receipt["strategy_workers"]["pids"])) == 6
    jobs = json.loads(run_two.predictions_path.read_text())["jobs"]
    assert len(jobs) == 6
    assert {job["kind"] for job in jobs} == {"variant", "control"}
    for job in jobs:
        sessions = [row["session"] for row in job["prediction"]["features"]]
        assert sessions == (["2024-01-02"] if job["fold"] == "fold-0" else ["2024-01-03"])


def test_pilot_callback_cannot_escape_os_sandbox_to_outcomes_network_or_processes(tmp_path):
    absolute_outcome = tmp_path / "outside" / "labels.txt"
    absolute_outcome.parent.mkdir()
    write_text_atomic(absolute_outcome, "ABSOLUTE_OUTCOME_BYTES\n")
    _, _, runner, identity, features = _setup(
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
    dependency = base / "callbacks" / "round2_dependency.py"
    callback = base / "callbacks" / "round2_callback.py"
    write_text_atomic(dependency, "VALUE = 1\n")
    write_text_atomic(
        callback,
        "from round2_dependency import VALUE\n"
        "def strategy(features, parameters, seed, mode):\n    return {'value': VALUE}\n"
        "def outcomes(predictions, labels, evaluation):\n    return {'value': VALUE}\n",
    )
    contract = complete_contract(base)
    reference = {
        "module": "round2_callback",
        "function": "strategy" if section == "strategy" else "outcomes",
        "source": "callbacks/round2_callback.py",
        "kind": "module",
        "sha256": file_sha256(callback),
        "dependencies": [{
            "module": "round2_dependency",
            "source": "callbacks/round2_dependency.py",
            "kind": "module",
            "sha256": file_sha256(dependency),
        }],
    }
    contract[section]["callback"] = reference
    spec = StudySpec.from_dict(contract)
    resolved = spec.resolve(base)
    write_text_atomic(dependency, "VALUE = 2\n")
    with pytest.raises(Exception, match="dependency changed after resolution"):
        build_callback_package(resolved, reference, tmp_path / "execution")


def test_sandbox_refuses_undeclared_runtime_import(tmp_path):
    base = tmp_path / "contract"
    base.mkdir()
    contract = complete_contract(base)
    callback = base / "callbacks" / "undeclared_callback.py"
    write_text_atomic(
        callback,
        "import numpy\n"
        "def strategy(features, parameters, seed, mode):\n    return {'value': 1}\n",
    )
    reference = {
        "module": "undeclared_callback",
        "function": "strategy",
        "source": "callbacks/undeclared_callback.py",
        "kind": "module",
        "sha256": file_sha256(callback),
        "dependencies": [],
    }
    contract["strategy"]["callback"] = reference
    resolved = StudySpec.from_dict(contract).resolve(base)
    package = build_callback_package(resolved, reference, tmp_path / "execution")
    feature_root = tmp_path / "features"
    feature_root.mkdir()
    write_text_atomic(feature_root / "fixture.json", "{}\n")
    with pytest.raises(SandboxError, match="undeclared callback import: numpy"):
        run_sandboxed(
            package,
            {
                "callback": reference,
                "package_sha256": package.digest,
                "parameters": {},
                "seed": 1,
                "phase": "pilot",
                "mode": "strategy",
                "memory_mb": 256,
            },
            feature_root=feature_root,
            label_root=None,
            runtime_root=tmp_path / "execution",
            timeout=5,
        )


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


def test_cli_rejects_repository_work_root_before_creating_artifacts(tmp_path):
    base = tmp_path / "contract"
    base.mkdir()
    contract = complete_contract(base)
    spec_path = base / "study.json"
    write_text_atomic(spec_path, json.dumps(contract))
    repository = tmp_path / "private"
    repository.mkdir()
    write_text_atomic(repository / ".git", "gitdir: elsewhere\n")
    with pytest.raises(ValueError, match="outside"):
        main([
            "--spec", str(spec_path),
            "--base-dir", str(base),
            "--cache-root", str(tmp_path / "cache"),
            "--work-root", str(repository / "runs"),
            "--ledger", str(base / "census.jsonl"),
            "--trial", "trial",
            "--attempt", "attempt",
        ])
    assert not (repository / "runs").exists()


@pytest.mark.parametrize("state", ["unreconciled", "stale"])
def test_outcome_access_is_impossible_without_current_reconciled_census(tmp_path, state):
    _, ledger, runner, identity, features = _setup(
        tmp_path, reconcile=state != "unreconciled",
    )
    if state == "stale":
        ledger.register(
            trial="later-selection",
            study_sha256="d" * 64,
            source_ref={"path": "later.json", "sha256": "e" * 64},
            selection_start=141,
        )

    with pytest.raises(Exception, match=state):
        runner.run(
            trial=identity,
            attempt=state,
            features=features,
        )
    assert not any(row["kind"] == "evaluation_started" for row in ledger.read())


def test_concurrent_selection_before_terminal_quarantines_result(tmp_path, monkeypatch):
    import farm.research.runner as runner_module

    _, ledger, runner, identity, features = _setup(tmp_path)
    original = runner_module._verdict

    def register_during_evaluation(result, rules):
        ledger.register(
            trial="concurrent-selection",
            study_sha256="d" * 64,
            source_ref={"path": "concurrent.json", "sha256": "e" * 64},
            selection_start=141,
        )
        return original(result, rules)

    monkeypatch.setattr(runner_module, "_verdict", register_during_evaluation)
    with pytest.raises(TrialLedgerError, match="quarantined"):
        runner.run(trial=identity, attempt="race", features=features)
    kinds = [row["kind"] for row in ledger.read()]
    assert kinds[-3:] == ["evaluation_started", "registered", "failed"]
    assert "evaluated" not in kinds
    quarantine = tmp_path / "work" / "synthetic-contract" / "v1" / "race" / "result.quarantined.json"
    assert quarantine.is_file()


def test_missing_declared_control_refuses_evaluated_terminal(tmp_path):
    _, ledger, runner, identity, features = _setup(
        tmp_path, evaluation_callback="missing_control_evaluation",
    )
    with pytest.raises(StudyRunError, match="every declared control"):
        runner.run(trial=identity, attempt="missing-control", features=features)
    assert [row["kind"] for row in ledger.read()][-2:] == ["evaluation_started", "failed"]


def test_misaligned_fold_labels_refuse_evaluated_terminal(tmp_path):
    _, ledger, runner, identity, features = _setup(
        tmp_path, job_shape=(1, 2), label_callback="misaligned_label_recipe",
    )
    with pytest.raises(Exception, match="row keys are not fold-aligned"):
        runner.run(trial=identity, attempt="misaligned", features=features)
    assert [row["kind"] for row in ledger.read()][-2:] == ["evaluation_started", "failed"]


def test_overlapping_pass_and_admit_thresholds_use_pass_precedence(tmp_path):
    _, _, runner, identity, features = _setup(
        tmp_path, evaluation_callback="strong_evaluation_recipe",
    )
    run = runner.run(trial=identity, attempt="strong", features=features)
    assert json.loads(run.result_path.read_text())["verdict"] == "pass"
