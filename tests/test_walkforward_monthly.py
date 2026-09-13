"""farm/walkforward/monthly.py against hand-computed values and a synthetic fixture."""
import json
import math
from datetime import date

import numpy as np
import pytest

from farm.walkforward import monthly as wm
from farm.walkforward.controls import declaration


# ------------------------------------------------------------ series ------ #
def test_month_end_points_keeps_last_row_per_month():
    ds = [date(2016, 8, 26), date(2016, 8, 31), date(2016, 9, 15), date(2016, 9, 30)]
    eq = [100.0, 101.0, 90.0, 110.0]
    assert wm.month_end_points(ds, eq) == [["2016-08", 101.0], ["2016-09", 110.0]]


def test_monthly_returns_labels_later_month():
    pts = [["2016-08", 100.0], ["2016-09", 110.0], ["2016-10", 99.0]]
    rets = wm.monthly_returns(pts)
    assert [m for m, _ in rets] == ["2016-09", "2016-10"]
    assert rets[0][1] == pytest.approx(0.10)
    assert rets[1][1] == pytest.approx(-0.10)


# ------------------------------------------------------------ bootstrap --- #
class _ScriptedRng:
    """Hands back pre-decided draws so the index path can be checked by hand."""
    def __init__(self, starts, uniforms):
        self._s, self._u = np.asarray(starts), np.asarray(uniforms, dtype=float)

    def integers(self, lo, hi, size):
        return self._s.reshape(size)

    def random(self, size):
        return self._u.reshape(size)


def test_stationary_bootstrap_indices_hand_path():
    # n=5, p=1/2. cont = u >= 0.5 -> [T, T, F, T, T]; position 0 is always a start.
    # idx: start 2 -> continue 3 -> new start 4 (u=0.1) -> continue 0 (wrap) -> continue 1
    rng = _ScriptedRng(starts=[2, 0, 4, 1, 3], uniforms=[0.9, 0.9, 0.1, 0.9, 0.9])
    idx = wm.stationary_bootstrap_indices(5, 1, mean_block=2, rng=rng)
    assert idx.tolist() == [[2, 3, 4, 0, 1]]


def test_stationary_bootstrap_block_one_is_iid():
    rng = _ScriptedRng(starts=[4, 3, 2, 1, 0], uniforms=[0.99] * 5)
    idx = wm.stationary_bootstrap_indices(5, 1, mean_block=1, rng=rng)
    assert idx.tolist() == [[4, 3, 2, 1, 0]]     # never continues a block


def test_block_bootstrap_ci_constant_series_is_degenerate():
    ci = wm.block_bootstrap_ci([0.01] * 30, stat="mean", n_boot=200)
    assert ci["lo"] == pytest.approx(0.01) and ci["hi"] == pytest.approx(0.01)
    assert ci["contains_zero"] is False and ci["mean_block"] == wm.MEAN_BLOCK_MONTHS


def test_block_bootstrap_ci_seeded_and_centred():
    rng = np.random.default_rng(7)
    x = rng.normal(0.005, 0.03, size=120)
    a = wm.block_bootstrap_ci(x, stat="mean", n_boot=2000, seed=1)
    b = wm.block_bootstrap_ci(x, stat="mean", n_boot=2000, seed=1)
    assert a == b                                   # deterministic in the seed
    assert a["lo"] < x.mean() < a["hi"]
    assert a["hi"] - a["lo"] > 0
    assert wm.block_bootstrap_ci([1.0, 2.0], stat="mean") is None   # below MIN_BOOTSTRAP_N
    with pytest.raises(ValueError):
        wm.block_bootstrap_ci(x, stat="max")


# ------------------------------------------------------------ Newey-West -- #
def test_newey_west_t_hand_values():
    # x = 1..5: mean 3, d = [-2,-1,0,1,2]; g0 = 10/5 = 2; g1 = 4/5; g2 = -1/5.
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    nw0 = wm.newey_west_t(x, lag=0)
    assert nw0["t"] == pytest.approx(3.0 / math.sqrt(2.0 / 5.0))          # 4.7434
    nw2 = wm.newey_west_t(x, lag=2)
    lrv = 2.0 + 2.0 * ((2 / 3) * 0.8 + (1 / 3) * (-0.2))                  # 2.9333
    assert nw2["se"] == pytest.approx(math.sqrt(lrv / 5))
    assert nw2["t"] == pytest.approx(3.0 / math.sqrt(lrv / 5))            # 3.9168
    assert nw2["lag"] == 2


def test_newey_west_t_positive_autocorrelation_widens_se():
    x = np.repeat([0.02, -0.01], 30)                       # long runs -> autocorrelated
    assert wm.newey_west_t(x, lag=3)["se"] > wm.newey_west_t(x, lag=0)["se"]
    assert math.isnan(wm.newey_west_t([1.0, 2.0])["t"])


# ------------------------------------------------------------ verdict ----- #
def test_verdict_rule():
    base = {"n_months": 60, "median_ci": {"lo": 0.001, "hi": 0.01, "contains_zero": False},
            "nw": {"t": 2.0}}
    assert wm.verdict(base) == "BEATS"
    assert wm.verdict({**base, "nw": {"t": 1.0}}) == "INDISTINGUISHABLE"
    assert wm.verdict({**base, "median_ci": {"lo": -0.01, "hi": -0.001, "contains_zero": False},
                       "nw": {"t": -2.5}}) == "TRAILS"
    assert wm.verdict({**base, "n_months": 12}) == "NO-DATA"


def test_control_and_insample_rules():
    for cid, expected in (
        ("template_top5", "ew_benchmark"),
        ("dual_momentum", "spy_benchmark"),
        ("sector_momentum", "spy_benchmark"),
        ("multi_asset_trend", "spy_benchmark"),
        ("xs_momentum_12_1", "ew_benchmark"),
        ("ew_benchmark", None),
    ):
        assert wm.control_of({"config_id": cid, "comparison": declaration(cid)}) == expected
    assert wm.insample_folds({"config_id": "template_top5"}) == {10}        # July cohort
    assert wm.insample_folds({"config_id": "ew_voltarget"}) == set()        # August cohort
    assert wm.insample_folds({"config_id": "x", "registered": "2026-07-30"}) == {10}


def test_load_results_retains_only_flagged_retired_evidence(tmp_path):
    protocol = {"anchor": "2026-09-04", "train_months": 24,
                "validate_months": 12, "step_months": 12, "n_folds": 10}
    for cid in ("spy_benchmark", "multi_asset_trend", "news_gated_momo"):
        payload = {"config_id": cid, "protocol": protocol, "folds": [],
                   "fill_model": "v3", "universe_policy": "all"}
        (tmp_path / f"{cid}.json").write_text(json.dumps(payload))
    assert set(wm.load_results(tmp_path)) == {"spy_benchmark", "multi_asset_trend"}


def test_load_results_never_mixes_source_trees_but_keeps_legacy_retirement(tmp_path):
    protocol = {"anchor": "2026-09-04", "train_months": 24,
                "validate_months": 12, "step_months": 12, "n_folds": 10}
    rows = {
        "spy_benchmark": "tree-a",
        "dual_momentum": "tree-a",
        "ew_benchmark": "tree-b",
        "sector_momentum": None,
        "multi_asset_trend": None,
    }
    for cid, source in rows.items():
        payload = {"config_id": cid, "protocol": protocol, "folds": [],
                   "fill_model": "v3", "universe_policy": "all"}
        if source:
            payload["source_sha256"] = source
        (tmp_path / f"{cid}.json").write_text(json.dumps(payload))
    assert set(wm.load_results(tmp_path)) == {
        "spy_benchmark", "dual_momentum", "multi_asset_trend",
    }


# ------------------------------------------------------------ fixture ----- #
def _fixture(cid, drift, seed, registered, n_folds=10):
    """Synthetic walk-forward result with a validate_monthly_equity per fold."""
    rng = np.random.default_rng(seed)
    folds, proto = [], []
    for k in range(1, n_folds + 1):
        y = 2015 + k
        split, end = f"{y}-08-28", f"{y + 1}-08-28"
        eq, pts = 100.0, [[f"{y}-08", 100.0]]
        for m in range(1, 13):
            yy, mm = (y, 8 + m) if 8 + m <= 12 else (y + 1, 8 + m - 12)
            eq *= 1.0 + drift + rng.normal(0, 0.02)
            pts.append([f"{yy}-{mm:02d}", eq])
        f = {"index": k, "train_start": f"{y - 2}-08-28", "split_date": split,
             "validate_end": end}
        proto.append(dict(f))
        folds.append({**f, "status": "ok", "validate_monthly_equity": pts})
    return {"config_id": cid, "name": cid, "strategy": cid, "registered": registered,
            "fill_model": "v3", "source_sha256": "same-source",
            "universe_policy": "all", "initial_cash": 39_000.0,
            "execution_profile": {"id": "baseline_v1"},
            "data_snapshot": {"sha256": "same-data"},
            "comparison": declaration(cid),
            "protocol": {"folds": proto, "n_folds": n_folds}, "folds": folds}


def test_paired_excess_drops_insample_fold_and_pairs_months():
    book = _fixture("template_top5", 0.02, 1, "2026-07-17")
    ctrl = _fixture("ew_benchmark", 0.0, 2, "2026-07-17")
    rows = wm.paired_excess(book, ctrl, exclude=wm.insample_folds(book))
    assert len(rows) == 9 * 12
    assert all(r["fold"] != 10 for r in rows)
    assert rows[0]["month"] == "2016-09"
    assert rows[0]["excess"] == pytest.approx(rows[0]["book"] - rows[0]["control"])
    kept = wm.paired_excess(book, ctrl, exclude=set())
    assert len(kept) == 120


def test_build_and_write_report_on_synthetic_fixture(tmp_path, monkeypatch):
    results = {
        "ew_benchmark": _fixture("ew_benchmark", 0.0, 2, "2026-07-17"),
        "spy_benchmark": _fixture("spy_benchmark", 0.0, 3, "2026-07-17"),
        "template_top5": _fixture("template_top5", 0.03, 1, "2026-07-17"),   # clear winner
        "turtle_breakout": _fixture("turtle_breakout", -0.03, 4, "2026-07-28"),  # clear loser
        "dual_momentum": _fixture("dual_momentum", 0.0, 5, "2026-07-17"),    # noise
        "ew_voltarget": _fixture("ew_voltarget", 0.0, 6, "2026-08-18"),      # keeps fold 10
    }
    rows = {r["config_id"]: r for r in wm.build(results)}
    assert rows["template_top5"]["verdict"] == "BEATS"
    assert rows["turtle_breakout"]["verdict"] == "TRAILS"
    assert rows["dual_momentum"]["control"] == "spy_benchmark"
    assert rows["dual_momentum"]["verdict"] == "INDISTINGUISHABLE"
    assert rows["ew_benchmark"]["verdict"] == "reference"
    assert rows["template_top5"]["n_months"] == 108 and rows["ew_voltarget"]["n_months"] == 120
    assert rows["template_top5"]["beat_rate"] > 0.5 > rows["turtle_breakout"]["beat_rate"]

    rd = tmp_path / "results"
    rd.mkdir()
    for cid, r in results.items():
        (rd / f"{cid}.json").write_text(json.dumps(r))
    readme = tmp_path / "README.md"
    readme.write_text("| [template_top5](template_top5.md) | PASS | x |\n"
                      "| [turtle_breakout](turtle_breakout.md) | REVIEW | x |\n")
    atomic_paths = []
    real_atomic_write = wm.resources.write_text_atomic

    def recording_atomic_write(path, text):
        atomic_paths.append(path)
        real_atomic_write(path, text)

    monkeypatch.setattr(wm.resources, "write_text_atomic", recording_atomic_write)
    md, js = wm.write_report(results_dir=rd, out_dir=tmp_path, bt_dir=tmp_path / "none",
                             stamp="2099-01-01", readme=readme)
    text = md.read_text()
    assert "| template_top5 | ew_benchmark | 108 | 10 |" in text
    assert "| template_top5 | PASS | BEATS | no |" in text
    payload = json.loads(js.read_text())
    assert payload["fold_level_verdicts"] == {"template_top5": "PASS", "turtle_breakout": "REVIEW"}
    assert payload["proxy"] == []                     # no backtests dir -> empty proxy
    assert atomic_paths == [md, js]
    assert list(tmp_path.glob("monthly-2099-01-01.*.tmp")) == []


def test_fold_level_verdicts_accepts_current_and_legacy_shapes(tmp_path):
    p = tmp_path / "README.md"
    p.write_text(
        "| [sector_momentum](sector_momentum.md) | `fixed_etf_history` | "
        "spy_benchmark | WATCH | **INDISTINGUISHABLE** | 9 |\n"
        "| [multi_asset_trend](multi_asset_trend.md) | spy_benchmark | WATCH | x |\n"
        "| [template_top5](template_top5.md) | PASS | x |\n"
        "| [old_book](old_book.md) | `legacy` | ew_benchmark | RETIRED (REVIEW) | x |\n"
    )
    assert wm.fold_level_verdicts(p) == {
        "sector_momentum": "WATCH", "multi_asset_trend": "WATCH",
        "template_top5": "PASS", "old_book": "REVIEW",
    }


def test_no_control_explanation_names_the_incompatibility():
    assert wm._why("no-benchmark", {
        "verdict": "NO-CONTROL",
        "control_reason": "different data-quality class",
    }) == "control comparison suppressed: different evidence class"


def test_load_results_never_mixes_protocol_anchors(tmp_path):
    old = _fixture("ew_benchmark", 0.0, 1, "2026-07-17")
    new = _fixture("spy_benchmark", 0.0, 2, "2026-07-17")
    old["protocol"].update({"anchor": "2026-08-28", "train_months": 24,
                              "validate_months": 12, "step_months": 12})
    new["protocol"].update({"anchor": "2026-09-04", "train_months": 24,
                              "validate_months": 12, "step_months": 12})
    (tmp_path / "old.json").write_text(json.dumps(old))
    (tmp_path / "new.json").write_text(json.dumps(new))
    assert set(wm.load_results(tmp_path)) == {"spy_benchmark"}


def test_load_results_excludes_retired_artifacts(tmp_path):
    live = _fixture("spy_benchmark", 0.0, 1, "2026-07-17")
    retired = _fixture("news_gated_momo", 0.0, 2, "2026-08-03")
    for d in (live, retired):
        d["protocol"].update({"anchor": "2026-09-04", "train_months": 24,
                                "validate_months": 12, "step_months": 12})
    (tmp_path / "live.json").write_text(json.dumps(live))
    (tmp_path / "retired.json").write_text(json.dumps(retired))
    assert set(wm.load_results(tmp_path)) == {"spy_benchmark"}


def test_load_results_never_mixes_fill_models(tmp_path):
    old = _fixture("ew_benchmark", 0.0, 1, "2026-07-17")
    new = _fixture("spy_benchmark", 0.0, 2, "2026-07-17")
    for d in (old, new):
        d["protocol"].update({"anchor": "2026-09-04", "train_months": 24,
                                "validate_months": 12, "step_months": 12})
        d["universe_policy"] = "all"
    old["fill_model"], new["fill_model"] = "v2", "v3"
    (tmp_path / "old.json").write_text(json.dumps(old))
    (tmp_path / "new.json").write_text(json.dumps(new))
    assert set(wm.load_results(tmp_path)) == {"spy_benchmark"}


@pytest.mark.parametrize(
    ("field", "old_value", "new_value"),
    [
        ("initial_cash", 39_000.0, 100_000.0),
        ("execution_profile", {"id": "baseline_v1"}, {"id": "cost_2x_v1"}),
        (
            "execution_profile",
            {"id": "baseline_v1", "fixed_adverse_bps": 5.0},
            {"id": "baseline_v1", "fixed_adverse_bps": 25.0},
        ),
        ("data_snapshot", {"sha256": "before"}, {"sha256": "after"}),
        (
            "comparison",
            {"protocol": "control-v1", "control_id": "ew_benchmark"},
            {"protocol": "control-v2", "control_id": None},
        ),
    ],
)
def test_load_results_never_mixes_capital_cost_or_data_cohorts(
        tmp_path, field, old_value, new_value):
    old = _fixture("ew_benchmark", 0.0, 1, "2026-07-17")
    new = _fixture("spy_benchmark", 0.0, 2, "2026-07-17")
    for d in (old, new):
        d["protocol"].update({"anchor": "2026-09-04", "train_months": 24,
                              "validate_months": 12, "step_months": 12})
        d.update({"fill_model": "v4", "universe_policy": "all",
                  "source_sha256": "same-source", "initial_cash": 39_000.0,
                  "execution_profile": {"id": "baseline_v1"},
                  "data_snapshot": {"sha256": "same-data"}})
    old[field], new[field] = old_value, new_value
    (tmp_path / "old.json").write_text(json.dumps(old))
    (tmp_path / "new.json").write_text(json.dumps(new))
    assert len(wm.load_results(tmp_path)) == 1


def test_monthly_build_suppresses_cross_evidence_class_comparison():
    candidate = _fixture("template_top5", 0.03, 1, "2026-07-17")
    control = _fixture("ew_benchmark", 0.0, 2, "2026-07-17")
    candidate["data_quality_class"] = "static_fundamental_lookahead"
    control["data_quality_class"] = "current_universe_survivor_biased"

    row = next(r for r in wm.build({"template_top5": candidate,
                                    "ew_benchmark": control})
               if r["config_id"] == "template_top5")

    assert row["verdict"] == "NO-CONTROL"
    assert row["n_months"] == 0
    assert row["control_reason"] == "different data-quality class"


@pytest.mark.parametrize(
    ("field", "candidate_value", "control_value"),
    [
        ("source_sha256", "source-a", "source-b"),
        ("fill_model", "v4", "v3"),
        ("universe_policy", "all", "exclude-leveraged"),
        ("initial_cash", 39_000.0, 100_000.0),
        ("execution_profile", {"id": "baseline_v1"}, {"id": "cost_2x_v1"}),
        (
            "execution_profile",
            {"id": "baseline_v1", "fixed_adverse_bps": 5.0},
            {"id": "baseline_v1", "fixed_adverse_bps": 25.0},
        ),
        ("data_snapshot", {"sha256": "before"}, {"sha256": "after"}),
    ],
)
def test_monthly_build_suppresses_mixed_research_cohorts(
        field, candidate_value, control_value):
    candidate = _fixture("template_top5", 0.03, 1, "2026-07-17")
    control = _fixture("ew_benchmark", 0.0, 2, "2026-07-17")
    candidate[field], control[field] = candidate_value, control_value

    row = next(r for r in wm.build({"template_top5": candidate,
                                    "ew_benchmark": control})
               if r["config_id"] == "template_top5")

    assert row["verdict"] == "NO-CONTROL"
    assert row["n_months"] == 0
    assert row["control_reason"] == "different research cohort"


def test_proxy_results_cuts_continuous_series_into_folds(tmp_path):
    wf = {"ew_benchmark": _fixture("ew_benchmark", 0.0, 2, "2026-07-17")}
    months = [f"{y}-{m:02d}" for y in range(2015, 2019) for m in range(1, 13)]
    (tmp_path / "ew_benchmark__15y.json").write_text(json.dumps(
        {"monthly_equity": [[m, 100.0 + i] for i, m in enumerate(months)]}))
    px = wm.proxy_results(wf, tmp_path)["ew_benchmark"]
    f1 = px["folds"][0]
    assert f1["index"] == 1
    assert [m for m, _ in f1["validate_monthly_equity"]][:2] == ["2016-08", "2016-09"]
    assert f1["validate_monthly_equity"][-1][0] == "2017-08"
    assert len(f1["validate_monthly_equity"]) == 13                 # base + 12 months
    assert px["folds"][-1]["validate_end"] == "2019-08-28"           # 2018-12 truncates fold 3
    assert len(px["folds"]) == 3
