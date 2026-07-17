"""Resource-governance helpers for the §12.7 job queue.

Small, dependency-light readings of the box's state (load, RAM, disk) plus a
merge-don't-clobber writer for data/_meta.json. Shared by queue_runner.py and
intraday.py so both honour the same caps and report honestly.

No psutil: RAM comes from /proc/meminfo, load from os.getloadavg, disk from
os.walk + shutil.disk_usage — all stdlib, all cheap.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


# --------------------------------------------------------------------------- #
# process niceness (§12.7: nice 19 + ionice class 3, best-effort)
# --------------------------------------------------------------------------- #
def apply_niceness() -> None:
    """Re-nice this process to 19 and set idle I/O priority. Both best-effort:
    a box without ionice or a locked-down nice() must not break the run."""
    try:
        os.nice(19)
        print("[queue] re-niced to 19")
    except Exception as exc:  # noqa: BLE001 - niceness is advisory
        print(f"[queue] os.nice(19) failed, continuing: {exc}")
    try:
        r = subprocess.run(
            ["ionice", "-c3", "-p", str(os.getpid())],
            check=False, capture_output=True, text=True,
        )
        if r.returncode == 0:
            print("[queue] ionice class 3 (idle) set")
        else:
            print(f"[queue] ionice returned {r.returncode}, continuing")
    except Exception as exc:  # noqa: BLE001 - ionice may be absent
        print(f"[queue] ionice unavailable, continuing: {exc}")


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


def dir_size_gb(path: str | Path) -> float:
    """Total on-disk size of a directory tree, in GiB."""
    path = Path(path)
    if not path.exists():
        return 0.0
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total / (1024 ** 3)


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
def read_meta(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def merge_meta(path: str | Path, updates: dict) -> None:
    """Shallow-merge top-level keys into data/_meta.json, preserving every key
    written by other jobs (collect.py's health block, etc.)."""
    path = Path(path)
    meta = read_meta(path)
    meta.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2))


def update_disk_warning(path: str | Path, store_gb: float, soft_gb: float = 60.0) -> None:
    """Set (or clear) the top-level disk_warning field per the §12.7 soft cap.
    Merges so it never disturbs the intraday block or collect's health fields."""
    if store_gb > soft_gb:
        warning = {
            "store_gb": round(store_gb, 2),
            "soft_cap_gb": soft_gb,
            "flagged_at": datetime.now(timezone.utc).isoformat(),
            "message": f"store/ is {store_gb:.1f} GiB, over the {soft_gb:.0f} GiB soft cap",
        }
        merge_meta(path, {"disk_warning": warning})
    else:
        # below the soft cap -> clear any stale warning (merge preserves siblings)
        merge_meta(path, {"disk_warning": None})
