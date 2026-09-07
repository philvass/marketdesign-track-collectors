"""ACER (acer.europa.eu) — the EU agency whose decisions and methodologies are
the primary record of European market design.

Discovery: the individual-decisions search listing, with a static fallback.
Acts are PDFs, so this source leans on the shared core's extraction, which
refuses image-only streams rather than shipping them to the analysis models.
"""
from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from core import (Candidate, CollectorError, UpstreamUnavailable, get_with_retry,
                  extract_pdf_text, html_to_text, slugify, MAX_CONTENT_CHARS)

INSTITUTION = "ACER"
DOCUMENT_TYPE = "REGULATOR"

ACER_SEARCH_URL = (
    "https://www.acer.europa.eu/documents/search?"
    "f%5B0%5D=area%3A45&f%5B1%5D=type_of_publication%3A30"
)
ACER_FALLBACK_URL = (
    "https://www.acer.europa.eu/documents/official-documents/individual-decisions?page=0"
)

DATE_RE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")
DECISION_RE = re.compile(r"\bDecision\s+(?:No\s+)?0?(\d{1,2})[-/]?(20\d{2})\b", re.I)


def normalise_date(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%d.%m.%Y").date().isoformat()
    except ValueError:
        return None


def source_id_from_title(title: str) -> str:
    m = DECISION_RE.search(title)
    if m:
        return f"acer-decision-{int(m.group(1)):02d}-{m.group(2)}"
    digest = hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]
    return f"acer-{digest}"


def _nearest_date(anchor) -> str | None:
    # ACER cards place the date shortly before the decision link. Walk previous
    # rendered strings so this remains resilient to small Drupal markup changes.
    seen = 0
    for text in anchor.find_all_previous(string=True):
        value = " ".join(str(text).split())
        if not value:
            continue
        seen += len(value)
        m = DATE_RE.search(value)
        if m:
            return normalise_date(m.group(1))
        if seen > 1200:
            break
    return None


def parse_candidates(html: str, base_url: str) -> list[Candidate]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, Candidate] = {}
    for a in soup.find_all("a", href=True):
        title = " ".join(a.get_text(" ", strip=True).split())
        if not title or "annex" in title.lower():
            continue
        if not DECISION_RE.search(title):
            continue
        # Avoid administrative-board decisions and unrelated link text.
        if not title.lower().startswith("acer decision"):
            continue
        url = urljoin(base_url, a["href"])
        sid = source_id_from_title(title)
        cand = Candidate(
            source_id=sid,
            title=title,
            publication_date=_nearest_date(a),
            url=url,
        )
        # First occurrence on ACER's listing is the primary decision file.
        found.setdefault(sid, cand)
    return list(found.values())


def discover(session: requests.Session) -> tuple[str, list[Candidate]]:
    errors: list[str] = []
    for url in (ACER_SEARCH_URL, ACER_FALLBACK_URL):
        try:
            r = get_with_retry(session, url)
            candidates = parse_candidates(r.text, r.url)
            if candidates:
                return r.url, candidates
            errors.append(f"{url}: no decisions parsed")
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise CollectorError("ACER discovery failed: " + " | ".join(errors))


def fetch_content(session: requests.Session, candidate: Candidate) -> str:
    r = get_with_retry(session, candidate.url, timeout=45)
    content_type = (r.headers.get("content-type") or "").lower()
    if "pdf" in content_type or candidate.url.lower().endswith(".pdf"):
        text = extract_pdf_text(r.content)
    else:
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = "\n".join(
            line.strip() for line in soup.get_text("\n").splitlines() if line.strip()
        )
        text = text[:60000]
    if len(text) < 200:
        raise CollectorError(f"Too little source text extracted from {candidate.url}")
    return text
