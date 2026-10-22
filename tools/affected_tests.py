"""Select the tests a change can affect: the fast tier for agents and pull requests.

``python -m tools.affected_tests`` prints the test files to run for the changes since the
merge base with ``origin/main`` (committed, staged, unstaged and untracked); ``--run`` runs
ruff, compileall and pytest on them. CI still runs the full suite in both timezones on
``main``; this tool only decides what runs earlier.

Selection is static and errs towards running more:

- The reverse dependency graph of tracked files. A file *imports* a module through an
  ``import`` statement (function-level ones too, plus the package ``__init__`` files they
  execute) or a string naming the module (``"engine.collect"``, ``"tools.x:main"``,
  ``-m tools.x``), which is how jobs and subprocesses run it. A file *reads* a file it names
  by path, unique path suffix, ``a / "b" / "c"`` join or file glob (``"run_daily.sh"``,
  ``"docs/plans"``, ``"*.service"``). Shell scripts and systemd units import and read what
  they name the same way; data and configuration files (JSON, TOML, YAML) and content are
  leaves: they change only when they change.
- Imports are followed transitively. A test that reads a changed file is selected; a script
  or unit that reads it passes the change on as if it had changed; a Python module that
  reads it passes it on one import further, to the files that import it: modules name
  repository files as defaults that tests replace with their own, and following every
  importer of a module that names a report selects most of the suite.
- ``CONTRACT_TESTS`` always run; ``CONTENT_READERS`` run whenever content changes.
- The full suite runs for ``FULL_SUITE_PATHS``, for anything every test session loads
  (``tests/conftest.py``'s module-level imports, the speed plugin and the files they name),
  for a deleted non-content file (what used it cannot be traced), and for a changed file no
  test reaches (an unknown dependency is never assumed to be none).
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = "tests/"

# Always selected: the repository-wide contracts that read code and documents as text.
CONTRACT_TESTS = (
    "tests/contracts/test_no_secrets.py",
    "tests/contracts/test_provider_contracts.py",  # provider replay
    "tests/contracts/test_runtime_environment.py",
    "tests/test_documentation_integrity.py",
    "tests/test_e1_forward_status.py",  # E1, sector and XS runtime contracts
    "tests/test_experiment_runner.py",
    "tests/test_forward_cost_break_continuity.py",
    "tests/test_forward_review.py",
    "tests/test_live_store_paths.py",  # live-store lint
    "tests/test_operating_contract.py",
    "tests/test_p15_registration.py",
    "tests/test_public_hygiene.py",
    "tests/test_r15_integration.py",
    "tests/test_registration_identity.py",
    "tests/test_schedule_contract.py",  # static schedule contract
    "tests/test_sector_forward_status.py",
    "tests/test_walkforward_evidence.py",
    "tests/test_xs_forward_review.py",
    "tests/test_xs_forward_status.py",
)
# Content: reports, screens, documents. Changes here reach only the tests that name the
# file, CONTRACT_TESTS (documentation integrity reads every Markdown file) and
# CONTENT_READERS. docs/*.py is code: it is imported and linted.
CONTENT_PATHS = ("data/", "docs/")
CODE_SUFFIXES_IN_CONTENT = (".py",)
# Tests that read content when they run, from a full run recorded with ``--record-reads``
# (``--content-readers`` prints this list from the record). Static analysis misses reads
# through a module more than one import away from the test.
CONTENT_READERS = (
    "tests/contracts/test_provider_contracts.py",
    "tests/contracts/test_runtime_environment.py",
    "tests/test_agent_evaluation_reporting.py",
    "tests/test_documentation_integrity.py",
    "tests/test_operating_contract.py",
    "tests/test_p15_registration.py",
    "tests/test_p16_challenger_runner.py",
    "tests/test_p16_operator_digest.py",
    "tests/test_p16_trial_store.py",
    "tests/test_p22_round4.py",
    "tests/test_registration_identity.py",
    "tests/test_sync.py",
    "tests/test_walkforward_migration_audit.py",
)
# A change here can alter how every test runs or what is selected: run the full suite.
FULL_SUITE_PATHS = (
    ".github/",
    "pyproject.toml",
    "tests/conftest.py",
    "tests/speed_plugin.py",
    "tools/affected_tests.py",
    "uv.lock",
)
SESSION_ROOTS = ("tests/conftest.py", "tests/speed_plugin.py")
# A changed file with one of these suffixes that no test reaches needs no test.
INERT_SUFFIXES = (".gitkeep", ".md")
IGNORED_PARTS = frozenset({
    ".git", ".next", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__", "node_modules",
})
# Non-Python files that run what they name.
RUNNING_SUFFIXES = frozenset({".service", ".sh", ".timer"})
# A one-component name (``"README.md"``, ``"reports"``) naming more files than this is too
# generic to be a dependency; a name with a slash, or an exact repository path, always is.
MAX_NAME_MATCHES = 8
TOKEN = re.compile(r"[A-Za-z0-9_*][A-Za-z0-9_./*-]*")
# A glob names files only with a literal extension: not ``*`` or a calendar (``*-*-*``).
FILE_GLOB = re.compile(r"\.[A-Za-z0-9]+$")


def is_content(path: str) -> bool:
    return path.startswith(CONTENT_PATHS) and not path.endswith(CODE_SUFFIXES_IN_CONTENT)


def is_test_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return path.startswith(TEST_ROOT) and name.startswith("test_") and name.endswith(".py")


def git(*args: str, root: Path = REPO_ROOT) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True,
    ).stdout


def changed_files(base: str, head: str | None = None, *, root: Path = REPO_ROOT) -> list[str]:
    """Paths changed since the merge base; with no head, include the working tree."""
    merge_base = git("merge-base", base, head or "HEAD", root=root).strip()
    if head is None:
        names = git("diff", "--name-only", "--no-renames", merge_base, root=root).splitlines()
        names += git("ls-files", "--others", "--exclude-standard", root=root).splitlines()
    else:
        names = git("diff", "--name-only", "--no-renames", merge_base, head, root=root).splitlines()
    return sorted(set(filter(None, names)))


def tracked_files(root: Path = REPO_ROOT) -> list[str]:
    files = git("ls-files", "--cached", "--others", "--exclude-standard", root=root).splitlines()
    return sorted(
        name for name in set(files)
        if not IGNORED_PARTS.intersection(name.split("/")) and (root / name).is_file()
    )


def module_name(path: str) -> str | None:
    if not path.endswith(".py"):
        return None
    parts = path[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts or not all(part.isidentifier() for part in parts):
        return None
    return ".".join(parts)


def python_facts(root: str, path: str) -> tuple | None:
    """Imported module names (each with whether it is module level) and string literals."""
    try:
        tree = ast.parse(Path(root, path).read_bytes(), filename=path)
    except (SyntaxError, ValueError, OSError):
        return None
    package = (module_name(path) or "").split(".")
    if not path.endswith("__init__.py"):
        package = package[:-1]
    imports: list[tuple[str, bool]] = []
    strings: list[str] = []
    docstrings: set[int] = set()
    top_level = {id(node) for node in tree.body}
    for node in ast.walk(tree):  # breadth first: a definition comes before its docstring
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
        elif isinstance(node, ast.Import):
            imports += [(alias.name, id(node) in top_level) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package[: len(package) - node.level + 1]
                base = ".".join([*anchor, base] if base else anchor)
            top = id(node) in top_level
            imports += [(base, top)] + [(f"{base}.{alias.name}", top) for alias in node.names]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                strings.append(node.value)
        elif isinstance(node, (ast.BinOp, ast.Call)):
            strings += joined_paths(node)
    return imports, strings


def joined_paths(node: ast.AST) -> list[str]:
    """``root / "data" / "reports"`` and ``Path("a", "b")``: runs of literal parts, joined."""
    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, ast.Div):
            return []
        parts: list[ast.AST] = []
        while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            parts.append(node.right)
            node = node.left
        parts.append(node)
        parts.reverse()
    else:
        parts = list(node.args)
    runs, current = [], []
    for part in [*parts, None]:
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            current.append(part.value.strip("/"))
            continue
        if len(current) > 1:
            runs.append("/".join(current))
        current = []
    return runs


class Graph:
    """Reverse import and read edges over the tracked files of one checkout."""

    def __init__(self, root: Path = REPO_ROOT, files: list[str] | None = None):
        self.root = root
        self.files = tracked_files(root) if files is None else files
        self.file_set = set(self.files)
        self.modules = {name: path for path in self.files if (name := module_name(path))}
        self.suffixes: dict[str, set[str]] = defaultdict(set)
        for path in self.files:
            parts = path.split("/")
            for start in range(len(parts)):
                self.suffixes["/".join(parts[start:])].add(path)
                for end in range(start + 1, len(parts)):  # directories: every file below
                    self.suffixes["/".join(parts[start:end])].add(path)
        self._globs: dict[str, set[str]] = {}
        self._names: dict[str, tuple[set[str], set[str]]] = {}
        self.importers: dict[str, set[str]] = defaultdict(set)
        self.readers: dict[str, set[str]] = defaultdict(set)
        self.module_level: dict[str, set[str]] = {}
        self.named_data: dict[str, set[str]] = {}
        python = [path for path in self.files if path.endswith(".py")]
        with ProcessPoolExecutor(max_workers=min(8, os.cpu_count() or 1)) as pool:
            facts = dict(zip(python, pool.map(python_facts, [str(root)] * len(python), python,
                                              chunksize=32), strict=True))
        for path in self.files:
            imported, read = self._dependencies(path, facts.get(path))
            for dependency in imported - {path}:
                self.importers[dependency].add(path)
            for dependency in read - {path}:
                self.readers[dependency].add(path)

    def _module_files(self, name: str) -> set[str]:
        """The module's file and every package ``__init__`` importing it executes."""
        found, parts = set(), name.split(".")
        for end in range(1, len(parts) + 1):
            path = self.modules.get(".".join(parts[:end]))
            if path:
                found.add(path)
        return found

    def _named(self, text: str) -> tuple[set[str], set[str]]:
        """(modules, files) one string or one script names."""
        if text not in self._names:
            modules: set[str] = set()
            files: set[str] = set()
            for token in TOKEN.findall(text):
                token = token.strip("./-")
                if "*" in token:
                    files |= self._globbed(token)
                    continue
                for candidate in {token, token.split(":", 1)[0]}:
                    modules |= self._module_files(candidate) if candidate in self.modules else set()
                    if candidate in self.file_set:
                        files.add(candidate)
                    matches = self.suffixes.get(candidate)
                    if matches and ("/" in candidate or len(matches) <= MAX_NAME_MATCHES):
                        files |= matches
            self._names[text] = (modules, files)
        return self._names[text]

    def _globbed(self, pattern: str) -> set[str]:
        if not FILE_GLOB.search(pattern):
            return set()
        if pattern not in self._globs:
            name = pattern.rsplit("/", 1)[-1]
            self._globs[pattern] = {
                path for path in self.files
                if fnmatch.fnmatchcase(path.rsplit("/", 1)[-1], name)
                and ("/" not in pattern or fnmatch.fnmatchcase(path, f"*{pattern}"))
            }
        return self._globs[pattern]

    def _dependencies(self, path: str, facts: tuple | None) -> tuple[set[str], set[str]]:
        imported: set[str] = set()
        read: set[str] = set()
        if path.endswith(".py"):
            if facts is None:  # unparsable: compileall fails; the file itself is selected
                return imported, read
            imports, strings = facts
            module_level: set[str] = set()
            for name, top in imports:
                files = self._module_files(name)
                imported |= files
                if top:
                    module_level |= files
            for text in strings:
                modules, files = self._named(text)
                imported |= modules
                read |= files
            self.module_level[path] = module_level
            self.named_data[path] = {item for item in read if not item.endswith(".py")}
        elif Path(path).suffix in RUNNING_SUFFIXES:
            try:
                imported, read = self._named((self.root / path).read_text(errors="replace"))
            except OSError:
                pass
        return imported, read

    def _imported_by(self, start: set[str], hops: int | None = None) -> set[str]:
        seen, frontier = set(start), set(start)
        while frontier and hops != 0:
            frontier = {item for path in frontier for item in self.importers.get(path, ())} - seen
            seen |= frontier
            hops = None if hops is None else hops - 1
        return seen

    def closure(self, changed: set[str]) -> set[str]:
        """Every file a change can affect (the rules are in the module docstring)."""
        affected = self._imported_by(set(changed))
        expanded = dict.fromkeys(affected, -1)  # import hops already followed from a file
        queue = sorted(affected)
        while queue:
            item = queue.pop()
            for reader in sorted(self.readers.get(item, ())):
                if is_content(item) and not is_test_file(reader):
                    continue
                hops = -1 if not reader.endswith(".py") else 0 if is_content(item) else 1
                if expanded.get(reader, -2) == -1 or expanded.get(reader, -2) >= hops >= 0:
                    continue
                expanded[reader] = hops
                new = self._imported_by({reader}, None if hops == -1 else hops) - affected
                affected |= new | {reader}
                queue += sorted(path for path in new | {reader}
                                if hops == -1 or not path.endswith(".py"))
        return affected

    def session_files(self) -> set[str]:
        """What every test session loads: the session roots, their module-level imports
        transitively, and the data files they name (``durations.json``)."""
        roots = [path for path in SESSION_ROOTS if path in self.file_set]
        seen, stack = set(roots), list(roots)
        while stack:
            for dependency in self.module_level.get(stack.pop(), ()):
                if dependency not in seen:
                    seen.add(dependency)
                    stack.append(dependency)
        for root in roots:
            seen |= self.named_data.get(root, set())
        return seen


def select(changed: list[str], graph: Graph | None = None) -> dict:
    """``{"mode": "full"|"selected", "tests": [...], "reasons": [...]}`` for these changes."""

    def full(reason: str) -> dict:
        return {"mode": "full", "tests": [], "reasons": [reason]}

    for path in changed:
        if path.startswith(FULL_SUITE_PATHS):
            return full(f"{path}: full-suite path")
    graph = graph or Graph()
    present = [path for path in changed if path in graph.file_set]
    for path in sorted(set(present) & graph.session_files()):
        return full(f"{path}: loaded by every test session")
    for path in sorted(set(changed) - set(present)):
        if not is_content(path) and not is_test_file(path):
            return full(f"{path}: deleted; what used it cannot be traced")
    tests = set(CONTRACT_TESTS)
    reasons: list[str] = []
    if any(is_content(path) for path in changed):
        tests |= set(CONTENT_READERS)
        reasons.append(f"content changed: {len(CONTENT_READERS)} content readers")
    for path in present:
        reached = {item for item in graph.closure({path}) if is_test_file(item)}
        if not reached and not is_content(path) and not path.endswith(INERT_SUFFIXES):
            return full(f"{path}: no test reaches it; its dependants are unknown")
        tests |= reached
        if reached:
            reasons.append(f"{path}: {len(reached)} test files")
    return {"mode": "selected", "tests": sorted(tests & graph.file_set), "reasons": reasons}


def content_readers(record: dict[str, list[str]]) -> list[str]:
    """Test files a ``--record-reads`` record shows reading content."""
    return sorted(
        test for test, paths in record.items()
        if is_test_file(test) and any(is_content(path) for path in paths)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--base", default="origin/main", help="compare with the merge base of this ref")
    parser.add_argument("--head", help="compare up to this commit instead of the working tree")
    parser.add_argument("--files", nargs="*", help="use these changed paths instead of git")
    parser.add_argument("--explain", action="store_true", help="print why tests are selected")
    parser.add_argument("--run", action="store_true", help="run ruff, compileall and pytest")
    parser.add_argument("--workers", default="8", help="pytest-xdist workers for --run")
    parser.add_argument("--content-readers", metavar="RECORD",
                        help="print the content readers in a --record-reads record and exit")
    args = parser.parse_args(argv)
    if args.content_readers:
        print("\n".join(content_readers(json.loads(Path(args.content_readers).read_text()))))
        return 0
    changed = args.files if args.files is not None else changed_files(args.base, args.head)
    selection = select(changed)
    if args.explain:
        for line in selection["reasons"]:
            print(f"# {line}", file=sys.stderr)
        print(f"# {len(changed)} changed files; mode {selection['mode']}; "
              f"{len(selection['tests'])} test files", file=sys.stderr)
    tests = selection["tests"] if selection["mode"] == "selected" else []
    if not args.run:
        print("\n".join(tests) or "tests")
        return 0
    python = sys.executable
    steps = [
        [python, "-m", "ruff", "check", "."],
        [python, "-m", "compileall", "-q", "engine", "sim", "server", "tests", "farm", "tools"],
        [python, "-m", "pytest", "-q", "-W", "error", "-n", args.workers, *tests],
    ]
    for step in steps:
        code = subprocess.run(step, cwd=REPO_ROOT).returncode
        if code:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
