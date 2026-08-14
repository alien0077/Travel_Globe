from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_global_corridor_bridges import Terminal, _grid_key, build_relay_components, find_bridge_candidates


def terminal(
    chain_id: str,
    side: str,
    point: tuple[float, float],
    *,
    component: str,
    heading: float,
    dates: set[str] | None = None,
) -> Terminal:
    return Terminal(
        chain_id=chain_id,
        side=side,
        component_id=component,
        point=point,
        heading_deg=heading,
        dates=frozenset(dates or {"2026-08-01", "2026-08-02"}),
        support_days=2,
        support_legs=5,
        aircraft_examples=("a1", "a2"),
        region_tags=("Asia",),
        edge_key=f"edge-{chain_id}-{side}",
    )


def test_local_multiday_relay_is_inferred_not_observed() -> None:
    source = terminal("a", "end", (20.0, 120.0), component="c1", heading=90)
    target = terminal("b", "start", (20.0, 121.0), component="c2", heading=90)

    candidates = find_bridge_candidates(
        [source, target],
        {_grid_key(target.point): [target]},
        max_bridge_km=150,
        max_turn_deg=15,
        min_shared_dates=2,
        min_terminal_legs=3,
        min_terminal_aircraft=2,
    )

    assert candidates
    assert candidates[0]["status"] == "corridor_bridge_inferred"
    assert candidates[0]["reason"] == "multiday_directionally_compatible_local_relay"


def test_long_gap_is_not_filled() -> None:
    source = terminal("a", "end", (20.0, 120.0), component="c1", heading=90)
    target = terminal("b", "start", (20.0, 125.0), component="c2", heading=90)

    candidates = find_bridge_candidates(
        [source, target],
        {(0, 0): [target]},
        max_bridge_km=150,
        max_turn_deg=15,
        min_shared_dates=2,
        min_terminal_legs=3,
        min_terminal_aircraft=2,
    )

    assert candidates == []


def test_relay_component_keeps_bridge_separate_from_observed_status() -> None:
    chains = [
        {"chainId": "a", "componentId": "c1", "dates": ["2026-08-01"], "regionTags": ["Asia"]},
        {"chainId": "b", "componentId": "c2", "dates": ["2026-08-02"], "regionTags": ["Europe"]},
    ]
    bridges = [{"bridgeId": "bridge-1", "fromChain": "a", "toChain": "b"}]

    components = build_relay_components(chains, bridges)

    assert len(components) == 1
    assert components[0]["status"] == "corridor_relay_candidate"
    assert components[0]["observedCrossRegion"] is True
    assert components[0]["bridgeCrossRegion"] is False
