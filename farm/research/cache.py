"""Content-addressed immutable cache for research panels, universes, and tables."""

from __future__ import annotations

import errno
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

import duckdb
import numpy as np
import pandas as pd

from farm.study.data import DataDeclaration, Dividend, PriceSource
from farm.study.panel import FIELDS, Panel, PanelBars
from farm.study.universe import ListingInterval, Universe

from .canonical import canonical_bytes, canonical_sha256, file_sha256, fsync_tree

CACHE_SCHEMA_VERSION = 1
KINDS = frozenset({"panel", "universe", "feature", "label"})
NAMESPACE_BY_KIND = {
    "panel": "inputs",
    "universe": "inputs",
    "feature": "features",
    "label": "outcomes",
}


class CacheError(RuntimeError):
    pass


class CacheCorruption(CacheError):
    pass


class CacheConflict(CacheError):
    pass


def _repo_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _safe_name(value: str) -> str:
    if not value or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in value):
        raise ValueError(f"unsafe cache partition name: {value!r}")
    return value


def _array(path: Path) -> np.ndarray:
    result = np.load(path, mmap_mode="r", allow_pickle=False)
    result.flags.writeable = False
    return result


@dataclass(frozen=True)
class CacheObject:
    kind: str
    digest: str
    path: Path
    manifest: Mapping[str, Any]
    hit: bool
    bytes_read: int

    @property
    def data_path(self) -> Path:
        return self.path / "data"

    def file(self, relative: str) -> Path:
        path = (self.data_path / relative).resolve()
        if not path.is_relative_to(self.data_path.resolve()) or not path.is_file():
            raise CacheCorruption(f"cache file is unavailable: {relative}")
        return path

    def read_json(self, relative: str) -> Any:
        return json.loads(self.file(relative).read_text(encoding="utf-8"))

    def load_array(self, relative: str) -> np.ndarray:
        return _array(self.file(relative))

    def parquet_files(self) -> tuple[Path, ...]:
        return tuple(sorted(self.data_path.rglob("*.parquet")))

    def read_table(self) -> pd.DataFrame:
        paths = self.parquet_files()
        if not paths:
            raise CacheCorruption("cache table has no Parquet parts")
        connection = duckdb.connect(":memory:")
        try:
            return connection.execute(
                "SELECT * FROM read_parquet(?, hive_partitioning = true) ORDER BY ALL",
                [[str(path) for path in paths]],
            ).fetchdf()
        finally:
            connection.close()


@dataclass(frozen=True)
class CachedPanel:
    object: CacheObject
    source: PriceSource


@dataclass(frozen=True)
class CachedUniverse:
    object: CacheObject
    universe: Universe
    coverage: np.ndarray
    exclusions: Mapping[str, tuple[str, ...]]


class ResearchCache:
    """Publish and verify immutable research objects below a private cache root."""

    def __init__(self, root: str | Path, *, repository_root: str | Path | None = None):
        self.root = Path(root).resolve()
        repository = (Path(repository_root).resolve() if repository_root is not None
                      else _repo_root(Path.cwd().resolve()))
        if repository is not None and self.root.is_relative_to(repository):
            raise ValueError("research cache root must be outside the repository")
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def digest(kind: str, identity: Mapping[str, Any]) -> str:
        if kind not in KINDS:
            raise ValueError(f"unknown cache kind: {kind}")
        return canonical_sha256({
            "cache_schema_version": CACHE_SCHEMA_VERSION,
            "identity": identity,
            "kind": kind,
        })

    def _object_path(self, kind: str, digest: str) -> Path:
        return self.root / NAMESPACE_BY_KIND[kind] / "objects" / "sha256" / digest

    def _build_path(self, kind: str, digest: str) -> Path:
        return self.root / NAMESPACE_BY_KIND[kind] / "builds" / f"{digest}.{uuid.uuid4().hex}"

    @staticmethod
    def _inventory(data_root: Path) -> list[dict[str, Any]]:
        files = []
        for path in sorted(data_root.rglob("*")):
            if path.is_symlink():
                raise CacheError("cache objects may not contain symbolic links")
            if path.is_file():
                files.append({
                    "path": path.relative_to(data_root).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": file_sha256(path),
                })
        if not files:
            raise CacheError("cache builder produced no files")
        return files

    def _load(self, kind: str, digest: str, *, hit: bool) -> CacheObject:
        target = self._object_path(kind, digest)
        manifest_path = target / "manifest.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise CacheCorruption(f"cache manifest is unavailable: {digest}")
        raw = manifest_path.read_bytes()
        try:
            manifest = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CacheCorruption(f"cache manifest is invalid: {digest}") from exc
        required = {
            "cache_schema_version", "kind", "namespace", "digest", "identity", "files",
            "content_sha256", "metadata",
        }
        if (not isinstance(manifest, dict) or set(manifest) != required
                or manifest.get("cache_schema_version") != CACHE_SCHEMA_VERSION
                or manifest.get("kind") != kind or manifest.get("namespace") != NAMESPACE_BY_KIND[kind]
                or manifest.get("digest") != digest
                or self.digest(kind, manifest.get("identity", {})) != digest):
            raise CacheCorruption(f"cache manifest differs: {digest}")
        files = manifest.get("files")
        if not isinstance(files, list) or not files:
            raise CacheCorruption(f"cache inventory is empty: {digest}")
        expected_paths, bytes_read = set(), len(raw)
        for index, row in enumerate(files):
            if not isinstance(row, dict) or set(row) != {"path", "size", "sha256"}:
                raise CacheCorruption(f"cache inventory row {index} differs: {digest}")
            relative = Path(row["path"])
            path = (target / "data" / relative).resolve()
            if (relative.is_absolute() or ".." in relative.parts
                    or not path.is_relative_to((target / "data").resolve())
                    or not path.is_file() or path.is_symlink()
                    or type(row["size"]) is not int or row["size"] < 0
                    or path.stat().st_size != row["size"]):
                raise CacheCorruption(f"cache file differs: {row.get('path')}")
            observed = file_sha256(path)
            bytes_read += row["size"]
            if observed != row["sha256"]:
                raise CacheCorruption(f"cache file hash differs: {row['path']}")
            expected_paths.add(relative.as_posix())
        actual_paths = {
            path.relative_to(target / "data").as_posix()
            for path in (target / "data").rglob("*") if path.is_file()
        }
        if actual_paths != expected_paths or manifest["content_sha256"] != canonical_sha256(files):
            raise CacheCorruption(f"cache inventory differs: {digest}")
        return CacheObject(kind, digest, target, MappingProxyType(manifest), hit, bytes_read)

    def get(self, kind: str, identity: Mapping[str, Any]) -> CacheObject | None:
        digest = self.digest(kind, identity)
        target = self._object_path(kind, digest)
        return self._load(kind, digest, hit=True) if target.exists() else None

    def build(
        self,
        kind: str,
        identity: Mapping[str, Any],
        writer: Callable[[Path], Mapping[str, Any]],
    ) -> CacheObject:
        digest = self.digest(kind, identity)
        target = self._object_path(kind, digest)
        if target.exists():
            return self._load(kind, digest, hit=True)
        temporary = self._build_path(kind, digest)
        data_root = temporary / "data"
        data_root.mkdir(parents=True)
        try:
            metadata = dict(writer(data_root))
            json.loads(canonical_bytes(metadata))
            files = self._inventory(data_root)
            manifest = {
                "cache_schema_version": CACHE_SCHEMA_VERSION,
                "kind": kind,
                "namespace": NAMESPACE_BY_KIND[kind],
                "digest": digest,
                "identity": json.loads(canonical_bytes(identity)),
                "files": files,
                "content_sha256": canonical_sha256(files),
                "metadata": metadata,
            }
            (temporary / "manifest.json").write_bytes(canonical_bytes(manifest, newline=True))
            fsync_tree(temporary)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.rename(temporary, target)
            except OSError as exc:
                if exc.errno not in {errno.EEXIST, errno.ENOTEMPTY} or not target.exists():
                    raise
                winner = self._load(kind, digest, hit=True)
                if winner.manifest["content_sha256"] != manifest["content_sha256"]:
                    raise CacheConflict(f"concurrent cache builders disagreed: {digest}") from exc
                shutil.rmtree(temporary)
                return winner
            parent_descriptor = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent_descriptor)
            finally:
                os.close(parent_descriptor)
            return self._load(kind, digest, hit=False)
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise

    @staticmethod
    def _declaration(source: PriceSource) -> dict[str, Any]:
        declaration = source.declaration
        return {
            "source": declaration.source,
            "snapshot_sha256": declaration.snapshot_sha256,
            "point_in_time": declaration.point_in_time,
            "survivor_status": declaration.survivor_status,
            "timezone": declaration.timezone,
            "session_open": declaration.session_open,
            "session_close": declaration.session_close,
            "daily_bar_lag_seconds": declaration.daily_bar_lag.total_seconds(),
        }

    @staticmethod
    def _write_panel(data_root: Path, source: PriceSource) -> Mapping[str, Any]:
        panel = source.panel
        arrays = data_root / "arrays"
        arrays.mkdir()
        for field in FIELDS:
            np.save(arrays / f"field-{field}.npy", panel.fields[field], allow_pickle=False)
        np.save(arrays / "present.npy", panel.present, allow_pickle=False)
        np.save(arrays / "funding-at.npy", panel.funding_at, allow_pickle=False)
        np.save(arrays / "open-available-at.npy", panel.open_available_at, allow_pickle=False)
        np.save(arrays / "daily-available-at.npy", panel.daily_available_at, allow_pickle=False)
        intraday = {}
        for index, (clock, values) in enumerate(sorted(panel.intraday.items())):
            name = f"intraday-{index:04d}.npy"
            np.save(arrays / name, values, allow_pickle=False)
            intraday[clock] = name
        metadata = {
            "format": "study-panel-npy-v1",
            "tickers": list(panel.tickers),
            "sessions": [session.isoformat() for session in panel.sessions],
            "bar_count": panel.bar_count,
            "declaration": ResearchCache._declaration(source),
            "intraday": intraday,
            "dividends": [row.canonical() for row in source.dividends],
        }
        (data_root / "panel.json").write_bytes(canonical_bytes(metadata, newline=True))
        return {"format": metadata["format"], "bar_count": panel.bar_count}

    def panel(
        self,
        identity: Mapping[str, Any],
        builder: Callable[[], PriceSource],
    ) -> CachedPanel:
        obj = self.get("panel", identity)
        if obj is None:
            built: PriceSource | None = None

            def write(data_root: Path) -> Mapping[str, Any]:
                nonlocal built
                built = builder()
                if not isinstance(built, PriceSource):
                    raise TypeError("panel builder must return PriceSource")
                return self._write_panel(data_root, built)

            obj = self.build("panel", identity, write)
        return CachedPanel(obj, self.load_panel(obj))

    @staticmethod
    def load_panel(obj: CacheObject) -> PriceSource:
        if obj.kind != "panel":
            raise ValueError("cache object is not a panel")
        metadata = obj.read_json("panel.json")
        if not isinstance(metadata, dict) or metadata.get("format") != "study-panel-npy-v1":
            raise CacheCorruption("panel metadata schema differs")
        required = {"format", "tickers", "sessions", "bar_count", "declaration", "intraday", "dividends"}
        if set(metadata) != required:
            raise CacheCorruption("panel metadata fields differ")
        tickers = tuple(metadata["tickers"])
        sessions = tuple(date.fromisoformat(value) for value in metadata["sessions"])
        shape = len(tickers), len(sessions)
        arrays = obj.data_path / "arrays"
        fields = {field: _array(arrays / f"field-{field}.npy") for field in FIELDS}
        present = _array(arrays / "present.npy")
        funding_at = _array(arrays / "funding-at.npy")
        open_at = _array(arrays / "open-available-at.npy")
        daily_at = _array(arrays / "daily-available-at.npy")
        intraday = {clock: _array(arrays / filename)
                    for clock, filename in metadata["intraday"].items()}
        if (any(array.shape != shape for array in (*fields.values(), *intraday.values(), present, funding_at))
                or open_at.shape != (len(sessions),) or daily_at.shape != (len(sessions),)
                or present.dtype != np.bool_ or metadata["bar_count"] != int(present.sum())):
            raise CacheCorruption("panel array shapes or counts differ")
        panel = Panel.__new__(Panel)
        panel.tickers, panel.sessions, panel.bar_count = tickers, sessions, metadata["bar_count"]
        panel.ticker_index = MappingProxyType({value: index for index, value in enumerate(tickers)})
        panel.session_index = MappingProxyType({value: index for index, value in enumerate(sessions)})
        panel.fields, panel.intraday = MappingProxyType(fields), MappingProxyType(intraday)
        panel.funding_at, panel.present = funding_at, present
        panel.open_available_at, panel.daily_available_at = open_at, daily_at
        panel.session_days = np.asarray(sessions, dtype="datetime64[D]")
        panel.session_days.flags.writeable = False
        panel.bars = PanelBars(panel)
        declaration_row = metadata["declaration"]
        declaration = DataDeclaration(
            declaration_row["source"],
            declaration_row["snapshot_sha256"],
            declaration_row["point_in_time"],
            declaration_row["survivor_status"],
            declaration_row["timezone"],
            declaration_row["session_open"],
            declaration_row["session_close"],
            timedelta(seconds=declaration_row["daily_bar_lag_seconds"]),
        )
        dividends = tuple(Dividend(
            row["ticker"], date.fromisoformat(row["ex_date"]), row["cash_amount"],
            datetime.fromisoformat(row["available_at"]),
        ) for row in metadata["dividends"])
        source = PriceSource.__new__(PriceSource)
        source.declaration, source.panel, source.bars = declaration, panel, panel.bars
        source.dividends = dividends
        source._dividends = MappingProxyType({ticker: tuple(
            row for row in dividends if row.ticker == ticker
        ) for ticker in {row.ticker for row in dividends}})
        return source

    @staticmethod
    def _coverage(universe: Universe) -> np.ndarray:
        source = universe.source
        result = np.zeros((len(source.tickers), len(source.sessions)), dtype=np.bool_)
        for ticker_index, ticker in enumerate(source.tickers):
            for session_index, session in enumerate(source.sessions):
                result[ticker_index, session_index] = universe.is_listed(ticker, session)
        result.flags.writeable = False
        return result

    def universe(
        self,
        identity: Mapping[str, Any],
        source: PriceSource,
        builder: Callable[[], Universe],
        *,
        exclusions: Mapping[str, Sequence[str]] | None = None,
    ) -> CachedUniverse:
        obj = self.get("universe", identity)
        if obj is None:
            def write(data_root: Path) -> Mapping[str, Any]:
                universe = builder()
                if universe.source.declaration.snapshot_sha256 != source.declaration.snapshot_sha256:
                    raise CacheError("universe source differs from cached panel source")
                if universe.listings is None:
                    raise CacheError("cached universe requires point-in-time listing intervals")
                rows = [{
                    "ticker": row.ticker,
                    "listed_from": row.listed_from.isoformat(),
                    "listed_through": row.listed_through.isoformat() if row.listed_through else None,
                } for row in universe.listings]
                (data_root / "universe.json").write_bytes(canonical_bytes({
                    "format": "study-universe-v1",
                    "source_sha256": source.declaration.snapshot_sha256,
                    "delisting_return": universe.delisting_return,
                    "listings": rows,
                    "exclusions": {key: sorted(set(value))
                                   for key, value in sorted((exclusions or {}).items())},
                }, newline=True))
                coverage = self._coverage(universe)
                np.save(data_root / "coverage.npy", coverage, allow_pickle=False)
                return {"format": "study-universe-v1", "listing_count": len(rows)}
            obj = self.build("universe", identity, write)
        metadata = obj.read_json("universe.json")
        required = {"format", "source_sha256", "delisting_return", "listings", "exclusions"}
        if (not isinstance(metadata, dict) or set(metadata) != required
                or metadata["format"] != "study-universe-v1"
                or metadata["source_sha256"] != source.declaration.snapshot_sha256):
            raise CacheCorruption("universe metadata differs")
        listings = tuple(ListingInterval(
            row["ticker"], date.fromisoformat(row["listed_from"]),
            date.fromisoformat(row["listed_through"]) if row["listed_through"] else None,
        ) for row in metadata["listings"])
        universe = Universe(source, listings, delisting_return=metadata["delisting_return"])
        coverage = obj.load_array("coverage.npy")
        expected_shape = len(source.tickers), len(source.sessions)
        if coverage.shape != expected_shape or coverage.dtype != np.bool_:
            raise CacheCorruption("universe coverage shape differs")
        frozen_exclusions = MappingProxyType({
            key: tuple(value) for key, value in metadata["exclusions"].items()
        })
        return CachedUniverse(obj, universe, coverage, frozen_exclusions)

    def table(
        self,
        kind: str,
        identity: Mapping[str, Any],
        builder: Callable[[], pd.DataFrame],
        *,
        family: str,
        date_column: str = "session",
        expected_columns: Sequence[str] | None = None,
    ) -> CacheObject:
        if kind not in {"feature", "label"}:
            raise ValueError("cached table kind must be feature or label")
        family_name = _safe_name(family)
        obj = self.get(kind, identity)
        if obj is not None:
            return obj

        def write(data_root: Path) -> Mapping[str, Any]:
            frame = builder()
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                raise CacheError("table builder must return a non-empty DataFrame")
            if date_column not in frame.columns:
                raise CacheError(f"table is missing partition column {date_column!r}")
            columns = [str(column) for column in frame.columns]
            if expected_columns is not None and columns != list(expected_columns):
                raise CacheError("table schema differs from the declared output schema")
            if len(columns) != len(set(columns)):
                raise CacheError("table columns must be unique")
            days = pd.to_datetime(frame[date_column], errors="raise").dt.date
            connection = duckdb.connect(":memory:")
            try:
                for day in sorted(set(days)):
                    partition = data_root / f"family={family_name}" / f"date={day.isoformat()}"
                    partition.mkdir(parents=True)
                    selected = frame.loc[days == day].copy()
                    connection.register("selected_rows", selected)
                    connection.execute(
                        "COPY selected_rows TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                        [str(partition / "part-00000.parquet")],
                    )
                    connection.unregister("selected_rows")
            finally:
                connection.close()
            schema = [{"name": str(name), "dtype": str(dtype)}
                      for name, dtype in frame.dtypes.items()]
            (data_root / "table.json").write_bytes(canonical_bytes({
                "format": "study-table-parquet-v1",
                "kind": kind,
                "family": family_name,
                "date_column": date_column,
                "columns": columns,
                "schema": schema,
                "rows": len(frame),
                "partitions": len(set(days)),
            }, newline=True))
            return {"format": "study-table-parquet-v1", "rows": len(frame), "columns": columns}

        return self.build(kind, identity, write)
