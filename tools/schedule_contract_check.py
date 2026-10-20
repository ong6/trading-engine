#!/usr/bin/env python3
"""Check the host and schedule contract in ``server/schedule-contract.json``.

``--static`` checks this checkout's unit files, installer autostart set and managed cron
block against the manifest. ``--live`` checks the host read-only: user units, crontab, and
every process holding a live store database (found by reading ``/proc/*/fd`` links, so the
check never opens a database). Exit 0 when clean, 2 on violations, 3 when a probe failed.
The hourly ops digest runs the live check and publishes it to ``/meta``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from server import schedule_contract

REPO_ROOT = Path(__file__).resolve().parents[1]


def _installer_contract() -> tuple[frozenset[str], dict[str, str]]:
    # Imported only for --static: the installer pulls in modules that load DuckDB.
    from tools import install_automation

    monitor = install_automation.scheduler_monitor
    cron = {**monitor.expected_cron_entries(REPO_ROOT),
            **monitor.expected_auxiliary_cron_entries(REPO_ROOT)}
    return frozenset(install_automation.AUTOSTART_UNITS), cron


def _summary(result: dict) -> str:
    lines = [f"schedule contract: {result['status']} ({', '.join(result['modes'])})"]
    lines += [f"- {item['rule']}: {item['subject']} {json.dumps(item['detail'], sort_keys=True)}"
              for item in result["violations"]]
    lines += [f"- excepted {item['rule']}: {item['subject']} ({item['exception']})"
              for item in result["exceptions"]]
    lines += [f"- probe error: {error}" for error in result["errors"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--static", action="store_true", help="check this checkout")
    parser.add_argument("--live", action="store_true", help="check the host, read-only")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    parser.add_argument("--engine-root", type=Path, default=None,
                        help="live checkout whose store is audited (default ~/trading-engine)")
    args = parser.parse_args(argv)
    static = args.static or not args.live
    autostart, cron = _installer_contract() if static else (None, None)
    result = schedule_contract.check(static=static, live=args.live, repo_root=REPO_ROOT,
                                     autostart=autostart, expected_cron=cron,
                                     **({"engine_root": args.engine_root} if args.live else {}))
    print(json.dumps(result, indent=1, sort_keys=True) if args.json else _summary(result))
    return schedule_contract.exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
