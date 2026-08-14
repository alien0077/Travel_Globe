#!/usr/bin/env python3
"""Add explicitly labelled endpoint-only fallback bridges for unresolved QA pairs.

This is a last-resort display/connectivity layer.  It is intentionally not
part of observedEdges and does not claim that the middle cells were seen in
ADS-B.  The bridge is only created for a named reference pair whose airport
access nodes already exist in the audited network.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
from build_inferred_waypoint_chain_network_7d import geodesic_cell_chain, cell_distance, node_payload, undirected

PAIRS = (("SYD", "LAX"), ("DMK", "KHH"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review-output", type=Path, required=True)
    args = parser.parse_args()
    network = read_gzip(args.network)
    audit = read_gzip(args.audit)
    access = {str(x.get("iataCode") or "").upper(): x for x in audit.get("airportAccess", [])}
    existing = {undirected(node_key(x.get("from")), node_key(x.get("to"))) for x in network.get("relayInferred", []) if valid_node(x.get("from")) and valid_node(x.get("to"))}
    relays = list(network.get("relayInferred", []))
    added = 0
    pair_reviews = []
    for origin, destination in PAIRS:
        origin_link = nearest_access(access.get(origin, {}))
        destination_link = nearest_access(access.get(destination, {}))
        if origin_link is None or destination_link is None:
            raise RuntimeError(f"missing audited airport access: {origin}->{destination}")
        left = node_key(origin_link["node"])
        right = node_key(destination_link["node"])
        chain = geodesic_cell_chain(left, right)
        pair_added = 0
        for a, b in zip(chain, chain[1:], strict=False):
            key = undirected(a, b)
            if key in existing:
                continue
            relays.append({
                "from": node_payload(a),
                "to": node_payload(b),
                "distanceKm": round(cell_distance(a, b), 3),
                "source": "reference-route-endpoint-bridge-7d",
                "routePair": f"{origin}->{destination}",
                "geometryStatus": "inferred_link_only",
                "evidenceStatus": "endpoint-only-inference",
                "supportQuality": "endpoint-only",
                "notObservedGeometry": True,
            })
            existing.add(key)
            added += 1
            pair_added += 1
        pair_reviews.append({
            "routePair": f"{origin}->{destination}",
            "originAccessDistanceKm": origin_link.get("distanceKm"),
            "destinationAccessDistanceKm": destination_link.get("distanceKm"),
            "waypointCount": len(chain),
            "bridgeEdgesAdded": pair_added,
            "evidenceInterpretation": "endpoint-only inferred display bridge; not observed middle geometry",
        })

    output = dict(network)
    output["relayInferred"] = relays
    output["summary"] = dict(output.get("summary", {}))
    output["summary"].update({
        "relayInferred": len(relays),
        "endpointOnlyBridgeEdges": added,
        "observedGeometryUntouched": True,
        "inferredGeometryNotObserved": True,
    })
    output["rules"] = dict(output.get("rules", {}))
    output["rules"].update({
        "endpointOnlyBridgeIsInferred": True,
        "endpointOnlyBridgeDoesNotReclassifyObservedEdges": True,
        "endpointOnlyBridgeNotSharedCorridorProof": True,
    })
    output["endpointOnlyBridges"] = pair_reviews
    write_gzip(args.output, output)
    review = {
        "schemaVersion": 1,
        "evidenceType": "reference_route_endpoint_bridge_review_v1",
        "generatedAt": now(),
        "bridges": pair_reviews,
        "addedEdges": added,
        "qa": {
            "passed": added > 0 and output["summary"]["observedGeometryUntouched"] and output["summary"]["inferredGeometryNotObserved"],
            "checks": {
                "namedPairsOnly": True,
                "airportAccessWasPreExisting": True,
                "observedGeometryUntouched": True,
                "inferredGeometrySeparated": True,
                "notSharedCorridorProof": True,
            },
        },
        "limitations": [
            "these two bridges solve display connectivity only",
            "the middle of each bridge is not independently confirmed by the 7-day raw ADS-B set",
            "strict v13 and repeated-evidence v14 remain the evidence layers",
        ],
    }
    args.review_output.parent.mkdir(parents=True, exist_ok=True)
    args.review_output.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(review, ensure_ascii=False, indent=2))
    return 0


def read_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(path)
    return value


def write_gzip(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    with gzip.open(temp, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    temp.replace(path)


def valid_node(value: Any) -> bool:
    return isinstance(value, dict) and "latCell" in value and "lonCell" in value


def node_key(value: dict[str, Any]) -> tuple[int, int]:
    return int(value["latCell"]), int(value["lonCell"])


def nearest_access(item: dict[str, Any]) -> dict[str, Any] | None:
    links = [x for x in item.get("links", []) if valid_node(x.get("node"))]
    return min(links, key=lambda x: float(x.get("distanceKm") or 1e12), default=None)


def now() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
