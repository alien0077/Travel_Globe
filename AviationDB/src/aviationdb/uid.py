from __future__ import annotations

from hashlib import sha256


def normalize_ident(value: str) -> str:
    return " ".join(value.strip().upper().split())


def stable_uid(prefix: str, *parts: object) -> str:
    payload = "|".join("" if part is None else str(part) for part in parts)
    digest = sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def point_uid(
    ident: str,
    latitude: float,
    longitude: float,
    fir: str | None,
    point_type: str,
    source_id: str | None = None,
) -> str:
    return stable_uid(
        "pt",
        normalize_ident(ident),
        f"{latitude:.6f}",
        f"{longitude:.6f}",
        fir or "",
        point_type,
        source_id or "",
    )


def airway_uid(designator: str, source_id: str, fir: str | None = None) -> str:
    return stable_uid("awy", normalize_ident(designator), source_id, fir or "")


def segment_uid(airway_id: str, sequence: int, from_uid: str, to_uid: str) -> str:
    return stable_uid("seg", airway_id, sequence, from_uid, to_uid)
