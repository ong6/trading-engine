"""engine.lib.log — stdout logging that is byte-identical to the print() it replaced."""
from __future__ import annotations

import json
import logging

import pytest

from engine.lib import log as elog


@pytest.fixture(autouse=True)
def _reset_logging(monkeypatch):
    """Each test starts from a clean env and re-reads it; restore afterwards."""
    monkeypatch.delenv(elog.LEVEL_ENV, raising=False)
    monkeypatch.delenv(elog.JSON_ENV, raising=False)
    yield
    monkeypatch.delenv(elog.LEVEL_ENV, raising=False)
    monkeypatch.delenv(elog.JSON_ENV, raising=False)
    elog.configure(force=True)


def _handlers():
    return [h for h in logging.getLogger(elog.ROOT_NAME).handlers
            if getattr(h, elog._MARK, False)]


def test_message_only_matches_print(capsys):
    elog.configure(force=True)
    log = elog.get_logger("league")
    d, n = "2026-09-02", 3
    log.info("[league] %s: fills=%d", d, n)
    log.info(f"[league]   {d}: carried")
    log.warning("[league] WARN 2 position(s) marked stale")
    log.error("TODO: price verify failed")
    out = capsys.readouterr()
    assert out.out == ("[league] 2026-09-02: fills=3\n"
                       "[league]   2026-09-02: carried\n"
                       "[league] WARN 2 position(s) marked stale\n"
                       "TODO: price verify failed\n")
    assert out.err == ""


def test_leading_newline_and_unicode_preserved(capsys):
    elog.configure(force=True)
    elog.get_logger("signals").info("\n[signals] macro_signals now holds 1,234 rows → done")
    assert capsys.readouterr().out == "\n[signals] macro_signals now holds 1,234 rows → done\n"


def test_debug_hidden_at_default_level(capsys):
    elog.configure(force=True)
    log = elog.get_logger("x")
    log.debug("[x] hidden")
    log.info("[x] shown")
    assert capsys.readouterr().out == "[x] shown\n"


def test_level_env(monkeypatch, capsys):
    monkeypatch.setenv(elog.LEVEL_ENV, "WARNING")
    elog.configure(force=True)
    log = elog.get_logger("x")
    log.info("[x] info")
    log.warning("[x] WARN something")
    assert capsys.readouterr().out == "[x] WARN something\n"

    monkeypatch.setenv(elog.LEVEL_ENV, "debug")
    elog.configure(force=True)
    log.debug("[x] dbg")
    assert capsys.readouterr().out == "[x] dbg\n"


def test_json_mode_shape(monkeypatch, capsys):
    monkeypatch.setenv(elog.JSON_ENV, "1")
    elog.configure(force=True)
    elog.get_logger("screen").warning("[screen] WARN %d stale", 7)
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert set(rec) == {"ts", "level", "tag", "msg"}
    assert rec["level"] == "WARNING"
    assert rec["tag"] == "screen"
    assert rec["msg"] == "[screen] WARN 7 stale"
    assert rec["ts"].endswith("+00:00")


def test_no_duplicate_handlers_on_repeated_get_logger(capsys):
    elog.configure(force=True)
    for _ in range(5):
        elog.configure()
        elog.get_logger("a")
        elog.get_logger("b")
    assert len(_handlers()) == 1
    assert logging.getLogger(elog.ROOT_NAME).propagate is False
    elog.get_logger("a").info("[a] once")
    assert capsys.readouterr().out == "[a] once\n"


def test_configure_force_replaces_not_stacks():
    elog.configure(force=True)
    elog.configure(force=True)
    assert len(_handlers()) == 1


def test_module_reload_does_not_stack_handlers(capsys):
    import importlib

    elog.configure(force=True)
    elog.get_logger("a")
    mod = importlib.reload(elog)
    mod.get_logger("b").info("[b] once")
    assert len(_handlers()) == 1
    assert capsys.readouterr().out == "[b] once\n"


def test_root_logger_untouched_and_no_stderr(capsys):
    elog.configure(force=True)
    before = list(logging.getLogger().handlers)
    elog.get_logger("q").error("FATAL: nothing")
    assert logging.getLogger().handlers == before
    out = capsys.readouterr()
    assert out.out == "FATAL: nothing\n" and out.err == ""
