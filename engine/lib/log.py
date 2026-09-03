"""Stdout logging that is byte-identical to the `print(f"[tag] ...")` it replaces.

    from engine.lib.log import get_logger
    log = get_logger("league")
    log.info("[league] %s: fills=%d", d, n)      # prints exactly: [league] 2026-09-02: fills=3

Design points (A6 of docs/architecture-review-2026-09-02.md):

* The formatter is ``%(message)s`` — no timestamp, no level name — so the nightly
  log (logs/cron.log, logs/run-*.log) and the grep-based checks in BUILDLOG /
  how-it-works (``grep "TODO"``, ``"=== done"``, ``[league]``, ``WARN``, ``FATAL``)
  keep working unchanged. Callers keep their own ``[tag]`` / ``WARN`` / ``TODO:``
  prefixes in the message text; nothing is added.
* Records go to ``sys.stdout`` (looked up at emit time, so pytest's ``capsys`` and
  any later redirection see them) and are flushed per record. Flushing the shared
  ``sys.stdout`` also drains pending ``print()`` output, so lines written by both
  mechanisms keep their order under cron / ``tee``.
* ``TRADING_ENGINE_LOG_LEVEL`` (default ``INFO``) sets the threshold.
* ``TRADING_ENGINE_LOG_JSON=1`` switches every line to one JSON object
  ``{"ts", "level", "tag", "msg"}`` for machine consumption. Off by default.
* Configuration is idempotent: one handler on the ``trading_engine`` logger,
  regardless of how many modules import this or how often ``get_logger`` runs.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

ROOT_NAME = "trading_engine"
LEVEL_ENV = "TRADING_ENGINE_LOG_LEVEL"
JSON_ENV = "TRADING_ENGINE_LOG_JSON"
DEFAULT_LEVEL = "INFO"


_MARK = "_trading_engine_stdout_handler"


class _StdoutHandler(logging.Handler):
    """Write ``format(record)`` + newline to the *current* ``sys.stdout`` and flush."""

    def __init__(self) -> None:
        super().__init__()
        # identity marker survives importlib.reload (a fresh class object would
        # defeat isinstance and stack a second handler)
        setattr(self, _MARK, True)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            stream = sys.stdout
            stream.write(msg + "\n")
            stream.flush()
        except RecursionError:  # pragma: no cover - mirrors logging.StreamHandler
            raise
        except Exception:  # noqa: BLE001 - never let logging take the run down
            self.handleError(record)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        tag = record.name
        prefix = ROOT_NAME + "."
        if tag.startswith(prefix):
            tag = tag[len(prefix):]
        return json.dumps({
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "tag": tag,
            "msg": record.getMessage(),
        }, ensure_ascii=False)


def _json_enabled() -> bool:
    return os.environ.get(JSON_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _level_from_env() -> int:
    raw = os.environ.get(LEVEL_ENV, DEFAULT_LEVEL).strip().upper() or DEFAULT_LEVEL
    if raw.isdigit():
        return int(raw)
    level = logging.getLevelName(raw)
    return level if isinstance(level, int) else logging.INFO


def configure(force: bool = False) -> logging.Logger:
    """Attach the single stdout handler to the ``trading_engine`` logger.

    Idempotent: a second call is a no-op unless ``force=True`` (tests use that to
    re-read the environment).
    """
    root = logging.getLogger(ROOT_NAME)
    ours = [h for h in root.handlers if getattr(h, _MARK, False)]
    if ours and not force:
        return root
    for h in ours:
        root.removeHandler(h)
    handler = _StdoutHandler()
    handler.setFormatter(_JsonFormatter() if _json_enabled()
                         else logging.Formatter("%(message)s"))
    root.addHandler(handler)
    root.setLevel(_level_from_env())
    root.propagate = False  # never double-print through the stdlib root logger
    return root


def get_logger(tag: str) -> logging.Logger:
    """Logger for one subsystem, e.g. ``get_logger("league")``.

    The tag only surfaces in JSON mode; text mode prints the message verbatim.
    """
    configure()
    return logging.getLogger(f"{ROOT_NAME}.{tag}")
