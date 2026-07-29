from __future__ import annotations

import importlib.util
from pathlib import Path


def load_exporter():
    path = Path(__file__).resolve().parents[1] / "scripts" / "export_route_fallback_pack.py"
    spec = importlib.util.spec_from_file_location("export_route_fallback_pack", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_route_fallback_pack = load_exporter().build_route_fallback_pack


def test_build_route_fallback_pack_keeps_provenance_counts():
    fusion = {
        "sourceRegistry": {
            "observed_adsb": {"defaultConfidence": 0.95, "offlineRedistribution": "private_pack_only"},
            "static_route_graph": {"defaultConfidence": 0.62, "offlineRedistribution": "allowed_with_odbl_provenance"},
        },
        "routes": [
            {
                "id": "KHH-NRT",
                "originIata": "KHH",
                "destinationIata": "NRT",
                "bestSource": "static_route_graph",
                "routeScore": 84,
                "hasObservedAdsb": False,
                "requiresFallbackShape": True,
                "sources": [
                    {
                        "type": "static_route_graph",
                        "openFlightsCount": 5,
                        "aircraftTypes": ["321", "738"],
                    },
                    {"type": "airport_pair_fallback"},
                ],
            },
            {
                "id": "TPE-NRT",
                "originIata": "TPE",
                "destinationIata": "NRT",
                "bestSource": "observed_adsb",
                "routeScore": 137,
                "hasObservedAdsb": True,
                "requiresFallbackShape": False,
                "sources": [
                    {"type": "observed_adsb", "sampleCount": 7, "variantCount": 2},
                ],
            },
        ],
    }
    suspicious = {
        "airports": [
            {
                "iata": "KHH",
                "icao": "RCKH",
                "countryCode": "TW",
                "airportType": "large_airport",
                "severity": "critical",
                "routeGraphScore": 203,
                "routeGraphDestinations": 37,
                "observedEndpointRoutes": 0,
                "observedEndpointSamples": 0,
            }
        ]
    }

    pack = build_route_fallback_pack(fusion, suspicious)

    assert pack["summary"] == {
        "routes": 2,
        "observedRoutes": 1,
        "fallbackRoutes": 1,
        "connectivityFallbackRoutes": 0,
        "suspiciousAirports": 1,
        "criticalSuspiciousAirports": 1,
    }
    assert pack["routes"][0]["id"] == "KHH-NRT"
    assert pack["routes"][0]["sourceTypes"] == ["static_route_graph", "airport_pair_fallback"]
    assert pack["routes"][1]["observedSampleCount"] == 7
    assert pack["suspiciousAirports"][0]["iata"] == "KHH"
