"""The fast tier's test selection: graph edges, fallbacks and the pinned test lists."""
from __future__ import annotations

import ast
import json
import os
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
    "data/impl.txt": "VALUE = 1\n",
    "engine/plugins/__init__.py": "",
    "engine/plugins/alpha.py": "ALPHA = 1\n",
    "engine/loader.py": (
        "import importlib\n\n\ndef load(name):\n"
        '    return importlib.import_module(f"engine.plugins.{name}")\n'
    ),
    "tests/test_loader.py": "from engine import loader\n",
    "tests/test_link.py": "from engine import link\n",
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
    (root / "engine" / "link.py").symlink_to("../data/impl.txt")
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
    # a module that reads content is reached like any reader: its importers' tests run
    assert "tests/test_writer.py" in _tests(["data/reports/r.json"], graph)
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


def test_symlinks_and_their_targets_are_code_and_reach_their_importers(graph, toy):
    assert graph.symlinked == {"engine/link.py", "data/impl.txt"}
    assert at.scope(["data/impl.txt"], toy) == "code"
    assert at.scope(["data/reports/r.json"], toy) == "content"
    assert "tests/test_link.py" in _tests(["data/impl.txt"], graph)


@pytest.mark.parametrize(("path", "content"), [
    ("data/reports/r.json", True), ("docs/a.md", True), ("data/x.csv", True),
    ("docs/site/index.html", True), ("docs/img/plot.PNG", True), ("data/x.jsonl", True),
    ("docs/history/tool.py", False), ("data/run.sh", False), ("docs/q.sql", False),
    ("data/c.toml", False), ("docs/c.yaml", False), ("data/tool", False), ("README.md", False),
])
def test_content_is_a_document_or_image_under_data_or_docs(path, content):
    assert at.is_content(path) is content


def test_a_module_a_computed_import_can_name_runs_the_full_suite(graph):
    selection = at.select(["engine/plugins/alpha.py"], graph)
    assert selection["mode"] == "full"
    assert "engine/loader.py imports a computed name under engine.plugins" in selection["reasons"][0]


@pytest.mark.parametrize(("source", "computed"), [
    ('import importlib\nimportlib.import_module(f"engine.jobs.{n}")\n', ["engine.jobs"]),
    ("from importlib import import_module\nimport_module(name)\n", [""]),
    ('import importlib\nimportlib.import_module("engine." + n)\n', [""]),
    ('__import__(prefix + "x")\n', [""]),
    ('ARGS = [python, "-m", module]\n', [""]),
    ('ARGS = [python, "-m", "engine." + n]\n', [""]),
    ('ARGS = ("python", "-m", *rest)\n', [""]),
    ('CMD = f"python -m farm.{name} --x"\n', ["farm"]),
    ('CMD = "python -m %s --x" % name\n', [""]),
    ('CMD = "python -m engine.{} --x".format(name)\n', [""]),
    ("import runpy\nrunpy.run_module(name)\n", [""]),
    ("import importlib.util\nimportlib.util.find_spec(name)\n", [""]),
    ('import importlib\ngetattr(importlib, "import_module")(name)\n', [""]),
    ('import importlib\nimportlib.import_module("engine.collect")\nARGS = ["-m", "a.b"]\n', []),
])
def test_computed_imports_are_found_with_their_literal_prefix(tmp_path, source, computed):
    (tmp_path / "tools" / "sub").mkdir(parents=True)
    (tmp_path / "tools" / "sub" / "run.py").write_text(source)
    assert at.python_facts(str(tmp_path), "tools/sub/run.py")[2] == computed


def test_a_computed_name_without_a_prefix_runs_the_full_suite_for_any_module(tmp_path):
    files = {"engine/__init__.py": "", "engine/core.py": "", "farm/__init__.py": "",
             "farm/runner.py": "import runpy\n\n\ndef run(name):\n    runpy.run_module(name)\n",
             "tests/test_core.py": "from engine import core\n"}
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    selection = at.select(["engine/core.py"], at.Graph(tmp_path, list(files)))
    assert selection["mode"] == "full"
    assert "farm/runner.py imports a computed name under any package" in selection["reasons"][0]


def test_only_the_reviewed_files_import_computed_names():
    graph = at.Graph()
    assert graph.computed == {}, f"unreviewed computed imports: {graph.computed}"
    assert set(at.REVIEWED_COMPUTED_IMPORTS) == {
        "farm/research/worker.py", "tests/test_affected_tests.py", "tools/release_deploy.py"}
    for path in at.REVIEWED_COMPUTED_IMPORTS:  # an exemption that no longer applies goes
        assert at.python_facts(str(REPO_ROOT), path)[2], path


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
        assert len(names) == len(set(names))
        for name in names:
            assert name in tracked, name
    assert set(at.FULL_SUITE_PATHS) >= {
        ".github/", "pyproject.toml", "tests/conftest.py", "tests/speed_plugin.py", "uv.lock",
    }
    assert at.CONTENT_PATHS == ("data/", "docs/")


def test_every_recorded_content_read_is_reached_by_the_graph_or_always_runs(monkeypatch):
    """Drift check against recorded reads: the committed tests/content_reads.json, or a fresh
    full-run record named by AFFECTED_TESTS_READS (``pytest -n 8 --record-reads PATH``)."""
    monkeypatch.setattr(at, "CONTRACT_TESTS", PINNED["contract"])
    committed = json.loads(at.CONTENT_READS.read_text())
    assert at.content_readers(committed) == list(PINNED["content"])
    fresh = os.environ.get("AFFECTED_TESTS_READS")
    record = json.loads(Path(fresh).read_text()) if fresh else committed
    assert at.unreached_content_reads(record, at.Graph()) == []


def test_the_drift_check_reports_a_content_read_the_graph_misses(graph):
    record = {
        "tests/test_docs.py": ["docs/guide.md"],  # names it: reached
        "tests/test_job.py": ["data/reports/r.json"],  # a contract test (toy): always runs
        "tests/test_core.py": ["data/reports/r.json", "engine/core.py"],  # not reached
        "tests/test_user.py": ["data/reports"],  # a listing: no reader of r.json reaches it
        "tests/test_rel.py": ["docs/gone.md"],  # no longer tracked: nothing to check
    }
    assert at.unreached_content_reads(record, graph) == [
        "tests/test_core.py reads data/reports/r.json", "tests/test_user.py reads data/reports"]
