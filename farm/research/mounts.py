"""Narrow read-only handles exposed to research callbacks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ReadOnlyMount:
    """Expose declared artifact readers without a writable or sibling namespace."""

    def __init__(self, root: str | Path):
        self._root = Path(root).resolve()
        if not self._root.is_dir():
            raise ValueError("read-only mount root is unavailable")

    def _file(self, relative: str) -> Path:
        requested = Path(relative)
        path = (self._root / requested).resolve()
        if (requested.is_absolute() or ".." in requested.parts
                or not path.is_relative_to(self._root) or not path.is_file()
                or path.is_symlink()):
            raise ValueError(f"artifact file is unavailable: {relative}")
        return path

    def read_bytes(self, relative: str) -> bytes:
        return self._file(relative).read_bytes()

    def read_json(self, relative: str):
        return json.loads(self.read_bytes(relative))

    def load_array(self, relative: str) -> Any:
        import numpy as np

        result = np.load(self._file(relative), mmap_mode="r", allow_pickle=False)
        result.flags.writeable = False
        return result

    def read_parquet(self, pattern: str = "**/*.parquet") -> Any:
        from engine.lib import db

        if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise ValueError("Parquet pattern must remain within the mount")
        paths = tuple(sorted(path for path in self._root.glob(pattern) if path.is_file()))
        if not paths:
            raise ValueError("read-only mount has no matching Parquet files")
        connection = db.connect(":memory:", wait_s=0)
        try:
            return connection.execute(
                "SELECT * FROM read_parquet(?, hive_partitioning = true) ORDER BY ALL",
                [[str(path) for path in paths]],
            ).fetchdf()
        finally:
            connection.close()


class OutcomeAccessSentinel:
    """Test double that fails on any result-bearing namespace access."""

    def __getattribute__(self, name):
        if name in {"__class__", "__repr__"}:
            return object.__getattribute__(self, name)
        raise AssertionError("outcome namespace was accessed before predictions were sealed")
