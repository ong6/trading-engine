"""Audit or apply one vendor-neutral point-in-time import manifest."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from engine import pit_import
from engine.lib import db
from engine.lib.settings import DEFAULT_DB


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    result = pit_import.audit_manifest(args.manifest, args.data_root)
    result["mode"] = "audit"
    if args.apply:
        con = db.connect(args.database, wait_s=0)
        try:
            result = {**result, **pit_import.import_manifest(
                con, args.manifest, args.data_root, imported_at=datetime.now(timezone.utc)
            ), "mode": "apply"}
        finally:
            con.close()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
