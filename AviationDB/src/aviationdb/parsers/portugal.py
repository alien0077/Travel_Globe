"""Portugal NAV AIS eAIP HTML Parser - canonical build integration."""
from __future__ import annotations

import re
from html.parser import HTMLParser

from aviationdb.geo import CoordinateParseError, haversine_nm, initial_bearing_degrees, parse_coordinate
from aviationdb.models import Airway, AirwaySegment, Issue, NavPoint
from aviationdb.parsers.taiwan import ParsedDataset
from aviationdb.uid import airway_uid, normalize_ident, point_uid, segment_uid

FIR = "LISBOA"
COUNTRY = "PT"
REGION = "europe"

_COORD_RE = re.compile(r"\d{6}(?:\.\d+)?[NS]\s*\d{7}(?:\.\d+)?[EW]", re.IGNORECASE)


def parse_portugal_eaip_documents(documents: dict[str, str], source_id: str) -> ParsedDataset:
    dataset = ParsedDataset()
    point_by_ident: dict[str, NavPoint] = {}

    for doc_id, html in documents.items():
        if doc_id == "enr_4_4":
            pts = _parse_enr44_points(html, source_id, dataset.issues)
            for pt in pts:
                point_by_ident.setdefault(pt.ident, pt)
                dataset.points.append(pt)
        elif doc_id in ("enr_3_1", "enr_3_3"):
            awys, segs = _parse_routes(html, source_id, point_by_ident, dataset.points, dataset.issues)
            dataset.airways.extend(awys)
            dataset.segments.extend(segs)

    return dataset


def _extract_tables(html: str) -> list[list[list[str]]]:
    class P(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.tables: list[list[list[str]]] = []
            self._t: list[list[str]] | None = None
            self._r: list[str] | None = None
            self._c: list[str] | None = None
            self._depth = 0

        def handle_starttag(self, tag: str, _attrs: object) -> None:
            if tag == "table":
                self._depth += 1
                if self._depth == 1:
                    self._t = []
            elif tag == "tr" and self._depth == 1 and self._t is not None:
                self._r = []
            elif tag in {"td", "th"} and self._depth == 1 and self._r is not None:
                self._c = []

        def handle_data(self, data: str) -> None:
            if self._c is not None:
                self._c.append(data)

        def handle_endtag(self, tag: str) -> None:
            if tag in {"td", "th"} and self._depth == 1 and self._r is not None and self._c is not None:
                self._r.append(" ".join("".join(self._c).split()))
                self._c = None
            elif tag == "tr" and self._depth == 1 and self._t is not None and self._r is not None:
                if any(c.strip() for c in self._r):
                    self._t.append(self._r)
                self._r = None
            elif tag == "table":
                if self._depth == 1 and self._t is not None:
                    self.tables.append(self._t)
                    self._t = None
                self._depth -= 1

    p = P()
    p.feed(html)
    return p.tables


def _split_coords(s: str) -> tuple[str | None, str | None]:
    m = re.match(r"(\d+(?:\.\d+)?[NS])\s*(\d+(?:\.\d+)?[EW])", s, re.I)
    return (m.group(1), m.group(2)) if m else (None, None)


def _parse_enr44_points(html: str, source_id: str, issues: list[Issue]) -> list[NavPoint]:
    points: list[NavPoint] = []
    for tbl in _extract_tables(html):
        if not tbl:
            continue
        h = " ".join(tbl[0]).upper().replace(" ", "")
        if "NAME-CODE" not in h:
            continue
        for row in tbl[1:]:
            if len(row) < 2:
                continue
            txt = " ".join(row)
            cm = _COORD_RE.search(txt)
            if not cm:
                continue
            before = txt[: cm.start()].strip()
            toks = before.split()
            ident = ""
            for t in reversed(toks):
                t2 = re.sub(r"[^A-Z0-9]", "", t.upper())
                if t2 and len(t2) >= 3 and not t2.isdigit():
                    ident = t2
                    break
            if not ident:
                continue
            try:
                cs = _split_coords(cm.group(0))
                if cs[0] is None or cs[1] is None:
                    continue
                lat = parse_coordinate(cs[0])
                lon = parse_coordinate(cs[1])
            except (CoordinateParseError, ValueError):
                continue
            ident = normalize_ident(ident)
            points.append(
                NavPoint(
                    uid=point_uid(ident, lat, lon, FIR, "SIGNIFICANT_POINT", source_id),
                    ident=ident,
                    name=ident,
                    latitude=lat,
                    longitude=lon,
                    point_type="SIGNIFICANT_POINT",
                    usage_type="ENROUTE",
                    country=COUNTRY,
                    fir=FIR,
                    region_code=REGION,
                    source_id=source_id,
                )
            )
    return points


def _parse_routes(
    html: str,
    source_id: str,
    point_by_ident: dict[str, NavPoint],
    dataset_points: list[NavPoint],
    issues: list[Issue],
) -> tuple[list[Airway], list[AirwaySegment]]:
    airways: list[Airway] = []
    all_segments: list[AirwaySegment] = []

    for tbl in _extract_tables(html):
        designator = None
        for row in tbl[:10]:
            if not row:
                continue
            c = row[0].strip()
            if c.upper().startswith(("ROUTE DESIGNATOR", "1")):
                continue
            m = re.match(r"^([A-Z]\d{1,4}[A-Z]?)", c.upper())
            if m:
                designator = normalize_ident(m.group(1))
                break
        if not designator:
            continue

        awy = Airway(
            uid=airway_uid(designator, source_id, FIR),
            designator=designator,
            route_type="ATS",
            country=COUNTRY,
            fir=FIR,
            source_id=source_id,
        )
        route_points: list[NavPoint] = []
        route_segments: list[AirwaySegment] = []
        pending_dist: float | None = None

        for row in tbl:
            txt = " ".join(row)
            cm = _COORD_RE.search(txt)
            if not cm:
                for cell in row:
                    mm = re.search(r"(\d+(?:\.\d+)?)\s*(?:NM|KM)", cell, re.I)
                    if mm:
                        v = float(mm.group(1))
                        if mm.group(0).upper().endswith("KM"):
                            v *= 0.539957
                        if 0.1 <= v <= 9999:
                            pending_dist = v
                continue
            before = txt[: cm.start()].strip()
            before = re.sub(r"^[▲∆▼]\s*", "", before).strip()
            toks = before.split()
            raw_id = ""
            for t in reversed(toks):
                t2 = re.sub(r"[^A-Z0-9]", "", t.upper())
                if t2 and len(t2) >= 3 and not t2.isdigit():
                    raw_id = t2
                    break
            if not raw_id:
                continue
            ident = normalize_ident(re.sub(r"[^A-Z0-9]", "", raw_id.upper()))
            try:
                ls = cm.group(0).split()
                lat = parse_coordinate(ls[0])
                lon = parse_coordinate(ls[1])
            except (CoordinateParseError, ValueError):
                continue

            stored = point_by_ident.get(ident)
            if stored is None:
                stored = NavPoint(
                    uid=point_uid(ident, lat, lon, FIR, "SIGNIFICANT_POINT", source_id),
                    ident=ident,
                    name=ident,
                    latitude=lat,
                    longitude=lon,
                    point_type="SIGNIFICANT_POINT",
                    usage_type="ENROUTE",
                    country=COUNTRY,
                    fir=FIR,
                    region_code=REGION,
                    source_id=source_id,
                )
                point_by_ident[ident] = stored
                dataset_points.append(stored)

            if route_points:
                prev = route_points[-1]
                seq = len(route_points)
                d = pending_dist or haversine_nm(
                    (prev.latitude, prev.longitude), (stored.latitude, stored.longitude)
                )
                br = initial_bearing_degrees((prev.latitude, prev.longitude), (stored.latitude, stored.longitude))
                route_segments.append(
                    AirwaySegment(
                        uid=segment_uid(awy.uid, seq, prev.uid, stored.uid),
                        airway_uid=awy.uid,
                        sequence=seq,
                        from_point_uid=prev.uid,
                        to_point_uid=stored.uid,
                        distance_nm=round(d, 2),
                        initial_course_deg=round(br, 1),
                        reverse_course_deg=round((br + 180) % 360, 1),
                        source_id=source_id,
                    )
                )
            route_points.append(stored)
            pending_dist = None

        if len(route_points) >= 2:
            airways.append(awy)
            all_segments.extend(route_segments)

    return airways, all_segments
