"""Select the tests a change can affect: the fast tier for agents and pull requests.

``python -m tools.affected_tests`` prints the test files to run for the changes since the
merge base with ``origin/main`` (committed, staged, unstaged and untracked); ``--run`` runs
ruff, compileall and pytest on them. The fast tier (this selection, locally and on pull
requests and branches) is quick feedback, not the gate: ``main``'s full run in both
timezones is, and a lane is merged only after both timezone suites pass.

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
  for a deleted non-content file (what used it cannot be traced), for a module under a
  package some file imports by a computed name (``import_module(f"engine.{x}")``; with no
  literal prefix, as in ``["-m", name]``, ``"engine." + n``, %-formatting, ``run_module``,
  ``find_spec`` or ``getattr(importlib, ...)``, any module) outside
  ``REVIEWED_COMPUTED_IMPORTS``, and for a
  changed file no test reaches (an unknown dependency is never assumed to be none).
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import http.client
import json
import math
import os
import re
import subprocess
import sys
import urllib.request
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
    # Known misses: a full run's recorded reads show these read units, registration JSON,
    # README.md or docs/ through modules two or more imports away, which the graph misses.
    "tests/test_agent_evaluation_reporting.py",
    "tests/test_agent_release_review_store.py",
    "tests/test_backup_database.py",
    "tests/test_dataset_catalogue.py",
    "tests/test_install_automation.py",
    "tests/test_log_retention.py",
    "tests/test_p15_preopen.py",
    "tests/test_p16_challenger_runner.py",
    "tests/test_p16_eval_inputs.py",
    "tests/test_p16_operator_digest.py",
    "tests/test_p16_reporting.py",
    "tests/test_release_deploy.py",
    "tests/test_service_units.py",
)
# Content: reports, screens, documents and images under these trees, and nothing that runs.
# Any other suffix there (.py, .sh, .sql, .toml, .yaml, none), a tracked symlink and the
# target of one are code. A content change reaches the tests that read it like any change
# (documentation integrity, a contract test, reads every Markdown file) plus CONTENT_READERS.
CONTENT_PATHS = ("data/", "docs/")
CONTENT_SUFFIXES = (
    ".csv", ".gif", ".html", ".ico", ".jpeg", ".jpg", ".json", ".jsonl", ".md", ".png", ".svg",
    ".txt", ".webp",
)
# Tests that read content when they run: the readers in CONTENT_READS, the content part of
# a full run recorded with the speed plugin's ``--record-reads`` (``--save-content-reads``
# writes it). tests/test_affected_tests.py fails when a recorded reader is neither
# reached by the graph from what it read nor a contract test.
CONTENT_READS = REPO_ROOT / "tests" / "content_reads.json"
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
    "tests/content_reads.json",
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
# ``-m`` followed by a module name with a computed part, in an f-string, or a placeholder
# for %-formatting or str.format.
COMPUTED_DASH_M = re.compile(r"-m\s+([\w.]*)\x00")
COMPUTED_FORMAT_M = re.compile(r"-m\s+[\w.]*(%[-\w]*[sr]|\{)")
IMPORT_FUNCTIONS = frozenset({"__import__", "find_spec", "import_module", "run_module"})
# Files whose computed imports were reviewed and are bounded elsewhere; any other computed
# import selects the full suite for every change to a module (``select``).
REVIEWED_COMPUTED_IMPORTS = {
    "farm/research/worker.py": "loads a study's callback module, verified by hash, inside the "
                               "research sandbox; farm/research/tests run in the checks job",
    "tools/release_deploy.py": "_python_module runs `-m *args`; its only caller passes the "
                               "string-literal module names of run_migration's table, which "
                               "are import edges already",
    "tests/test_affected_tests.py": "the computed imports are sources it parses as test data",
    "engine/lib/snapshots.py": "loads the migration modules named by its own string-literal "
                               "MIGRATION_MODULES, which are import edges already",
    "engine/schema_migrations.py": "run_fresh_initializers imports the string-literal "
                                   "BOOTSTRAP_CALLS modules of migration 0000, which are import "
                                   "edges of that module already",
    "tests/test_baseline_table_coverage.py": "resolves constants only in the engine/, sim/, "
                                             "server/, tools/ and farm/ sources it scans as "
                                             "text; main's full suite runs it on every change",
}


# CI (``--ci-plan``): summed recorded seconds of a selection per shard, four workers each.
SHARD_SECONDS = 240.0
FULL_SHARDS = 4
UNKNOWN_FILE_SECONDS = 2.0
BOTH_TIMEZONES = ["UTC", "Asia/Singapore"]
FAST_TIMEZONES = ["UTC"]
MAIN_REF = "refs/heads/main"


def is_content(path: str, symlinked: frozenset[str] = frozenset()) -> bool:
    """A content path by name; ``symlinked`` (from ``symlinked_paths``) makes it code."""
    return (path.startswith(CONTENT_PATHS) and path.lower().endswith(CONTENT_SUFFIXES)
            and path not in symlinked)


def symlinked_paths(root: Path = REPO_ROOT) -> frozenset[str]:
    """Tracked symlinks and the repository paths they point at."""
    found: set[str] = set()
    for line in git("ls-files", "-s", root=root).splitlines():
        meta, _, path = line.partition("\t")
        if meta.startswith("120000 "):
            found.add(path)
            try:
                target = os.path.normpath(os.path.join(os.path.dirname(path),
                                                       os.readlink(root / path)))
            except OSError:
                continue
            found.add(Path(target).as_posix())
    return frozenset(found)


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
    computed: list[str] = []
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
                if COMPUTED_FORMAT_M.search(node.value):  # "-m %s" % name, "-m {}".format(name)
                    computed.append("")
        elif isinstance(node, (ast.BinOp, ast.Call)):
            strings += joined_paths(node)
            if isinstance(node, ast.Call):
                computed += computed_imports(node)
        elif isinstance(node, ast.JoinedStr):
            computed += [match.group(1).strip(".") for match in
                         COMPUTED_DASH_M.finditer(_template(node))]
        elif isinstance(node, (ast.List, ast.Tuple)):
            for flag, value in zip(node.elts, node.elts[1:], strict=False):
                if (isinstance(flag, ast.Constant) and flag.value == "-m"
                        and not isinstance(value, ast.Constant)):
                    computed.append(_literal_head(value))
    return imports, strings, computed


def import_closure(roots: tuple[str, ...], root: Path = REPO_ROOT) -> tuple[str, ...]:
    """The repo-local Python files ``roots`` import, transitively (the roots included).

    The same import resolution as ``Graph`` (a module and the package ``__init__`` files its
    import executes), over the importing files only: cheap enough to run at process start.
    """
    def resolve(name: str) -> list[str]:
        parts, found = name.split("."), []
        for end in range(1, len(parts) + 1):
            stem = Path(root, *parts[:end])
            for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
                if candidate.is_file():
                    found.append(candidate.relative_to(root).as_posix())
        return found

    seen, stack = set(roots), list(roots)
    while stack:
        facts = python_facts(str(root), stack.pop())
        for name, _top in (facts[0] if facts else ()):
            for path in resolve(name):
                if path not in seen:
                    seen.add(path)
                    stack.append(path)
    return tuple(sorted(seen))


def _template(node: ast.JoinedStr) -> str:
    """An f-string's literal parts with NUL where a value is formatted in."""
    return "".join(part.value if isinstance(part, ast.Constant) else "\0" for part in node.values)


def _literal_head(node: ast.AST) -> str:
    """The module-name prefix fixed before the first computed part: ``f"engine.{x}"`` gives
    ``engine``; a name computed entirely gives the empty string."""
    if isinstance(node, ast.JoinedStr):
        return re.sub(r"[^\w.]", "", _template(node).split("\0", 1)[0]).strip(".")
    return ""


def computed_imports(node: ast.Call) -> list[str]:
    """A module loaded by a name not written out: ``import_module``, ``__import__``,
    ``runpy.run_module`` or ``find_spec`` given anything but a string literal, and any
    ``getattr(..., "import_module")``. An f-string's literal prefix bounds the package;
    anything else (``"engine." + n``, a variable) can name any module: ``""``."""
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if name == "getattr" and len(node.args) > 1 and isinstance(node.args[1], ast.Constant) \
            and node.args[1].value in IMPORT_FUNCTIONS:
        return [""]
    if name not in IMPORT_FUNCTIONS or not node.args or isinstance(node.args[0], ast.Constant):
        return []
    return [_literal_head(node.args[0])]


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
        self.symlinked = symlinked_paths(root)
        self.computed: dict[str, set[str]] = {}  # module prefix -> files importing under it
        for path in self.files:
            if (root / path).is_symlink():  # the link runs whatever it points at
                target = Path(os.path.normpath(os.path.join(os.path.dirname(path),
                                                            os.readlink(root / path))))
                self.importers[target.as_posix()].add(path)
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
            for raw_token in TOKEN.findall(text):
                token = raw_token.strip("./-")
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
            imports, strings, computed = facts
            for prefix in computed if path not in REVIEWED_COMPUTED_IMPORTS else ():
                self.computed.setdefault(prefix, set()).add(path)
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
                # a script, or any module reading content, passes the change to every
                # importer; a module reading a code file passes it one import on
                hops = -1 if not reader.endswith(".py") or is_content(item, self.symlinked) else 1
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
    for path in changed:
        name = module_name(path) or ""
        for prefix, importers in sorted(graph.computed.items()):
            if name and (not prefix or name == prefix or name.startswith(f"{prefix}.")):
                return full(f"{path}: {sorted(importers)[0]} imports a computed name under "
                            f"{prefix or 'any package'}")
    for path in sorted(set(changed) - set(present)):
        if not is_content(path, graph.symlinked) and not is_test_file(path):
            return full(f"{path}: deleted; what used it cannot be traced")
    tests = set(CONTRACT_TESTS)
    reasons: list[str] = []
    if any(is_content(path, graph.symlinked) for path in changed):
        tests |= set(CONTENT_READERS)
        reasons.append(f"content changed: {len(CONTENT_READERS)} content readers")
    for path in present:
        reached = {item for item in graph.closure({path}) if is_test_file(item)}
        if (not reached and not is_content(path, graph.symlinked)
                and not path.endswith(INERT_SUFFIXES)):
            return full(f"{path}: no test reaches it; its dependants are unknown")
        tests |= reached
        if reached:
            reasons.append(f"{path}: {len(reached)} test files")
    return {"mode": "selected", "tests": sorted(tests & graph.file_set), "reasons": reasons}


def scope(changed: list[str], root: Path = REPO_ROOT) -> str:
    """The CI paths filter: ``content`` when every changed path is content, else ``code``."""
    symlinked = symlinked_paths(root)
    return "content" if all(is_content(path, symlinked) for path in changed) else "code"


def estimated_seconds(tests: list[str], root: Path = REPO_ROOT) -> float:
    try:
        recorded = json.loads((root / "tests" / "durations.json").read_text())["files"]
    except (OSError, ValueError, KeyError):
        recorded = {}
    if not tests:
        return SHARD_SECONDS * FULL_SHARDS
    return sum(recorded.get(test, UNKNOWN_FILE_SECONDS) for test in tests)


def range_files(base: str, *, root: Path = REPO_ROOT) -> list[str]:
    """Every path any commit in ``base..HEAD`` changed (each against its first parent),
    plus the net difference: a code change later reverted still counts as code."""
    names = set(changed_files(base, "HEAD", root=root))
    for commit in git("rev-list", f"{base}..HEAD", root=root).split():
        parent = git("rev-list", "--parents", "-n", "1", commit, root=root).split()[1:2]
        args = ["diff", "--name-only", "--no-renames", parent[0], commit] if parent else [
            "show", "--name-only", "--format=", commit]
        names |= set(filter(None, git(*args, root=root).splitlines()))
    return sorted(names)


def github_json(url: str, token: str) -> dict:
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def last_full_success(repository: str, token: str, api: str = "https://api.github.com") -> str | None:
    """The head commit of the newest ``main`` run of this workflow whose full matrix (every
    ``test`` job, both timezones, all shards) succeeded, or None."""
    runs = github_json(f"{api}/repos/{repository}/actions/workflows/ci.yml/runs"
                       "?branch=main&status=success&per_page=30", token)["workflow_runs"]
    for run in runs:
        if run["event"] not in {"push", "schedule", "workflow_dispatch"}:
            continue
        jobs = github_json(f"{run['jobs_url']}?per_page=100", token)["jobs"]
        tests = [job for job in jobs if job["name"].startswith("test (")]
        if len(tests) == FULL_SHARDS * len(BOTH_TIMEZONES) and all(
                job["conclusion"] == "success" for job in tests):
            return run["head_sha"]
    return None


def ci_plan(event: str, base: str, ref: str = MAIN_REF, *, root: Path = REPO_ROOT) -> dict:
    """What the CI workflow runs for one event.

    ``tier`` is ``full`` (every test in both timezones on four shards) or ``selected``
    (``select`` on the changes since ``base``, sharded by recorded durations).

    - ``main``: ``base`` is the last commit whose full run succeeded (``last_full_success``),
      so a push after a cancelled, failed or skipped full run is still compared with code
      that passed. The push is ``selected`` in both timezones only when no commit since
      then touched code (``range_files``); otherwise ``full``.
    - Pull requests and other branches: the fast tier, ``selected`` in one timezone (the
      full suite there when ``select`` falls back). It is feedback, not the gate: ``main``'s
      full run in both timezones is.
    - ``full`` also for the schedule, manual runs, a missing, unreachable or non-ancestor
      ``main`` base, and an empty range. Content-only runs skip the checks job and the UI
      build.
    """
    on_main = event == "push" and ref == MAIN_REF
    plan = {"tier": "full", "scope": "code", "base": base, "timezones": BOTH_TIMEZONES,
            "shards": list(range(FULL_SHARDS)), "reasons": []}
    changed = None
    if event in {"schedule", "workflow_dispatch"} or not base.strip("0"):
        plan["reasons"].append(f"{event}: full run")
    else:
        try:
            if on_main:
                git("merge-base", "--is-ancestor", base, "HEAD", root=root)
            changed = range_files(base, root=root) if on_main else changed_files(base, "HEAD", root=root)
        except subprocess.CalledProcessError:
            plan["reasons"].append(f"base {base} is not reachable or not an ancestor: full run")
    if changed == []:
        plan["reasons"].append("nothing changed since the base: full run")
        changed = None
    if changed is not None:
        plan["scope"] = scope(changed, root)
        plan["reasons"].append(f"{len(changed)} changed files, scope {plan['scope']}")
    if changed is not None and (plan["scope"] == "content" or not on_main):
        selection = select(changed, Graph(root))
        plan["reasons"] += selection["reasons"]
        plan["tier"] = "selected"
        plan["timezones"] = BOTH_TIMEZONES if on_main else FAST_TIMEZONES
        if selection["mode"] == "selected":
            seconds = estimated_seconds(selection["tests"], root)
            plan["shards"] = list(range(min(FULL_SHARDS, max(1, math.ceil(seconds / SHARD_SECONDS)))))
    return plan | {"shard_count": len(plan["shards"])}


def ci_verdict(needs: dict) -> list[str]:
    """Problems with the jobs one plan required; empty when the run passed.

    ``needs`` is the workflow's ``needs`` context. A job the plan required must succeed:
    hygiene and the plan always, the tier's test job (both for an unknown tier), and the
    checks and UI build unless the scope is ``content``: anything unknown fails closed.
    """
    plan = needs.get("changes", {})
    outputs = plan.get("outputs") or {}
    required = {"hygiene", "changes"}
    if plan.get("result") == "success":
        tier = outputs.get("tier")
        required |= {"full": {"test"}, "selected": {"selected"}}.get(tier, {"test", "selected"})
        if outputs.get("scope") != "content":
            required |= {"checks", "ui-build"}
    problems = [f"{name}: {needs.get(name, {}).get('result', 'missing')}"
                for name in sorted(required) if needs.get(name, {}).get("result") != "success"]
    problems += [f"{name}: {job.get('result')}" for name, job in sorted(needs.items())
                 if name not in required and job.get("result") not in {"success", "skipped"}]
    return problems


def reads_content(path: str) -> bool:
    """A recorded read of content: a content file, or a listing of a content directory."""
    return is_content(path) or (path.startswith(CONTENT_PATHS) and "." not in path.rsplit("/", 1)[-1])


def content_reads(record: dict[str, list[str]]) -> dict[str, list[str]]:
    """The content part of a ``--record-reads`` record, by test file."""
    reads = {test: sorted(path for path in paths if reads_content(path))
             for test, paths in record.items() if is_test_file(test)}
    return {test: paths for test, paths in sorted(reads.items()) if paths}


def content_readers(record: dict[str, list[str]]) -> list[str]:
    """Test files a ``--record-reads`` record shows reading content."""
    return sorted(content_reads(record))


def unreached_content_reads(record: dict[str, list[str]], graph: Graph) -> list[str]:
    """Recorded content reads the selection would not follow: the reading test is not a
    contract test and no tracked content file it read (or listed) reaches it."""
    problems = []
    for test, paths in content_reads(record).items():
        if test in CONTRACT_TESTS or test not in graph.file_set:
            continue
        for path in paths:
            sources = [path] if path in graph.file_set else [
                item for item in graph.files
                if item.startswith(f"{path}/") and is_content(item, graph.symlinked)]
            if sources and not any(test in graph.closure({source}) for source in sources):
                problems.append(f"{test} reads {path}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--base", default="origin/main", help="compare with the merge base of this ref")
    parser.add_argument("--head", help="compare up to this commit instead of the working tree")
    parser.add_argument("--files", nargs="*", help="use these changed paths instead of git")
    parser.add_argument("--explain", action="store_true", help="print why tests are selected")
    parser.add_argument("--run", action="store_true", help="run ruff, compileall and pytest")
    parser.add_argument("--workers", default="8", help="pytest-xdist workers for --run")
    parser.add_argument("--skip-slow", action="store_true",
                        help="with --run, leave out tests marked slow (CI still runs them)")
    parser.add_argument("--content-readers", metavar="RECORD",
                        help="print the content readers in a --record-reads record and exit")
    parser.add_argument("--save-content-reads", metavar="RECORD",
                        help=f"write the content part of a --record-reads record to {CONTENT_READS.name}")
    parser.add_argument("--ci-plan", metavar="EVENT",
                        help="write the CI plan for this GitHub event to $GITHUB_OUTPUT")
    parser.add_argument("--ref", default=os.environ.get("GITHUB_REF", MAIN_REF),
                        help="the Git ref the CI event ran on")
    parser.add_argument("--ci-verdict", action="store_true",
                        help="fail unless the jobs in $CI_NEEDS that the plan required passed")
    args = parser.parse_args(argv)
    if args.ci_plan:
        base = args.base
        if args.ci_plan == "push" and args.ref == MAIN_REF:
            try:  # fails closed: no lookup means no base, which plans the full tier
                base = last_full_success(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"],
                                         os.environ.get("GITHUB_API_URL", "https://api.github.com")) or ""
            except (KeyError, OSError, ValueError, http.client.HTTPException) as error:
                print(f"last full run lookup failed ({error!r}): full run")
                base = ""
        plan = ci_plan(args.ci_plan, base, args.ref)
        lines = [f"{key}={json.dumps(value) if isinstance(value, list) else value}"
                 for key, value in plan.items() if key != "reasons"]
        print("\n".join([*plan["reasons"], *lines]))
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as handle:
                handle.write("\n".join(lines) + "\n")
        return 0
    if args.ci_verdict:
        problems = ci_verdict(json.loads(os.environ["CI_NEEDS"]))
        print("\n".join(problems) or "every required job passed")
        return 1 if problems else 0
    if args.save_content_reads:
        from engine.lib.resources import write_text_atomic  # needs the project environment

        reads = content_reads(json.loads(Path(args.save_content_reads).read_text()))
        write_text_atomic(CONTENT_READS, json.dumps(reads, indent=1) + "\n")
        return 0
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
        [python, "-m", "pytest", "-q", "-W", "error", "-n", args.workers,
         *(["-m", "not slow"] if args.skip_slow else []), *tests],
    ]
    for step in steps:
        code = subprocess.run(step, cwd=REPO_ROOT).returncode
        if code:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
