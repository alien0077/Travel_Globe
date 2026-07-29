from __future__ import annotations

import json

from aviationdb.observed_routes import Airport, AirportIndex, BuildOptions, build_observed_routes


def test_build_observed_route_from_readsb_trace(tmp_path):
    index = AirportIndex(
        [
            Airport("KHH", "RCKH", "Kaohsiung International Airport", "large_airport", 22.5771, 120.35),
            Airport("NRT", "RJAA", "Narita International Airport", "large_airport", 35.7647, 140.386),
        ]
    )
    trace = {
        "icao": "abc123",
        "timestamp": 1720000000,
        "trace": [
            [0, 22.58, 120.35, "ground", 0, None, 2, 0, {"flight": "FD234   "}],
            [600, 23.2, 120.0, 12000, 300, 20, 0, 0, {"flight": "FD234   "}],
            [1800, 24.5, 121.0, 30000, 450, 34, 0, 0, {"flight": "FD234   "}],
            [3600, 27.0, 124.0, 35000, 460, 38, 0, 0, {"flight": "FD234   "}],
            [5400, 30.5, 129.0, 35000, 460, 43, 0, 0, {"flight": "FD234   "}],
            [7200, 33.5, 135.5, 26000, 420, 50, 0, 0, {"flight": "FD234   "}],
            [8400, 35.1, 139.0, 9000, 260, 60, 0, 0, {"flight": "FD234   "}],
            [9000, 35.77, 140.39, "ground", 0, None, 0, 0, {"flight": "FD234   "}],
        ],
    }
    trace_path = tmp_path / "trace_full_abc123.json"
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    groups, stats = build_observed_routes(
        [trace_path],
        index,
        BuildOptions(min_points=4, max_airport_km=80, simplify_tolerance_km=20),
    )

    assert stats.traces_parsed == 1
    assert stats.samples_accepted == 1
    assert "KHH-NRT" in groups
    group = groups["KHH-NRT"]
    assert group.sample_count == 1
    assert group.best_variant().example_flights == {"FD234"}
    assert group.best_variant().representative_points[0] == (22.58, 120.35)
