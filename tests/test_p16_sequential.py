import numpy as np
import pytest

from farm.p16_sequential import by_session_offset, mixture_test


def test_zero_and_one_observation_have_known_mixture_wealth():
    zero = mixture_test([0] * 100, mixing_variance=1.0)
    assert zero["log_e_value"] == pytest.approx(0, abs=1e-14)
    # Nearly uniform prior: average of the midpoint bets on [0,.5] is exactly .25.
    one = mixture_test([2], mixing_variance=1e100)
    assert np.exp(one["log_e_value"]) == pytest.approx(1.5)
    negative = mixture_test([-2], mixing_variance=1e100)
    assert np.exp(negative["log_e_value"]) == pytest.approx(0.5)
    assert negative["log_anytime_p_bound"] == 0 and not negative["rejected"]


def test_wrong_direction_cannot_pass_and_crossings_are_retained():
    assert not mixture_test([-0.5] * 200, mixing_variance=1)["rejected"]
    passed = mixture_test([0.5] * 100, mixing_variance=1)
    assert passed["rejected"]
    reversed_later = mixture_test([0.5] * 100 + [-2] * 200, mixing_variance=1)
    assert reversed_later["rejected"]
    assert reversed_later["first_crossing_index"] == passed["first_crossing_index"]
    assert reversed_later["max_log_e_value"] == pytest.approx(passed["max_log_e_value"])


def test_unavailable_decisions_and_pending_labels_do_not_move_offsets():
    rows = [{"session_index": day, "status": "scored", "delta_ic": 0.5} for day in range(31)]
    rows[5]["status"] = "decision_unavailable"
    rows[10]["status"] = "pending_label"
    report = by_session_offset(rows, mixing_variance=1)
    assert report["primary"]["consumed_session_indices"] == [0]
    assert report["primary"]["skipped_decision_indices"] == [5]
    assert report["primary"]["blocked_at"] == {"session_index": 10, "reason": "pending_label"}
    assert report["robustness"][0]["consumed_session_indices"] == [1, 6, 11, 16, 21, 26]
    rows[10]["status"] = "scored"
    resolved = by_session_offset(rows, mixing_variance=1)
    assert resolved["primary"]["consumed_session_indices"] == [0, 10, 15, 20, 25, 30]
    assert not resolved["robustness_is_gating"]
    missing = by_session_offset([row for row in rows if row["session_index"] != 5], mixing_variance=1)
    assert missing["primary"]["blocked_at"] == {"session_index": 5, "reason": "missing_session_record"}


def test_bounded_null_simulation_counts_any_crossing_not_just_final_value():
    # The proof is the conditional-mean supermartingale argument; this seeded
    # simulation checks the implementation with the extremal zero-mean null.
    rng = np.random.default_rng(162026)
    bets = (np.arange(64) + 0.5) / 128
    log_prior = -bets * bets / 2
    log_prior -= np.log(np.exp(log_prior).sum())
    shocks = rng.choice([-2.0, 2.0], size=(5000, 200))
    # An independent binomial sufficient-statistic calculation gives each
    # path's wealth from its win/loss counts, without iterative wealth updates.
    hits = np.zeros(len(shocks), dtype=bool)
    wins = np.zeros(len(shocks))
    for count, column in enumerate(shocks.T, 1):
        wins += column > 0
        components = (wins[:, None] * np.log1p(2 * bets)
                      + (count - wins[:, None]) * np.log1p(-2 * bets))
        terms = components + log_prior
        maximum = terms.max(axis=1)
        log_e = maximum + np.log(np.exp(terms - maximum[:, None]).sum(axis=1))
        hits |= log_e >= np.log(20)
    assert hits.mean() < 0.05
    for index in range(25):
        assert mixture_test(shocks[index], mixing_variance=1)["rejected"] == bool(hits[index])


def test_invalid_bounds_and_prior_are_rejected():
    with pytest.raises(ValueError, match="inside"):
        mixture_test([2.01], mixing_variance=1)
    with pytest.raises(ValueError, match="positive"):
        mixture_test([0], mixing_variance=0)
    with pytest.raises(ValueError, match="unique"):
        by_session_offset([{"session_index": 0}, {"session_index": 0}], mixing_variance=1)


def test_tiny_frozen_prior_does_not_produce_nan_evidence():
    result = mixture_test([0, 0, 0], mixing_variance=1e-320)
    assert result["log_e_value"] == pytest.approx(0)
    assert result["rejected"] is False
