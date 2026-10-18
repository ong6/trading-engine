import concurrent.futures
import importlib
import json
from datetime import datetime, timedelta, timezone

from engine.lib.resources import write_text_atomic
from farm.research.canonical import canonical_sha256
from farm.research.trials import JsonlTrialLedger, TrialLedgerError, trial_id

pytest = importlib.import_module("pytest")

NOW = datetime(2026, 10, 18, 18, tzinfo=timezone.utc)


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
            attempt=attempt, payload={"source_ref": {"run": index}},
            event_at=NOW + timedelta(minutes=index),
        )
        ledger.append(
            kind=terminal, event_id=f"terminal-{index}", trial=first,
            attempt=attempt, payload={"source_ref": {"status": terminal}},
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
        attempt="attempt-a", payload={"source_ref": {"spec": "a"}}, event_at=NOW,
    )
    retried = ledger.append(
        kind="evaluation_started", event_id="attempt-a-started", trial=first,
        attempt="attempt-a", payload={"source_ref": {"spec": "a"}},
        event_at=NOW + timedelta(hours=1),
    )
    assert retried == row and len(ledger.read()) == 2
    with pytest.raises(TrialLedgerError, match="reused"):
        ledger.append(
            kind="evaluation_started", event_id="attempt-a-started", trial=first,
            attempt="attempt-a", payload={"source_ref": {"spec": "changed"}}, event_at=NOW,
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
        payload={"source_ref": {"run": 1}}, event_at=NOW + timedelta(minutes=1),
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
            attempt=f"attempt-{index}", payload={"source_ref": {"run": index}},
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
