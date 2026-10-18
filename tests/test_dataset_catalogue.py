import ast
import copy
import fnmatch
import re
from pathlib import Path

import pytest
import yaml

from engine.accounts.sources import SOURCE_PATHS, SOURCE_TABLES


ROOT = Path(__file__).resolve().parents[1]
CATALOGUE_PATH = ROOT / "schemas" / "datasets.yaml"
CODE_ROOTS = tuple(ROOT / name for name in ("engine", "farm", "server", "sim", "tools"))
REQUIRED_FIELDS = {
    "id",
    "kind",
    "location",
    "schema_owner",
    "producer",
    "readers",
    "semantics",
    "clock_and_key",
    "retention",
    "backup",
    "rebuild",
    "registration",
    "quality_gate",
}
ALLOWED_KINDS = {
    "duckdb_table",
    "duckdb_view",
    "file_set",
    "generation",
    "external_backup",
}
ALLOWED_SEMANTICS = {
    "authoritative",
    "append_only_evidence",
    "mutable_projection",
    "current_state",
    "derived",
    "cache",
}
LIST_FIELDS = {"schema_owner", "producer", "readers", "registration"}
TEXT_FIELDS = REQUIRED_FIELDS - LIST_FIELDS - {"kind", "semantics"}
DDL_RE = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?"
    r"(?!(?:TEMP|TEMPORARY)\s)(TABLE|VIEW)\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
MANAGED_PATH_RE = re.compile(
    r"(?:^|[\s`(])(?:trading-engine/)?"
    r"((?:store|data|logs|scratch)/[A-Za-z0-9_.*{}<>/-]+(?:\.[A-Za-z0-9_*{}<>-]+)?)"
)
FALSE_DDL_NAMES = {"if", "so"}
EXTERNAL_DYNAMIC_CONSTANTS = {
    "RETENTION_TABLE": "broker_paper_authority_retained_events",
    "RISK_EVIDENCE_TABLE": "broker_paper_authority_risk_evaluations",
}
NON_DUCKDB_DDL_SOURCES = {Path("tools/ops_digest.py")}
IGNORED_MANAGED_PATHS = {
    # A historical repair docstring describes a store/Yahoo price ratio; it is
    # not a path.  The script is retained under docs/history.
    "store/yahoo",
    "store/.agent-fault-drill.lock",
    "store/agent-shadow-control.json.lock",
    "data/_meta.json.lock",
}


def _load_catalogue() -> dict:
    return yaml.safe_load(CATALOGUE_PATH.read_text())


def _python_sources() -> list[Path]:
    return sorted(path for root in CODE_ROOTS for path in root.rglob("*.py"))


def _catalogued_objects(catalogue: dict) -> set[str]:
    return {
        f"{dataset['kind'].removeprefix('duckdb_')}:"
        f"{dataset['location'].rsplit('.', 1)[1]}"
        for dataset in catalogue["datasets"]
        if dataset["kind"] in {"duckdb_table", "duckdb_view"}
    }


def _literal_constants(tree: ast.AST) -> dict[str, object]:
    constants = {}
    for node in getattr(tree, "body", []):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if len(targets) != 1 or not isinstance(targets[0], ast.Name):
            continue
        try:
            constants[targets[0].id] = ast.literal_eval(node.value)
        except (TypeError, ValueError):
            continue
    return constants


def _joined_template(node: ast.JoinedStr) -> str:
    parts = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        elif isinstance(value, ast.FormattedValue):
            if isinstance(value.value, ast.Name):
                parts.append("{" + value.value.id + "}")
            elif isinstance(value.value, ast.Attribute):
                parts.append("{" + value.value.attr + "}")
            else:
                parts.append("{expression}")
    return "".join(parts)


def _dynamic_objects(tree: ast.AST, path: Path) -> set[str]:
    constants = _literal_constants(tree)
    objects = set()
    unresolved = []
    dynamic_re = re.compile(
        r"\bCREATE\s+(?:OR\s+REPLACE\s+)?"
        r"(?!(?:TEMP|TEMPORARY)\s)(TABLE|VIEW)\s+"
        r"(?:IF\s+NOT\s+EXISTS\s+)?\{([A-Za-z_][A-Za-z0-9_]*)\}",
        re.IGNORECASE,
    )
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        for kind, variable in dynamic_re.findall(_joined_template(node)):
            names = constants.get(variable, EXTERNAL_DYNAMIC_CONSTANTS.get(variable))
            if names is None and variable == "table":
                names = constants.get("TABLES")
            if isinstance(names, str):
                names = [names]
            if not isinstance(names, (list, tuple, set, frozenset)) or not all(
                isinstance(name, str) for name in names
            ):
                unresolved.append((node.lineno, variable))
                continue
            objects.update(f"{kind.lower()}:{name}" for name in names)
    assert unresolved == [], {"source": str(path.relative_to(ROOT)), "unresolved": unresolved}
    return objects


def _declared_objects(sources: list[Path]) -> set[str]:
    objects = set()
    for path in sources:
        if path.is_relative_to(ROOT) and path.relative_to(ROOT) in NON_DUCKDB_DDL_SOURCES:
            continue
        text = path.read_text()
        tree = ast.parse(text, filename=str(path))
        for kind, name in DDL_RE.findall(text):
            if name.lower() not in FALSE_DDL_NAMES:
                objects.add(f"{kind.lower()}:{name}")
        objects.update(_dynamic_objects(tree, path))
    named = {item.split(":", 1)[1] for item in objects}
    for relations in SOURCE_TABLES.values():
        objects.update(
            f"table:{relation}" for relation in relations if relation not in named
        )
    return objects


def _path_references(sources: list[Path]) -> set[str]:
    references = set()
    for path in sources:
        tree = ast.parse(path.read_text(), filename=str(path))
        strings = (
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
        for value in strings:
            references.update(MANAGED_PATH_RE.findall(value))
    return {
        value.rstrip("`'\".,:;)")
        for value in references
        if value.rstrip("`'\".,:;)") not in IGNORED_MANAGED_PATHS
        and value.rstrip("`'\".,:;").split("/", 1)[-1]
    }


def _location_patterns(catalogue: dict) -> list[str]:
    patterns = []
    for dataset in catalogue["datasets"]:
        if dataset["kind"] in {"file_set", "generation"}:
            location = dataset["location"]
            if "{" in location:
                before, choices, after = re.fullmatch(r"([^{}]*)\{([^{}]+)\}(.*)", location).groups()
                patterns.extend(f"{before}{choice}{after}" for choice in choices.split(","))
            else:
                patterns.append(location)
    return patterns


def _covered_path(reference: str, patterns: list[str]) -> bool:
    if reference in {"store/", "data/", "logs/", "scratch/"}:
        return True
    return any(
        fnmatch.fnmatchcase(reference, pattern)
        or (pattern.endswith("/**") and reference == pattern[:-3])
        for pattern in patterns
    )


def _validate_catalogue(catalogue: dict) -> None:
    assert catalogue["catalogue_version"] == 2
    datasets = catalogue["datasets"]
    assert datasets
    assert all(set(dataset) == REQUIRED_FIELDS for dataset in datasets)
    assert all(dataset["kind"] in ALLOWED_KINDS for dataset in datasets)
    assert all(dataset["semantics"] in ALLOWED_SEMANTICS for dataset in datasets)
    assert all(
        isinstance(dataset[field], str) and dataset[field].strip()
        for dataset in datasets
        for field in TEXT_FIELDS | {"kind", "semantics"}
    )
    assert all(
        isinstance(dataset[field], list)
        and dataset[field]
        and all(isinstance(value, str) and value.strip() for value in dataset[field])
        for dataset in datasets
        for field in LIST_FIELDS
    )
    ids = [dataset["id"] for dataset in datasets]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[a-z][a-z0-9_.-]+", identifier) for identifier in ids)
    identities = [(dataset["kind"], dataset["location"]) for dataset in datasets]
    assert len(identities) == len(set(identities))

    relation_location = re.compile(
        r"(?:store/.+\.duckdb|scratch/.+\.duckdb|memory://[^#]+)"
        r"#main\.[A-Za-z_][A-Za-z0-9_]*$"
    )
    assert all(
        relation_location.fullmatch(dataset["location"])
        for dataset in datasets
        if dataset["kind"] in {"duckdb_table", "duckdb_view"}
    )
    assert all(
        "#" not in dataset["location"]
        for dataset in datasets
        if dataset["kind"] in {"file_set", "generation", "external_backup"}
    )


def test_catalogue_records_implement_the_accepted_contract():
    _validate_catalogue(_load_catalogue())


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("kind", "duckdb_objects"),
        ("semantics", "authoritative_and_cache"),
        ("readers", []),
        ("retention", ""),
        ("location", "store/market.duckdb"),
    ],
)
def test_catalogue_validator_rejects_invalid_contracts(field, invalid):
    catalogue = copy.deepcopy(_load_catalogue())
    catalogue["datasets"][0][field] = invalid

    with pytest.raises(AssertionError):
        _validate_catalogue(catalogue)


def test_catalogue_matches_every_persistent_ddl_object_bidirectionally():
    catalogue = _load_catalogue()
    declared = _declared_objects(_python_sources())
    catalogued = _catalogued_objects(catalogue)

    assert catalogued == declared, {
        "missing_from_catalogue": sorted(declared - catalogued),
        "listed_but_gone": sorted(catalogued - declared),
    }


def test_catalogue_covers_managed_file_references():
    catalogue = _load_catalogue()
    patterns = _location_patterns(catalogue)
    uncovered = sorted(
        reference
        for reference in _path_references(_python_sources())
        if not _covered_path(reference, patterns)
    )

    assert uncovered == []


def test_unknown_table_and_managed_raw_family_are_detected(tmp_path):
    source = tmp_path / "producer.py"
    source.write_text(
        'from pathlib import Path\n'
        'RAW = Path("store/pit/new-provider/raw")\n'
        'DDL = "CREATE TABLE new_provider_rows (id BIGINT)"\n'
        'DYNAMIC_TABLE = "new_provider_dynamic_rows"\n'
        'DYNAMIC_DDL = f"CREATE TABLE {DYNAMIC_TABLE} (id BIGINT)"\n'
    )
    catalogue = _load_catalogue()

    assert "table:new_provider_rows" in _declared_objects([source]) - _catalogued_objects(catalogue)
    assert "table:new_provider_dynamic_rows" in (
        _declared_objects([source]) - _catalogued_objects(catalogue)
    )
    assert "store/pit/new-provider/raw" in {
        reference
        for reference in _path_references([source])
        if not _covered_path(reference, _location_patterns(catalogue))
    }


def test_account_source_databases_and_tables_are_catalogued():
    catalogue = _load_catalogue()
    datasets = catalogue["datasets"]

    for source, (_environment_name, filename) in SOURCE_PATHS.items():
        database = f"store/pit/{filename}"
        assert any(
            dataset["kind"] == "file_set" and dataset["location"] == database
            for dataset in datasets
        ), f"account source database is uncatalogued: {database}"
        catalogued = {
            dataset["location"].rsplit(".", 1)[1]
            for dataset in datasets
            if dataset["kind"] in {"duckdb_table", "duckdb_view"}
            and dataset["location"].startswith(database + "#main.")
        }
        assert set(SOURCE_TABLES[source]) <= catalogued, {
            "database": database,
            "missing": sorted(set(SOURCE_TABLES[source]) - catalogued),
        }
