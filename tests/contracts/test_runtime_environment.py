"""Every executable the units, drivers and runbooks call resolves on the recorded host PATHs."""
from __future__ import annotations

import pytest

from tools import provider_contracts as contracts

RECORD = contracts.load_record()


def _commands(text):
    return [words[0] for _line, words in contracts.shell_commands(text)[0]]


def test_record_is_the_systemd_and_clean_shell_path_without_home_paths():
    assert RECORD["schema_version"] == 1
    assert set(RECORD["paths"]) == {"systemd_user", "env_i"}
    for path in RECORD["paths"].values():
        assert all(entry.startswith(("/usr", "/bin", "/sbin")) or entry == "."
                   for entry in path.split(":"))
    assert all(set(resolved) == {"systemd_user", "env_i"} for resolved in RECORD["commands"].values())


def test_this_checkout_resolves_every_executable():
    assert contracts.environment_problems(contracts.REPO_ROOT, RECORD) == []


def test_every_unit_driver_and_runbook_is_covered():
    files = {source["file"] for source in contracts.contract_sources(contracts.REPO_ROOT)}

    assert "docs/settlement-runbook.md" in files
    assert "engine/lib/driver.sh" in files and "server/run_p15_scoring.sh" in files
    assert {f"server/{p.name}" for p in (contracts.REPO_ROOT / "server").glob("*.service")} <= files


def _checkout(tmp_path, runbook="", unit="", script=""):
    root = tmp_path / "checkout"
    for folder in ("docs", "server", "engine/lib"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "docs/deploy-runbook.md").write_text(f"```bash\n{runbook}```\n")
    (root / "server/x.service").write_text(f"[Service]\n{unit}\n")
    (root / "server/run_x.sh").write_text(script)
    (root / "server/run_x.sh").chmod(0o755)
    return root


def test_bare_node_in_a_runbook_is_refused_and_the_documented_variable_passes(tmp_path):
    bare = contracts.environment_problems(_checkout(tmp_path, "node --version\n"), RECORD)
    fixed = contracts.environment_problems(_checkout(
        tmp_path, '"${NODE_BIN:-$HOME/tools/node/bin}/node" --version\n'), RECORD)

    assert bare == ["docs/deploy-runbook.md:2: bare `node` is not on the env_i or systemd_user PATH"]
    assert fixed == []


def test_unknown_name_and_missing_unit_script_are_refused(tmp_path):
    root = _checkout(tmp_path, "frobnicate --now\n",
                     "ExecStart=%h/trading-engine/server/run_missing.sh\n"
                     "ExecStartPre=-%h/trading-engine/server/run_x.sh")

    problems = contracts.environment_problems(root, RECORD)

    assert problems == [
        "server/x.service:2: %h/trading-engine/server/run_missing.sh is not an executable "
        "file in the checkout",
        "docs/deploy-runbook.md:2: frobnicate is not in the environment record "
        "(re-record with env-check --record on the host)",
    ]


def test_live_check_resolves_on_the_given_path(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "tool").write_text("#!/bin/sh\n")
    (bin_dir / "tool").chmod(0o755)
    root = _checkout(tmp_path, "tool\nnode\n")
    record = {"paths": {"systemd_user": str(bin_dir), "env_i": f"{bin_dir}:."}}

    problems = contracts.environment_problems(root, record, host_home=tmp_path)

    assert problems == ["docs/deploy-runbook.md:3: bare `node` is not on the env_i or "
                        "systemd_user PATH"]


@pytest.mark.parametrize(("text", "expected"), [
    (".venv/bin/python - <<'PY'\nimport os\nos.system('rm -rf x')\nPY\ngit status\n",
     [".venv/bin/python", "git"]),
    ('cat > "$S/functions.bash" <<\'F\'\nhelper() {\n  curl -s x\n}\nF\nhelper\n',
     ["cat", "curl", "helper"]),
    ('x="$(crontab -l)"; mapfile -t L < <(find . -name y)\n', ["mapfile", "crontab", "find"]),
    ('case "$g" in\n  *[!a-z]*) echo bad; exit 1 ;;\nesac\nif [[ a =~ b|c ]]; then tr a b; fi\n',
     ["echo", "exit", "tr"]),
    ("timeout 5 bash -c 'sleep 1; awk 1 f' | xargs -r systemctl --user stop\n",
     ["timeout", "bash", "sleep", "awk", "xargs", "systemctl"]),
    ("exec 9>lock\nflock -n 9 || exit 1\nA=(1 2) B=x env -u Y date\n", ["flock", "exit", "env", "date"]),
])
def test_shell_lexer_finds_command_words(text, expected):
    assert _commands(text) == expected


def test_bash_function_definitions_are_not_executables():
    commands, functions = contracts.shell_commands("p22_lock() {\n  flock -n 3\n}\np22_lock\n")

    assert functions == {"p22_lock"}
    assert contracts.classify("p22_lock", functions) == ("function", "p22_lock")
    assert [words[0] for _line, words in commands] == ["flock", "p22_lock"]
