import json

from engine.lib import resources as rsc


def test_read_meta_missing_or_corrupt_is_empty(tmp_path):
    assert rsc.read_meta(tmp_path / "nope.json") == {}
    bad = tmp_path / "_meta.json"
    bad.write_text("{not json")
    assert rsc.read_meta(bad) == {}


def test_merge_meta_preserves_siblings(tmp_path):
    p = tmp_path / "_meta.json"
    p.write_text(json.dumps({"collect": {"rows": 1}, "intraday": {"ok": True}}))
    rsc.merge_meta(p, {"intraday": {"ok": False}})
    got = json.loads(p.read_text())
    assert got == {"collect": {"rows": 1}, "intraday": {"ok": False}}


def test_write_text_atomic_leaves_no_temp_files(tmp_path):
    p = tmp_path / "sub" / "_meta.json"
    rsc.write_text_atomic(p, "hello")
    assert p.read_text() == "hello"
    assert [f.name for f in p.parent.iterdir()] == ["_meta.json"]


def test_disk_warning_set_above_soft_cap(tmp_path):
    p = tmp_path / "_meta.json"
    p.write_text(json.dumps({"collect": 1}))
    rsc.update_disk_warning(p, 61.5, soft_gb=60.0)
    got = json.loads(p.read_text())
    assert got["collect"] == 1
    w = got["disk_warning"]
    assert w["store_gb"] == 61.5 and w["soft_cap_gb"] == 60.0
    assert "over the 60 GiB soft cap" in w["message"]


def test_disk_warning_cleared_at_or_below_cap(tmp_path):
    p = tmp_path / "_meta.json"
    rsc.update_disk_warning(p, 70.0, soft_gb=60.0)
    assert json.loads(p.read_text())["disk_warning"] is not None
    rsc.update_disk_warning(p, 60.0, soft_gb=60.0)          # boundary: not over
    assert json.loads(p.read_text())["disk_warning"] is None


def test_dir_size_gb(tmp_path):
    assert rsc.dir_size_gb(tmp_path / "missing") == 0.0
    (tmp_path / "a.bin").write_bytes(b"x" * (1024 ** 2))
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "b.bin").write_bytes(b"y" * (1024 ** 2))
    assert rsc.dir_size_gb(tmp_path) * 1024 == 2.0


def test_readings_never_block_on_unknown(monkeypatch):
    monkeypatch.setattr(rsc.os, "getloadavg", lambda: (_ for _ in ()).throw(OSError()))
    assert rsc.load_5min() == 0.0
    assert rsc.root_free_gb("/definitely/not/a/path") == float("inf")
