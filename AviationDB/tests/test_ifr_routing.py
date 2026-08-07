from __future__ import annotations

from aviationdb.ifr_routing import select_ifr_route_shape
from aviationdb.ifr_routing import dedupe_candidates


def _airport(iata: str, icao: str, lat: float, lon: float) -> dict:
    return {"iataCode": iata, "icaoCode": icao, "latitude": lat, "longitude": lon}


def _pack(direction: str = "both") -> dict:
    return {
        "schemaVersion": 2,
        "region": "test",
        "points": [
            ["DEP1", 0.2, 0.0, "SIGNIFICANT_POINT", "fixture"],
            ["MID1", 1.0, 0.0, "SIGNIFICANT_POINT", "fixture"],
            ["ARR1", 1.8, 0.0, "SIGNIFICANT_POINT", "fixture"],
        ],
        "airways": [["A1", "ATS", "fixture", direction, 0, 45000, "TEST"]],
        "segments": [
            [0, 1, 0, 48.0, direction, 0, 45000, "fixture", "TEST", 0.9],
            [1, 2, 0, 48.0, direction, 0, 45000, "fixture", "TEST", 0.9],
        ],
    }


def test_directed_ifr_route_validates_real_edges() -> None:
    result = select_ifr_route_shape(
        _pack("both"),
        _airport("AAA", "AAAA", 0.0, 0.0),
        _airport("BBB", "BBBB", 2.0, 0.0),
        route_id="AAAA-BBBB",
        pair_source={"exists": True},
        k=3,
    )

    assert result["routeUnavailable"] is False
    assert result["selected"]["method"] == "directed_airway_graph"
    assert result["selected"]["edgeValidation"] == {"valid": True, "invalidSegments": []}
    assert result["selected"]["points"][0]["ident"] == "AAA"
    assert result["selected"]["points"][-1]["ident"] == "BBB"
    assert [edge["airway"] for edge in result["selected"]["airways"]]


def test_unknown_direction_is_not_silently_treated_as_bidirectional() -> None:
    result = select_ifr_route_shape(
        _pack("unknown"),
        _airport("AAA", "AAAA", 0.0, 0.0),
        _airport("BBB", "BBBB", 2.0, 0.0),
        route_id="AAAA-BBBB",
        k=3,
    )

    assert result["routeUnavailable"] is True
    assert result["unavailableReason"] == "directed_airway_path_not_found"


def test_forward_edges_do_not_create_reverse_fake_route() -> None:
    result = select_ifr_route_shape(
        _pack("forward"),
        _airport("BBB", "BBBB", 2.0, 0.0),
        _airport("AAA", "AAAA", 0.0, 0.0),
        route_id="BBBB-AAAA",
        k=3,
    )

    assert result["routeUnavailable"] is True


def test_distance_limited_recovery_can_use_valid_directed_edges_after_scoring_rejects() -> None:
    result = select_ifr_route_shape(
        {
            "schemaVersion": 2,
            "region": "test",
            "points": [
                ["DEP1", 0.2, 0.0, "SIGNIFICANT_POINT", "fixture"],
                ["AWAY", -0.1, 0.0, "SIGNIFICANT_POINT", "fixture"],
                ["ARR1", 1.8, 0.0, "SIGNIFICANT_POINT", "fixture"],
            ],
            "airways": [["A1", "ATS", "fixture", "both", 0, 45000, "TEST"]],
            "segments": [
                [0, 1, 0, 18.0, "both", 0, 45000, "fixture", "TEST", 0.9],
                [1, 2, 0, 114.0, "both", 0, 45000, "fixture", "TEST", 0.9],
            ],
        },
        _airport("AAA", "AAAA", 0.0, 0.0),
        _airport("BBB", "BBBB", 2.0, 0.0),
        route_id="AAAA-BBBB",
        k=3,
    )

    assert result["routeUnavailable"] is False
    assert result["selected"]["provenance"]["recovery"] == "distance_limited_raw_directed_path"
    assert result["selected"]["metrics"]["detourRatio"] <= 1.65


def test_distance_limited_recovery_rejects_excessive_detours() -> None:
    result = select_ifr_route_shape(
        {
            "schemaVersion": 2,
            "region": "test",
            "points": [
                ["DEP1", 0.2, 0.0, "SIGNIFICANT_POINT", "fixture"],
                ["FAR1", -10.0, 0.0, "SIGNIFICANT_POINT", "fixture"],
                ["FAR2", -10.0, 2.0, "SIGNIFICANT_POINT", "fixture"],
                ["ARR1", 1.8, 0.0, "SIGNIFICANT_POINT", "fixture"],
            ],
            "airways": [["A1", "ATS", "fixture", "both", 0, 45000, "TEST"]],
            "segments": [
                [0, 1, 0, 612.0, "both", 0, 45000, "fixture", "TEST", 0.9],
                [1, 2, 0, 120.0, "both", 0, 45000, "fixture", "TEST", 0.9],
                [2, 3, 0, 712.0, "both", 0, 45000, "fixture", "TEST", 0.9],
            ],
        },
        _airport("AAA", "AAAA", 0.0, 0.0),
        _airport("BBB", "BBBB", 2.0, 0.0),
        route_id="AAAA-BBBB",
        k=3,
    )

    assert result["routeUnavailable"] is True


def test_candidate_deduplication_preserves_distinct_connectors() -> None:
    shared_path = [10, 11, 12, 13]
    candidates = [
        {
            "nodePath": shared_path,
            "provenance": {
                "originConnector": {"ident": "HCN"},
                "destinationConnector": {"ident": "TYE"},
            },
        },
        {
            "nodePath": [9, *shared_path],
            "provenance": {
                "originConnector": {"ident": "TNN"},
                "destinationConnector": {"ident": "TYE"},
            },
        },
    ]

    assert len(dedupe_candidates(candidates)) == 2
