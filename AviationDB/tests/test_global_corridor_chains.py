from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_global_corridor_chains import Edge, UnionFind, build_chains, chain_to_json, find_gap_candidates


def edge(key: str, start: tuple[int, int], end: tuple[int, int], days: int = 3) -> Edge:
    from build_global_corridor_chains import bearing_deg, cell_center

    return Edge(key, start, end, days, 10, ("2026-08-01",), bearing_deg(cell_center(start), cell_center(end)))


def test_build_chains_joins_shared_vertices_with_direction() -> None:
    edges = [
        edge("a", (100, 100), (100, 101)),
        edge("b", (100, 101), (100, 102)),
        edge("c", (100, 102), (101, 102)),
    ]

    chains = build_chains(edges, max_turn_deg=100)

    assert len(chains) == 1
    assert chains[0].edge_keys == ("a", "b", "c")
    assert len(chains[0].points) == 4
    assert chain_to_json(chains[0])["edgeKeys"] == ["a", "b", "c"]


def test_build_chains_does_not_cross_missing_vertex() -> None:
    edges = [edge("a", (100, 100), (100, 101)), edge("b", (100, 103), (100, 104))]

    chains = build_chains(edges, max_turn_deg=50)

    assert len(chains) == 2


def test_gap_candidate_is_separate_from_observed_chain() -> None:
    edges = [edge("a", (100, 100), (100, 101)), edge("b", (100, 105), (100, 106))]
    union_find = UnionFind()
    for item in edges:
        union_find.union(item.start, item.end)
    chains = build_chains(edges, max_turn_deg=50, union_find=union_find)

    gaps = find_gap_candidates(chains, union_find, max_gap_km=500, max_turn_deg=50)

    assert len(gaps) == 1
    assert gaps[0]["status"] == "unresolved_gap"
    assert gaps[0]["distanceKm"] > 0
