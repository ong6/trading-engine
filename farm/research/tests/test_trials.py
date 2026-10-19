import concurrent.futures
import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.lib.resources import write_text_atomic
from farm.research.canonical import canonical_sha256
from farm.research.trials import CensusGenesis, JsonlTrialLedger, TrialLedgerError, trial_id

pytest = importlib.import_module("pytest")

NOW = datetime(2026, 10, 18, 18, tzinfo=timezone.utc)


def _started():
    return {"source_ref": {
        "study_sha256": "a" * 64,
        "feature_sha256": "b" * 64,
        "phase": "development",
    }}


def _terminal(kind, *, attempt, trial):
    if kind == "failed":
        return {"source_ref": {
            "error": "SyntheticFailure", "message": "fixture", "study_sha256": "a" * 64,
        }}
    if kind == "abandoned":
        return {"source_ref": {"reason": "fixture", "evidence_sha256": "c" * 64}}
    return {"source_ref": {
        "attempt_id": attempt,
        "feature_sha256": "b" * 64,
        "label_sha256": "c" * 64,
        "outcome_accessed": True,
        "phase": "development",
        "predictions_sha256": "d" * 64,
        "result_sha256": "e" * 64,
        "study_sha256": "a" * 64,
        "trial_id": trial,
        "census_reconciliation": {},
        "strategy_workers": {},
        "worker_pids": [],
    }}


def _register(ledger, name="trial-a", selection=140, parameters=None):
    identity = trial_id("a" * 64, parameters or {"variant": name})
    return identity, ledger.register(
        trial=identity,
        study_sha256="a" * 64,
        source_ref={"path": "trials/source.csv", "sha256": "b" * 64, "key": name},
        selection_start=selection,
        event_at=NOW,
    )


def test_unevaluable_failed_and_abandoned_attempts_remain_counted(tmp_path):
    ledger = JsonlTrialLedger(tmp_path / "events.jsonl")
    first, _ = _register(ledger)
    for index, terminal in enumerate(("failed", "abandoned", "evaluated"), 1):
        attempt = f"try-{index}"
        ledger.append(
            kind="evaluation_started", event_id=f"start-{index}", trial=first,
                attempt=attempt, payload=_started(),
            event_at=NOW + timedelta(minutes=index),
        )
        ledger.append(
            kind=terminal, event_id=f"terminal-{index}", trial=first,
                attempt=attempt, payload=_terminal(terminal, attempt=attempt, trial=first),
            event_at=NOW + timedelta(minutes=index, seconds=1),
        )
    summary = ledger.summary()
    assert summary.selection_n == 140
    assert summary.selection_contributions == 1
    assert summary.attempts == 3
    assert summary.status == "unreconciled"


def test_retry_is_idempotent_but_parameter_change_has_new_trial_and_count(tmp_path):
    ledger = JsonlTrialLedger(tmp_path / "events.jsonl")
    first, _ = _register(ledger)
    row = ledger.append(
        kind="evaluation_started", event_id="attempt-a-started", trial=first,
        attempt="attempt-a", payload=_started(), event_at=NOW,
    )
    retried = ledger.append(
        kind="evaluation_started", event_id="attempt-a-started", trial=first,
        attempt="attempt-a", payload=_started(),
        event_at=NOW + timedelta(hours=1),
    )
    assert retried == row and len(ledger.read()) == 2
    with pytest.raises(TrialLedgerError, match="reused"):
        ledger.append(
            kind="evaluation_started", event_id="attempt-a-started", trial=first,
            attempt="attempt-a", payload={"source_ref": {
                "study_sha256": "a" * 64, "feature_sha256": "f" * 64,
                "phase": "development",
            }}, event_at=NOW,
        )

    second, _ = _register(ledger, "trial-b", 141, {"threshold": 2})
    assert first != second
    assert ledger.summary().selection_n == 141


def test_gap_parent_terminal_and_holdout_rules_fail_closed(tmp_path):
    ledger = JsonlTrialLedger(tmp_path / "events.jsonl")
    first, _ = _register(ledger)
    with pytest.raises(TrialLedgerError, match="gap-free"):
        _register(ledger, "gap", 142)
    with pytest.raises(TrialLedgerError, match="no start"):
        ledger.append(
            kind="failed", event_id="missing", trial=first, attempt="x", payload={}, event_at=NOW,
        )
    with pytest.raises(TrialLedgerError, match="before an evaluation"):
        ledger.append(
            kind="holdout_opened", event_id="holdout", trial=first, payload={}, event_at=NOW,
        )


def test_reconciliation_seals_census_and_later_event_makes_it_stale(tmp_path):
    ledger = JsonlTrialLedger(tmp_path / "events.jsonl")
    first, _ = _register(ledger)
    ledger.reconcile({"source.csv": "c" * 64}, event_id="reconcile-v1", event_at=NOW)
    assert ledger.summary().status == "complete"
    assert ledger.selection_n() == 140
    ledger.append(
        kind="evaluation_started", event_id="later", trial=first, attempt="later",
        payload=_started(), event_at=NOW + timedelta(minutes=1),
    )
    assert ledger.summary().status == "stale"
    with pytest.raises(TrialLedgerError, match="stale"):
        ledger.selection_n()


def test_concurrent_writers_serialize_and_tampering_is_refused(tmp_path):
    ledger = JsonlTrialLedger(tmp_path / "events.jsonl")
    first, _ = _register(ledger)

    def append(index):
        return ledger.append(
            kind="evaluation_started", event_id=f"start-{index}", trial=first,
            attempt=f"attempt-{index}", payload=_started(),
            event_at=NOW + timedelta(seconds=index),
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(append, range(16)))
    assert len(ledger.read()) == 17

    rows = [json.loads(line) for line in ledger.path.read_text().splitlines()]
    rows[3]["payload"] = {"source_ref": {"run": 999}}
    write_text_atomic(ledger.path, "\n".join(json.dumps(row) for row in rows) + "\n")
    with pytest.raises(TrialLedgerError, match="identity differs"):
        ledger.read()


def test_trial_id_is_canonical():
    assert trial_id("d" * 64, {"b": 2, "a": 1}) == canonical_sha256({
        "parameters": {"a": 1, "b": 2}, "study_sha256": "d" * 64,
    })


def test_genesis_is_derived_from_exact_accepted_public_census_and_refuses_drift(tmp_path):
    accepted = CensusGenesis.accepted()
    assert accepted.row_count == 103
    assert accepted.n_contribution == 139
    assert accepted.source_sha256 == (
        "07ba583900406735b422d91437ebd21db4cfdd59ba4d160db86f7f73a34395b7"
    )
    source = Path(__file__).resolve().parents[3] / "docs" / "p16-trial-census.json"
    changed = tmp_path / "p16-trial-census.json"
    rows = json.loads(source.read_text())
    rows[0]["n_contribution"] += 1
    write_text_atomic(changed, json.dumps(rows))
    with pytest.raises(TrialLedgerError, match="public census hash differs"):
        CensusGenesis.from_public_census(changed)


def test_runtime_terminals_require_evidence_monotonic_time_and_live_trial(tmp_path):
    ledger = JsonlTrialLedger(tmp_path / "events.jsonl")
    trial, _ = _register(ledger)
    ledger.append(
        kind="evaluation_started", event_id="start", trial=trial, attempt="attempt",
        payload=_started(), event_at=NOW + timedelta(hours=1),
    )
    with pytest.raises(TrialLedgerError, match="payload fields differ"):
        ledger.append(
            kind="evaluated", event_id="empty", trial=trial, attempt="attempt",
            payload={}, event_at=NOW + timedelta(hours=2),
        )
    with pytest.raises(TrialLedgerError, match="predates"):
        ledger.append(
            kind="evaluated", event_id="inverted", trial=trial, attempt="attempt",
            payload=_terminal("evaluated", attempt="attempt", trial=trial), event_at=NOW,
        )

    retired_ledger = JsonlTrialLedger(tmp_path / "retired.jsonl")
    retired, _ = _register(retired_ledger)
    retired_ledger.append(
        kind="retired", event_id="retired", trial=retired,
        payload={"source_ref": {
            "evidence_sha256": "a" * 64,
            "result_sha256": "b" * 64,
            "reason": "fixture",
        }},
        event_at=NOW,
    )
    with pytest.raises(TrialLedgerError, match="already started"):
        retired_ledger.append(
            kind="evaluation_started", event_id="after-retired", trial=retired,
            attempt="later", payload=_started(), event_at=NOW + timedelta(minutes=1),
        )


def test_duplicate_confirmation_is_refused(tmp_path):
    ledger = JsonlTrialLedger(tmp_path / "events.jsonl")
    trial, _ = _register(ledger)
    ledger.append(
        kind="evaluation_started", event_id="start", trial=trial, attempt="attempt",
        payload=_started(), event_at=NOW,
    )
    ledger.append(
        kind="holdout_opened", event_id="holdout", trial=trial,
        payload={"source_ref": {"marker": "fixture"}}, event_at=NOW + timedelta(seconds=1),
    )
    payload = {"source_ref": {
        "evidence_sha256": "a" * 64,
        "result_sha256": "b" * 64,
        "reason": "fixture",
    }}
    ledger.append(
        kind="confirmed", event_id="confirmed", trial=trial, payload=payload,
        event_at=NOW + timedelta(seconds=2),
    )
    with pytest.raises(TrialLedgerError, match="already been confirmed"):
        ledger.append(
            kind="confirmed", event_id="confirmed-again", trial=trial, payload=payload,
            event_at=NOW + timedelta(seconds=3),
        )
