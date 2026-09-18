"""The broker-neutral work must remain internal until later gates authorize wiring."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BROKER_MODULES = {
    "agent_paper_evidence",
    "broker_contract",
    "broker_emergency_stop",
    "broker_human_paper_approval",
    "broker_human_paper_review",
    "broker_ledger",
    "broker_paper_activation_plan",
    "broker_paper_authority_transcript",
    "broker_paper_consumption_plan",
    "broker_paper_intent",
    "broker_paper_lease",
    "broker_paper_risk_evaluation",
    "broker_paper_risk_projection",
    "broker_paper_runtime",
    "broker_paper_startup_scan",
    "broker_paper_startup_store",
    "broker_paper_usage",
    "broker_reconciliation",
    "broker_risk",
    "broker_risk_control",
    "broker_risk_fault_drills",
    "broker_risk_snapshot",
    "broker_startup_readiness",
    "broker_submission",
    "broker_submission_resolution",
    "disabled_live_broker_adapter",
    "simulator_broker_adapter",
}
ENTRYPOINTS = (
    "server/main.py",
    "server/agent_shadow_runner.py",
    "server/agent_proposals.py",
    "server/tickets.py",
    "sim/league.py",
)
READ_ONLY_OPERATOR_ENTRYPOINTS = ("tools/review_agent_paper_intent.py",)


def _imported_broker_modules(relative: str) -> set[str]:
    tree = ast.parse((REPO_ROOT / relative).read_text(), filename=relative)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or "", *(alias.name for alias in node.names)]
        else:
            continue
        for name in names:
            leaf = name.rsplit(".", 1)[-1]
            if leaf in BROKER_MODULES:
                imported.add(leaf)
    return imported


def test_broker_boundary_is_not_wired_to_current_mutation_entrypoints():
    offenders = {
        relative: sorted(imported)
        for relative in ENTRYPOINTS
        if (imported := _imported_broker_modules(relative))
    }
    assert offenders == {}


def test_human_review_cli_imports_only_the_review_boundary():
    assert {
        relative: sorted(_imported_broker_modules(relative))
        for relative in READ_ONLY_OPERATOR_ENTRYPOINTS
    } == {
        "tools/review_agent_paper_intent.py": [
            "broker_contract",
            "broker_human_paper_review",
        ]
    }


def test_broker_boundary_has_no_public_route_decorators():
    offenders = []
    for relative in (
        "server/broker_contract.py",
        "server/agent_paper_evidence.py",
        "server/broker_emergency_stop.py",
        "server/broker_human_paper_approval.py",
        "server/broker_human_paper_review.py",
        "server/broker_ledger.py",
        "server/broker_paper_activation_plan.py",
        "server/broker_paper_authority_transcript.py",
        "server/broker_paper_consumption_plan.py",
        "server/broker_paper_intent.py",
        "server/broker_paper_lease.py",
        "server/broker_paper_risk_evaluation.py",
        "server/broker_paper_risk_projection.py",
        "server/broker_paper_runtime.py",
        "server/broker_paper_startup_scan.py",
        "server/broker_paper_startup_store.py",
        "server/broker_paper_usage.py",
        "server/broker_reconciliation.py",
        "server/broker_risk.py",
        "server/broker_risk_control.py",
        "server/broker_risk_fault_drills.py",
        "server/broker_risk_snapshot.py",
        "server/broker_startup_readiness.py",
        "server/broker_submission.py",
        "server/broker_submission_resolution.py",
        "server/disabled_live_broker_adapter.py",
        "server/simulator_broker_adapter.py",
    ):
        source = (REPO_ROOT / relative).read_text()
        if "@app." in source or "@router." in source:
            offenders.append(relative)
    assert offenders == []
