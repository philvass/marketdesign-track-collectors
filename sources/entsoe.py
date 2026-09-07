"""ENTSO-E (consultations.entsoe.eu) — the European TSO association.

Discovery: the public consultation hub, where network-code proposals, platform
methodologies and implementation frameworks are put to the market.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  extract_pdf_text, html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "ENTSO-E"
DOCUMENT_TYPE = "TSO"

ENTSOE_CONSULTATIONS_URL = "https://consultations.entsoe.eu/"

DATE_RE = re.compile(
    r"\b(?:Opened|Closes|Closed)\s+(\d{1,2})\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(20\d{2})\b",
    re.I,
)

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def normalise_entsoe_date(day: str, month: str, year: str) -> str:
    return datetime(
        int(year),
        MONTHS[month.lower()],
        int(day),
    ).date().isoformat()


def source_id_from_url(url: str) -> str:
    path = url.split("?", 1)[0].strip("/").split("/")
    slug = "-".join(path[-2:]).lower()
    slug = re.sub(r"[^a-z0-9-]+", "-", slug).strip("-")
    return f"entsoe-consultation-{slug}"


def parse_candidates(html: str, base_url: str) -> list[Candidate]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, Candidate] = {}

    for a in soup.find_all("a", href=True):
        title = " ".join(a.get_text(" ", strip=True).split())
        url = urljoin(base_url, a["href"])

        if not title:
            continue
        if "consultations.entsoe.eu" not in url:
            continue
        if url.rstrip("/") == base_url.rstrip("/"):
            continue
        if "/consultation_finder/" in url:
            continue
        if "/user_uploads/" in url:
            continue
        if url.lower().endswith(".pdf"):
            continue

        # Exclude Consultation Hub navigation, legal and support pages.
        excluded_paths = (
            "/accessibility_policy/",
            "/terms_and_conditions/",
            "/cookie_policy/",
            "/privacy_policy/",
            "/support/",
        )
        if any(path in url for path in excluded_paths):
            continue
        if "#" in url:
            continue

        # Consultation detail pages use paths such as /markets/ishm-assessment/.
        path_parts = [p for p in url.split("?", 1)[0].split("/") if p]
        if len(path_parts) < 2:
            continue

        sid = source_id_from_url(url)

        # Avoid duplicate menu/footer links to the same consultation.
        found.setdefault(
            sid,
            Candidate(
                source_id=sid,
                title=title,
                publication_date=None,
                url=url,
            ),
        )

    return list(found.values())


def discover(session: requests.Session) -> tuple[str, list[Candidate]]:
    r = get_with_retry(session, ENTSOE_CONSULTATIONS_URL)
    candidates = parse_candidates(r.text, r.url)
    if not candidates:
        raise CollectorError("ENTSO-E consultation discovery returned no candidates")
    return r.url, candidates


def fetch_content(session: requests.Session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    content_type = (r.headers.get("content-type") or "").lower()
    if "pdf" in content_type or candidate.url.lower().endswith(".pdf"):
        text = extract_pdf_text(r.content)
    else:
        soup = BeautifulSoup(r.text, "html.parser")

        page_text = soup.get_text(" ", strip=True)
        opened = re.search(
            r"\bOpened\s+(\d{1,2})\s+"
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(20\d{2})\b",
            page_text,
            re.I,
        )
        if opened:
            candidate.publication_date = normalise_entsoe_date(
                opened.group(1),
                opened.group(2),
                opened.group(3),
            )

        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = "\n".join(
            line.strip() for line in soup.get_text("\n").splitlines() if line.strip()
        )
        text = text[:60000]
    if len(text) < 200:
        raise CollectorError(f"Too little source text extracted from {candidate.url}")
    return text
