"""Resource-governance helpers for the §12.7 job queue.

Small, dependency-light readings of the box's state (load, RAM, disk) plus a
merge-don't-clobber writer for data/_meta.json. Shared by queue_runner.py and
intraday.py so both honour the same caps and report honestly.

No psutil: RAM comes from /proc/meminfo, load from os.getloadavg, disk from
os.walk + shutil.disk_usage — all stdlib, all cheap.
"""
from __future__ import annotations

import fcntl
import json
import os
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from engine.lib.log import get_logger

log = get_logger("queue")


@contextmanager
def advisory_file_lock(path: str | Path):
    """Serialize cooperating processes around a shared filesystem artifact.

    The lock file is intentionally persistent: unlinking it after release can
    let a new process lock a different inode while an existing waiter still
    holds the old one.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


# --------------------------------------------------------------------------- #
# process niceness (§12.7: nice 19 + ionice class 3, best-effort)
# --------------------------------------------------------------------------- #
def apply_niceness() -> None:
    """Re-nice this process to 19 and set idle I/O priority. Both best-effort:
    a box without ionice or a locked-down nice() must not break the run."""
    try:
        os.nice(19)
        log.info("[queue] re-niced to 19")
    except Exception as exc:  # noqa: BLE001 - niceness is advisory
        log.warning(f"[queue] os.nice(19) failed, continuing: {exc}")
    try:
        r = subprocess.run(
            ["ionice", "-c3", "-p", str(os.getpid())],
            check=False, capture_output=True, text=True,
        )
        if r.returncode == 0:
            log.info("[queue] ionice class 3 (idle) set")
        else:
            log.info(f"[queue] ionice returned {r.returncode}, continuing")
    except Exception as exc:  # noqa: BLE001 - ionice may be absent
        log.info(f"[queue] ionice unavailable, continuing: {exc}")


# --------------------------------------------------------------------------- #
# resource readings
# --------------------------------------------------------------------------- #
def load_5min() -> float:
    """5-minute load average (index 1 of getloadavg)."""
    try:
        return os.getloadavg()[1]
    except (OSError, AttributeError):
        return 0.0  # unknown -> don't block


def free_ram_gb() -> float:
    """Available RAM in GiB from /proc/meminfo MemAvailable."""
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    return kb / 1024 / 1024
    except (OSError, ValueError):
        pass
    return float("inf")  # unknown -> don't block


# store/snapshots/ holds immutable read-only copies of the engine database. They
# are bounded by their own retention (latest + N, tools/publish_snapshot.py), so
# the §12.7 soft cap measures the live store without them and snapshots carry a
# separate cap: room for the retained pair plus one in-flight publication.
STORE_SOFT_GB = 60.0
SNAPSHOTS_DIRNAME = "snapshots"
SNAPSHOT_SOFT_GB = 35.0


def dir_size_gb(path: str | Path, *, exclude: tuple[str, ...] = ()) -> float:
    """Total on-disk size of a directory tree, in GiB.

    ``exclude`` names top-level children of ``path`` that are left out. Symlinks
    are not followed, so snapshots/market-latest does not count its target twice.
    """
    path = Path(path)
    if not path.exists():
        return 0.0
    total = 0
    for root, dirs, files in os.walk(path):
        if root == str(path):
            dirs[:] = [name for name in dirs if name not in exclude]
            files = [name for name in files if name not in exclude]
        for name in files:
            try:
                info = os.lstat(os.path.join(root, name))
            except OSError:
                continue
            if not stat.S_ISLNK(info.st_mode):
                total += info.st_size
    return total / (1024 ** 3)


def live_store_gb(store_dir: str | Path) -> float:
    """Size of store/ without its snapshots/ subtree, in GiB (the soft-cap figure)."""
    return dir_size_gb(store_dir, exclude=(SNAPSHOTS_DIRNAME,))


def snapshots_gb(store_dir: str | Path) -> float:
    """Size of store/snapshots/, in GiB (measured against SNAPSHOT_SOFT_GB)."""
    return dir_size_gb(Path(store_dir) / SNAPSHOTS_DIRNAME)


def root_free_gb(path: str = "/") -> float:
    """Free space on the filesystem holding `path`, in GiB."""
    import shutil
    try:
        return shutil.disk_usage(path).free / (1024 ** 3)
    except OSError:
        return float("inf")


# --------------------------------------------------------------------------- #
# _meta.json — merge, never clobber
# --------------------------------------------------------------------------- #
def write_text_atomic(path: str | Path, text: str) -> None:
    """Write `text` to `path` atomically: a temp file in the same directory then
    os.replace() onto the target. A torn write can never leave a partial (or
    empty) file that a later read would swallow as {} and clobber sibling keys.

    Preserve an existing target's permissions. New generated artifacts use the
    ordinary non-executable file mode instead of inheriting mkstemp's private
    0600 mode.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        mode = 0o644
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            os.fchmod(fh.fileno(), mode)
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_meta(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _read_meta_for_update(path: Path) -> dict:
    """Read a writable snapshot without converting corruption into emptiness."""
    if not path.exists():
        return {}
    try:
        meta = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError("refusing to replace malformed metadata JSON") from exc
    if not isinstance(meta, dict):
        raise ValueError("refusing to replace non-object metadata JSON")
    return meta


def merge_meta(path: str | Path, updates: dict) -> None:
    """Process-safely merge top-level keys into the shared metadata snapshot.

    Atomic replacement prevents readers from seeing a torn file.  The adjacent
    advisory lock also covers the preceding read, so parallel producers cannot
    both read the same snapshot and then erase whichever sibling publishes
    first.  Every writer of ``data/_meta.json`` must use this helper.
    """
    path = Path(path)
    lock_path = path.with_name(f"{path.name}.lock")
    with advisory_file_lock(lock_path):
        meta = _read_meta_for_update(path)
        meta.update(updates)
        write_text_atomic(path, json.dumps(meta, indent=2))


def update_disk_warning(
    path: str | Path,
    store_gb: float,
    soft_gb: float = STORE_SOFT_GB,
    *,
    snapshots_gb: float | None = None,
    snapshot_soft_gb: float = SNAPSHOT_SOFT_GB,
) -> None:
    """Set (or clear) the top-level disk_warning field per the §12.7 soft cap.

    ``store_gb`` is the live store without snapshots/ (``live_store_gb``). When
    ``snapshots_gb`` is given, ``snapshot_disk_warning`` is set or cleared
    against its own cap in the same merge. Merges so it never disturbs the
    intraday block or collect's health fields."""
    flagged_at = datetime.now(timezone.utc).isoformat()
    updates: dict = {"disk_warning": None}
    if store_gb > soft_gb:
        updates["disk_warning"] = {
            "store_gb": round(store_gb, 2),
            "soft_cap_gb": soft_gb,
            "flagged_at": flagged_at,
            "message": (
                f"store/ is {store_gb:.1f} GiB excluding {SNAPSHOTS_DIRNAME}/, "
                f"over the {soft_gb:.0f} GiB soft cap"
            ),
        }
    if snapshots_gb is not None:
        updates["snapshot_disk_warning"] = None
        if snapshots_gb > snapshot_soft_gb:
            updates["snapshot_disk_warning"] = {
                "snapshots_gb": round(snapshots_gb, 2),
                "soft_cap_gb": snapshot_soft_gb,
                "flagged_at": flagged_at,
                "message": (
                    f"store/{SNAPSHOTS_DIRNAME}/ is {snapshots_gb:.1f} GiB, over the "
                    f"{snapshot_soft_gb:.0f} GiB snapshot cap"
                ),
            }
    # below a cap -> clear any stale warning (merge preserves siblings)
    merge_meta(path, updates)
