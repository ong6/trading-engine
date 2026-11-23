#!/usr/bin/env python3
"""Write the next P15 registration revision for pinned-file changes that alter no registered value.

``python -m tools.repin [--root DIR] [--deployed REF] [--reason-file FILE] [--check]
[--rehearse]`` compares the checkout with the deployed revision ``REF`` (default: the SHA the
deployer recorded in its state file, else ``origin/main``) and writes at most two commits:

(b) only when a forward-record closure digest changed (E1, sector or XS): the new
    ``EXPECTED_RUNTIME_CONTRACT_SHA256``; ``AMENDED_RUNTIME_CONTRACT_SHA256``, the AMENDED file
    list and the "revision N, installed DATE" comment taken from the deployed predecessor's
    published report at ``REF``; the deployed-runtime test fixtures and the XS literal test.
(c) the registration: pinned file hashes, ``source_commit`` (the last commit touching a pinned
    file, after (b)), revision ``REF``'s plus one, ``revision_reason`` (boilerplate around the
    one sentence in ``--reason-file``) and ``registration_sha256``; plus the two literals in
    ``tests/test_p15_registration.py``.

It refuses (exit 2, nothing written) when the tree is dirty; when a registration key other
than the code identity, revision, reason and self-hash differs from ``REF``; when any
module-level constant of the three forward-record modules other than the expected and amended
digests changed (contract versions, migration text, superseded digests, file lists, config and
profile hashes, baselines, kill criteria); when a published report at ``REF`` is INVALID; or
when ``test_p15_registered_derived_identities_match_code`` fails. ``--check`` writes nothing and
exits 2 when a re-pin is needed, 0 when the checkout is already pinned.

``--rehearse`` runs the digest-only rehearsal: the changed families' ``--migrate-runtime-contract``
commands against the newest published snapshot (read-only) and a temporary copy of the live
``data/``, asserting that only runtime identity fields change in the reports.
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from engine.lib.provenance import canonical_sha256

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRATION = "server/p15-registration.json"
REGISTRATION_TEST = "tests/test_p15_registration.py"
XS_TEST = "tests/test_xs_forward_review.py"
DERIVED_TEST = f"{REGISTRATION_TEST}::test_p15_registered_derived_identities_match_code"
DEPLOYER_STATE = Path.home() / ".local/state/trading-engine/auto-deploy/state.json"
DEFAULT_ENGINE_ROOT = Path.home() / "trading-engine"
REVISION_KEYS = {"code_identity", "registration_revision", "registration_sha256",
                 "revision_reason"}
MUTABLE_CONSTANTS = {"EXPECTED_RUNTIME_CONTRACT_SHA256", "AMENDED_RUNTIME_CONTRACT_SHA256",
                     "AMENDED_RUNTIME_CONTRACT_FILES"}
BOILERPLATE = ("No admission gate, label rule, fetch limit, frozen statistic, strategy, model, "
               "schedule or retained outcome is tuned. The deployed revision-20 model amendment "
               "and revision-21 to revision-{deployed} collection, storage and recovery behavior "
               "remain in force.")


@dataclass(frozen=True)
class Family:
    key: str
    label: str
    module: str
    path: str
    report: str
    fixture: str
    frozen_key: str | None  # where the report keeps its runtime identity


FAMILIES = (
    Family("e1", "E1", "farm.experiment_runner", "farm/experiment_runner.py",
           "data/reports/experiments/e1-spy-monday-forward.json",
           "tests/fixtures/e1_deployed_runtime.json", None),
    Family("sector", "sector", "engine.forward_review", "engine/forward_review.py",
           "data/reports/forward/sector_momentum.json",
           "tests/fixtures/sector_momentum_deployed_frozen_runtime.json", "frozen_runtime"),
    Family("xs", "XS", "engine.xs_forward_review", "engine/xs_forward_review.py",
           "data/reports/forward/xs_momentum_12_1.json",
           "tests/fixtures/xs_momentum_12_1_deployed_frozen_runtime.json", "frozen_runtime"),
)
# Report fields a digest-only migration may change (dotted paths below the runtime identity).
IDENTITY_FIELDS = ("runtime_contract_sha256", "runtime_contract_files",
                   "signal_boundary.protocol_contract.runtime_contract_sha256")


class Refused(RuntimeError):
    """The checkout cannot be re-pinned mechanically."""


@dataclass
class Plan:
    deployed_ref: str
    deployed_revision: int
    revision: int
    changed_families: list[str] = field(default_factory=list)
    contract_edits: dict[str, str] = field(default_factory=dict)  # path -> new text
    registration_text: str | None = None
    reason: str | None = None

    @property
    def needed(self) -> bool:
        return bool(self.contract_edits or self.registration_text)


def git(root: Path, *args: str, check: bool = True) -> str:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=False)
    if check and done.returncode:
        raise Refused(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout.strip() if done.returncode == 0 else ""


def _python(root: Path) -> str:
    venv = root / ".venv/bin/python"
    return str(venv) if venv.exists() else sys.executable


def _env(root: Path, **extra: str) -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1", **extra}


def default_deployed(root: Path, state_file: Path = DEPLOYER_STATE) -> str:
    """The deployer's recorded SHA when it is known here, else ``origin/main``."""
    try:
        sha = json.loads(state_file.read_text()).get("deployed_sha")
    except (OSError, ValueError, AttributeError):
        sha = None
    known = isinstance(sha, str) and subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=root, capture_output=True,
    ).returncode == 0
    return sha if known else "origin/main"


def _constants(text: str) -> dict[str, str]:
    """Module-level UPPER_CASE assignments, by name, as a structural dump of the value."""
    found = {}
    for node in ast.parse(text).body:
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, ast.AnnAssign) and node.value else [])
        for target in targets:
            if isinstance(target, ast.Name) and target.id.isupper():
                found[target.id] = ast.dump(node.value)
    return found


def _literal(text: str, name: str):
    for node in ast.parse(text).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name):
            return ast.literal_eval(node.value)
    raise Refused(f"{name} is not a literal assignment")


def closure_digest(root: Path, family: Family) -> str:
    """The family's runtime-contract digest of the checkout's bytes, by its own code."""
    attribute = "_runtime_contract_sha256"
    done = subprocess.run(
        [_python(root), "-c", f"import {family.module} as m; print(m.{attribute}())"],
        cwd=root, env=_env(root), capture_output=True, text=True, check=False)
    if done.returncode or not re.fullmatch(r"[0-9a-f]{64}", done.stdout.strip()):
        raise Refused(f"{family.key} closure digest failed: {done.stderr.strip()[-400:]}")
    return done.stdout.strip()


def _report_identity(report: dict, family: Family) -> dict:
    return report[family.frozen_key] if family.frozen_key else report


def _install_date(root: Path, ref: str, family: Family, digest: str) -> str:
    """The UTC date the deployed digest first appeared in the published report at ``ref``."""
    done = subprocess.run(
        ["git", "log", "--reverse", "--date=format-local:%Y-%m-%d", "--format=%cd",
         f"-S{digest}", ref, "--", family.report],
        cwd=root, env={**os.environ, "TZ": "UTC"}, capture_output=True, text=True, check=False)
    dates = done.stdout.split()
    if done.returncode or not dates:
        raise Refused(f"no install date for the deployed {family.key} digest at {ref}")
    return dates[0]


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def reason_text(revision: int, deployed: int, sentence: str, versions: dict[str, int],
                changed: list[str]) -> str:
    named = {family.key: f"{family.label} v{versions[family.key]}" for family in FAMILIES}
    moved = [named[f.key] for f in FAMILIES if f.key in changed]
    still = [named[f.key] for f in FAMILIES if f.key not in changed]
    parts = []
    if moved:
        verb = (f"keep their contract versions and migrate only the literal deployed "
                f"revision-{deployed} digests" if len(moved) > 1 else
                f"keeps its contract version and migrates only the literal deployed "
                f"revision-{deployed} digest")
        parts.append(f"{_join(moved)} {verb}")
    if still:
        parts.append(f"{_join(still)} {'are' if len(still) > 1 else 'is'} unchanged")
    clause = "; ".join(parts) + "."
    clause = clause[0].upper() + clause[1:]
    return (f"Revision {revision} after deployed revision {deployed}: {sentence} {clause} "
            + BOILERPLATE.format(deployed=deployed))


def read_sentence(path: Path) -> str:
    sentence = " ".join(path.read_text().split())
    if not sentence or not sentence.endswith(".") or '"' in sentence:
        raise Refused("the reason file must hold one sentence ending in a full stop, no quotes")
    return sentence


def _dump(payload: dict) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _replace_once(text: str, pattern: str, replacement, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise Refused(f"cannot find {label}")
    return updated


def _module_edit(text: str, family: Family, computed: str, deployed: dict | None,
                 deployed_revision: int, revision: int, installed: str | None) -> str:
    text = _replace_once(
        text, r'^(EXPECTED_RUNTIME_CONTRACT_SHA256 = \(\n    ")[0-9a-f]{64}("\n\))',
        lambda m: m.group(1) + computed + m.group(2), f"{family.key} expected digest")
    if deployed is None:
        return text
    text = _replace_once(
        text, r"^(AMENDED_RUNTIME_CONTRACT_SHA256 = ')[0-9a-f]{64}(')",
        lambda m: m.group(1) + deployed["runtime_contract_sha256"] + m.group(2),
        f"{family.key} amended digest")
    if "AMENDED_RUNTIME_CONTRACT_FILES" in _constants(text):
        rendered = "".join(f"    '{name}',\n" for name in deployed["runtime_contract_files"])
        text = _replace_once(
            text, r"^AMENDED_RUNTIME_CONTRACT_FILES = \(\n(?:    '[^'\n]*',\n)*\)",
            lambda _m: f"AMENDED_RUNTIME_CONTRACT_FILES = (\n{rendered})",
            f"{family.key} amended file list")
    return _replace_once(
        text,
        r"^(# The deployed code identity of this same contract version \(revision )\d+"
        r"(, installed\n# )\d{4}-\d{2}-\d{2}(\)\. Revision )\d+ [^\n]*;$",
        lambda m: (f"{m.group(1)}{deployed_revision}{m.group(2)}{installed}{m.group(3)}"
                   f"{revision} changes code inside this closure;"),
        f"{family.key} deployed-identity comment")


def _replace_strings(value, old: str, new: str):
    if isinstance(value, dict):
        return {key: _replace_strings(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_strings(item, old, new) for item in value]
    return new if value == old else value


def _fixture_edit(text: str, deployed: dict) -> str:
    fixture = json.loads(text)
    fixture = _replace_strings(fixture, fixture["runtime_contract_sha256"],
                               deployed["runtime_contract_sha256"])
    fixture["runtime_contract_files"] = list(deployed["runtime_contract_files"])
    return json.dumps(fixture, indent=2) + "\n"


def _xs_test_edit(text: str, old: str, new: str, deployed_revision: int, revision: int) -> str:
    text = _replace_once(
        text, r"^def test_revision\d+_migration_requires_literal_revision\d+_predecessor\(",
        f"def test_revision{revision}_migration_requires_literal_revision"
        f"{deployed_revision}_predecessor(", "the XS literal-predecessor test")
    if old not in text:
        raise Refused("the XS literal-predecessor test does not cite the amended digest")
    return text.replace(old, new)


def _check_clean(root: Path, ignore: set[str]) -> None:
    dirty = [line[3:] for line in git(root, "status", "--porcelain",
                                      "--untracked-files=normal").splitlines()
             if line[3:] not in ignore]
    if dirty:
        raise Refused(f"uncommitted or untracked changes: {', '.join(dirty[:5])}")


def _derived_identities(root: Path) -> None:
    done = subprocess.run(
        [_python(root), "-m", "pytest", "-q", "-p", "no:cacheprovider", "-n", "0", DERIVED_TEST],
        cwd=root, env=_env(root), capture_output=True, text=True, check=False)
    if done.returncode:
        tail = "\n".join((done.stdout + done.stderr).splitlines()[-8:])
        raise Refused(f"derived identities do not match the code:\n{tail}")


def plan(root: Path, ref: str, sentence: str | None, *, check: bool = False,
         derived_check=None) -> Plan:
    """Validate the checkout against ``ref`` and compute every edit; writes nothing.

    ``check`` plans without a reason sentence (a placeholder stands in; nothing is written).
    """
    ref_sha = git(root, "rev-parse", "--verify", f"{ref}^{{commit}}")
    before = json.loads(git(root, "show", f"{ref_sha}:{REGISTRATION}"))
    current = json.loads((root / REGISTRATION).read_text())
    moved = sorted(key for key in set(before) | set(current)
                   if key not in REVISION_KEYS and before.get(key) != current.get(key))
    if moved:
        raise Refused(f"registered values changed since {ref}: {', '.join(moved)}")
    deployed_revision = before["registration_revision"]
    revision = deployed_revision + 1
    if current["registration_revision"] > revision:
        raise Refused(f"revision {current['registration_revision']} is past {revision}")
    result = Plan(ref_sha, deployed_revision, revision)
    versions = {}
    for family in FAMILIES:
        text = (root / family.path).read_text()
        old = _constants(git(root, "show", f"{ref_sha}:{family.path}"))
        new = _constants(text)
        frozen = sorted(name for name in set(old) | set(new)
                        if name not in MUTABLE_CONSTANTS and old.get(name) != new.get(name))
        if frozen:
            raise Refused(f"{family.path}: frozen constants changed: {', '.join(frozen)}")
        versions[family.key] = _literal(text, "RUNTIME_CONTRACT_VERSION")
        report = json.loads(git(root, "show", f"{ref_sha}:{family.report}"))
        if report.get("status") == "INVALID":
            raise Refused(f"the published {family.key} report at {ref} is INVALID")
        published = _report_identity(report, family)
        if published.get("runtime_contract_version") != versions[family.key]:
            raise Refused(f"the published {family.key} report at {ref} is not contract "
                          f"v{versions[family.key]}")
        computed = closure_digest(root, family)
        expected = _literal(text, "EXPECTED_RUNTIME_CONTRACT_SHA256")
        amended = _literal(text, "AMENDED_RUNTIME_CONTRACT_SHA256")
        migrate = computed != published["runtime_contract_sha256"]
        if migrate:
            result.changed_families.append(family.key)
        if computed == expected and (not migrate or amended == published[
                "runtime_contract_sha256"]):
            continue
        installed = (_install_date(root, ref_sha, family, published["runtime_contract_sha256"])
                     if migrate else None)
        result.contract_edits[family.path] = _module_edit(
            text, family, computed, published if migrate else None, deployed_revision,
            revision, installed)
        if migrate:
            fixture = (root / family.fixture).read_text()
            result.contract_edits[family.fixture] = _fixture_edit(fixture, published)
            if family.key == "xs":
                result.contract_edits[XS_TEST] = _xs_test_edit(
                    (root / XS_TEST).read_text(), amended,
                    published["runtime_contract_sha256"], deployed_revision, revision)
    (derived_check or _derived_identities)(root)
    _plan_registration(root, result, current, sentence, versions, check)
    return result


def _plan_registration(root: Path, result: Plan, current: dict, sentence: str | None,
                       versions: dict[str, int], check: bool) -> None:
    files = current["code_identity"]["files"]
    contents = {path: (result.contract_edits[path].encode() if path in result.contract_edits
                       else (root / path).read_bytes()) for path in files}
    hashes = {path: hashlib.sha256(contents[path]).hexdigest() for path in files}
    pinned_edit = bool(set(result.contract_edits) & set(files))
    source = None if pinned_edit else git(root, "rev-list", "-1", "HEAD", "--", *sorted(files))
    identity_same = hashes == files and source == current["code_identity"]["source_commit"]
    already = current["registration_revision"] == result.revision
    if identity_same and (not already or sentence is None):
        return  # pinned bytes are registered; nothing to revise (or only a reason to keep)
    if sentence is None and not already and not check:
        raise Refused(f"revision {result.revision} needs --reason-file with one sentence")
    reason = (reason_text(result.revision, result.deployed_revision, sentence, versions,
                          result.changed_families) if sentence
              else current["revision_reason"] if already else "<reason pending>")
    if identity_same and reason == current["revision_reason"]:
        return
    result.reason = reason
    result.registration_text = "pending" if source is None else _render_registration(
        current, hashes, source, result.revision, reason)


def _render_registration(current: dict, hashes: dict, source: str, revision: int,
                         reason: str) -> str:
    payload = copy.deepcopy(current)
    payload["code_identity"]["files"] = {path: hashes[path] for path in current[
        "code_identity"]["files"]}
    payload["code_identity"]["source_commit"] = source
    payload["registration_revision"] = revision
    payload["revision_reason"] = reason
    payload.pop("registration_sha256")
    payload["registration_sha256"] = canonical_sha256(payload)
    ordered = {key: payload[key] for key in current}  # keep the published key order
    return _dump(ordered)


def _registration_test(text: str, revision: int, reason: str) -> str:
    text = _replace_once(text, r'^(    assert registration\["registration_revision"\] == )\d+$',
                         lambda m: f"{m.group(1)}{revision}", "the revision literal")
    return _replace_once(text, r'^(    assert registration\["revision_reason"\] == ).*$',
                         lambda m: m.group(1) + json.dumps(reason, ensure_ascii=False),
                         "the reason literal")


def _commit(root: Path, paths: list[str], message: str) -> str:
    git(root, "add", "--", *paths)
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD")


def apply(root: Path, result: Plan, message: str | None = None) -> list[str]:
    """Write and commit the planned edits: (b) contract digests, then (c) the registration."""
    commits = []
    if result.contract_edits:
        for path, text in result.contract_edits.items():
            (root / path).write_text(text)
        labels = [f.label for f in FAMILIES if f.key in result.changed_families] or ["closure"]
        commits.append(_commit(root, sorted(result.contract_edits), (
            f"Accept the published revision-{result.deployed_revision} {_join(labels)} "
            "identities for migration")))
    if result.registration_text:
        current = json.loads((root / REGISTRATION).read_text())
        files = current["code_identity"]["files"]
        hashes = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in files}
        source = git(root, "rev-list", "-1", "HEAD", "--", *sorted(files))
        (root / REGISTRATION).write_text(_render_registration(
            current, hashes, source, result.revision, result.reason))
        test = root / REGISTRATION_TEST
        test.write_text(_registration_test(test.read_text(), result.revision, result.reason))
        commits.append(_commit(root, [REGISTRATION, REGISTRATION_TEST],
                               message or f"Pin registration revision {result.revision}"))
    return commits


def migration_argv(python: str, family: Family) -> list[str]:
    """The family's explicit digest migration (its module is a string literal in FAMILIES)."""
    return [python, "-m", family.module, "--migrate-runtime-contract"]


def _differences(before, after, prefix: str = "") -> list[str]:
    if isinstance(before, dict) and isinstance(after, dict):
        found = []
        for key in sorted(set(before) | set(after)):
            found += _differences(before.get(key), after.get(key), f"{prefix}{key}.")
        return found
    return [] if before == after else [prefix.rstrip(".")]


def rehearse(root: Path, changed: list[str], engine_root: Path = DEFAULT_ENGINE_ROOT) -> dict:
    """Digest-only rehearsal of the changed families' migrations; never touches live state."""
    families = [family for family in FAMILIES if family.key in changed]
    if not families:
        return {"status": "ok", "families": [], "detail": "no closure digest changed"}
    snapshots = sorted((engine_root / "store/snapshots").glob("market-2*.duckdb"))
    if not snapshots:
        raise Refused("no published store snapshot to rehearse against")
    with tempfile.TemporaryDirectory(prefix="repin-rehearsal-") as scratch:
        data = Path(scratch) / "data"
        shutil.copytree(engine_root / "data", data, symlinks=True)
        env = _env(root, TRADING_ENGINE_DB=str(snapshots[-1]), TRADING_ENGINE_DATA_DIR=str(data))
        result = {"status": "ok", "snapshot": snapshots[-1].name, "families": []}
        for family in families:
            report = data / Path(family.report).relative_to("data")
            before = json.loads(report.read_text())
            done = subprocess.run(migration_argv(_python(root), family), cwd=root, env=env,
                                  capture_output=True, text=True, check=False, timeout=1800)
            if done.returncode:
                raise Refused(f"{family.key} rehearsal failed: "
                              f"{(done.stderr or done.stdout).strip()[-400:]}")
            after = json.loads(report.read_text())
            prefix = f"{family.frozen_key}." if family.frozen_key else ""
            allowed = {prefix + name for name in IDENTITY_FIELDS}
            unexpected = [path for path in _differences(before, after) if path not in allowed]
            if unexpected:
                raise Refused(f"{family.key} rehearsal changed {', '.join(unexpected)}")
            result["families"].append(family.key)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--deployed", help="deployed revision (default: deployer state, "
                        "else origin/main)")
    parser.add_argument("--reason-file", type=Path, help="one sentence: why this revision")
    parser.add_argument("--message", help="commit message for the registration commit")
    parser.add_argument("--check", action="store_true", help="report only; exit 2 if needed")
    parser.add_argument("--rehearse", action="store_true",
                        help="also run the digest-only migration rehearsal")
    parser.add_argument("--engine-root", type=Path, default=DEFAULT_ENGINE_ROOT)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        ref = args.deployed or default_deployed(root)
        ignore = set()
        if args.reason_file and args.reason_file.resolve().is_relative_to(root):
            ignore.add(str(args.reason_file.resolve().relative_to(root)))
        _check_clean(root, ignore)
        sentence = read_sentence(args.reason_file) if args.reason_file else None
        result = plan(root, ref, sentence, check=args.check)
        print(f"deployed {ref} ({result.deployed_ref[:12]}) is revision "
              f"{result.deployed_revision}; closures changed: "
              f"{', '.join(result.changed_families) or 'none'}")
        for path in sorted(result.contract_edits):
            print(f"  contract edit: {path}")
        if result.registration_text:
            print(f"  registration revision {result.revision}")
        if args.rehearse:
            rehearsal = rehearse(root, result.changed_families, args.engine_root.expanduser())
            print(f"rehearsal: {json.dumps(rehearsal, sort_keys=True)}")
        if args.check or not result.needed:
            print("re-pin needed" if result.needed else "registration is current")
            return 2 if result.needed else 0
        for commit in apply(root, result, args.message):
            print(f"committed {commit}")
        return 0
    except Refused as exc:
        print(f"REFUSED  {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
