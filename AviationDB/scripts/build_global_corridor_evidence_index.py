#!/usr/bin/env python3
"""Write a reverse-searchable evidence index for the final provisional graph."""

from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Build global corridor edge/chain/bridge evidence index.")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--chains", type=Path, required=True)
    parser.add_argument("--bridges", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review-output", type=Path, required=True)
    args = parser.parse_args()

    chains = _read_gzip(args.chains).get("chains", [])
    bridges_payload = _read_gzip(args.bridges)
    bridges = bridges_payload.get("bridges", [])
    chain_refs = [
        {
            "chainId": item.get("chainId"),
            "componentId": item.get("componentId"),
            "edgeKeys": item.get("edgeKeys", []),
            "dates": item.get("dates", []),
            "regionTags": item.get("regionTags", []),
            "status": item.get("status"),
        }
        for item in chains
    ]
    edge_keys = sorted({str(key) for item in chain_refs for key in item["edgeKeys"]})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(args.db)
    has_supplemental_sources = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'supplemental_edge_sources'"
    ).fetchone() is not None
    with gzip.open(args.output, "wt", encoding="utf-8", compresslevel=6) as handle:
        handle.write('{"schemaVersion":1,"evidenceType":"raw_derived_global_corridor_evidence_index","generatedAt":')
        json.dump(datetime.now(UTC).isoformat(), handle)
        handle.write(',"source":')
        json.dump(
            {"database": str(args.db), "chains": str(args.chains), "bridges": str(args.bridges), "ifrExcluded": True},
            handle, ensure_ascii=False, separators=(",", ":"),
        )
        handle.write(',"summary":')
        json.dump(
            {"chainCount": len(chain_refs), "indexedEdgeCount": len(edge_keys), "bridgeCount": len(bridges)},
            handle, ensure_ascii=False, separators=(",", ":"),
        )
        handle.write(',"chains":')
        json.dump(chain_refs, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write(',"edges":[')
        first = True
        for batch in _batches(edge_keys, 800):
            placeholders = ",".join("?" for _ in batch)
            source_select = "s.source_type" if has_supplemental_sources else "NULL"
            source_join = "LEFT JOIN supplemental_edge_sources s ON s.edge_key = e.edge_key" if has_supplemental_sources else ""
            rows = connection.execute(
                f"""
                SELECT e.edge_key, e.from_lat, e.from_lon, e.to_lat, e.to_lon,
                       e.support_legs, e.aircraft_json, e.callsigns_json,
                       GROUP_CONCAT(d.date), {source_select}
                FROM edges e
                JOIN edge_dates d ON d.edge_key = e.edge_key
                {source_join}
                WHERE e.edge_key IN ({placeholders})
                GROUP BY e.edge_key
                """,
                batch,
            )
            for row in rows:
                if not first:
                    handle.write(",")
                first = False
                handle.write(json.dumps(_edge_payload(row), ensure_ascii=False, separators=(",", ":")))
        handle.write('],"bridges":')
        json.dump(bridges, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("}\n")
    connection.close()

    supported = [item for item in bridges if item.get("status") == "corridor_bridge_inferred"]
    candidates = [item for item in bridges if item.get("status") == "candidate_gap"]
    review = {
        "schemaVersion": 1,
        "evidenceType": "global_corridor_bridge_review",
        "generatedAt": datetime.now(UTC).isoformat(),
        "policy": {
            "supportedOnlyForFeederLookup": True,
            "candidateAndUnresolvedExcludedFromRuntime": True,
            "noLongStraightLineFill": True,
            "ifrExcluded": True,
        },
        "summary": {
            "supported": len(supported),
            "holdoutReady": sum(item.get("validationStatus") == "holdout_ready" for item in supported),
            "candidateGaps": len(candidates),
            "unresolvedGapReason": "local evidence or holdout threshold not satisfied",
        },
        "supported": supported,
        "candidateGaps": candidates,
    }
    args.review_output.parent.mkdir(parents=True, exist_ok=True)
    args.review_output.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(
        {"output": str(args.output), "reviewOutput": str(args.review_output), "summary": review["summary"]},
        ensure_ascii=False, indent=2,
    ))
    return 0


def _edge_payload(row: tuple[Any, ...]) -> dict[str, Any]:
    edge_key, from_lat, from_lon, to_lat, to_lon, support_legs, aircraft, callsigns, dates, source_type = row
    return {
        "edgeKey": str(edge_key),
        "from": {"latCell": int(from_lat), "lonCell": int(from_lon)},
        "to": {"latCell": int(to_lat), "lonCell": int(to_lon)},
        "supportLegs": int(support_legs),
        "supportDates": sorted({value for value in (dates or "").split(",") if value}),
        "aircraftExamples": json.loads(aircraft or "[]"),
        "callsignExamples": json.loads(callsigns or "[]"),
        "sourceType": source_type or "raw_derived_unbiased",
    }


def _batches(values: list[str], size: int):
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _read_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
