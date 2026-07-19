from __future__ import annotations

import re
import zipfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlparse

from aviationdb.config import PROJECT_ROOT, resolve_project_path, source_config
from aviationdb.models import REDISTRIBUTION_ALLOWED, SourceMetadata
from aviationdb.parsers.arinc424 import parse_faa_cifp, parse_minimal_cifp_fixture
from aviationdb.parsers.austria import parse_austria_pdf_documents
from aviationdb.parsers.brunei import parse_brunei_pdf_documents
from aviationdb.parsers.chile import parse_chile_pdf_documents
from aviationdb.parsers.cuba import parse_cuba_pdf_documents
from aviationdb.parsers.ead import parse_ead_documents
from aviationdb.parsers.flightgear import parse_databases as parse_flightgear
from aviationdb.parsers.xplane import scan_databases as parse_xplane
from aviationdb.parsers.denmark import parse_denmark_pdf_documents
from aviationdb.parsers.europe import ROW_CLASS_EAIP_SOURCES, parse_europe_eaip_documents
from aviationdb.parsers.france import parse_france_pdf_documents
from aviationdb.parsers.hongkong import parse_hongkong_eaip_documents
from aviationdb.parsers.india import parse_india_eaip_documents
from aviationdb.parsers.korea import parse_korea_eaip_documents
from aviationdb.parsers.kuwait import parse_kuwait_pdf_documents
from aviationdb.parsers.maldives import parse_maldives_pdf_documents
from aviationdb.parsers.mauritius import parse_mauritius_pdf_documents
from aviationdb.parsers.malaysia import parse_malaysia_pdf_documents
from aviationdb.parsers.portugal import parse_portugal_eaip_documents
from aviationdb.parsers.romania import parse_romania_pdf_documents
from aviationdb.parsers.singapore import parse_singapore_eaip_documents
from aviationdb.parsers.spain import parse_spain_documents
from aviationdb.parsers.taiwan import ParsedDataset, parse_taiwan_eaip_documents, parse_taiwan_eaip_fixture
from aviationdb.parsers.vietnam import parse_vietnam_eaip_documents
from aviationdb.repository import AviationRepository


def build_source(repository: AviationRepository, source_id: str) -> ParsedDataset:
    config = source_config()["sources"][source_id]
    dataset = _parse_source(source_id, config)
    if source_id == "ead":
        repository.connection.execute("PRAGMA foreign_keys=OFF")
    source = SourceMetadata(
        source_id=source_id,
        provider=config["provider"],
        country=config.get("country"),
        source_url=config["source_url"],
        source_type=config["source_type"],
        airac_cycle=config.get("airac_cycle"),
        effective_date=config.get("effective_date"),
        raw_file_sha256=_dataset_fingerprint(config),
        license_url=config.get("license_url"),
        redistribution_status=config.get("redistribution_status", "unknown"),
        retrieved_at=datetime.now(UTC).isoformat(),
        allow_app_bundle=bool(config.get("allow_app_bundle"))
        and config.get("redistribution_status") == REDISTRIBUTION_ALLOWED,
    )
    repository.upsert_source(source)
    repository.insert_airports(dataset.airports)
    repository.insert_nav_points(dataset.points)
    repository.insert_airways(dataset.airways)
    repository.insert_segments(dataset.segments)
    for issue in dataset.issues:
        repository.add_parse_issue(issue)
    return dataset


def build_all(repository: AviationRepository, reset: bool = True) -> dict[str, ParsedDataset]:
    repository.init_schema()
    if reset:
        repository.reset_public_data()
    built: dict[str, ParsedDataset] = {}
    # Fixture is intentionally redistributable and powers public app tests.
    for source_id in ["fixture", "taiwan", "faa"]:
        built[source_id] = build_source(repository, source_id)
    return built


def _parse_source(source_id: str, config: dict[str, object]) -> ParsedDataset:
    fixture_files = config.get("fixture_files")
    if source_id == "hongkong":
        official_documents = _read_existing_raw_files(config)
        if official_documents:
            return parse_hongkong_eaip_documents(official_documents, source_id)
        raise ValueError("Source hongkong requires downloaded raw eAIP files")
    if source_id == "korea":
        official_documents = _read_existing_raw_files(config)
        if official_documents:
            return parse_korea_eaip_documents(official_documents, source_id)
        raise ValueError("Source korea requires downloaded raw eAIP files")
    if source_id == "singapore":
        official_documents = _read_existing_raw_files(config)
        if official_documents:
            return parse_singapore_eaip_documents(official_documents, source_id)
        raise ValueError("Source singapore requires downloaded raw eAIP files")
    if source_id == "malaysia":
        official_document_bytes = _read_existing_raw_file_bytes(config)
        if official_document_bytes:
            return parse_malaysia_pdf_documents(official_document_bytes, source_id)
        raise ValueError("Source malaysia requires downloaded raw AIP PDF files")
    if source_id == "france":
        official_document_bytes = _read_existing_raw_file_bytes(config)
        if official_document_bytes:
            return parse_france_pdf_documents(official_document_bytes, source_id)
        raise ValueError("Source france requires downloaded raw AIP PDF files")
    if source_id == "denmark":
        official_document_bytes = _read_existing_raw_file_bytes(config)
        if official_document_bytes:
            return parse_denmark_pdf_documents(official_document_bytes, source_id)
        raise ValueError("Source denmark requires downloaded raw AIP PDF files")
    if source_id == "austria":
        official_document_bytes = _read_existing_raw_file_bytes(config)
        if official_document_bytes:
            return parse_austria_pdf_documents(official_document_bytes, source_id)
        raise ValueError("Source austria requires downloaded raw AIP PDF files")
    if source_id == "brunei":
        official_document_bytes = _read_existing_raw_file_bytes(config)
        if official_document_bytes:
            return parse_brunei_pdf_documents(official_document_bytes, source_id)
        raise ValueError("Source brunei requires downloaded raw AIP PDF files")
    if source_id == "kuwait":
        official_document_bytes = _read_existing_raw_file_bytes(config)
        if official_document_bytes:
            return parse_kuwait_pdf_documents(official_document_bytes, source_id)
        raise ValueError("Source kuwait requires downloaded raw AIP PDF files")
    if source_id == "maldives":
        official_document_bytes = _read_existing_raw_file_bytes(config)
        if official_document_bytes:
            return parse_maldives_pdf_documents(official_document_bytes, source_id)
        raise ValueError("Source maldives requires downloaded raw AIP PDF files")
    if source_id == "mauritius":
        official_document_bytes = _read_existing_raw_file_bytes(config)
        if official_document_bytes:
            return parse_mauritius_pdf_documents(official_document_bytes, source_id)
        raise ValueError("Source mauritius requires downloaded raw AIP PDF files")
    if source_id == "portugal":
        official_documents = _read_existing_raw_files(config)
        if official_documents:
            return parse_portugal_eaip_documents(official_documents, source_id)
        raise ValueError("Source portugal requires downloaded raw eAIP files")
    if source_id == "vietnam":
        official_documents = _read_existing_raw_files(config)
        if official_documents:
            return parse_vietnam_eaip_documents(official_documents, source_id)
        raise ValueError("Source vietnam requires downloaded raw eAIP files")
    if source_id == "romania":
        official_document_bytes = _read_existing_raw_file_bytes(config)
        if official_document_bytes:
            return parse_romania_pdf_documents(official_document_bytes, source_id)
        raise ValueError("Source romania requires downloaded raw AIP PDF files")
    if source_id == "chile":
        official_document_bytes = _read_existing_raw_pdf_dir(config)
        if official_document_bytes:
            return parse_chile_pdf_documents(official_document_bytes, source_id)
        raise ValueError("Source chile requires downloaded raw AIP PDF files")
    if source_id == "spain":
        official_document_bytes = _read_existing_raw_file_bytes(config)
        if official_document_bytes:
            return parse_spain_documents(official_document_bytes, source_id)
        raise ValueError("Source spain requires downloaded raw AIP CSV/PDF files")
    if source_id == "india":
        official_documents = _read_existing_india_raw_files(config)
        if official_documents:
            return parse_india_eaip_documents(official_documents, source_id)
        raise ValueError("Source india requires downloaded raw eAIP files")
    if source_id == "cuba":
        official_document_bytes = _read_existing_raw_file_bytes(config)
        if official_document_bytes:
            return parse_cuba_pdf_documents(official_document_bytes, source_id)
        raise ValueError("Source cuba requires downloaded raw AIP PDF files")
    if source_id == "ead":
        return parse_ead_documents(source_id)
    if source_id == "flightgear":
        return _build_flightgear(source_id)
    if source_id in ROW_CLASS_EAIP_SOURCES:
        official_documents = _read_existing_europe_raw_files(config)
        if official_documents:
            return parse_europe_eaip_documents(official_documents, source_id)
        raise ValueError(f"Source {source_id} requires downloaded raw eAIP files")
    if not isinstance(fixture_files, dict):
        raise ValueError(f"Source {source_id} has no fixture files")
    if source_id == "fixture":
        html = _read_fixture(str(fixture_files["taiwan_eaip"]))
        return parse_taiwan_eaip_fixture(html, source_id)
    if source_id == "taiwan":
        official_documents = _read_existing_raw_files(config)
        if official_documents:
            return parse_taiwan_eaip_documents(official_documents, source_id)
        html = _read_fixture(str(fixture_files["taiwan_eaip"]))
        return parse_taiwan_eaip_fixture(html, source_id)
    if source_id == "faa":
        official_document_bytes = _read_existing_raw_file_bytes(config)
        for path_id, payload in official_document_bytes.items():
            if path_id.endswith("zip"):
                cifp = _read_faa_cifp_from_zip(payload)
                if cifp is not None:
                    return parse_faa_cifp(cifp, source_id)
        text = _read_fixture(str(fixture_files["faa_cifp"]))
        return parse_minimal_cifp_fixture(text, source_id)
    raise ValueError(f"Unsupported source: {source_id}")


def _build_flightgear(source_id: str) -> ParsedDataset:
    from aviationdb.parsers.flightgear import parse_databases
    from aviationdb.models import Airway, AirwaySegment, NavPoint
    from aviationdb.uid import airway_uid, point_uid, segment_uid
    
    data = parse_databases(source_id)
    pts = data["points"]
    awys = data["airways"]
    dataset = ParsedDataset()
    
    # Insert points
    seen: set[str] = set()
    for (ident, region), info in pts.items():
        if ident in seen:
            continue
        seen.add(ident)
        dataset.points.append(NavPoint(
            uid=point_uid(ident, info["lat"], info["lon"], "FG_GLOBAL",
                          info["type"], source_id),
            ident=ident, name=ident,
            latitude=info["lat"], longitude=info["lon"],
            point_type=info["type"], usage_type="ENROUTE",
            country="XX", fir="FG_GLOBAL", region_code="global",
            source_id=source_id,
        ))
    
    # Collect all points from awy.dat first
    awy_point_uids: dict[str, NavPoint] = {}
    for seg in awys:
        for ident, lat, lon in [(seg["from_ident"], seg["from_lat"], seg["from_lon"]),
                                 (seg["to_ident"], seg["to_lat"], seg["to_lon"])]:
            uid = point_uid(ident, lat, lon, "FG_GLOBAL", "SIGNIFICANT_POINT", source_id)
            if uid not in awy_point_uids:
                awy_point_uids[uid] = NavPoint(
                    uid=uid, ident=ident, name=ident,
                    latitude=lat, longitude=lon,
                    point_type="SIGNIFICANT_POINT", usage_type="ENROUTE",
                    country="XX", fir="FG_GLOBAL", region_code="global",
                    source_id=source_id,
                )
    for pt in awy_point_uids.values():
        if pt.ident not in seen:
            seen.add(pt.ident)
            dataset.points.append(pt)
    
    # Insert airways from awy.dat
    route_segments: dict[str, list[dict]] = {}
    for seg in awys:
        route = seg["route"]
        if route not in route_segments:
            route_segments[route] = []
        route_segments[route].append(seg)
    
    point_uids = {p.uid for p in dataset.points}
    for route_name, segs in route_segments.items():
        if not segs:
            continue
        awy = Airway(
            uid=airway_uid(route_name, source_id, "FG_GLOBAL"),
            designator=route_name,
            route_type="ATS",
            country="XX", fir="FG_GLOBAL",
            source_id=source_id,
        )
        dataset.airways.append(awy)
        
        for i, seg in enumerate(segs, 1):
            from_uid = point_uid(seg["from_ident"], seg["from_lat"], seg["from_lon"],
                                 "FG_GLOBAL", "SIGNIFICANT_POINT", source_id)
            to_uid = point_uid(seg["to_ident"], seg["to_lat"], seg["to_lon"],
                               "FG_GLOBAL", "SIGNIFICANT_POINT", source_id)
            if from_uid not in point_uids or to_uid not in point_uids:
                continue
            dataset.segments.append(AirwaySegment(
                uid=segment_uid(awy.uid, i, from_uid, to_uid),
                airway_uid=awy.uid, sequence=i,
                from_point_uid=from_uid, to_point_uid=to_uid,
                source_id=source_id,
            ))
    
    return dataset


def _read_fixture(relative_path: str) -> str:
    return resolve_project_path(relative_path).read_text(encoding="utf-8")


def _dataset_fingerprint(config: dict[str, object]) -> str:
    fixture_files = config.get("fixture_files")
    raw_files = _configured_raw_files(config)
    hasher = sha256()
    if isinstance(fixture_files, dict):
        for value in sorted(str(item) for item in fixture_files.values()):
            path = PROJECT_ROOT / value
            if path.exists():
                hasher.update(path.read_bytes())
    for value in sorted(raw_files.values()):
        path = PROJECT_ROOT / value
        if path.exists():
            hasher.update(path.read_bytes())
    for path in _configured_raw_route_files(config):
        if path.exists():
            hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _read_existing_raw_files(config: dict[str, object]) -> dict[str, str]:
    raw_files = _configured_raw_files(config)
    documents: dict[str, str] = {}
    for document_id, raw_path in sorted(raw_files.items()):
        path = PROJECT_ROOT / str(raw_path)
        if path.exists():
            documents[str(document_id)] = path.read_text(encoding="utf-8")
    return documents


def _read_existing_raw_file_bytes(config: dict[str, object]) -> dict[str, bytes]:
    raw_files = _configured_raw_files(config)
    documents: dict[str, bytes] = {}
    for document_id, raw_path in sorted(raw_files.items()):
        path = PROJECT_ROOT / str(raw_path)
        if path.exists():
            documents[str(document_id)] = path.read_bytes()
    return documents


def _read_existing_raw_pdf_dir(config: dict[str, object]) -> dict[str, bytes]:
    raw_dir = config.get("raw_dir")
    if not isinstance(raw_dir, str):
        return _read_existing_raw_file_bytes(config)
    path = PROJECT_ROOT / raw_dir
    if not path.exists():
        return {}
    return {
        item.stem.replace(".", "_").replace(" ", "_").lower(): item.read_bytes()
        for item in sorted(path.glob("*.pdf"))
    }


def _read_existing_india_raw_files(config: dict[str, object]) -> dict[str, str]:
    documents = _read_existing_raw_files(config)
    for path in _configured_raw_route_files(config):
        route = _india_route_designator_from_filename(path.name)
        if route is None:
            continue
        documents[f"route_{route}"] = path.read_text(encoding="utf-8")
    return documents


def _read_existing_europe_raw_files(config: dict[str, object]) -> dict[str, str]:
    documents: dict[str, str] = {}
    for document_id, raw_path in sorted(_configured_raw_files(config).items()):
        path = PROJECT_ROOT / str(raw_path)
        if not path.exists():
            continue
        if path.suffix.lower() == ".zip":
            documents.update(_read_eaip_html_from_zip(path))
            continue
        if path.suffix.lower() == ".json":
            continue
        documents[str(document_id)] = path.read_text(encoding="utf-8")
    for path in _configured_raw_route_files(config):
        if path.name == "manifest.json":
            continue
        document_id = path.stem.replace(".", "_").replace(" ", "_").lower()
        documents.setdefault(document_id, path.read_text(encoding="utf-8"))
    return documents


def _read_eaip_html_from_zip(path: Path) -> dict[str, str]:
    documents: dict[str, str] = {}
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            member_path = Path(name)
            member_name = member_path.name
            if not member_name.lower().endswith(".html"):
                continue
            if "-ENR-" not in member_name:
                continue
            if not any(section in member_name for section in ["-ENR-3.", "-ENR-4."]):
                continue
            payload = archive.read(name)
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                text = payload.decode("latin-1")
            document_id = member_path.stem.replace(".", "_").replace(" ", "_").lower()
            documents[document_id] = text
    return documents


def _read_faa_cifp_from_zip(payload: bytes) -> str | None:
    from io import BytesIO

    with zipfile.ZipFile(BytesIO(payload)) as archive:
        for name in archive.namelist():
            if Path(name).name == "FAACIFP18":
                return archive.read(name).decode("latin-1")
    return None


def _configured_raw_files(config: dict[str, object]) -> dict[str, str]:
    files: dict[str, str] = {}
    raw_files = config.get("raw_files")
    if isinstance(raw_files, dict):
        files.update({str(key): str(value) for key, value in raw_files.items()})
    route_documents = config.get("official_route_documents")
    raw_route_dir = config.get("raw_route_dir")
    if isinstance(route_documents, dict) and isinstance(raw_route_dir, str):
        for route, url in route_documents.items():
            filename = Path(unquote(urlparse(str(url)).path)).name
            files[f"route_{route}"] = str(Path(raw_route_dir) / filename)
    return files


def _configured_raw_route_files(config: dict[str, object]) -> list[Path]:
    raw_route_dir = config.get("raw_route_dir")
    if not isinstance(raw_route_dir, str):
        return []
    route_dir = PROJECT_ROOT / raw_route_dir
    if not route_dir.exists():
        return []
    return sorted(route_dir.glob("*.html"))


def _india_route_designator_from_filename(filename: str) -> str | None:
    match = re.search(r"IN-ENR-3\.\d([A-Z]{1,2}\d{1,4}[A-Z]?)-en-GB\.html$", filename)
    if match is None:
        return None
    return match.group(1)
