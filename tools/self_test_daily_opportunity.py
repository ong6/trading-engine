#!/usr/bin/env python3
"""Run the non-mutating P8/P9 contract checks and an isolated end-to-end simulation."""
from __future__ import annotations

import json
import subprocess

from engine.lib.settings import REPO_ROOT
from server import daily_opportunity_self_test

TESTS = (
    "tests/test_daily_opportunities.py",
    "tests/test_agent_model_client.py",
    "tests/test_service_units.py",
    "tests/test_install_automation.py",
)


def main() -> int:
    structural = daily_opportunity_self_test.run()
    command = [str(REPO_ROOT / ".venv/bin/python"), "-m", "pytest", "-q", "-W", "error", *TESTS]
    completed = subprocess.run(command, cwd=REPO_ROOT, check=False, text=True, capture_output=True)
    result = {
        "status": "pass" if structural["status"] == "pass" and completed.returncode == 0 else "failed",
        "structural": structural,
        "test_files": list(TESTS),
        "pytest_exit_code": completed.returncode,
        "pytest_summary": completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else None,
        "execution_scope": "temporary_databases_only",
        "live_database_mutated": False,
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
