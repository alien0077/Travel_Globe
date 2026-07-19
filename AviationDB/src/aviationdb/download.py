from __future__ import annotations

import hashlib
import json
import re
import zipfile
from base64 import b64decode
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from aviationdb.config import PROJECT_ROOT

USER_AGENT = "TravelGlobeAviationDB/0.1 (+https://github.com/alien0077/Travel_Globe)"
DEFAULT_TIMEOUT_SECONDS = 45


@dataclass(frozen=True)
class Link:
    href: str
    text: str


@dataclass(frozen=True)
class FaaCifpProduct:
    cycle: str
    url: str
    effective_date: str | None
    ending_date: str | None


class _AnchorExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[Link] = []
        self._href_stack: list[str | None] = []
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = next((value for key, value in attrs if key.lower() == "href"), None)
        self._href_stack.append(href)
        self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href_stack:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href_stack:
            return
        href = self._href_stack.pop()
        if href:
            text = " ".join("".join(self._text_parts).split())
            self.links.append(Link(href=href, text=text))
        self._text_parts = []


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        return None


def download_source(source_id: str, config: dict[str, Any]) -> dict[str, Any]:
    if source_id == "taiwan":
        return probe_taiwan_source(config)
    if config.get("source_type") in {"eaip_xhtml", "aip_pdf"}:
        return download_eaip_documents(source_id, config)
    if source_id == "japan":
        return probe_japan_swim_source(config)
    if source_id == "faa":
        return download_faa_cifp(config)
    raise ValueError(f"Unsupported download source: {source_id}")


def probe_taiwan_source(config: dict[str, Any]) -> dict[str, Any]:
    base_url = str(config["source_url"]).rstrip("/")
    portal_url = urljoin(base_url + "/", "aimportalapp/")
    endpoints = [
        urljoin(base_url + "/", "aimportalapp/api/airac-calendar/aeronautical-dates"),
        urljoin(base_url + "/", "aimportalapp/api/airac-calendar/available-aeronautical-dates/"),
        urljoin(base_url + "/", "aimportalapp/api/data"),
    ]
    checks: list[dict[str, Any]] = []
    portal = _request_status(portal_url)
    for endpoint in endpoints:
        checks.append(_request_status(endpoint, follow_redirects=False))

    auth_redirects = [
        item
        for item in checks
        if item.get("status_code") in {301, 302, 303, 307, 308} and "oauth2" in str(item.get("location", ""))
    ]
    artifacts = _download_configured_documents(config)
    status = "downloaded_with_auth_gated_api" if artifacts else ("auth_required" if auth_redirects else "needs_review")
    result = {
        "source": "taiwan",
        "provider": config["provider"],
        "retrieved_at": _now(),
        "status": status,
        "portal": portal,
        "checks": checks,
        "artifacts": artifacts,
        "notes": [
            "Public eAIP HTML documents were downloaded from configured document URLs.",
            "Operational SPA APIs still redirect to OIDC and are not required for these static eAIP pages.",
            "Artifacts are kept under data/raw and must not be published in app packs without manual license review.",
        ],
    }
    _write_manifest(PROJECT_ROOT / "data" / "raw" / "taiwan" / "download_probe.json", result)
    return result


def download_eaip_documents(source_id: str, config: dict[str, Any]) -> dict[str, Any]:
    raw_dir = PROJECT_ROOT / str(config.get("raw_dir", f"data/raw/{source_id}"))
    artifacts = _download_configured_documents(config)
    downloaded_count = sum(1 for artifact in artifacts if artifact.get("status") == "downloaded")
    result = {
        "source": source_id,
        "provider": config["provider"],
        "retrieved_at": _now(),
        "status": "downloaded" if downloaded_count == len(artifacts) and artifacts else "partial_or_failed",
        "portal": _request_status(str(config["source_url"])),
        "redistribution_status": config.get("redistribution_status", "manual_review_required"),
        "artifacts": artifacts,
        "notes": [
            "Configured public eAIP HTML documents were downloaded.",
            "Artifacts are kept under data/raw and must not be published in app packs without manual license review.",
        ],
    }
    _write_manifest(raw_dir / "manifest.json", result)
    return result


def probe_japan_swim_source(config: dict[str, Any]) -> dict[str, Any]:
    base_url = str(config["source_url"]).rstrip("/")
    service_ids = config.get("service_ids", {})
    amqp_service_ids = config.get("amqp_service_ids", {})
    raw_dir = PROJECT_ROOT / str(config.get("raw_dir", "data/raw/japan/swim"))
    public_services = _fetch_json(
        _swim_url(base_url, "/api/services/public?sortItem=3&sortOrder=2&acquireNumber=100&serviceType=2&search=")
    )
    distribution_services = _fetch_json(
        _swim_url(base_url, "/api/services/public?sortItem=3&sortOrder=2&acquireNumber=100&serviceType=1&search=")
    )
    aip_services = extract_swim_aip_services(public_services) + extract_swim_aip_services(distribution_services)

    service_details: dict[str, Any] = {}
    target_checks: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    for service_id in _configured_service_ids(service_ids):
        details = _fetch_json(_swim_url(base_url, f"/api/services/{service_id}/details"))
        authority = _fetch_json(_swim_url(base_url, f"/api/services/{service_id}/check/authority"))
        documents = _fetch_json(_swim_url(base_url, f"/api/services/{service_id}/documents"))
        references = _fetch_json(_swim_url(base_url, f"/api/services/{service_id}/references"))
        service_url = (
            details.get("datas", {})
            .get("serviceUniqueInfo", {})
            .get("serviceUrl")
        )
        if isinstance(service_url, str) and service_url:
            target_checks.append(_request_status(service_url))

        artifacts.extend(
            _download_swim_files(
                base_url,
                service_id,
                "document",
                documents.get("datas", {}).get("documentList", []),
                raw_dir,
            )
        )
        artifacts.extend(
            _download_swim_files(
                base_url,
                service_id,
                "reference",
                references.get("datas", {}).get("referenceList", []),
                raw_dir,
            )
        )
        service_details[service_id] = {
            "details": _redact_swim_details(details),
            "authority": authority,
            "documents": documents,
            "references": references,
        }

    direct_access_forbidden = any(item.get("status_code") == 403 for item in target_checks)
    result = {
        "source": "japan",
        "provider": config["provider"],
        "retrieved_at": _now(),
        "status": "metadata_downloaded_aip_target_forbidden" if direct_access_forbidden else "metadata_downloaded",
        "portal": _request_status(base_url),
        "aip_services": aip_services,
        "data_distribution_services": _matching_services(aip_services, _configured_service_ids(amqp_service_ids)),
        "api_integration": {
            "common_spec": "S9001_4-COMMON-API-250530.pdf",
            "webapi_auth": "Login API returns Set-Cookie; subsequent WebAPI calls must send Cookie.",
            "amqp_required_for": _configured_service_ids(amqp_service_ids),
            "amqp_requirements": [
                "service application and approval in SWIM portal",
                "queue auth ID",
                "queue password",
                "receiving queue ID",
                "broker URL",
            ],
            "protocol": "AMQP 1.0; SWIM spec notes one-hour idle session timeout.",
        },
        "service_details": service_details,
        "target_checks": target_checks,
        "artifacts": artifacts,
        "notes": [
            "SWIM portal public APIs expose AIP service metadata and documentation.",
            "AIP Browsing Service S2004 and AIP File Download Service S2002 target URLs returned 403.",
            "Common API spec indicates M2001/P2005 AIP data distribution uses AMQP, not public HTTP download.",
            "Downloaded documents are service manuals and secondary-use references, not operational AIP route data.",
            "No Japan AIP raw/processed data may be published until manual redistribution review is complete.",
        ],
    }
    _write_manifest(raw_dir / "download_probe.json", result)
    return result


def download_faa_cifp(config: dict[str, Any]) -> dict[str, Any]:
    source_url = str(config["source_url"])
    download_page_url = urljoin(source_url.rstrip("/") + "/", "download/")
    page = _fetch_text(download_page_url)
    products = extract_faa_cifp_products(page, download_page_url)
    if not products:
        result = {
            "source": "faa",
            "provider": config["provider"],
            "retrieved_at": _now(),
            "status": "no_download_link",
            "download_page_url": download_page_url,
            "artifacts": [],
            "notes": ["No CIFP zip link was found on the FAA download page."],
        }
        _write_manifest(PROJECT_ROOT / "data" / "raw" / "faa" / "manifest.json", result)
        return result

    product = products[0]
    target_dir = PROJECT_ROOT / "data" / "raw" / "faa" / product.cycle
    target_dir.mkdir(parents=True, exist_ok=True)
    zip_path = target_dir / Path(product.url).name
    _download_binary(product.url, zip_path)
    digest = _sha256_file(zip_path)
    entries = _zip_entries(zip_path)
    result = {
        "source": "faa",
        "provider": config["provider"],
        "retrieved_at": _now(),
        "status": "downloaded",
        "download_page_url": download_page_url,
        "agreement_required": True,
        "redistribution_status": config.get("redistribution_status", "manual_review_required"),
        "artifacts": [
            {
                "path": str(zip_path.relative_to(PROJECT_ROOT)),
                "url": product.url,
                "cycle": product.cycle,
                "effective_date": product.effective_date,
                "ending_date": product.ending_date,
                "size_bytes": zip_path.stat().st_size,
                "sha256": digest,
                "zip_entries_sample": entries[:20],
                "zip_entry_count": len(entries),
            }
        ],
        "notes": [
            "FAA CIFP is raw ARINC 424 data and requires additional processing.",
            "Artifact is kept under data/raw and must not be published in app packs without manual license review.",
        ],
    }
    _write_manifest(PROJECT_ROOT / "data" / "raw" / "faa" / "manifest.json", result)
    return result


def extract_faa_cifp_products(html: str, base_url: str) -> list[FaaCifpProduct]:
    extractor = _AnchorExtractor()
    extractor.feed(html)
    products: list[FaaCifpProduct] = []
    for link in extractor.links:
        match = re.search(r"CIFP[_\s-]?(\d{6})\.zip", link.href, flags=re.IGNORECASE)
        if not match:
            match = re.search(r"CIFP\s+(\d{6})", link.text, flags=re.IGNORECASE)
        if not match:
            continue
        row_html = _row_containing(html, link.href)
        dates = re.findall(r"([A-Z][a-z]{2}\s+\d{2},\s+\d{4})", row_html)
        products.append(
            FaaCifpProduct(
                cycle=match.group(1),
                url=urljoin(base_url, link.href),
                effective_date=dates[0] if dates else None,
                ending_date=dates[1] if len(dates) > 1 else None,
            )
        )
    return products


def extract_swim_aip_services(payload: dict[str, Any]) -> list[dict[str, Any]]:
    services = payload.get("datas", [])
    if not isinstance(services, list):
        return []
    aip_services: list[dict[str, Any]] = []
    seen: set[str] = set()
    for service in services:
        if not isinstance(service, dict):
            continue
        service_id = str(service.get("serviceId", ""))
        name = f"{service.get('serviceName', '')} {service.get('serviceNameJp', '')} {service.get('serviceNameEn', '')}"
        category = service.get("serviceCategoryCode")
        if service_id in seen:
            continue
        if category == 2 or "AIP" in name:
            seen.add(service_id)
            aip_services.append(
                {
                    "serviceId": service_id,
                    "serviceName": service.get("serviceName"),
                    "serviceCategoryCode": service.get("serviceCategoryCode"),
                    "lifecycleName": service.get("lifecycleName"),
                    "workingStatusName": service.get("workingStatusName"),
                    "lastUpdate": service.get("lastUpdate"),
                }
            )
    return aip_services


def _matching_services(services: list[dict[str, Any]], service_ids: list[str]) -> list[dict[str, Any]]:
    wanted = set(service_ids)
    return [service for service in services if service.get("serviceId") in wanted]


def _row_containing(html: str, needle: str) -> str:
    index = html.find(needle)
    if index < 0:
        return ""
    start = html.rfind("<tr", 0, index)
    end = html.find("</tr>", index)
    if start < 0 or end < 0:
        return ""
    return html[start : end + len("</tr>")]


def _request_status(url: str, follow_redirects: bool = True) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    opener = build_opener() if follow_redirects else build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            body = response.read(512)
            return {
                "url": url,
                "status_code": response.status,
                "content_type": response.headers.get("content-type"),
                "content_length": response.headers.get("content-length"),
                "body_prefix_bytes": len(body),
            }
    except HTTPError as exc:
        return {
            "url": url,
            "status_code": exc.code,
            "content_type": exc.headers.get("content-type"),
            "location": exc.headers.get("location"),
            "error": str(exc.reason),
        }
    except URLError as exc:
        return {"url": url, "status_code": None, "error": str(exc.reason)}


def _fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
        return cast(bytes, response.read()).decode("utf-8", errors="replace")


def _fetch_json(url: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_fetch_text(url)))


def _download_binary(url: str, target: Path) -> None:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response, target.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)


def _download_configured_documents(config: dict[str, Any]) -> list[dict[str, Any]]:
    documents = dict[str, str]()
    official_documents = config.get("official_documents")
    if isinstance(official_documents, dict):
        documents.update({str(key): str(value) for key, value in official_documents.items()})
    route_documents = config.get("official_route_documents")
    if isinstance(route_documents, dict):
        documents.update({f"route_{key}": str(value) for key, value in route_documents.items()})
    raw_files = config.get("raw_files")
    if not documents or not isinstance(raw_files, dict):
        return []

    artifacts: list[dict[str, Any]] = []
    for document_id, url in sorted(documents.items()):
        raw_path = _configured_raw_path(config, document_id, url)
        if not isinstance(url, str) or raw_path is None:
            continue
        target = PROJECT_ROOT / raw_path
        download_target = target.with_name(f"{target.name}.download")
        target.parent.mkdir(parents=True, exist_ok=True)
        artifact: dict[str, Any] = {
            "id": document_id,
            "path": str(target.relative_to(PROJECT_ROOT)),
            "url": url,
        }
        try:
            _download_binary(url, download_target)
            if _looks_like_blocked_download(download_target):
                download_target.unlink(missing_ok=True)
                raise ValueError("Downloaded page appears to be a bot-protection or CAPTCHA page")
            download_target.replace(target)
        except (HTTPError, URLError, TimeoutError) as error:
            artifact.update({"status": "failed", "error": str(error)})
        except ValueError as error:
            artifact.update({"status": "failed", "error": str(error)})
        else:
            artifact.update(
                {
                    "status": "downloaded",
                    "size_bytes": target.stat().st_size,
                    "sha256": _sha256_file(target),
                }
            )
        artifacts.append(artifact)
    return artifacts


def _looks_like_blocked_download(path: Path) -> bool:
    prefix = path.read_bytes()[:4096].lower()
    return b"captcha" in prefix or b"radware" in prefix or b"bot-protection" in prefix


def _configured_raw_path(config: dict[str, Any], document_id: str, url: str) -> str | None:
    raw_files = config.get("raw_files")
    if isinstance(raw_files, dict) and isinstance(raw_files.get(document_id), str):
        return str(raw_files[document_id])
    if not document_id.startswith("route_"):
        return None
    raw_route_dir = config.get("raw_route_dir")
    if not isinstance(raw_route_dir, str):
        return None
    filename = Path(unquote(urlparse(url).path)).name
    return str(Path(raw_route_dir) / filename)


def _swim_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + path


def _configured_service_ids(service_ids: object) -> list[str]:
    if not isinstance(service_ids, dict):
        return []
    return sorted(str(value) for value in service_ids.values())


def _download_swim_files(
    base_url: str,
    service_id: str,
    file_kind: str,
    items: object,
    raw_dir: Path,
) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    artifacts: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = item.get(f"{file_kind}Id")
        filename = item.get("fileName")
        if not isinstance(item_id, int) or not isinstance(filename, str):
            continue
        target = raw_dir / service_id / f"{file_kind}s" / _safe_filename(filename)
        endpoint = _swim_url(base_url, f"/api/services/{service_id}/{file_kind}/download/{item_id}")
        artifact: dict[str, Any] = {
            "service_id": service_id,
            "kind": file_kind,
            "id": item_id,
            "file_name": filename,
            "path": str(target.relative_to(PROJECT_ROOT)),
            "url": endpoint,
        }
        try:
            payload = _fetch_json(endpoint)
            file_data = payload.get("datas", {}).get("fileData")
            if not isinstance(file_data, str):
                raise ValueError("SWIM file payload does not contain fileData")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b64decode(file_data))
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            artifact.update({"status": "failed", "error": str(error)})
        else:
            artifact.update(
                {
                    "status": "downloaded",
                    "size_bytes": target.stat().st_size,
                    "sha256": _sha256_file(target),
                    "content_type": payload.get("datas", {}).get("contentType"),
                }
            )
        artifacts.append(artifact)
    return artifacts


def _safe_filename(filename: str) -> str:
    return re.sub(r"[/\\:\0]", "_", filename)


def _redact_swim_details(details: dict[str, Any]) -> dict[str, Any]:
    redacted = json.loads(json.dumps(details))
    unique_info = redacted.get("datas", {}).get("serviceUniqueInfo", {})
    if isinstance(unique_info, dict):
        for key in ["topicQueueAuthId", "topicQueueAuthPassword"]:
            if key in unique_info and unique_info[key]:
                unique_info[key] = "[redacted]"
    return cast(dict[str, Any], redacted)


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def _zip_entries(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        return archive.namelist()


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(UTC).isoformat()
