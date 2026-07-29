from __future__ import annotations

import importlib.util
from pathlib import Path


def load_fusion_builder():
    path = Path(__file__).resolve().parents[1] / "scripts" / "build_route_source_fusion.py"
    spec = importlib.util.spec_from_file_location("build_route_source_fusion", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fusion_builder = load_fusion_builder()
_airport_lookup = fusion_builder._airport_lookup
_ensure_all_airport_connectivity = fusion_builder._ensure_all_airport_connectivity
_merge_route_records = fusion_builder._merge_route_records
_observed_routes = fusion_builder._observed_routes
_static_route_graph_routes = fusion_builder._static_route_graph_routes
_suspicious_airports = fusion_builder._suspicious_airports


def test_static_route_without_observed_becomes_fallback():
    airports = {
        "airports": [
            {
                "iataCode": "KHH",
                "icaoCode": "RCKH",
                "name": "Kaohsiung International Airport",
                "countryCode": "TW",
                "type": "large_airport",
                "scheduledService": True,
            },
            {
                "iataCode": "NRT",
                "icaoCode": "RJAA",
                "name": "Narita International Airport",
                "countryCode": "JP",
                "type": "large_airport",
                "scheduledService": True,
            },
        ]
    }
    context = {
        "contexts": [
            {
                "iataCode": "KHH",
                "routeGraph": {
                    "airlines": ["FD", "CI"],
                    "destinations": [
                        {"code": "NRT", "count": 5, "aircraftTypes": ["321", "738"]},
                    ],
                },
            }
        ]
    }

    airport_lookup = _airport_lookup(airports)
    static_routes = _static_route_graph_routes(context, airport_lookup)
    records = _merge_route_records(static_routes, {}, fallback_min_score=20)

    khh_nrt = next(record for record in records if record["id"] == "KHH-NRT")
    assert khh_nrt["bestSource"] == "static_route_graph"
    assert khh_nrt["hasObservedAdsb"] is False
    assert khh_nrt["requiresFallbackShape"] is True
    assert [source["type"] for source in khh_nrt["sources"]] == [
        "static_route_graph",
        "airport_pair_fallback",
    ]


def test_observed_route_keeps_adsb_priority_over_static_fallback():
    observed_payload = {
        "routes": [
            {
                "originIata": "TPE",
                "destinationIata": "NRT",
                "sampleCount": 7,
                "variantCount": 2,
                "representative": {"points": [[25.0, 121.0], [35.7, 140.3]]},
            }
        ]
    }
    static_routes = {
        ("TPE", "NRT"): {
            "origin": "TPE",
            "destination": "NRT",
            "openFlightsCount": 10,
            "aircraftTypes": ["321"],
            "airlines": ["CI"],
        }
    }

    observed_routes = _observed_routes(observed_payload)
    records = _merge_route_records(static_routes, observed_routes, fallback_min_score=20)

    tpe_nrt = records[0]
    assert tpe_nrt["id"] == "TPE-NRT"
    assert tpe_nrt["bestSource"] == "observed_adsb"
    assert tpe_nrt["hasObservedAdsb"] is True
    assert tpe_nrt["requiresFallbackShape"] is False
    assert "airport_pair_fallback" not in {source["type"] for source in tpe_nrt["sources"]}


def test_suspicious_airport_flags_busy_static_graph_with_zero_observed_endpoints():
    airports = {
        "KHH": {
            "iataCode": "KHH",
            "icaoCode": "RCKH",
            "name": "Kaohsiung International Airport",
            "countryCode": "TW",
            "type": "large_airport",
        }
    }
    context = {
        "contexts": [
            {
                "iataCode": "KHH",
                "routeGraph": {
                    "outgoingRoutes": 65,
                    "incomingRoutes": 64,
                    "destinations": [{"code": "NRT"} for _ in range(37)],
                },
            }
        ]
    }

    suspicious = _suspicious_airports(airports, context, {}, min_score=10)

    assert suspicious[0]["iata"] == "KHH"
    assert suspicious[0]["severity"] == "critical"
    assert suspicious[0]["observedEndpointSamples"] == 0


def test_ensure_all_airport_connectivity_adds_low_confidence_pair_for_missing_airport():
    airports = {
        "KHH": {"iataCode": "KHH", "countryCode": "TW", "latitude": 22.5771, "longitude": 120.35},
        "TPE": {"iataCode": "TPE", "countryCode": "TW", "latitude": 25.0777, "longitude": 121.2328},
        "NRT": {"iataCode": "NRT", "countryCode": "JP", "latitude": 35.7647, "longitude": 140.386},
    }
    route_records = [
        {
            "id": "TPE-NRT",
            "originIata": "TPE",
            "destinationIata": "NRT",
            "bestSource": "observed_adsb",
            "routeScore": 20,
            "hasObservedAdsb": True,
            "requiresFallbackShape": False,
            "sources": [{"type": "observed_adsb", "confidence": 0.95}],
        }
    ]

    records, added = _ensure_all_airport_connectivity(airports, route_records)

    assert len(added) == 2
    khh_tpe = next(route for route in records if route["id"] == "KHH-TPE")
    assert khh_tpe["bestSource"] == "airport_connectivity_fallback"
    assert khh_tpe["hasObservedAdsb"] is False
    assert khh_tpe["requiresFallbackShape"] is True
    assert khh_tpe["sources"][0]["reason"] == "nearest_connected_airport_same_country"
