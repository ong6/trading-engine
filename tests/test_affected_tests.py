"""The fast tier's test selection: graph edges, fallbacks and the pinned test lists."""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from tools import affected_tests as at

REPO_ROOT = Path(__file__).resolve().parents[1]
PINNED = {"contract": at.CONTRACT_TESTS, "content": at.CONTENT_READERS}
TOY = {
    "pyproject.toml": "[project]\nname = 'toy'\n",
    "engine/__init__.py": "",
    "engine/base.py": "BASE = 1\n",
    "engine/core.py": "VALUE = 1\n",
    "engine/user.py": "from engine import core\n",
    "engine/rel.py": "from . import core\n",
    "engine/job.py": 'JOBS = {"collect": "engine.user:main"}\n',
    "engine/doc_only.py": '"""Mentions engine.unused only in prose."""\n',
    "engine/unused.py": "UNUSED = 1\n",
    "engine/reader.py": (
        "from pathlib import Path\n"
        'RULES = Path(__file__).parent / "settings" / "rules.json"\n'
    ),
    "engine/reader_user.py": "from engine import reader\n",
    "engine/writer.py": 'REPORT = "data/reports/r.json"\n',
    "engine/settings/rules.json": "{}\n",
    "engine/run.sh": "python -m engine.rel\n",
    "units/a.service": "[Service]\n",
    "docs/guide.md": "# Guide\n",
    "data/reports/r.json": "{}\n",
    "tests/conftest.py": "from engine import base\n\n\ndef helper():\n    from engine import unused\n",
    "tests/speed_plugin.py": "",
    "tests/test_core.py": "from engine import core\n",
    "tests/test_user.py": "import engine.user\n",
    "tests/test_rel.py": "from engine.rel import core\n",
    "tests/test_job.py": "from engine import job\n",
    "tests/test_doc_only.py": "from engine import doc_only\n",
    "tests/test_reader_user.py": "from engine import reader\n",
    "tests/test_far_reader.py": "from engine import reader_user\n",
    "tests/test_writer.py": "from engine import writer\n",
    "tests/test_script.py": 'SCRIPT = "engine/run.sh"\n',
    "tests/test_units.py": 'UNITS = sorted(ROOT.glob("*.service"))\nCAL = "*-*-* 21:00"\n',
    "tests/test_docs.py": 'DOC = ROOT / "docs" / "guide.md"\n',
}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True).stdout


@pytest.fixture(scope="module")
def toy(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("toy")
    for name, text in TOY.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    _git(root, "init", "-q")
    _git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "toy")
    return root


@pytest.fixture(scope="module")
def graph(toy: Path) -> at.Graph:
    return at.Graph(toy)


@pytest.fixture(autouse=True)
def toy_lists(monkeypatch):
    monkeypatch.setattr(at, "CONTRACT_TESTS", ("tests/test_job.py",))
    monkeypatch.setattr(at, "CONTENT_READERS", ("tests/test_doc_only.py",))


def _tests(changed: list[str], graph: at.Graph) -> list[str]:
    selection = at.select(changed, graph)
    assert selection["mode"] == "selected", selection["reasons"]
    return selection["tests"]


def test_imports_are_followed_transitively_and_relatively(graph):
    assert _tests(["engine/core.py"], graph) == [
        "tests/test_core.py", "tests/test_job.py", "tests/test_rel.py", "tests/test_script.py",
        "tests/test_user.py",
    ]


def test_a_string_naming_a_module_is_an_import_and_a_docstring_is_not(graph):
    assert "engine/job.py" in graph.importers["engine/user.py"]
    assert "engine/doc_only.py" not in graph.importers.get("engine/unused.py", set())


def test_a_read_reaches_the_reader_and_its_direct_importers_only(graph):
    selected = _tests(["engine/settings/rules.json"], graph)
    assert "tests/test_reader_user.py" in selected
    assert "tests/test_far_reader.py" not in selected


def test_a_script_passes_on_what_it_runs_and_a_file_glob_lists_files(graph):
    assert "tests/test_script.py" in _tests(["engine/rel.py"], graph)
    assert _tests(["units/a.service"], graph) == ["tests/test_job.py", "tests/test_units.py"]
    assert graph._globbed("*-*-*") == set()


def test_content_reaches_tests_that_name_it_and_the_content_readers(graph):
    assert _tests(["docs/guide.md"], graph) == [
        "tests/test_doc_only.py", "tests/test_docs.py", "tests/test_job.py",
    ]
    assert "tests/test_writer.py" not in _tests(["data/reports/r.json"], graph)
    assert _tests(["docs/removed.md"], graph) == ["tests/test_doc_only.py", "tests/test_job.py"]


@pytest.mark.parametrize(("changed", "reason"), [
    (["pyproject.toml"], "full-suite path"),
    ([".github/workflows/ci.yml"], "full-suite path"),
    (["tests/conftest.py"], "full-suite path"),
    (["engine/base.py"], "loaded by every test session"),
    (["engine/gone.py"], "deleted"),
    (["engine/unused.py"], "no test reaches it"),
])
def test_unknown_or_session_wide_changes_run_the_full_suite(graph, changed, reason):
    selection = at.select(changed, graph)
    assert selection["mode"] == "full"
    assert reason in selection["reasons"][0]


def test_conftest_function_level_imports_are_not_session_wide(graph):
    assert "engine/unused.py" not in graph.session_files()
    assert {"engine/base.py", "engine/__init__.py"} <= graph.session_files()


def test_changed_files_include_commits_and_the_working_tree(toy, tmp_path):
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(toy), str(clone))
    _git(clone, "checkout", "-qb", "lane")
    (clone / "engine" / "core.py").write_text("VALUE = 2\n")
    _git(clone, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "commit", "-qam", "change")
    (clone / "engine" / "user.py").write_text("from engine import core  # edited\n")
    (clone / "engine" / "new.py").write_text("")
    assert at.changed_files("origin/main", root=clone) == [
        "engine/core.py", "engine/new.py", "engine/user.py",
    ]
    assert at.changed_files("origin/main", "HEAD", root=clone) == ["engine/core.py"]


def test_joined_literal_path_parts_name_one_path():
    node = ast.parse('root / "data" / "reports" / name / "a" / "b.json"').body[0].value
    assert at.joined_paths(node) == ["data/reports", "a/b.json"]
    call = ast.parse('Path("docs", "plans", suffix)').body[0].value
    assert at.joined_paths(call) == ["docs/plans"]


def test_content_readers_come_from_a_read_record():
    record = {
        "tests/test_a.py": ["data/_meta.json", "engine/x.py"],
        "tests/test_b.py": ["docs/history/tool.py", "server/x.json"],
        "tests/test_c.py": ["docs/scope.md"],
    }
    assert at.content_readers(record) == ["tests/test_a.py", "tests/test_c.py"]


def test_pinned_lists_name_real_tests_and_the_full_suite_triggers():
    tracked = set(_git(REPO_ROOT, "ls-files").splitlines())
    for names in PINNED.values():
        assert names == tuple(sorted(set(names)))
        for name in names:
            assert name in tracked, name
    assert set(at.FULL_SUITE_PATHS) >= {
        ".github/", "pyproject.toml", "tests/conftest.py", "tests/speed_plugin.py", "uv.lock",
    }
    assert at.CONTENT_PATHS == ("data/", "docs/")
    assert not at.is_content("docs/history/tool.py")
