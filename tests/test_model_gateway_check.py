"""Tests for the GET-only model gateway preflight."""

from __future__ import annotations

import json

import pytest

from server import agent_model_client
from tools import model_gateway_check

CURRENT = "traecli 0.210.1"


def health(**overrides):
    return {
        "ok": True, "proxy_version": agent_model_client.REQUIRED_PROXY_VERSION,
        "proxy_source_sha256": agent_model_client.REQUIRED_PROXY_SOURCE_SHA256,
        "traex": CURRENT, "token": {"present": True, "hours_left": 178.5},
        "relogin": {"last_ok": True}, "catalog": {"age_s": 49_481},
        **overrides,
    }


def catalog(entry=None):
    return {"object": "list", "data": [
        entry or dict(agent_model_client.EXPECTED_MODEL_CATALOG_ENTRY), {"id": "other"},
    ]}


def failed(report):
    return set(report["failed"])


def test_current_pins_pass_and_report_semantic_versions_only():
    report = model_gateway_check.evaluate(health(), catalog(), CURRENT)

    assert report["ok"] is True and report["status"] == "ok" and report["failed"] == []
    assert report["runtime"] == {"startup": "0.210.1", "installed": "0.210.1", "drift": False}
    assert report["restart_simulation"] == {
        "startup_runtime": "0.210.1", "status": "ok", "failed": [],
    }
    assert CURRENT not in json.dumps(report)


@pytest.mark.parametrize(("overrides", "name", "status"), [
    ({"ok": False}, "proxy_healthy", "fail"),
    ({"token": {"present": False, "hours_left": 100}}, "proxy_healthy", "fail"),
    ({"proxy_version": "0.8"}, "proxy_version", "fail"),
    ({"proxy_source_sha256": "0" * 64}, "proxy_source_sha256", "fail"),
    ({"traex": "traecli 0.299.9"}, "startup_runtime", "fail"),
    ({"traex": None}, "startup_runtime", "fail"),
    ({"token": {"present": True, "hours_left": 1.9}}, "token_hours_left", "warn"),
    ({"token": {"present": True, "hours_left": None}}, "token_hours_left", "warn"),
    ({"relogin": {"last_ok": False}}, "relogin_last_ok", "warn"),
    ({"catalog": {"age_s": 48 * 3600 + 1}}, "catalog_age", "warn"),
    ({"catalog": {"age_s": None}}, "catalog_age", "warn"),
])
def test_each_mismatch_fails_with_its_severity(overrides, name, status):
    report = model_gateway_check.evaluate(health(**overrides), catalog(), CURRENT)

    assert report["ok"] is False and failed(report) == {name}
    assert report["status"] == status


def test_relogin_not_yet_attempted_passes():
    report = model_gateway_check.evaluate(health(relogin={"last_ok": None}), catalog(), CURRENT)
    assert report["ok"] is True


def test_catalog_entry_drift_or_absence_fails():
    drifted = {**agent_model_client.EXPECTED_MODEL_CATALOG_ENTRY, "description": "changed"}
    assert failed(model_gateway_check.evaluate(health(), catalog(drifted), CURRENT)) == {
        "model_catalog_entry"}
    report = model_gateway_check.evaluate(health(), None, CURRENT, error="HTTP 503")
    assert failed(report) == {"model_catalog_entry"}
    assert report["checks"][4]["observed"] == "HTTP 503"


def test_unreviewed_installed_runtime_warns_before_a_restart_breaks_calls():
    report = model_gateway_check.evaluate(health(), catalog(), "traecli 0.299.9")

    assert failed(report) == {"restart_runtime"} and report["status"] == "warn"
    assert report["runtime"]["drift"] is True
    assert report["runtime"]["installed"].startswith("unreviewed:")
    assert report["restart_simulation"]["status"] == "fail"
    assert set(report["restart_simulation"]["failed"]) == {"startup_runtime", "restart_runtime"}
    assert failed(model_gateway_check.evaluate(health(), catalog(), None)) == {"restart_runtime"}


def test_reviewed_drift_passes_and_restart_simulation_passes(monkeypatch):
    previous = "traecli 0.209.0"
    monkeypatch.setattr(agent_model_client, "REVIEWED_TRAECLI_RUNTIMES", {
        **agent_model_client.REVIEWED_TRAECLI_RUNTIMES,
        "0.209.0": agent_model_client.canonical_sha256(previous),
    })
    monkeypatch.setattr(agent_model_client, "REVIEWED_TRAECLI_RUNTIME_SHA256", (
        *agent_model_client.REVIEWED_TRAECLI_RUNTIME_SHA256,
        agent_model_client.canonical_sha256(previous),
    ))

    report = model_gateway_check.evaluate(health(traex=previous), catalog(), CURRENT)

    assert report["ok"] is True
    assert report["runtime"] == {"startup": "0.209.0", "installed": "0.210.1", "drift": True}
    assert report["restart_simulation"]["status"] == "ok"


def test_check_uses_get_only_routes_and_reads_the_installed_version():
    paths, commands = [], []

    def fetch(path):
        paths.append(path)
        return health() if path == "/healthz" else catalog()

    def run(args, timeout):
        commands.append((args, timeout))
        return CURRENT + "\nbuild details\n"

    report = model_gateway_check.check(fetch=fetch, run=run, binary="/opt/cli")

    assert report["ok"] is True
    assert paths == ["/healthz", "/v1/models"]
    assert commands == [(["/opt/cli", "--version"], model_gateway_check.VERSION_TIMEOUT_S)]


def test_unreachable_proxy_fails():
    def fetch(path):
        raise agent_model_client.ConnectorError("Trae proxy is unavailable")

    report = model_gateway_check.check(fetch=fetch, run=lambda *_: None, binary="/opt/cli")

    assert report["status"] == "fail" and report["failed"] == ["proxy_reachable"]


def test_main_exits_non_zero_on_mismatch(monkeypatch, capsys):
    monkeypatch.setattr(model_gateway_check, "check", lambda **_: model_gateway_check.evaluate(
        health(token={"present": True, "hours_left": 1.0}), catalog(), CURRENT))
    assert model_gateway_check.main([]) == 1
    assert json.loads(capsys.readouterr().out)["failed"] == ["token_hours_left"]

    monkeypatch.setattr(model_gateway_check, "check", lambda **_: model_gateway_check.evaluate(
        health(), catalog(), CURRENT))
    assert model_gateway_check.main([]) == 0


@pytest.mark.parametrize('remaining', [48.0, 47.9, 36.0, 12.0, 2.0])
def test_token_renewal_window_does_not_warn_before_routine_relogin(remaining):
    report = model_gateway_check.evaluate(
        health(token={'present': True, 'hours_left': remaining}), catalog(), CURRENT)
    assert report['status'] == 'ok'


@pytest.mark.parametrize('last_ok', [True, None, False])
def test_imminent_expiry_warns_even_if_an_older_relogin_succeeded(last_ok):
    report = model_gateway_check.evaluate(
        health(token={'present': True, 'hours_left': 1.9}, relogin={'last_ok': last_ok}),
        catalog(), CURRENT)
    assert 'token_hours_left' in report['failed']
    assert report['status'] == 'warn'


def test_failed_relogin_warns_with_plenty_of_token_lifetime():
    report = model_gateway_check.evaluate(health(relogin={'last_ok': False}), catalog(), CURRENT)
    assert failed(report) == {'relogin_last_ok'}


def test_runtime_resolution_prefers_effective_unit_pin_with_safe_quoting(tmp_path, monkeypatch):
    pinned = tmp_path / 'pinned cli'
    pinned.write_text('')
    pinned.chmod(0o755)
    monkeypatch.setenv('TRAEX_BIN', '/different/cli')
    commands = []

    def run(args, timeout):
        commands.append(args)
        if args[0] == 'systemctl':
            return f'Environment="TRAEX_BIN={pinned}" IRRELEVANT="$(touch never)"\n'
        assert args == [str(pinned), '--version']
        return CURRENT + '\nbuild details\n'

    report = model_gateway_check.check(fetch=lambda path: health() if path == '/healthz'
                                       else catalog(), run=run)
    assert report['runtime']['installed'] == '0.210.1'
    assert report['restart_simulation']['status'] == 'ok'
    assert commands[0] == ['systemctl', '--user', 'show', 'trae-proxy.service', '-p', 'Environment']


@pytest.mark.parametrize('environment', [None, '', 'Environment=PATH=/usr/bin',
                                         'Environment="TRAEX_BIN=broken',
                                         'Environment=TRAEX_BIN=/absent/cli'])
def test_runtime_resolution_falls_back_when_unit_pin_is_absent_or_unreadable(
        environment, tmp_path, monkeypatch):
    fallback = tmp_path / 'local-cli'
    fallback.write_text('')
    fallback.chmod(0o755)
    monkeypatch.setenv('TRAEX_BIN', str(fallback))
    assert model_gateway_check.runtime_binary(lambda *_: environment) == str(fallback)


def test_runtime_resolution_handles_a_runner_error(tmp_path, monkeypatch):
    monkeypatch.delenv('TRAEX_BIN', raising=False)
    monkeypatch.setattr(model_gateway_check.shutil, 'which', lambda _: '/opt/local-cli')

    def unreadable(*_):
        raise OSError('manager unavailable')

    assert model_gateway_check.runtime_binary(unreadable) == '/opt/local-cli'
