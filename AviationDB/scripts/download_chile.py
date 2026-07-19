#!/usr/bin/env python3
"""Download Chile IFIS AIP ENR route/significant-point PDFs."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin

PROJECT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT / "data" / "raw" / "chile" / "current"
BASE_URL = "https://aipchile.dgac.gob.cl/"
ENR_INDEX_URL = urljoin(BASE_URL, "aip/vol1/seccion/enr")


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.links.append(value)


def _run_curl(url: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "curl",
            "-fL",
            "--retry",
            "2",
            "--connect-timeout",
            "20",
            "--max-time",
            "180",
            url,
            "-o",
            str(output_path),
        ],
        check=True,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_url(href: str) -> str:
    return urljoin(BASE_URL, quote(href, safe="/:"))


def _is_target_pdf(href: str) -> bool:
    lowered = href.lower()
    if not lowered.endswith(".pdf"):
        return False
    if "/enr 3 " in lowered or "/enr%203%20" in lowered:
        return True
    return any(marker in lowered for marker in ("enr 4.1", "enr%204.1", "enr 4.4", "enr%204.4"))


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    index_path = RAW_DIR / "ifis_enr_index.html"
    _run_curl(ENR_INDEX_URL, index_path)

    parser = LinkParser()
    parser.feed(index_path.read_text(encoding="utf-8", errors="ignore"))
    hrefs = sorted({href for href in parser.links if _is_target_pdf(href)})

    downloads: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    for href in hrefs:
        url = _safe_url(href)
        filename = Path(href).name.replace("/", "_")
        output_path = RAW_DIR / filename
        try:
            _run_curl(url, output_path)
            downloads.append(
                {
                    "href": href,
                    "url": url,
                    "path": str(output_path.relative_to(PROJECT)),
                    "bytes": output_path.stat().st_size,
                    "sha256": _sha256(output_path),
                }
            )
        except subprocess.CalledProcessError as error:
            errors.append({"href": href, "url": url, "error": str(error)})

    manifest = {
        "source": "chile",
        "provider": "Direccion General de Aeronautica Civil Chile / IFIS",
        "country": "CL",
        "source_url": BASE_URL,
        "index_url": ENR_INDEX_URL,
        "source_type": "aip_pdf",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "redistribution_status": "manual_review_required",
        "status": "downloaded" if downloads and not errors else "downloaded_partial",
        "files": downloads,
        "errors": errors,
        "notes": [
            "Downloaded ENR 3 route-description PDFs plus ENR 4.1 radio aids and ENR 4.4 significant-point PDFs from the public IFIS ENR index.",
            "Official redistribution remains manual_review_required; keep raw and derived artifacts private until reviewed.",
        ],
    }
    (RAW_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"Chile IFIS: downloaded {len(downloads)} files, errors {len(errors)}")


if __name__ == "__main__":
    main()
