"""The operating contract: frozen-layer budgets, BUILDLOG v2 format, plan headers, and the
metrics snapshot tool. These are the tests that make ``AGENTS.md`` enforceable.

Do not add documentation-prose assertions here; the contract forbids new doc-pinning tests.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tools import metrics_snapshot as ms

REPO_ROOT = Path(__file__).resolve().parents[1]
PLAN_STATUSES = {"proposed", "approved", "active", "done", "dropped"}
PLAN_HEADER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
REQUIRED_PLAN_SECTIONS = ("## Goal", "## Scope", "## Not in scope", "## Done when", "## Budget")


def test_contract_files_exist_and_point_at_each_other():
    agents = (REPO_ROOT / "AGENTS.md").read_text()
    claude = (REPO_ROOT / "CLAUDE.md").read_text()
    assert "AGENTS.md" in claude
    for required in ("docs/feedback.md", "docs/scope.md", "data/reports/metrics/README.md",
                     "next-admissible-actions", "docs/scope-budget.json"):
        assert required in agents, f"AGENTS.md must reference {required}"


def test_frozen_layers_are_within_budget():
    budget = ms.load_budget()
    sizes = ms.code_size(REPO_ROOT)
    over = {
        layer: (sizes[layer], ceiling)
        for layer, ceiling in budget["loc_ceiling"].items()
        if sizes[layer] > ceiling
    }
    assert not over, (
        "frozen layer over its ceiling; get the raise recorded in docs/feedback.md first: "
        f"{over}"
    )


def test_buildlog_v2_entries_obey_the_entry_budget():
    budget = ms.load_budget()["buildlog_entry"]
    text = (REPO_ROOT / "BUILDLOG.md").read_text()
    assert ms.BUILDLOG_V2_MARKER in text, "BUILDLOG.md must carry the format-v2 marker"
    entries = ms.buildlog_v2_entries(text)
    assert entries, "at least one v2 entry must follow the marker"
    for entry in entries:
        title = entry.splitlines()[0]
        assert len(entry.splitlines()) <= budget["max_lines"], f"too long: {title}"
        assert len(ms.SHA256.findall(entry)) <= budget["max_sha256"], f"too many hashes: {title}"
        for field in ("**Why:**", "**What:**", "**Evidence:**", "**Next:**"):
            assert field in entry, f"{title} is missing {field}"


def test_buildlog_v2_marker_sits_before_the_tail_marker_and_after_all_legacy_entries():
    text = (REPO_ROOT / "BUILDLOG.md").read_text()
    v2_at = text.index(ms.BUILDLOG_V2_MARKER)
    tail_at = text.index(ms.BUILDLOG_TAIL_MARKER)
    assert v2_at < tail_at


def _plans() -> list[Path]:
    return sorted(p for p in (REPO_ROOT / "docs" / "plans").glob("p*.md"))


def test_plans_exist_and_carry_a_valid_header_and_sections():
    plans = _plans()
    assert plans
    for path in plans:
        text = path.read_text()
        header = PLAN_HEADER.match(text)
        assert header, f"{path.name} has no YAML header"
        fields = dict(
            line.split(":", 1) for line in header.group(1).splitlines() if ":" in line
        )
        fields = {k.strip(): v.strip() for k, v in fields.items()}
        assert fields.get("status") in PLAN_STATUSES, f"{path.name}: bad status"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", fields.get("opened", "")), path.name
        for section in REQUIRED_PLAN_SECTIONS:
            assert section in text, f"{path.name} is missing {section}"


def test_plan_index_lists_every_plan():
    index = (REPO_ROOT / "docs" / "plans" / "README.md").read_text()
    for path in _plans():
        assert path.name in index, f"{path.name} is not indexed in docs/plans/README.md"


def test_scope_ledger_has_its_sections():
    scope = (REPO_ROOT / "docs" / "scope.md").read_text()
    for section in ("## In scope now", "## Approved plans", "## Not yet",
                    "## Never on this host", "## Proposed, not approved"):
        assert section in scope


def test_no_new_documentation_pinning_tests():
    """The count of doc-prose tests is frozen; fix docs, do not add assertions about them."""
    doc_tests = sorted((REPO_ROOT / "tests").glob("test_docs*.py"))
    count = sum(len(re.findall(r"^def test_", p.read_text(), re.MULTILINE)) for p in doc_tests)
    ceiling = ms.load_budget().get("doc_test_ceiling")
    assert ceiling is not None, "docs/scope-budget.json needs doc_test_ceiling"
    assert count <= ceiling, f"{count} doc tests > ceiling {ceiling}; retire, do not add"


def test_metrics_snapshot_runs_from_committed_artifacts(tmp_path: Path):
    snap = ms.snapshot(REPO_ROOT)
    for key in ("date", "code_size", "commit_shape", "ledger", "research", "budget"):
        assert key in snap
    assert snap["code_size"]["server"] > 0
    assert snap["research"]["active_books"] > 0
    target = ms.publish(tmp_path, snap)
    assert json.loads(target.read_text())["date"] == snap["date"]
    readme = (tmp_path / "README.md").read_text()
    assert snap["date"] in readme


@pytest.mark.parametrize(
    "text, expected",
    [
        ("## 2026-01-01 — a\n\nx\n" + ms.BUILDLOG_TAIL_MARKER, 1),
        ("intro\n## 2026-01-01 — a\n\nx\n## 2026-01-02 — b\n\ny\n" + ms.BUILDLOG_TAIL_MARKER, 2),
    ],
)
def test_buildlog_entry_splitter(text: str, expected: int):
    assert len(ms.buildlog_entries(text)) == expected


def test_budget_check_reports_each_violation():
    budget = {"loc_ceiling": {"server": 10}, "buildlog_entry": {"max_lines": 25, "max_sha256": 1}}
    hygiene = {"v2_max_lines": 30, "v2_max_sha256": 2}
    result = ms.budget_check({"server": 11}, hygiene, budget)
    assert not result["ok"]
    assert len(result["violations"]) == 3
