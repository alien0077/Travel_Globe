from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_long_leg_supplemental_graph import _sampled_edges, _walk_cells


def test_walk_cells_is_adjacent() -> None:
    cells = _walk_cells((10, 20), (13, 24))

    assert cells[0] == (10, 20)
    assert cells[-1] == (13, 24)
    assert all(
        max(abs(right[0] - left[0]), abs(right[1] - left[1])) <= 1
        for left, right in zip(cells, cells[1:], strict=False)
    )


def test_sampled_segment_over_local_limit_is_not_filled() -> None:
    stats = {}
    points = [{"lat": 20.0, "lon": 120.0}, {"lat": 20.0, "lon": 123.0}]

    assert _sampled_edges(points, stats) == set()
    assert stats["sampledGapsOverLimit"] == 1


def test_sampled_local_segment_creates_directed_edges() -> None:
    stats = {}
    points = [{"lat": 20.0, "lon": 120.0}, {"lat": 20.0, "lon": 120.5}]

    edges = _sampled_edges(points, stats)

    assert edges
    assert all(edge[0] == edge[2] for edge in edges)
    assert all(edge[1] < edge[3] for edge in edges)
