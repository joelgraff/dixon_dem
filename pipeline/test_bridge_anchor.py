"""A road that ends at a composed bridge meets the deck's height there (build_heightmap.py)."""
import numpy as np

import build_heightmap as bh


def test_the_profile_reaches_the_deck_at_the_end_and_returns_to_its_own():
    dists = np.linspace(0.0, 100.0, 51)
    ground = np.full_like(dists, 6.0)
    out = bh.anchor_profile(dists, ground, 100.0, {"start": 8.0, "end": None})
    assert abs(out[0] - 8.0) < 1e-9
    assert np.all(out[dists >= bh.BRIDGE_ANCHOR_BLEND_M] == 6.0)
    assert np.all(np.diff(out[dists <= bh.BRIDGE_ANCHOR_BLEND_M]) <= 1e-9)   # falls smoothly back


def test_either_end_of_a_road_can_meet_a_bridge():
    dists = np.linspace(0.0, 100.0, 51)
    ground = np.full_like(dists, 5.0)
    out = bh.anchor_profile(dists, ground, 100.0, {"start": 7.0, "end": 9.0})
    assert abs(out[0] - 7.0) < 1e-9 and abs(out[-1] - 9.0) < 1e-9
    assert abs(out[25] - 5.0) < 0.2 or out[25] > 5.0   # the middle is nearly untouched
    assert out[25] < 5.0 + 0.1


def test_a_short_road_is_pulled_by_both_ends():
    dists = np.linspace(0.0, 30.0, 16)
    out = bh.anchor_profile(dists, np.full_like(dists, 4.0), 30.0, {"start": 6.0, "end": 6.0})
    assert out.min() >= 4.0 and out[0] == 6.0 and out[-1] == 6.0


def test_no_ends_no_change():
    dists = np.linspace(0.0, 50.0, 26)
    base = np.linspace(3.0, 4.0, 26)
    assert np.array_equal(bh.anchor_profile(dists, base, 50.0, {"start": None, "end": None}), base)


if __name__ == "__main__":
    test_the_profile_reaches_the_deck_at_the_end_and_returns_to_its_own()
    test_either_end_of_a_road_can_meet_a_bridge()
    test_a_short_road_is_pulled_by_both_ends()
    test_no_ends_no_change()
    print("bridge anchor ok")
