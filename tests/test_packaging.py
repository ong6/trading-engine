"""Packaging and dependency declarations match the active Python source tree."""
from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOTS = ("engine", "farm", "server", "sim")
IMPORT_TO_DISTRIBUTION = {
    "curl_cffi": "curl-cffi",
    "duckdb": "duckdb",
    "fastapi": "fastapi",
    "numpy": "numpy",
    "openpyxl": "openpyxl",
    "pandas": "pandas",
    "pandas_market_calendars": "pandas-market-calendars",
    "requests": "requests",
    "xlrd": "xlrd",
    "yaml": "pyyaml",
    "yfinance": "yfinance",
}


def _source_files():
    for package in PACKAGE_ROOTS:
        yield from (REPO_ROOT / package).rglob("*.py")


def _top_level_imports(path: Path) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module.split(".", 1)[0])
    return imports


def _normalized_requirement_name(requirement: str) -> str:
    name = re.split(r"[<>=!~;\[]", requirement, maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def test_active_code_uses_package_qualified_internal_imports():
    offenders: list[str] = []
    internal_modules = {
        path.stem
        for package in PACKAGE_ROOTS
        for path in (REPO_ROOT / package).glob("*.py")
        if path.name != "__init__.py"
    }
    for path in _source_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".", 1)[0]]
            for name in names:
                if (
                    name in internal_modules
                    and name not in PACKAGE_ROOTS
                    and name not in sys.stdlib_module_names
                ):
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno}: bare import {name}"
                    )
    assert not offenders, "use package-qualified internal imports:\n" + "\n".join(offenders)


def test_direct_third_party_imports_are_declared_runtime_dependencies():
    imported = set().union(*(_top_level_imports(path) for path in _source_files()))
    third_party = imported - set(sys.stdlib_module_names) - set(PACKAGE_ROOTS)
    unknown = third_party - IMPORT_TO_DISTRIBUTION.keys()
    assert not unknown, f"third-party imports need a distribution mapping: {sorted(unknown)}"
    requirements = {
        _normalized_requirement_name(line)
        for line in (REPO_ROOT / "engine" / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    missing = {
        module: IMPORT_TO_DISTRIBUTION[module]
        for module in sorted(third_party)
        if IMPORT_TO_DISTRIBUTION[module] not in requirements
    }
    assert not missing, f"direct imports missing from runtime requirements: {missing}"


def test_pyproject_declares_only_active_package_trees():
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    assert project["build-system"]["build-backend"] == "setuptools.build_meta"
    assert project["tool"]["setuptools"]["packages"]["find"] == {
        "include": ["engine*", "farm*", "server*", "sim*"],
        "namespaces": False,
    }
    assert (REPO_ROOT / "farm" / "experiments" / "__init__.py").is_file()
    assert project["project"]["optional-dependencies"]["dev"] == [
        "pytest>=8",
        "ruff>=0.12",
    ]
