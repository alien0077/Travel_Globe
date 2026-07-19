from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_jsonish_config(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be an object: {path}")
    return data


def source_config(config_path: Path | None = None) -> dict[str, Any]:
    path = config_path or PROJECT_ROOT / "config" / "sources.yaml"
    return load_jsonish_config(path)


def countries_config() -> dict[str, Any]:
    return load_jsonish_config(PROJECT_ROOT / "config" / "countries.yaml")


def validation_config() -> dict[str, Any]:
    return load_jsonish_config(PROJECT_ROOT / "config" / "validation.yaml")


def resolve_project_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate
