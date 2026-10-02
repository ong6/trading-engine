from __future__ import annotations

import pytest

from engine.lib import db, settings


class _FakeConnection:
    def __init__(self):
        self.calls = []
        self.closed = False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return self

    def close(self):
        self.closed = True


def _clear_resource_environment(monkeypatch):
    for name in (
        settings.DUCKDB_THREADS_ENV,
        settings.DUCKDB_MEMORY_LIMIT_ENV,
        settings.DUCKDB_TEMP_DIR_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


def test_connect_leaves_duckdb_defaults_untouched_when_unset(monkeypatch, tmp_path):
    _clear_resource_environment(monkeypatch)
    connection = _FakeConnection()
    monkeypatch.setattr(db.duckdb, "connect", lambda *_args, **_kwargs: connection)

    assert db.connect(tmp_path / "market.duckdb") is connection
    assert connection.calls == []


def test_connect_applies_optional_resource_settings_immediately(monkeypatch, tmp_path):
    monkeypatch.setenv(settings.DUCKDB_THREADS_ENV, "7")
    monkeypatch.setenv(settings.DUCKDB_MEMORY_LIMIT_ENV, "3GB")
    monkeypatch.setenv(settings.DUCKDB_TEMP_DIR_ENV, "scratch/duckdb")
    connection = _FakeConnection()
    monkeypatch.setattr(db.duckdb, "connect", lambda *_args, **_kwargs: connection)

    assert db.connect(tmp_path / "market.duckdb") is connection
    assert connection.calls == [
        ("SET threads = ?", [7]),
        ("SET memory_limit = ?", ["3GB"]),
        ("SET temp_directory = ?", [str(settings.REPO_ROOT / "scratch/duckdb")]),
    ]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        (settings.DUCKDB_THREADS_ENV, "0"),
        (settings.DUCKDB_THREADS_ENV, "not-an-int"),
        (settings.DUCKDB_MEMORY_LIMIT_ENV, ""),
        (settings.DUCKDB_TEMP_DIR_ENV, ""),
    ],
)
def test_invalid_resource_setting_closes_connection(monkeypatch, tmp_path, name, value):
    _clear_resource_environment(monkeypatch)
    monkeypatch.setenv(name, value)
    connection = _FakeConnection()
    monkeypatch.setattr(db.duckdb, "connect", lambda *_args, **_kwargs: connection)

    with pytest.raises((TypeError, ValueError)):
        db.connect(tmp_path / "market.duckdb")
    assert connection.closed is True


def test_temp_directory_preserves_absolute_path(monkeypatch, tmp_path):
    _clear_resource_environment(monkeypatch)
    absolute = tmp_path / "spill"
    monkeypatch.setenv(settings.DUCKDB_TEMP_DIR_ENV, str(absolute))
    assert settings.duckdb_resource_settings() == (None, None, str(absolute))
