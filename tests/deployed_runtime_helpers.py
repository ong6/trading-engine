"""Runtime metadata copied from the deployed public forward records."""
import json
from pathlib import Path

FIXTURES = Path(__file__).with_name("fixtures")


def deployed_runtime(family: str) -> dict:
    name = {
        "sector": "sector_momentum_deployed_frozen_runtime.json",
        "xs": "xs_momentum_12_1_deployed_frozen_runtime.json",
        "e1": "e1_deployed_runtime.json",
    }[family]
    frozen = json.loads((FIXTURES / name).read_text())
    return {key: frozen[key] for key in (
        "runtime_contract_version", "runtime_contract_sha256",
        "superseded_runtime_contract_sha256", "runtime_contract_migration",
        "runtime_contract_files",
    )}
