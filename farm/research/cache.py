"""Content-addressed immutable cache for research panels, universes, and tables."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from engine.lib import db
from engine.lib.resources import write_text_atomic
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


def _identity_sha(value: str, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{field} must be a SHA-256")
    int(value, 16)
    return value


@dataclass(frozen=True)
class PanelCacheIdentity:
    generation_sha256: str
    part_sha256s: tuple[str, ...]
    columns: tuple[str, ...]
    date_start: str
    date_end: str
    normalization_version: str
    quality_version: str
    calendar_version: str
    availability_version: str

    @classmethod
    def from_source(
        cls,
        source: PriceSource,
        *,
        normalization_version: str,
        quality_version: str,
        calendar_version: str,
        availability_version: str,
    ) -> PanelCacheIdentity:
        derived = _panel_content_identity(source)
        return cls(
            **derived,
            normalization_version=normalization_version,
            quality_version=quality_version,
            calendar_version=calendar_version,
            availability_version=availability_version,
        )

    def as_dict(self) -> dict[str, Any]:
        _identity_sha(self.generation_sha256, "generation_sha256")
        if not self.part_sha256s or any(
                _identity_sha(item, "part_sha256s") != item for item in self.part_sha256s):
            raise ValueError("panel identity needs immutable source parts")
        if not self.columns or not all(self.columns):
            raise ValueError("panel identity needs selected columns")
        date.fromisoformat(self.date_start), date.fromisoformat(self.date_end)
        for field in (
            "normalization_version", "quality_version", "calendar_version",
            "availability_version",
        ):
            if not getattr(self, field):
                raise ValueError(f"panel identity needs {field}")
        return json.loads(canonical_bytes(asdict(self)))


@dataclass(frozen=True)
class UniverseCacheIdentity:
    membership_sha256: str
    exclusions_sha256: str
    delisting_return: float
    recipe_sha256: str
    coverage_version: str

    @classmethod
    def from_universe(
        cls,
        universe: Universe,
        *,
        exclusions: Mapping[str, Sequence[str]] | None = None,
        recipe_sha256: str,
        coverage_version: str,
    ) -> UniverseCacheIdentity:
        return cls(
            membership_sha256=_universe_membership_sha256(universe),
            exclusions_sha256=canonical_sha256(_normalize_exclusions(exclusions)),
            delisting_return=universe.delisting_return,
            recipe_sha256=recipe_sha256,
            coverage_version=coverage_version,
        )

    def as_dict(self, panel_sha256: str) -> dict[str, Any]:
        for field, value in (
            ("panel_sha256", panel_sha256),
            ("membership_sha256", self.membership_sha256),
            ("exclusions_sha256", self.exclusions_sha256),
            ("recipe_sha256", self.recipe_sha256),
        ):
            _identity_sha(value, field)
        if (isinstance(self.delisting_return, bool)
                or not isinstance(self.delisting_return, (int, float))
                or not -1 <= float(self.delisting_return) <= 0):
            raise ValueError("universe identity needs a valid delisting return")
        if not self.coverage_version:
            raise ValueError("universe identity needs a coverage version")
        return json.loads(canonical_bytes({"panel_sha256": panel_sha256, **asdict(self)}))


@dataclass(frozen=True)
class TableCacheIdentity:
    source_sha256: str
    schema_sha256: str
    recipe_sha256: str
    availability_version: str
    date_start: str
    date_end: str
    family: str

    @classmethod
    def from_frame(
        cls,
        frame: pd.DataFrame,
        *,
        recipe_sha256: str,
        availability_version: str,
        family: str,
        date_column: str = "session",
    ) -> TableCacheIdentity:
        derived = _table_content_identity(frame, date_column=date_column)
        return cls(
            **derived,
            recipe_sha256=recipe_sha256,
            availability_version=availability_version,
            family=family,
        )

    def as_dict(self) -> dict[str, Any]:
        for field in ("source_sha256", "schema_sha256", "recipe_sha256"):
            _identity_sha(getattr(self, field), field)
        date.fromisoformat(self.date_start), date.fromisoformat(self.date_end)
        _safe_name(self.family)
        if not self.availability_version:
            raise ValueError("table identity needs an availability version")
        return asdict(self)


def repository_containing(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        marker = candidate / ".git"
        file_marker = (marker.is_file() and marker.read_text(
            encoding="utf-8", errors="replace").startswith("gitdir:"))
        directory_marker = marker.is_dir() and (
            (marker / "HEAD").is_file() or (marker / "config").is_file()
        )
        if file_marker or directory_marker:
            return candidate
    return None


def _safe_name(value: str) -> str:
    if not value or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in value):
        raise ValueError(f"unsafe cache partition name: {value!r}")
    return value


def _panel_content_identity(source: PriceSource) -> dict[str, Any]:
    if not isinstance(source, PriceSource):
        raise TypeError("panel builder must return PriceSource")
    sessions = source.panel.sessions
    if not sessions:
        raise CacheError("cached panel requires at least one session")
    snapshot = source.declaration.snapshot_sha256
    _identity_sha(snapshot, "source snapshot_sha256")
    columns = (*FIELDS, *(f"bar_close@{clock}" for clock in sorted(source.panel.intraday)))
    content = hashlib.sha256()
    content.update(canonical_bytes({
        "declaration": {
            "source": source.declaration.source,
            "point_in_time": source.declaration.point_in_time,
            "survivor_status": source.declaration.survivor_status,
            "timezone": source.declaration.timezone,
            "session_open": source.declaration.session_open,
            "session_close": source.declaration.session_close,
            "daily_bar_lag_seconds": source.declaration.daily_bar_lag.total_seconds(),
        },
        "tickers": list(source.panel.tickers),
        "sessions": [session.isoformat() for session in sessions],
        "dividends": [row.canonical() for row in source.dividends],
    }))
    arrays = {
        **{f"field:{name}": value for name, value in source.panel.fields.items()},
        **{f"intraday:{clock}": value for clock, value in source.panel.intraday.items()},
        "present": source.panel.present,
        "funding_at": source.panel.funding_at,
        "open_available_at": source.panel.open_available_at,
        "daily_available_at": source.panel.daily_available_at,
    }
    for name, array in sorted(arrays.items()):
        contiguous = np.ascontiguousarray(array)
        content.update(canonical_bytes({
            "name": name, "dtype": contiguous.dtype.str, "shape": contiguous.shape,
        }))
        content.update(memoryview(contiguous).cast("B"))
    return {
        "generation_sha256": snapshot,
        "part_sha256s": (content.hexdigest(),),
        "columns": tuple(columns),
        "date_start": sessions[0].isoformat(),
        "date_end": sessions[-1].isoformat(),
    }


def _universe_membership_rows(universe: Universe) -> list[dict[str, Any]]:
    if not isinstance(universe, Universe) or universe.listings is None:
        raise CacheError("cached universe requires point-in-time listing intervals")
    return [{
        "ticker": row.ticker,
        "listed_from": row.listed_from.isoformat(),
        "listed_through": row.listed_through.isoformat() if row.listed_through else None,
    } for row in universe.listings]


def _universe_membership_sha256(universe: Universe) -> str:
    return canonical_sha256(_universe_membership_rows(universe))


def _normalize_exclusions(
    exclusions: Mapping[str, Sequence[str]] | None,
) -> dict[str, list[str]]:
    result = {}
    for ticker, reasons in sorted((exclusions or {}).items()):
        if (not isinstance(ticker, str) or not ticker
                or isinstance(reasons, (str, bytes))
                or not all(isinstance(reason, str) and reason for reason in reasons)):
            raise ValueError("universe exclusions must map tickers to reason strings")
        result[ticker] = sorted(set(reasons))
    return result


def _table_scalar(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, np.generic):
        return _table_scalar(value.item())
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, pd.Timedelta):
        return value.isoformat()
    if isinstance(value, float) and np.isnan(value):
        return None
    return value


def _table_content_identity(
    frame: pd.DataFrame, *, date_column: str,
) -> dict[str, str]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise CacheError("table builder must return a non-empty DataFrame")
    if date_column not in frame.columns:
        raise CacheError(f"table is missing partition column {date_column!r}")
    columns = [str(column) for column in frame.columns]
    if len(columns) != len(set(columns)):
        raise CacheError("table columns must be unique")
    schema = [{"name": str(name), "dtype": str(dtype)}
              for name, dtype in frame.dtypes.items()]
    days = pd.to_datetime(frame[date_column], errors="raise").dt.date
    rows = [[_table_scalar(value) for value in row]
            for row in frame.itertuples(index=False, name=None)]
    return {
        "source_sha256": canonical_sha256({"columns": columns, "schema": schema, "rows": rows}),
        "schema_sha256": canonical_sha256(schema),
        "date_start": min(days).isoformat(),
        "date_end": max(days).isoformat(),
    }


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
        connection = db.connect(":memory:", wait_s=0)
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
        detected = repository_containing(self.root)
        explicit = Path(repository_root).resolve() if repository_root is not None else None
        if detected is not None or (explicit is not None and self.root.is_relative_to(explicit)):
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
        return self._build(kind, identity, writer, allow_validated_receipt=False)

    def build_validated(
        self,
        kind: str,
        identity: Mapping[str, Any],
        writer: Callable[[Path], Mapping[str, Any]],
    ) -> CacheObject:
        return self._build(kind, identity, writer, allow_validated_receipt=True)

    def _build(
        self,
        kind: str,
        identity: Mapping[str, Any],
        writer: Callable[[Path], Mapping[str, Any]],
        *,
        allow_validated_receipt: bool,
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
            receipt = metadata.get("validated_study_receipt")
            if receipt is not None:
                if not allow_validated_receipt or not isinstance(receipt, dict):
                    raise CacheError("generic cache publication cannot claim StudySpec validation")
                unsigned = {key: value for key, value in receipt.items()
                            if key not in {"receipt_sha256", "content_sha256"}}
                unsigned["content_sha256"] = canonical_sha256(files)
                metadata["validated_study_receipt"] = {
                    **unsigned, "receipt_sha256": canonical_sha256(unsigned),
                }
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
            write_text_atomic(
                temporary / "manifest.json", canonical_bytes(manifest, newline=True).decode()
            )
            fsync_tree(temporary)
            for path in temporary.rglob("*"):
                if path.is_file():
                    path.chmod(0o444)
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
        write_text_atomic(
            data_root / "panel.json", canonical_bytes(metadata, newline=True).decode()
        )
        return {"format": metadata["format"], "bar_count": panel.bar_count}

    def panel(
        self,
        identity: PanelCacheIdentity,
        builder: Callable[[], PriceSource],
    ) -> CachedPanel:
        if not isinstance(identity, PanelCacheIdentity):
            raise TypeError("panel cache identity must be PanelCacheIdentity")
        identity_row = identity.as_dict()
        built = builder()
        derived_identity = {
            **_panel_content_identity(built),
            "normalization_version": identity.normalization_version,
            "quality_version": identity.quality_version,
            "calendar_version": identity.calendar_version,
            "availability_version": identity.availability_version,
        }
        derived_identity = json.loads(canonical_bytes(derived_identity))
        if identity_row != derived_identity:
            raise CacheError("panel cache identity differs from the built source")
        obj = self.get("panel", identity_row)
        if obj is None:
            def write(data_root: Path) -> Mapping[str, Any]:
                return self._write_panel(data_root, built)

            obj = self.build("panel", identity_row, write)
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
        identity: UniverseCacheIdentity,
        panel: CachedPanel,
        builder: Callable[[], Universe],
        *,
        exclusions: Mapping[str, Sequence[str]] | None = None,
    ) -> CachedUniverse:
        if not isinstance(identity, UniverseCacheIdentity):
            raise TypeError("universe cache identity must be UniverseCacheIdentity")
        if not isinstance(panel, CachedPanel):
            raise TypeError("universe cache requires a bound CachedPanel")
        verified_panel_object = self._load("panel", panel.object.digest, hit=True)
        source = self.load_panel(verified_panel_object)
        universe = builder()
        if not isinstance(universe, Universe):
            raise TypeError("universe builder must return Universe")
        if _panel_content_identity(universe.source) != _panel_content_identity(source):
            raise CacheError("universe source content differs from the cached panel")
        normalized_exclusions = _normalize_exclusions(exclusions)
        membership_rows = _universe_membership_rows(universe)
        identity_row = identity.as_dict(verified_panel_object.digest)
        derived_fields = {
            "membership_sha256": canonical_sha256(membership_rows),
            "exclusions_sha256": canonical_sha256(normalized_exclusions),
            "delisting_return": universe.delisting_return,
        }
        if any(identity_row[name] != value for name, value in derived_fields.items()):
            raise CacheError("universe cache identity differs from built content")
        bound_universe = Universe(
            source, universe.listings, delisting_return=universe.delisting_return,
        )
        obj = self.get("universe", identity_row)
        if obj is None:
            def write(data_root: Path) -> Mapping[str, Any]:
                write_text_atomic(data_root / "universe.json", canonical_bytes({
                    "format": "study-universe-v1",
                    "panel_sha256": verified_panel_object.digest,
                    "source_sha256": source.declaration.snapshot_sha256,
                    "source_content_sha256": _panel_content_identity(source)[
                        "part_sha256s"][0],
                    "delisting_return": bound_universe.delisting_return,
                    "listings": membership_rows,
                    "exclusions": normalized_exclusions,
                }, newline=True).decode())
                coverage = self._coverage(bound_universe)
                np.save(data_root / "coverage.npy", coverage, allow_pickle=False)
                return {
                    "format": "study-universe-v1", "listing_count": len(membership_rows),
                }
            obj = self.build("universe", identity_row, write)
        metadata = obj.read_json("universe.json")
        required = {
            "format", "panel_sha256", "source_sha256", "source_content_sha256",
            "delisting_return", "listings", "exclusions",
        }
        if (not isinstance(metadata, dict) or set(metadata) != required
                or metadata["format"] != "study-universe-v1"
                or metadata["panel_sha256"] != verified_panel_object.digest
                or metadata["source_sha256"] != source.declaration.snapshot_sha256
                or metadata["source_content_sha256"]
                != _panel_content_identity(source)["part_sha256s"][0]):
            raise CacheCorruption("universe metadata differs")
        if (metadata["listings"] != membership_rows
                or metadata["exclusions"] != normalized_exclusions
                or metadata["delisting_return"] != universe.delisting_return):
            raise CacheError("universe cache hit differs from caller content")
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
        identity: TableCacheIdentity,
        builder: Callable[[], pd.DataFrame],
        *,
        family: str,
        date_column: str = "session",
        expected_columns: Sequence[str] | None = None,
    ) -> CacheObject:
        if kind not in {"feature", "label"}:
            raise ValueError("cached table kind must be feature or label")
        if not isinstance(identity, TableCacheIdentity):
            raise TypeError("table cache identity must be TableCacheIdentity")
        family_name = _safe_name(family)
        identity_row = identity.as_dict()
        if identity.family != family_name:
            raise ValueError("table identity family differs from the cache partition family")
        frame = builder()
        derived_identity = {
            **_table_content_identity(frame, date_column=date_column),
            "recipe_sha256": identity.recipe_sha256,
            "availability_version": identity.availability_version,
            "family": family_name,
        }
        if identity_row != derived_identity:
            raise CacheError("table cache identity differs from the built frame")
        columns = [str(column) for column in frame.columns]
        if expected_columns is not None and columns != list(expected_columns):
            raise CacheError("table schema differs from the declared output schema")
        obj = self.get(kind, identity_row)
        if obj is not None:
            return obj

        def write(data_root: Path) -> Mapping[str, Any]:
            days = pd.to_datetime(frame[date_column], errors="raise").dt.date
            connection = db.connect(":memory:", wait_s=0)
            try:
                for day in sorted(set(days)):
                    partition = data_root / f"family={family_name}" / f"date={day.isoformat()}"
                    partition.mkdir(parents=True)
                    selected = frame.loc[days == day].copy()
                    with db.registered_frame(connection, "selected_rows", selected):
                        connection.execute(
                            "COPY selected_rows TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                            [str(partition / "part-00000.parquet")],
                        )
            finally:
                connection.close()
            schema = [{"name": str(name), "dtype": str(dtype)}
                      for name, dtype in frame.dtypes.items()]
            write_text_atomic(data_root / "table.json", canonical_bytes({
                "format": "study-table-parquet-v1",
                "kind": kind,
                "family": family_name,
                "date_column": date_column,
                "columns": columns,
                "schema": schema,
                "rows": len(frame),
                "partitions": len(set(days)),
            }, newline=True).decode())
            return {"format": "study-table-parquet-v1", "rows": len(frame), "columns": columns}

        return self.build(kind, identity_row, write)
