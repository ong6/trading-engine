"""Structural documentation checks that do not pin prose to implementation details."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from urllib.parse import unquote

from engine import queue_runner
from engine.lib.db import MARKET_DATE_MIN_COVERAGE, MARKET_DATE_MIN_NAMES
from server.driver_monitor import DRIVER_SCHEDULES
from server.risk import RISK_CONTROL_NAMES
from server.scheduler_monitor import expected_auxiliary_cron_entries, expected_cron_entries

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCUMENTATION_TREES = ("archive", "data", "docs", "ui")
IGNORED_PARTS = frozenset(
    {
        ".git",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }
)
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
URI_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
ATX_HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.+?)[ \t]*$")
FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
BUILDLOG_TAIL_MARKER = "<!-- append-only-tail: insert new verified entries immediately above this line -->"


def _markdown_files(root: Path = REPO_ROOT) -> list[Path]:
    candidates = list(root.glob("*.md"))
    for tree_name in DOCUMENTATION_TREES:
        tree = root / tree_name
        if tree.is_dir():
            candidates.extend(tree.rglob("*.md"))
    return sorted(
        path for path in candidates if not IGNORED_PARTS.intersection(path.relative_to(root).parts)
    )


def _github_heading_slug(title: str) -> str:
    title = re.sub(r"[ \t]+#+[ \t]*$", "", title)
    title = re.sub(r"\[([^]]*)\]\([^)]*\)", r"\1", title)
    title = re.sub(r"<[^>]*>", "", title)
    normalized = []
    for character in title.strip().lower():
        category = unicodedata.category(character)
        if character.isspace():
            normalized.append("-")
        elif category[0] in {"L", "N"} or character in {"-", "_"}:
            normalized.append(character)
    return "".join(normalized)


def _without_fenced_code(text: str) -> str:
    visible: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    for line in text.splitlines(keepends=True):
        fence = FENCE_OPEN.match(line)
        if fence:
            marker = fence.group(1)
            suffix = fence.group(2).rstrip("\r\n")
            if fence_character is None and (marker[0] == "~" or "`" not in suffix):
                fence_character = marker[0]
                fence_length = len(marker)
            elif (
                marker[0] == fence_character
                and len(marker) >= fence_length
                and not suffix.strip()
            ):
                fence_character = None
                fence_length = 0
        if fence_character is not None or fence:
            visible.append("".join(character if character in "\r\n" else " " for character in line))
        else:
            visible.append(line)
    return "".join(visible)


def _markdown_heading_fragments(text: str) -> set[str]:
    fragments: set[str] = set()
    occurrences: dict[str, int] = {}
    fence_character: str | None = None
    fence_length = 0
    for line in text.splitlines():
        fence = FENCE_OPEN.match(line)
        if fence:
            marker = fence.group(1)
            suffix = fence.group(2)
            if fence_character is None and (marker[0] == "~" or "`" not in suffix):
                fence_character = marker[0]
                fence_length = len(marker)
            elif (
                marker[0] == fence_character
                and len(marker) >= fence_length
                and not suffix.strip()
            ):
                fence_character = None
                fence_length = 0
            continue
        if fence_character is not None:
            continue
        heading = ATX_HEADING.match(line)
        if not heading:
            continue
        base = _github_heading_slug(heading.group(1))
        occurrence = occurrences.get(base, 0)
        occurrences[base] = occurrence + 1
        fragments.add(base if occurrence == 0 else f"{base}-{occurrence}")
    return fragments


def _markdown_link_errors(root: Path) -> tuple[int, list[str]]:
    missing: list[str] = []
    checked = 0
    fragment_cache: dict[Path, set[str]] = {}
    for source in _markdown_files(root):
        text = source.read_text(errors="replace")
        for match in MARKDOWN_LINK.finditer(_without_fenced_code(text)):
            raw_target = match.group(1).strip()
            if raw_target.startswith("<") and raw_target.endswith(">"):
                raw_target = raw_target[1:-1]
            target, separator, fragment = raw_target.partition("#")
            if URI_SCHEME.match(target):
                continue
            checked += 1
            resolved = source if not target else (source.parent / unquote(target)).resolve()
            problem = not resolved.exists() or not resolved.is_relative_to(root.resolve())
            if not problem and separator and resolved.is_file() and resolved.suffix.lower() == ".md":
                fragments = fragment_cache.setdefault(
                    resolved,
                    _markdown_heading_fragments(resolved.read_text(errors="replace")),
                )
                problem = unquote(fragment) not in fragments
            if problem:
                line = text.count("\n", 0, match.start()) + 1
                missing.append(f"{source.relative_to(root)}:{line}: {raw_target}")
    return checked, missing


def test_buildlog_ends_at_one_tail_marker():
    buildlog = (REPO_ROOT / "BUILDLOG.md").read_text()
    assert buildlog.count(BUILDLOG_TAIL_MARKER) == 1
    assert buildlog.endswith(f"{BUILDLOG_TAIL_MARKER}\n")


def test_markdown_discovery_is_limited_to_owned_trees(tmp_path: Path):
    expected = {
        tmp_path / "README.md",
        tmp_path / "archive" / "history.md",
        tmp_path / "data" / "reports" / "result.md",
        tmp_path / "docs" / "guide.md",
        tmp_path / "ui" / "README.md",
    }
    excluded = {
        tmp_path / "trading_engine-0.1.0" / "README.md",
        tmp_path / "unowned" / "notes.md",
        tmp_path / "docs" / "build" / "copied.md",
        tmp_path / "ui" / ".next" / "generated.md",
        tmp_path / "ui" / "node_modules" / "dependency.md",
    }
    for path in expected | excluded:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.stem}\n")
    assert set(_markdown_files(tmp_path)) == expected


def test_local_markdown_links_and_fragments_resolve():
    checked, missing = _markdown_link_errors(REPO_ROOT)
    assert checked, "no local Markdown links were discovered"
    assert not missing, "missing local Markdown targets:\n" + "\n".join(missing)


def test_documentation_index_links_every_owned_document():
    root = REPO_ROOT / "docs"
    index_path = root / "README.md"
    index = index_path.read_text()
    expected = {
        path.relative_to(root).as_posix() for path in root.rglob("*.md") if path != index_path
    }
    linked: set[str] = set()
    for raw_target in MARKDOWN_LINK.findall(index):
        target = unquote(raw_target.strip().strip("<>").split("#", 1)[0])
        if not target:
            continue
        resolved = (root / target).resolve()
        if resolved.is_relative_to(root.resolve()) and resolved.suffix == ".md":
            linked.add(resolved.relative_to(root.resolve()).as_posix())
    assert not sorted(expected - linked), f"documents missing from docs/README.md: {sorted(expected - linked)}"


def test_operations_guide_matches_runtime_constants():
    operations = (REPO_ROOT / "docs" / "how-it-works.md").read_text()
    architecture = (REPO_ROOT / "docs" / "architecture-reference.md").read_text()
    execution = (REPO_ROOT / "docs" / "design" / "trading-execution-design.md").read_text()
    engine_design = (REPO_ROOT / "docs" / "design" / "trading-engine-design.md").read_text()

    for control in RISK_CONTROL_NAMES:
        assert f"`{control}`" in operations
        assert f"`{control}`" in execution
    coverage = f"{MARKET_DATE_MIN_COVERAGE:.0%}"
    minimum_names = f"{MARKET_DATE_MIN_NAMES:,}"
    for text in (operations, engine_design):
        assert coverage in text
        assert minimum_names in text
        assert "breadth-qualified" in text
    assert f"up to {queue_runner.PARALLEL_JOBS_MAX}" in architecture
    assert "Up to eight" in operations

    cron = expected_cron_entries(REPO_ROOT)
    auxiliary = expected_auxiliary_cron_entries(REPO_ROOT)
    assert len(cron) == len(DRIVER_SCHEDULES) == 5
    assert len(auxiliary) == 1
    for _, name, log_name, _, _, hour, minute, _, _ in DRIVER_SCHEDULES:
        assert f"`{name}.sh`" in operations
        assert f"{hour:02d}:{minute:02d}" in operations
        assert f"`logs/{log_name}`" in operations
        assert f"/engine/{name}.sh" in cron[name]
    assert "tools.verify_friday_postflight --publish" in operations
