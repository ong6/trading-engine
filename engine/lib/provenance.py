"""Deterministic provenance for generated research artifacts."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from engine.lib.settings import REPO_ROOT

SOURCE_ROOTS = ("engine", "farm", "sim")
SOURCE_SUFFIXES = frozenset({".py", ".sh"})
SOURCE_FILES = ("pyproject.toml",)


def canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _git(*args: str, repo_root: Path = REPO_ROOT) -> str | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=repo_root, check=True, capture_output=True,
            text=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def runtime_source_hash(repo_root: Path = REPO_ROOT) -> tuple[str, int]:
    """Hash path names and bytes for the executable research/runtime source."""
    paths: list[Path] = []
    for root_name in SOURCE_ROOTS:
        root = repo_root / root_name
        if root.exists():
            paths.extend(
                p for p in root.rglob("*")
                if p.is_file() and p.suffix in SOURCE_SUFFIXES
            )
    paths.extend(p for name in SOURCE_FILES if (p := repo_root / name).is_file())
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.relative_to(repo_root).as_posix()):
        relative = path.relative_to(repo_root).as_posix().encode()
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest(), len(paths)


def research_provenance(config: dict, repo_root: Path = REPO_ROOT) -> dict:
    # Detach the recorded config from the caller. Strategy/replay code receives
    # mutable dictionaries, so retaining the same object could let a long run
    # change the config after its hash was computed.
    config_snapshot = json.loads(json.dumps(config, sort_keys=True))
    source_sha256, source_file_count = runtime_source_hash(repo_root)
    status = _git("status", "--porcelain", "--untracked-files=all", repo_root=repo_root)
    return {
        "config": config_snapshot,
        "config_sha256": canonical_sha256(config_snapshot),
        "git_sha": _git("rev-parse", "HEAD", repo_root=repo_root),
        "git_dirty": None if status is None else bool(status),
        "source_sha256": source_sha256,
        "source_file_count": source_file_count,
    }
