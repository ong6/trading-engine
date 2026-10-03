import json
from dataclasses import replace
from pathlib import Path

import pytest

from farm.study.audit import AuditExecutionError, audit_study
from farm.study.audit_report import json_bytes, markdown
from farm.study.examples import data_audit
from farm.study.protocol import run_identity
from sim import nyse


def test_fixture_is_fixed_fictional_calendar_with_independent_full_population():
    contract, reference, snapshots = data_audit.fixture()
    dates = sorted({bar.session for bar in reference.bars})
    assert len(dates) == 61 and all(nyse.is_session(day) for day in dates)
    assert dates[-1] == data_audit.DECISION_SESSION
    assert contract.sessions == (dates[-1],)
    assert contract.window_sessions == contract.min_history == 60
    assert len(reference.bars) == 244 and len(snapshots["incomplete"].bars) == 122
    assert {row.ticker for row in reference.listings} == set(data_audit.NAMES)
    assert sum(row.listed_through is not None for row in reference.listings) == 2
    assert all(row.available_at is not None for row in reference.listings)
    assert reference.membership_basis == "observed_source"


def test_native_reversal_agrees_with_frozen_independent_fee_arithmetic():
    summary = data_audit.run_demo()
    incomplete, complete = (summary["results"][name] for name in ("incomplete", "complete"))
    assert summary["capital"] == 40_000
    for name, result in (("incomplete", incomplete), ("complete", complete)):
        for key, expected in data_audit.EXPECTED[name].items():
            assert result["native"][key] == pytest.approx(expected, abs=1e-9, rel=0)
            assert result["independent"][key] == pytest.approx(expected, abs=1e-9, rel=0)
        assert result["attempts"]["capital"] == summary["capital"]
        assert len(result["attempts"]["trades"]) + len(result["attempts"]["unfilled_orders"]) == 4
        assert result["audit"]["outcomes"]["recorded_attempts"] == 4
    assert incomplete["native"]["net_return"] > 0 > complete["native"]["net_return"]
    assert incomplete["attempts"]["unfilled_counts"] == {"missing_entry_bar": 2}
    assert complete["attempts"]["unfilled_counts"] == {}
    for key in ("spec_source_sha256", "parameters_sha256", "cost_profile_hashes", "core_version"):
        assert incomplete["study_identity"][key] == complete["study_identity"][key]
    assert incomplete["study_identity"]["sha256"] != complete["study_identity"]["sha256"]
    assert incomplete["audit"]["snapshots"]["reference"] == complete["audit"]["snapshots"]["reference"]
    assert incomplete["audit"]["sessions"][0]["coverage"] == 0.5
    assert complete["audit"]["sessions"][0]["coverage"] == 1
    assert incomplete["audit"]["decision"] == "unusable"
    assert complete["audit"]["decision"] == "supported"


def test_future_signal_availability_does_not_reclassify_valid_later_outcomes():
    results = data_audit.run_demo()["results"]
    late, complete = results["late_input"], results["complete"]
    row = late["audit"]["sessions"][0]
    assert (row["expected"], row["complete_inputs"], row["late_inputs"]) == (4, 3, 1)
    assert late["audit"]["checks"]["availability"]["status"] == "fail"
    assert late["audit"]["decision"] == "unusable"
    assert late["native"] == complete["native"]
    assert late["study_identity"] == complete["study_identity"]
    assert late["audit"]["audit_id"] != complete["audit"]["audit_id"]
    assert late["audit"]["outcomes"]["trades"] == 4
    assert complete["audit"]["sessions"][0]["late_inputs"] == 0


def test_uncertain_population_and_required_unknown_basis_render_as_limited():
    contract, reference, snapshots = data_audit.fixture()
    incomplete_reference = audit_study(contract, snapshots["complete"],
                                       replace(reference, membership_complete=False))
    row = incomplete_reference["sessions"][0]
    assert row["coverage"] is None and row["known_subset_coverage"] == 1
    assert row["unresolved_eligibility"] == 0 and incomplete_reference["decision"] == "limited"
    assert json.loads(json_bytes(incomplete_reference)) == json.loads(json.dumps(incomplete_reference))
    unknown_basis = audit_study(contract, replace(snapshots["complete"], price_basis="unknown"), reference)
    assert unknown_basis["checks"]["price_basis"]["required"] is True
    assert unknown_basis["decision"] == "limited"
    assert json.loads(json_bytes(unknown_basis)) == json.loads(json.dumps(unknown_basis))


def test_sidecar_attachment_preserves_old_report_ledger_identity_and_holdout(tmp_path):
    contract, reference, snapshots = data_audit.fixture()
    snapshot = snapshots["complete"]
    before, ledger, data = data_audit.evaluate(snapshot, reference)
    original = json.dumps(before, sort_keys=True, allow_nan=False)
    ledger_bytes = json.dumps(ledger.as_dict(), sort_keys=True, allow_nan=False)
    marker = tmp_path / "holdout-opened.json"
    marker.write_bytes(b"frozen one-shot marker")
    audit = audit_study(replace(contract, study_run_id=before["identity"]["sha256"]),
                        snapshot, reference, outcomes=ledger.as_dict())
    from farm.study.audit_report import write_audit

    write_audit(tmp_path / "sidecar", audit)
    after, again, _ = data_audit.evaluate(snapshot, reference)
    assert json.dumps(after, sort_keys=True, allow_nan=False) == original
    assert json.dumps(again.as_dict(), sort_keys=True, allow_nan=False) == ledger_bytes
    assert run_identity(data_audit.STRATEGY, data_audit.COSTS,
                        data.primary.declaration.snapshot_sha256).as_dict() == before["identity"]
    assert marker.read_bytes() == b"frozen one-shot marker"


def test_offline_export_deterministic_parity_and_structured_cli_error(tmp_path, monkeypatch, capsys):
    first = data_audit.run_demo(tmp_path / "first")
    second = data_audit.run_demo(tmp_path / "second")
    assert first == second
    assert (tmp_path / "first/demo.json").read_bytes() == (tmp_path / "second/demo.json").read_bytes()
    comparison = (tmp_path / "first/demo.md").read_text()
    assert comparison == data_audit.demo_markdown(first)
    assert "| incomplete | 2/4 | 2/2 | $10.37032 | $389.62968 | +0.9740742% | unusable |" in comparison
    assert "| complete | 4/4 | 4/0 | $20.41616 | $-820.41616 | -2.0510404% | supported |" in comparison
    assert "(incomplete/audit.md)" in comparison and "Hindsight omission" in comparison
    serialized = json.dumps(first, sort_keys=True, allow_nan=False)
    assert str(tmp_path) not in serialized and "/Users/" not in serialized
    for name, result in first["results"].items():
        target = tmp_path / "first" / name
        assert (target / "audit.json").read_bytes() == json_bytes(result["audit"])
        assert (target / "audit.md").read_text() == markdown(result["audit"])
        assert (target / "report.json").read_bytes() == (
            tmp_path / "second" / name / "report.json").read_bytes()
    assert data_audit.main(["--output-dir", str(tmp_path / "cli")]) == 0
    assert json.loads(capsys.readouterr().out)["results"]["incomplete"]["net_return"] > 0

    def corrupt(_output):
        raise AuditExecutionError("fixture hash mismatch")

    monkeypatch.setattr(data_audit, "run_demo", corrupt)
    assert data_audit.main(["--output-dir", str(tmp_path / "failed")]) == 2
    failure = json.loads(capsys.readouterr().out)
    assert failure == AuditExecutionError("fixture hash mismatch").as_dict()
    assert "audit_id" not in failure and "decision" not in failure
    assert not Path(tmp_path / "failed").exists()
