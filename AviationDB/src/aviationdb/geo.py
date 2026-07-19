from __future__ import annotations

import re
from math import asin, atan2, cos, radians, sin, sqrt

EARTH_RADIUS_NM = 3440.065


class CoordinateParseError(ValueError):
    pass


def parse_coordinate_pair(text: str) -> tuple[float, float]:
    tokens = re.findall(r"\d+(?:\.\d+)?\s*[NSEW]|[NS]\s*\d+(?:\.\d+)?|[EW]\s*\d+(?:\.\d+)?", text.upper())
    if len(tokens) >= 2:
        lat = parse_coordinate(tokens[0])
        lon = parse_coordinate(tokens[1])
        return lat, lon

    dms = re.findall(
        r"(\d{1,3})[°\s]+(\d{1,2})['’′\s]+(\d{1,2}(?:\.\d+)?)[\"'’′″]{0,2}\s*([NSEW])",
        text.upper(),
    )
    if len(dms) >= 2:
        return _dms_to_decimal(*dms[0]), _dms_to_decimal(*dms[1])

    raise CoordinateParseError(f"Unable to parse coordinate pair: {text}")


def parse_coordinate(text: str) -> float:
    value = text.strip().upper().replace(" ", "")
    match = re.fullmatch(r"([NSEW])?(\d+(?:\.\d+)?)([NSEW])?", value)
    if not match:
        raise CoordinateParseError(f"Unable to parse coordinate: {text}")
    hemisphere = match.group(1) or match.group(3)
    if hemisphere is None:
        raise CoordinateParseError(f"Missing hemisphere in coordinate: {text}")
    digits = match.group(2)
    is_lon = hemisphere in {"E", "W"}
    degree_digits = 3 if is_lon else 2
    if len(digits.split(".")[0]) < degree_digits + 4:
        raise CoordinateParseError(f"Coordinate is too short: {text}")
    degrees = int(digits[:degree_digits])
    minutes = int(digits[degree_digits : degree_digits + 2])
    seconds = float(digits[degree_digits + 2 :])
    decimal = degrees + minutes / 60 + seconds / 3600
    if hemisphere in {"S", "W"}:
        decimal *= -1
    _validate_coordinate(decimal, is_lon)
    return decimal


def _dms_to_decimal(degrees: str, minutes: str, seconds: str, hemisphere: str) -> float:
    is_lon = hemisphere in {"E", "W"}
    decimal = int(degrees) + int(minutes) / 60 + float(seconds) / 3600
    if hemisphere in {"S", "W"}:
        decimal *= -1
    _validate_coordinate(decimal, is_lon)
    return decimal


def _validate_coordinate(value: float, is_lon: bool) -> None:
    lower, upper = (-180.0, 180.0) if is_lon else (-90.0, 90.0)
    if not lower <= value <= upper:
        raise CoordinateParseError(f"Coordinate out of range: {value}")


def haversine_nm(left: tuple[float, float], right: tuple[float, float]) -> float:
    lat1, lon1 = map(radians, left)
    lat2, lon2 = map(radians, right)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_NM * asin(sqrt(a))


def initial_bearing_degrees(left: tuple[float, float], right: tuple[float, float]) -> float:
    lat1, lon1 = map(radians, left)
    lat2, lon2 = map(radians, right)
    dlon = lon2 - lon1
    y = sin(dlon) * cos(lat2)
    x = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dlon)
    return (atan2(y, x) * 180 / 3.141592653589793 + 360) % 360
