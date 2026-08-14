#!/usr/bin/env python3
"""Resumable v12 waypoint reanalysis worker."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JOB = Path("/private/tmp/travel-globe-waypoint-reanalysis-7d-v12")
OUT = ROOT / "AviationDB/data/releases/private/observed-routes/adsblol/global-network-7d-025-repaired-2026-08-01-v12"
V11 = ROOT / "AviationDB/data/releases/private/observed-routes/adsblol/global-network-7d-025-repaired-2026-08-01-v11"
LONG = JOB / "long-legs"
STATUS = JOB / "status.json"
DONE = JOB / "done.json"
FAILED = JOB / "failed.json"
LOG = JOB / "pipeline.log"


def now() -> str:
    return datetime.now(UTC).isoformat()


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def step(name: str, command: list[str]) -> None:
    write(STATUS, {"state": "running", "phase": name, "updatedAt": now(), "jobDir": str(JOB), "outputRoot": str(OUT)})
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"=== {name} started {now()} ===\n")
        handle.flush()
        result = subprocess.run(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{name} failed with exit code {result.returncode}")


def main() -> int:
    if DONE.exists():
        return 0
    JOB.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    python = sys.executable
    try:
        if not (LONG / "manifest.json").exists() or json.loads((LONG / "status.json").read_text()).get("state") != "complete":
            step("long_leg_extraction", [python, "AviationDB/scripts/run_long_raw_legs_7d.py", "--job-dir", str(LONG), "--raw-root", str(ROOT / "AviationDB/data/raw/adsblol"), "--airport-index", str(ROOT / "shared/offline-packs/core-global/airports-index.json")])
        network = OUT / "global-corridor-network.json.gz"
        if not network.exists():
            step("waypoint_network", [python, "AviationDB/scripts/build_waypoint_network_7d.py", "--input-network", str(V11 / "global-corridor-network.json.gz"), "--long-legs-root", str(LONG), "--output-network", str(network), "--review-output", str(OUT / "waypoint-network-review.json")])
        step("connectivity_qa", [python, "AviationDB/scripts/validate_khh_global_network_7d.py", "--network", str(network), "--airports", str(ROOT / "shared/offline-packs/core-global/airports-index.json"), "--output", str(OUT / "khh-validation.json")])
        step("audit", [python, "AviationDB/scripts/audit_global_network_connectivity_7d.py", "--network", str(network), "--airports", str(ROOT / "shared/offline-packs/core-global/airports-index.json"), "--output-root", str(OUT / "connectivity"), "--status", str(JOB / "audit.status.json")])
        step("finalize", [python, "AviationDB/scripts/finalize_global_corridor_layers_7d.py", "--network", str(network), "--audit", str(OUT / "connectivity/global-connectivity-audit.json.gz"), "--raw-validation", str(OUT / "khh-validation.json"), "--output-root", str(OUT / "connectivity"), "--status", str(JOB / "finalize.status.json")])
        step("reference_qa", [python, "AviationDB/scripts/validate_reference_corridor_pairs_7d.py", "--network", str(network), "--audit", str(OUT / "connectivity/global-connectivity-audit.json.gz"), "--airports", str(ROOT / "shared/offline-packs/core-global/airports-index.json"), "--output", str(OUT / "reference-corridor-pairs-validation.json")])
        step("route_shape_qa", [python, "AviationDB/scripts/validate_reference_route_shapes_7d.py", "--network", str(network), "--audit", str(OUT / "connectivity/global-connectivity-audit.json.gz"), "--output", str(OUT / "reference-route-shape-qa.json")])
        write(DONE, {"state": "complete", "phase": "all_steps_complete", "updatedAt": now(), "outputRoot": str(OUT)})
        write(STATUS, {"state": "complete", "phase": "all_steps_complete", "updatedAt": now(), "jobDir": str(JOB), "outputRoot": str(OUT)})
        return 0
    except Exception as error:
        write(FAILED, {"state": "failed", "updatedAt": now(), "error": str(error), "jobDir": str(JOB)})
        write(STATUS, {"state": "failed", "updatedAt": now(), "jobDir": str(JOB), "error": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
