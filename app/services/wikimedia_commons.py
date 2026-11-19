"""Small Wikimedia Commons API adapter for image-provider testing.

Public Commons search does not require an API key. This module deliberately
does NOT implement the complete image-license/attribution publication manager.
Only verified CC0 metadata is eligible for automated video rendering in this
initial test; all other licenses remain available in the search audit but are
not downloaded automatically.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlsplit

import requests
from loguru import logger

API_URL = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = (
    "MoneyPrinterTurbo-WikimediaCommons-Test/0.1 "
    "(https://github.com/giliardtiktok03-commits/MoneyPrinterTurbo)"
)
CC0_URL = "https://creativecommons.org/publicdomain/zero/1.0/"
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
_ALLOWED_MIMES = frozenset({"image/jpeg", "image/png", "image/webp"})
_CC0_NAMES = frozenset({"cc0", "cc0 1.0", "cc0-1.0", "creative commons zero"})


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style"}:
            self.ignored += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style"}:
            self.ignored = max(0, self.ignored - 1)

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def _plain(value: object) -> str:
    if isinstance(value, dict):
        value = value.get("value", "")
    if not isinstance(value, str):
        return ""
    parser = _PlainText()
    parser.feed(value)
    return " ".join(html.unescape(" ".join(parser.parts)).split())[:2000]


def _valid_url(url: str, hostname: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https" and parsed.hostname == hostname
            and not parsed.username and not parsed.password
        )
    except ValueError:
        return False


def _classify(meta: dict[str, str]) -> tuple[str, str]:
    """Strict *test* rule, not a legal conclusion about the source file."""
    license_name = meta.get("LicenseShortName", "").strip().lower()
    license_url = meta.get("LicenseUrl", "").rstrip("/") + "/"
    restrictions = meta.get("Restrictions", "").strip()
    terms = meta.get("UsageTerms", "").lower()
    attribution_required = meta.get("AttributionRequired", "").strip().lower()
    copyrighted = meta.get("Copyrighted", "").strip().lower()
    # Block contradictions even when the declared license is CC0.
    if attribution_required in {"true", "yes", "1"}:
        return "NEEDS_REVIEW", "Commons reports required attribution"
    if copyrighted in {"true", "yes", "1"}:
        return "NEEDS_REVIEW", "Commons reports copyright restrictions"
    if not license_name:
        return "NEEDS_REVIEW", "Missing license name"
    if re.search(r"(?:\bnc\b|non.?commercial|no.?deriv|all rights reserved)", license_name + " " + terms, re.I):
        return "REJECTED", "Terms prohibit or restrict intended automated commercial reuse"
    if restrictions:
        return "NEEDS_REVIEW", "Additional rights or restrictions reported"
    if license_name in _CC0_NAMES and license_url == CC0_URL:
        return "AUTO_APPROVED", "CC0 metadata matched; check other rights before publication"
    return "NEEDS_REVIEW", "License needs review/attribution (trial accepts CC0 only)"


def search_images(search_term: str, limit: int = 12) -> list[dict]:
    """Search Commons file pages and fetch imageinfo/extmetadata in one API call."""
    if not str(search_term).strip():
        return []
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": str(search_term).strip(),
        "gsrnamespace": 6,
        "gsrlimit": max(1, min(30, int(limit))),
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": 1600,
        "iiextmetadatalanguage": "en",
        "format": "json",
        "formatversion": 2,
    }
    try:
        response = requests.get(
            API_URL, params=params,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=(10, 35),
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError, TypeError) as exc:
        logger.warning(f"Wikimedia Commons search failed: {type(exc).__name__}: {exc}")
        return []

    pages = payload.get("query", {}).get("pages", []) if isinstance(payload, dict) else []
    if not isinstance(pages, list):
        return []
    checked_at = datetime.now(timezone.utc).isoformat()
    results = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        infos = page.get("imageinfo")
        if not isinstance(infos, list) or not infos or not isinstance(infos[0], dict):
            continue
        info = infos[0]
        if info.get("mime") not in _ALLOWED_MIMES:
            continue
        raw_meta = info.get("extmetadata") or {}
        if not isinstance(raw_meta, dict):
            raw_meta = {}
        meta = {key: _plain(raw_meta.get(key)) for key in (
            "LicenseShortName", "LicenseUrl", "Artist", "Credit", "Attribution",
            "UsageTerms", "Restrictions", "Copyrighted", "AttributionRequired",
        )}
        decision, reason = _classify(meta)
        image_url = str(info.get("thumburl") or info.get("url") or "")
        if not _valid_url(image_url, "upload.wikimedia.org"):
            decision, reason = "REJECTED", "Unexpected media host or URL"
        title = str(page.get("title") or "")
        page_url = str(info.get("descriptionurl") or "")
        if not _valid_url(page_url, "commons.wikimedia.org"):
            page_url = "https://commons.wikimedia.org/wiki/" + quote(
                title.replace(" ", "_"), safe=":,()_-"
            )
        results.append({
            "provider": "wikimedia",
            "asset_id": str(page.get("pageid") or title),
            "title": title,
            "source_page": page_url,
            "image_url": image_url,
            "width": info.get("width"),
            "height": info.get("height"),
            "license": meta["LicenseShortName"],
            "license_url": meta["LicenseUrl"],
            "artist": meta["Artist"],
            "credit": meta["Credit"],
            "attribution": meta["Attribution"],
            "usage_terms": meta["UsageTerms"],
            "restrictions": meta["Restrictions"],
            "copyrighted": meta["Copyrighted"],
            "attribution_required": meta["AttributionRequired"],
            "decision": decision,
            "reason": reason,
            "checked_at": checked_at,
        })
    return results


def download_approved_image(item: dict) -> bytes | None:
    """Fetch only a previously screened CC0 image; verify host and size."""
    if item.get("decision") != "AUTO_APPROVED":
        return None
    url = str(item.get("image_url") or "")
    if not _valid_url(url, "upload.wikimedia.org"):
        return None
    try:
        with requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=(10, 40),
            stream=True, allow_redirects=False,
        ) as response:
            response.raise_for_status()
            if 300 <= response.status_code < 400:
                return None
            data = bytearray()
            for chunk in response.iter_content(chunk_size=128 * 1024):
                if chunk:
                    data.extend(chunk)
                if len(data) > MAX_DOWNLOAD_BYTES:
                    logger.warning("Wikimedia image exceeded test download size cap")
                    return None
            return bytes(data) if data else None
    except requests.RequestException as exc:
        logger.warning(f"Wikimedia image download failed: {type(exc).__name__}: {exc}")
        return None


def save_audit(task_directory: str, records: list[dict]) -> str:
    """Persist API decisions for debugging; not a final clearance certificate."""
    target = Path(task_directory) / "wikimedia-audit.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"source": "Wikimedia Commons", "trial": True, "files": records},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(target)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test Wikimedia Commons search API")
    parser.add_argument("query", help="Search phrase in English")
    args = parser.parse_args()
    print(json.dumps(search_images(args.query), ensure_ascii=False, indent=2))
