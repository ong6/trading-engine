import pytest

from server.sizing import size_position


def test_size_position_hand_values():
    out = size_position(39_000.0, 100.0, 95.0, 0.01)
    assert out == {"qty": 78, "risk_dollars": 390.0, "r_per_share": 5.0}


def test_size_position_floors_to_whole_shares():
    assert size_position(39_000.0, 100.0, 93.0)["qty"] == 55       # 390/7 = 55.71


def test_size_position_respects_risk_pct():
    assert size_position(100_000.0, 50.0, 45.0, 0.0025)["qty"] == 50


@pytest.mark.parametrize("entry,stop", [(100.0, 100.0), (95.0, 100.0)])
def test_size_position_rejects_non_long(entry, stop):
    with pytest.raises(ValueError):
        size_position(39_000.0, entry, stop)
