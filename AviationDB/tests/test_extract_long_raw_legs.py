from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from extract_long_raw_legs import _sample_points


class Point:
    def __init__(self, index: int) -> None:
        self.lat = float(index)
        self.lon = float(index) + 0.5
        self.elapsed_s = float(index * 60)
        self.altitude_ft = 30000
        self.track_deg = 90.0


def test_sample_points_preserves_endpoints_and_bounds_size() -> None:
    points = _sample_points([Point(index) for index in range(100)], 12)

    assert len(points) == 12
    assert points[0]["lat"] == 0.0
    assert points[-1]["lat"] == 99.0


def test_sample_points_keeps_short_leg_exactly() -> None:
    points = _sample_points([Point(index) for index in range(3)], 12)

    assert [item["lat"] for item in points] == [0.0, 1.0, 2.0]
