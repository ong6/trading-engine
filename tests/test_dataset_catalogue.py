import ast
import copy
import fnmatch
import json
import re
from pathlib import Path

import duckdb
import pytest
import yaml

from engine.accounts.sources import SOURCE_PATHS, SOURCE_TABLES
from tools import backup_database, release_manifest


ROOT = Path(__file__).resolve().parents[1]
CATALOGUE_PATH = ROOT / "schemas" / "datasets.yaml"
REHEARSAL_PATH = ROOT / "tests" / "fixtures" / "revision15-rehearsal-catalog.json"
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
PLACEHOLDER_TERMS = {
    "named operational producer",
    "inactive plan-owned producer",
    "owning operational service",
    "owning engine component",
    "owning evidence producer",
    "owning operational writer",
    "named evidence producer",
}
DDL_RE = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?"
    r"(?!(?:TEMP|TEMPORARY)\s)(TABLE|VIEW)\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
DYNAMIC_DDL_RE = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?"
    r"(?!(?:TEMP|TEMPORARY)\s)(TABLE|VIEW)\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?\{([A-Za-z_][A-Za-z0-9_]*)\}",
    re.IGNORECASE,
)
MANAGED_PATH_RE = re.compile(
    r"(?:^|[\s`(])(?:trading-engine/)?"
    r"((?:store|data|logs|scratch)/[A-Za-z0-9_.*{}<>/-]+"
    r"(?:\.[A-Za-z0-9_*{}<>-]+)?)"
)
FALSE_DDL_NAMES = {"if", "so"}
EXTERNAL_DYNAMIC_CONSTANTS = {
    "RETENTION_TABLE": "broker_paper_authority_retained_events",
    "RISK_EVIDENCE_TABLE": "broker_paper_authority_risk_evaluations",
}
IGNORED_MANAGED_PATHS = {
    "store/yahoo",  # Historical prose describes a store/Yahoo value ratio.
    "store/.agent-fault-drill.lock",
    "store/agent-shadow-control.json.lock",
    "data/_meta.json.lock",
}
PATH_BASES = {
    "REPO_ROOT": "",
    "DATA_DIR": "data",
    "DEFAULT_DATA_DIR": "data",
    "LOGS_DIR": "logs",
    "STORE_DIR": "store",
    "SCRATCH_DIR": "scratch",
    "SCRATCH_ROOT": "scratch",
    "WF_SCRATCH_ROOT": "scratch",
}
SOURCE_DATABASES = {
    Path("engine/daily_opportunities.py"): "memory://engine.daily_opportunities",
    Path("engine/free_sources.py"): "store/pit/free-sources.duckdb",
    Path("engine/free_sec.py"): "store/pit/free-sources.duckdb",
    Path("engine/free_sec_bulk.py"): "store/pit/sec-bulk.duckdb",
    Path("engine/free_massive_minute.py"): "store/pit/massive-minute.duckdb",
    Path("engine/free_massive_options.py"): "store/pit/options.duckdb",
    Path("farm/backtest/proofs.py"): "scratch/proofs/equiv.duckdb",
    Path("farm/credit_confirmed_experiment.py"): "scratch/credit-confirmed-spy-v1/**.duckdb",
}
NON_DUCKDB_DDL_SOURCES = {Path("tools/ops_digest.py")}

Relation = tuple[str, str, str, str]


def _load_catalogue() -> dict:
    return yaml.safe_load(CATALOGUE_PATH.read_text())


def _python_sources() -> list[Path]:
    return sorted(path for root in CODE_ROOTS for path in root.rglob("*.py"))


def _non_python_sources() -> list[Path]:
    suffixes = {".sh", ".service", ".timer", ".toml"}
    return sorted(
        path for root in CODE_ROOTS for path in root.rglob("*")
        if path.is_file() and path.suffix in suffixes
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
    assert all(
        not PLACEHOLDER_TERMS.intersection(
            str(value).lower()
            for field in REQUIRED_FIELDS
            for value in (
                dataset[field] if isinstance(dataset[field], list) else [dataset[field]]
            )
        )
        for dataset in datasets
    )


def _catalogue_relations(catalogue: dict) -> set[Relation]:
    relations = set()
    for dataset in catalogue["datasets"]:
        if dataset["kind"] not in {"duckdb_table", "duckdb_view"}:
            continue
        database, qualified = dataset["location"].split("#", 1)
        schema, name = qualified.split(".", 1)
        relations.add((database, schema, dataset["kind"].removeprefix("duckdb_"), name))
    return relations


def _catalogue_file_patterns(catalogue: dict) -> list[str]:
    return [
        dataset["location"]
        for dataset in catalogue["datasets"]
        if dataset["kind"] in {"file_set", "generation"}
    ]


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


def _dynamic_objects(tree: ast.AST, path: Path) -> set[tuple[str, str]]:
    constants = _literal_constants(tree)
    objects = set()
    unresolved = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        for kind, variable in DYNAMIC_DDL_RE.findall(_joined_template(node)):
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
            objects.update((kind.lower(), name) for name in names)
    assert unresolved == [], {"source": str(path.relative_to(ROOT)), "unresolved": unresolved}
    return objects


def _database_for_source(relative: Path) -> str | None:
    if relative in NON_DUCKDB_DDL_SOURCES:
        return None
    if relative.parts[:2] == ("farm", "replay"):
        return "scratch/replay/**/replay.duckdb"
    return SOURCE_DATABASES.get(relative, "store/market.duckdb")


def _source_relations(sources: list[Path]) -> set[Relation]:
    relations = set()
    for path in sources:
        relative = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        database = _database_for_source(relative)
        if database is None:
            continue
        text = path.read_text()
        tree = ast.parse(text, filename=str(path))
        objects = {
            (kind.lower(), name)
            for kind, name in DDL_RE.findall(text)
            if name.lower() not in FALSE_DDL_NAMES
        }
        objects.update(_dynamic_objects(tree, path))
        relations.update((database, "main", kind, name) for kind, name in objects)

    source_databases = {
        "account_daily": "store/pit/free-sources.duckdb",
        "account_minute": "store/pit/massive-minute.duckdb",
        "account_short": "store/pit/short-data.duckdb",
    }
    for source, names in SOURCE_TABLES.items():
        for name in names:
            kind = "view" if name == "free_daily_bars_adjusted" else "table"
            relations.add((source_databases[source], "main", kind, name))
    return relations


def _path_string(node: ast.AST, constants: dict[str, object]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return _joined_template(node).replace("{expression}", "*")
    if isinstance(node, ast.Name):
        if node.id in PATH_BASES:
            return PATH_BASES[node.id]
        value = constants.get(node.id)
        return value if isinstance(value, str) else None
    if isinstance(node, ast.Call) and len(node.args) == 1:
        return _path_string(node.args[0], constants)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _path_string(node.left, constants)
        right = _path_string(node.right, constants)
        if left is not None and right is not None:
            return "/".join(part.strip("/") for part in (left, right) if part)
    return None


def _path_references(python_sources: list[Path], other_sources: list[Path]) -> set[str]:
    references = set()
    for path in python_sources:
        text = path.read_text()
        tree = ast.parse(text, filename=str(path))
        constants = _literal_constants(tree)
        strings = (
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
        for value in strings:
            references.update(MANAGED_PATH_RE.findall(value))
        for node in ast.walk(tree):
            value = _path_string(node, constants)
            if value is not None and value.split("/", 1)[0] in {"store", "data", "logs", "scratch"}:
                references.add(value)
    for path in other_sources:
        references.update(MANAGED_PATH_RE.findall(path.read_text()))
    cleaned = {value.strip().rstrip("`'\".,:;)") for value in references}
    return {
        value for value in cleaned
        if value not in IGNORED_MANAGED_PATHS
        and value.split("/", 1)[-1]
        and not any(character.isspace() for character in value)
        and "{" not in value
    }


def _covered_path(reference: str, patterns: list[str]) -> bool:
    if reference in {
        "store", "store/", "store/pit", "data", "data/", "logs", "logs/",
        "scratch", "scratch/",
    }:
        return True
    return any(
        fnmatch.fnmatchcase(reference, pattern)
        or (pattern.endswith("/**") and reference == pattern[:-3])
        for pattern in patterns
    )


def _connection_relations(con, database: str) -> set[Relation]:
    return {
        (database, row[0], "view" if row[2] == "VIEW" else "table", row[1])
        for row in con.execute(
            "SELECT table_schema,table_name,table_type FROM information_schema.tables "
            "WHERE table_schema='main'"
        ).fetchall()
    }


def _fresh_market_relations() -> set[Relation]:
    from engine import account_watch, bitemporal_facts, p15_evaluation, p15_event_sources
    from engine import paper_accounts, pit_import, tradingview_history_archive
    from engine.lib import db
    from farm import experiment
    from server import agent_corporate_action_observations, agent_evaluation
    from server import agent_fault_drills, agent_independent_price_evidence
    from server import agent_price_observations, agent_provider_responses
    from server import agent_shadow_store, agent_store, daily_opportunity_store
    from server import p15_preopen, p15_price_fetch_attempts, p15_scoring_store
    from sim import p15_books, settle
    from sim.schema import init_sim_schema

    con = duckdb.connect()
    try:
        for initializer in (
            db.init_schema,
            db.init_queue_schema,
            db.init_mining_schema,
            db.init_signals_schema,
            db.init_actions_schema,
            db.init_price_rejects_schema,
            init_sim_schema,
            settle.ensure_table,
            paper_accounts.init_schema,
            account_watch.init_schema,
            pit_import.init_schema,
            bitemporal_facts.init_schema,
            tradingview_history_archive.init_schema,
            experiment.ensure_results_table,
            agent_corporate_action_observations.init_schema,
            agent_price_observations.init_schema,
            agent_evaluation.init_schema,
            agent_fault_drills.init_schema,
            agent_independent_price_evidence.init_schema,
            agent_provider_responses.init_schema,
            agent_shadow_store.init_schema,
            agent_store.init_schema,
            daily_opportunity_store.init_schema,
            p15_books.init_schema,
            p15_evaluation.init_look_schema,
            p15_event_sources.init_schema,
            p15_preopen.init_schema,
            p15_price_fetch_attempts.init_schema,
            p15_scoring_store.init_schema,
        ):
            initializer(con)
        return _connection_relations(con, "store/market.duckdb")
    finally:
        con.close()


def _fresh_pit_relations() -> set[Relation]:
    from engine import free_massive_minute, free_massive_options, free_sec, free_sec_bulk
    from engine import free_sources

    relations = set()
    initializers = {
        "store/pit/free-sources.duckdb": (free_sources.init_schema, free_sec.init_schema),
        "store/pit/sec-bulk.duckdb": (free_sec_bulk.init_schema,),
        "store/pit/massive-minute.duckdb": (free_massive_minute.init_schema,),
        "store/pit/options.duckdb": (free_massive_options.init_schema,),
    }
    for database, functions in initializers.items():
        con = duckdb.connect()
        try:
            for initializer in functions:
                initializer(con)
            relations.update(_connection_relations(con, database))
        finally:
            con.close()
    return relations


def _rehearsal_relations() -> set[Relation]:
    fixture = json.loads(REHEARSAL_PATH.read_text())
    assert fixture["table_count"] == len(fixture["tables"]) == 107
    assert fixture["tables"] == sorted(set(fixture["tables"]))
    return {
        (fixture["database"], fixture["schema"], "table", name)
        for name in fixture["tables"]
    }


def _coverage_difference(catalogued: set[Relation], inventories: set[Relation]):
    return inventories - catalogued, catalogued - inventories


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


def test_source_declared_relations_match_catalogue_bidirectionally():
    catalogue = _catalogue_relations(_load_catalogue())
    source = _source_relations(_python_sources())
    missing, gone = _coverage_difference(catalogue, source)
    assert missing == set(), {"missing_from_catalogue": sorted(missing)}
    assert gone == set(), {"listed_but_gone": sorted(gone)}


def test_fresh_market_and_pit_schemas_are_catalogued():
    catalogued = _catalogue_relations(_load_catalogue())
    fresh = _fresh_market_relations() | _fresh_pit_relations()
    assert fresh <= catalogued, {"missing_from_catalogue": sorted(fresh - catalogued)}


def test_pinned_revision15_rehearsal_catalogue_is_covered():
    catalogued = _catalogue_relations(_load_catalogue())
    rehearsal = _rehearsal_relations()
    assert rehearsal <= catalogued, {"missing_from_catalogue": sorted(rehearsal - catalogued)}


def test_account_source_and_backup_inventories_are_covered():
    catalogue = _load_catalogue()
    relations = _catalogue_relations(catalogue)
    patterns = _catalogue_file_patterns(catalogue)
    source_databases = {
        "account_daily": "store/pit/free-sources.duckdb",
        "account_minute": "store/pit/massive-minute.duckdb",
        "account_short": "store/pit/short-data.duckdb",
    }
    for source, (_environment_name, filename) in SOURCE_PATHS.items():
        database = source_databases[source]
        assert filename == Path(database).name
        assert _covered_path(database, patterns)
        for name in SOURCE_TABLES[source]:
            kind = "view" if name == "free_daily_bars_adjusted" else "table"
            assert (database, "main", kind, name) in relations

    for table in backup_database.REQUIRED_TABLES:
        assert ("store/market.duckdb", "main", "table", table) in relations
    backup_files = (
        *backup_database.OPERATIONAL_STATIC_FILES,
        *backup_database.OPTIONAL_OPERATIONAL_CONTROL_FILES,
        *release_manifest.PROSPECTIVE_EVIDENCE_FILES,
    )
    assert all(_covered_path(path, patterns) for path in backup_files)


def test_retired_short_source_has_portable_exact_recovery_identity():
    datasets = {dataset["id"]: dataset for dataset in _load_catalogue()["datasets"]}
    short = datasets["files.short_data_database"]

    assert "research-evidence-20261005-f7d4f695396c-52da75c8" in short["backup"]
    assert "f7d4f695396c6eb013a1238d612920748ba2d153c6cbf071da577f90ec755e06" in short["backup"]
    assert "59406972cdcd82f316a0034e699113be682768328fb8aeb4aadb54829f99fa66" in short["rebuild"]
    assert (ROOT / "docs/history/retired-pit-restore-2026-10-18.md").is_file()


def test_safety_critical_policy_facts_are_not_inherited_from_unrelated_families():
    datasets = {dataset["id"]: dataset for dataset in _load_catalogue()["datasets"]}

    operational = datasets["external.private_operational_backup"]
    assert operational["schema_owner"] == ["private trading-data backup repository"]
    assert operational["producer"] == ["daily backup exporter"]
    assert operational["readers"] == ["disaster restore"]
    assert operational["semantics"] == "append_only_evidence"
    assert "immutable Parquet delta generations" in operational["retention"]
    assert operational["backup"] == "This dataset is the current off-host operational backup target."
    assert operational["registration"] == ["operational recovery boundary"]
    assert "research-evidence-20261005" not in str(operational)

    primary = datasets["files.primary_database"]
    assert primary["semantics"] == "authoritative"
    assert primary["producer"] == ["operational engine writers through engine.lib.db.connect"]
    assert "sole mutable operational database" in primary["retention"]

    verifier = datasets["files.price_verifier_receipts"]
    assert verifier["semantics"] == "append_only_evidence"
    assert verifier["producer"] == ["independent price verifier"]
    assert verifier["registration"] == ["price-verification evidence"]

    short = datasets["files.short_data_database"]
    assert short["producer"] == ["retired Reg SHO and FINRA short-interest collectors"]
    assert short["readers"] == ["engine.accounts.sources", "sim.shorts", "account settlement"]


def test_every_rebuild_policy_is_an_explicit_action_or_refusal():
    admitted = (
        "not_rebuildable", "recompute", "fold", "restore", "rebuild", "render",
        "re-run", "empty schema",
    )
    ambiguous = [
        dataset["id"] for dataset in _load_catalogue()["datasets"]
        if not dataset["rebuild"].lower().startswith(admitted)
    ]
    assert ambiguous == []


def test_python_shell_and_service_managed_paths_are_catalogued():
    patterns = _catalogue_file_patterns(_load_catalogue())
    references = _path_references(_python_sources(), _non_python_sources())
    uncovered = sorted(path for path in references if not _covered_path(path, patterns))
    assert uncovered == []


def test_unknown_table_view_file_and_orphaned_deployed_table_are_detected(tmp_path):
    source = tmp_path / "producer.py"
    source.write_text(
        'from pathlib import Path\n'
        'from engine.lib.settings import REPO_ROOT\n'
        'RAW = REPO_ROOT / "store" / "pit" / "new-provider" / "raw"\n'
        'TABLE_DDL = "CREATE TABLE new_provider_rows (id BIGINT)"\n'
        'VIEW_DDL = "CREATE VIEW new_provider_latest AS SELECT 1"\n'
    )
    catalogued = _catalogue_relations(_load_catalogue())
    injected = _source_relations([source])
    missing, _gone = _coverage_difference(catalogued, injected)
    assert missing == {
        ("store/market.duckdb", "main", "table", "new_provider_rows"),
        ("store/market.duckdb", "main", "view", "new_provider_latest"),
    }
    orphan = {("store/market.duckdb", "main", "table", "deployed_orphan")}
    assert _coverage_difference(catalogued, orphan)[0] == orphan

    references = _path_references([source], [])
    assert "store/pit/new-provider/raw" in {
        path for path in references
        if not _covered_path(path, _catalogue_file_patterns(_load_catalogue()))
    }


def test_listed_but_gone_relation_is_detected():
    invented = {("store/market.duckdb", "main", "table", "listed_but_gone")}
    source = _source_relations(_python_sources())
    _missing, gone = _coverage_difference(source | invented, source)
    assert gone == invented
