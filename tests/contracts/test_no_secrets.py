"""Committed provider fixtures and the environment record carry no credential or home path."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import zipfile

import pytest

from tools import provider_contracts as contracts

FIXTURES = contracts.FIXTURES_DIR
KEY = "Zq" + "7Xk2Lm9Pw4Rt8Vb3Nc6Hd1Jf5Gs0Ya"  # assembled so this file never holds one


def _contents(path):
    data = path.read_bytes()
    if path.suffix == ".zip":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return b"".join(archive.read(name) for name in archive.namelist())
    return data


@pytest.mark.parametrize(
    "path", sorted(p for p in contracts.CONTRACTS_DIR.rglob("*") if p.suffix in {".json", ".zip"}),
    ids=lambda path: path.name,
)
def test_committed_contract_files_are_secret_free(path):
    assert contracts.find_secrets(_contents(path)) == []


@pytest.mark.parametrize("text", [
    f"https://api.massive.com/v3/reference/splits?apiKey={KEY}",
    f"Authorization: Bearer {KEY}",
    f'{{"request_id":"{KEY}"}}',
    "/" + "home/someone/trading-engine",
    "someone" + "@" + "example.com",
])
def test_scanner_flags_secret_like_text(text):
    assert contracts.find_secrets(text.encode())


def test_scanner_allows_provider_ids_and_credential_free_cursors():
    page = (FIXTURES / "massive-splits-page-1.json").read_bytes()
    assert "cursor=" in json.loads(page)["next_url"]
    assert contracts.find_secrets(page) == []
    assert contracts.find_secrets(b"no secret", known=(KEY.encode(),)) == []
    assert contracts.find_secrets(KEY.encode(), known=(KEY.encode(),))


def test_url_redaction_replaces_keys_and_refuses_credential_cursors():
    redacted = contracts.redact_url(f"https://api.massive.com/v3/x?limit=5&apiKey={KEY}")
    cursor = base64.urlsafe_b64encode(f"ap=1000&apiKey={KEY}".encode()).decode().rstrip("=")

    assert redacted == "https://api.massive.com/v3/x?limit=5&apiKey=REDACTED"
    with pytest.raises(contracts.ContractError, match="cursor"):
        contracts.redact_url(f"https://api.massive.com/v3/x?cursor={cursor}")


def _archive_root(tmp_path):
    """A source checkout whose provider archive holds the committed fixtures."""
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    root = tmp_path / "source"
    massive = root / contracts.ARCHIVE_DIRS["massive"]
    body = (FIXTURES / manifest["grouped_daily"]["file"]).read_bytes()
    sha = hashlib.sha256(body).hexdigest()
    day = massive / manifest["grouped_daily"]["session_date"]
    day.mkdir(parents=True)
    (day / f"{sha}.json").write_bytes(body)
    (day / "receipt.json").write_text(json.dumps({
        "date": day.name, "fetched_at": manifest["grouped_daily"]["fetched_at"],
        "raw_file": f"{sha}.json", "source_sha256": sha,
    }))
    (massive / "splits").mkdir()
    for page in manifest["splits"]["pages"]:
        payload = json.loads((FIXTURES / page["file"]).read_bytes())
        payload["next_url"] += f"&apiKey={KEY}"
        (massive / "splits" / f"{page['source_sha256']}.json").write_text(json.dumps(payload))
    options = root / contracts.ARCHIVE_DIRS["options"]
    options.mkdir(parents=True)
    for page in [*manifest["options"]["contracts"], manifest["options"]["daily"]]:
        shutil.copy(FIXTURES / page["file"], options / f"{page['source_sha256']}.json")
    (options / "options.duckdb").write_bytes(b"not a response")
    tiingo = root / contracts.ARCHIVE_DIRS["tiingo"]
    tiingo.mkdir(parents=True)
    shutil.copy(FIXTURES / manifest["tiingo"]["file"], tiingo / "archive.zip")
    return root


def test_harvest_redacts_url_keys_and_never_opens_a_database(tmp_path, monkeypatch):
    root, out = _archive_root(tmp_path), tmp_path / "out"
    opened = []
    real_open = contracts.os.open
    monkeypatch.setattr(contracts.os, "open", lambda path, *a, **k: (
        opened.append(str(path)), real_open(path, *a, **k))[1])

    result = contracts.harvest(root, out, home=tmp_path / "home")
    page = json.loads((out / "massive-splits-page-1.json").read_bytes())

    assert result["split_chain_lower_bound"] == 3
    assert page["next_url"].endswith("&apiKey=REDACTED")
    assert opened and not [path for path in opened if "duckdb" in path]
    assert all(contracts.find_secrets(_contents(path)) == [] for path in out.iterdir())


def test_harvest_fails_closed_on_a_secret_like_value(tmp_path):
    root, out = _archive_root(tmp_path), tmp_path / "out"
    daily = next(p for p in (root / contracts.ARCHIVE_DIRS["options"]).iterdir()
                 if b"DELAYED" in p.read_bytes())
    payload = json.loads(daily.read_bytes())
    daily.write_text(json.dumps({**payload, "request_id": KEY}))

    with pytest.raises(contracts.ContractError, match="not safe to commit"):
        contracts.harvest(root, out, home=tmp_path / "home")
    assert not out.exists() or not any(out.iterdir())


def test_harvest_refuses_a_known_credential(tmp_path):
    root, out, home = _archive_root(tmp_path), tmp_path / "out", tmp_path / "home"
    marker = "SPY261113C00727000"  # a recorded value standing in for a leaked key
    (home / ".config/trading-engine").mkdir(parents=True)
    (home / ".config/trading-engine/massive.key").write_text(marker + "\n")

    with pytest.raises(contracts.ContractError, match="known credential"):
        contracts.harvest(root, out, home=home)
